#!/usr/bin/env bash
# bootstrap-orgo.sh — take a fresh Orgo Linux computer to a running Hermes,
# the alans-way plugin and Tailscale, then wait for pairing.
#
# Idempotent: every step checks real state before acting, so a re-run after a
# partial failure resumes instead of reinstalling or duplicating supervisord
# entries. Progress is written atomically to $ALAN_STATE_DIR/state.json as
# {state, step, error, updated_at} for the provisioning backend to poll.
set -eEuo pipefail

STATE_DIR="${ALAN_STATE_DIR:-/var/lib/alan}"
STATE_FILE="$STATE_DIR/state.json"
LOG_FILE="${ALAN_LOG_FILE:-$STATE_DIR/bootstrap.log}"
BIN_DIR="${ALAN_BIN_DIR:-/usr/local/bin}"
SUPERVISOR_CONF_DIR="${SUPERVISOR_CONF_DIR:-/etc/supervisor/conf.d}"
TAILSCALE_STATE_DIR="${TAILSCALE_STATE_DIR:-/var/lib/tailscale}"
TAILSCALE_SOCKET="${TAILSCALE_SOCKET:-/var/run/tailscale/tailscaled.sock}"
SSHD_BIN="${SSHD_BIN:-/usr/sbin/sshd}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

# The same installer Alex's reference Orgo computer used: it git-clones
# NousResearch/hermes-agent and drops a shim on PATH.
HERMES_INSTALL_URL="https://hermes-agent.nousresearch.com/install.sh"
TAILSCALE_INSTALL_URL="https://tailscale.com/install.sh"
SETUP_URL_BASE="https://raw.githubusercontent.com/capthvnsen/alans-way-agents"
TAILSCALE_URL_TIMEOUT="${ALAN_TAILSCALE_URL_TIMEOUT:-120}"
WAIT_PAIRED_INTERVAL="${ALAN_WAIT_PAIRED_INTERVAL:-5}"
WAIT_PAIRED_TIMEOUT="${ALAN_WAIT_PAIRED_TIMEOUT:-600}"
LOGIN_URL_RE='https://login\.tailscale\.com/a/[A-Za-z0-9]+'

CALLBACK="" SECRET="" ID="" REPO_REF="main"
DRY_RUN=0 WAIT_PAIRED=0
CURRENT_STEP="init"

usage() {
    cat <<'EOF'
usage: bootstrap-orgo.sh [--callback URL] [--secret S] [--id ID]
       [--hermes-home DIR] [--repo-ref REF] [--dry-run] [--wait-paired]

  --callback URL   POST {"id","secret","url"} with the Tailscale login URL
  --secret S       callback shared secret
  --id ID          computer id; the tailnet hostname becomes alan-<id>
  --hermes-home    Hermes home directory (default $HERMES_HOME or ~/.hermes)
  --repo-ref REF   alans-way-agents ref for setup.sh (default main)
  --dry-run        print the commands instead of running them; writes nothing
  --wait-paired    poll `tailscale status` until BackendState=Running, then
                   write state {ready, paired}
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --callback) CALLBACK="$2"; shift 2;;
        --secret) SECRET="$2"; shift 2;;
        --id) ID="$2"; shift 2;;
        --hermes-home) HERMES_HOME="$2"; shift 2;;
        --repo-ref) REPO_REF="$2"; shift 2;;
        --dry-run) DRY_RUN=1; shift;;
        --wait-paired) WAIT_PAIRED=1; shift;;
        -h|--help) usage; exit 0;;
        *) echo "bootstrap-orgo: unknown flag: $1" >&2; usage >&2; exit 2;;
    esac
done

log() {
    local line="[bootstrap] $*"
    if [ "$DRY_RUN" = 1 ]; then
        printf '%s\n' "$line"
    else
        printf '%s\n' "$line" | tee -a "$LOG_FILE"
    fi
}

have() { command -v "$1" >/dev/null 2>&1; }

# first_conf_defining <name> — prints the first $SUPERVISOR_CONF_DIR/*.conf
# that defines [program:<name>]. Only *.conf files count: editor backups
# like hermes-gateway.conf.bak never load into supervisord.
first_conf_defining() {
    local name="$1" conf
    for conf in "$SUPERVISOR_CONF_DIR"/*.conf; do
        [ -f "$conf" ] || continue
        grep -q "^\[program:$name\]" "$conf" && { printf '%s' "$conf"; return 0; }
    done
    return 0
}

# conf_program_command <conf> <program> — the binary the conf's command=
# runs inside [program:<program>]. An indented command= is a ConfigParser
# continuation line, not a command, and does not count.
conf_program_command() {
    awk -v section="[program:$2]" '
        $0 == section {inside = 1; next}
        /^\[/         {inside = 0}
        inside && /^command=/ {sub(/^command=/, ""); print $1; exit}
    ' "$1"
}

# fix_conf_command <conf> <program> <command-line> — a conf that defines
# [program:<p>] without a parseable command= gets the line inserted right
# under the header. Writing a second [program:<p>] in another conf would
# break `supervisorctl reread` on the duplicate, so repair in place.
fix_conf_command() {
    local conf="$1" prog="$2" line="$3"
    if [ "$DRY_RUN" = 1 ]; then
        log "would repair $prog in $conf (add 'command=$line')"
        return 0
    fi
    if awk -v section="[program:$prog]" -v line="command=$line" '
        $0 == section && !added {print; print line; added = 1; next}
        {print}
    ' "$conf" >"$conf.alan-tmp" && mv "$conf.alan-tmp" "$conf"; then
        log "repaired $prog in $conf — added 'command=$line'"
    else
        rm -f "$conf.alan-tmp"
        log "WARNING: $conf defines $prog but has no command= line and could not be repaired"
    fi
    return 0
}

# first_conf_running <basename> — the first *.conf whose command= runs a
# binary literally named <basename>: absolute paths must exist, bare names
# must be on PATH. A command mentioning sshd ('sshd-healthcheck') does not
# count as a running sshd.
first_conf_running() {
    local want="$1" conf c
    for conf in "$SUPERVISOR_CONF_DIR"/*.conf; do
        [ -f "$conf" ] || continue
        while IFS= read -r c; do
            [ -n "$c" ] || continue
            case "$c" in
                */*) [ "${c##*/}" = "$want" ] && [ -x "$c" ] || continue;;
                *)   [ "$c" = "$want" ] && have "$c" || continue;;
            esac
            printf '%s' "$conf"
            return 0
        done < <(awk '/^command=/ {sub(/^command=/, ""); print $1}' "$conf")
    done
    return 0
}

# state <state> <step> [error] — atomic write via tmp file + mv.
state() {
    local s="$1" step="$2" err="${3:-}"
    if [ "$DRY_RUN" = 1 ]; then
        log "state -> $s $step${err:+ error=$err}"
        return 0
    fi
    local tmp="$STATE_DIR/.state.json.$$"
    python3 - "$tmp" "$s" "$step" "$err" <<'PY'
import datetime
import json
import sys

path, state, step, err = sys.argv[1:5]
doc = {
    "state": state,
    "step": step,
    "error": err if err else None,
    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(doc, f)
PY
    mv -f "$tmp" "$STATE_FILE"
}

on_err() {
    local last
    last="$(tail -n 1 "$LOG_FILE" 2>/dev/null || true)"
    [ -n "$last" ] || last="bootstrap failed (no log output)"
    state failed "$CURRENT_STEP" "$last" || true
}
trap on_err ERR

run() {
    if [ "$DRY_RUN" = 1 ]; then log "would run: $*"; return 0; fi
    printf '+ %s\n' "$*" >>"$LOG_FILE"
    "$@" >>"$LOG_FILE" 2>&1
}

run_sh() {
    if [ "$DRY_RUN" = 1 ]; then log "would run: $1"; return 0; fi
    printf '+ %s\n' "$1" >>"$LOG_FILE"
    bash -c "set -eEuo pipefail; $1" >>"$LOG_FILE" 2>&1
}

run_step() {
    CURRENT_STEP="$1"
    log "step: $1"
    state running "$1"
    "step_${1//-/_}"
}

# --- step: hermes --------------------------------------------------------

step_hermes() {
    if have hermes; then
        log "hermes already installed: $(command -v hermes)"
    else
        run_sh "curl -fsSL '$HERMES_INSTALL_URL' | bash"
    fi
    if ! have supervisorctl; then
        log "supervisorctl not found: Orgo computers run supervisord, so this does not look like one"
        return 1
    fi
    gateway_wrapper
    gateway_conf
    run supervisorctl reread
    run supervisorctl update
}

# Mirrors /usr/local/bin/orgo-hermes-gateway on Orgo's Hermes template:
# supervisord children get no HOME, the profile .env is folded in, and the
# gateway runs in this process because there is no systemd/s6 underneath.
gateway_wrapper() {
    if [ -x "$BIN_DIR/orgo-hermes-gateway" ]; then
        WRAPPER="$BIN_DIR/orgo-hermes-gateway"
        log "reusing Orgo gateway wrapper $WRAPPER"
        return 0
    fi
    WRAPPER="$BIN_DIR/alan-hermes-gateway"
    if [ -x "$WRAPPER" ]; then
        log "gateway wrapper already installed: $WRAPPER"
        return 0
    fi
    if [ "$DRY_RUN" = 1 ]; then
        log "would write $WRAPPER"
        return 0
    fi
    cat >"$WRAPPER" <<EOF
#!/usr/bin/env bash
# Written by bootstrap-orgo.sh. Mirrors orgo-hermes-gateway.
export HOME="$HOME"
export HERMES_HOME="$HERMES_HOME"
until [ -f "\$HERMES_HOME/config.yaml" ]; do sleep 15; done
set -a
[ -f "\$HOME/.env" ] && . "\$HOME/.env"
[ -f "\$HERMES_HOME/.env" ] && . "\$HERMES_HOME/.env"
set +a
exec hermes gateway run --no-supervise
EOF
    chmod 755 "$WRAPPER"
    log "wrote $WRAPPER"
}

# Orgo's Hermes template ships a platform-generated orgo.conf that already
# defines [program:hermes-gateway]. Reuse it; never add a second entry.
gateway_conf() {
    local conf cmd=""
    conf="$(first_conf_defining hermes-gateway)"
    if [ -n "$conf" ]; then
        cmd="$(conf_program_command "$conf" hermes-gateway)"
        if [ -z "$cmd" ]; then
            fix_conf_command "$conf" hermes-gateway "$WRAPPER"
            return 0
        fi
        if [ -x "$cmd" ] || have "${cmd##*/}"; then
            log "hermes-gateway already defined in $conf"
            return 0
        fi
        # A conf pointing at a missing binary would crash-loop forever —
        # put our wrapper at the path it references if we can write there.
        if [ "$DRY_RUN" = 0 ] && [ ! -e "$cmd" ] \
            && [ -w "$(dirname "$cmd")" ] && cp "$WRAPPER" "$cmd" 2>/dev/null; then
            chmod 755 "$cmd"
            log "installed the gateway wrapper at $cmd, which $conf pointed at but was missing"
            return 0
        fi
        log "WARNING: $conf defines hermes-gateway but '$cmd' is missing"
    fi
    if [ "$DRY_RUN" = 1 ]; then
        log "would write $SUPERVISOR_CONF_DIR/hermes-gateway.conf"
        return 0
    fi
    cat >"$SUPERVISOR_CONF_DIR/hermes-gateway.conf" <<EOF
; Written by bootstrap-orgo.sh — mirrors the hermes-gateway program in
; Orgo's platform-generated orgo.conf.
[program:hermes-gateway]
command=$WRAPPER
user=$(id -un)
autorestart=true
stopsignal=TERM
redirect_stderr=true
stdout_logfile=/var/log/alan-hermes-gateway.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=3
EOF
    log "wrote $SUPERVISOR_CONF_DIR/hermes-gateway.conf"
}

# --- step: alans-way -----------------------------------------------------

step_alans_way() {
    # setup.sh only knows systemd units, LaunchAgents and Scheduled Tasks for
    # the browser services; on Orgo (supervisord) we run it with
    # --skip-services and install the same programs as supervisord confs.
    local needs_supervisor=1
    have systemctl && needs_supervisor=0
    if [ -d "$HERMES_HOME/plugins/alans-way" ] \
        && { [ "$needs_supervisor" = 0 ] \
             || [ -f "$SUPERVISOR_CONF_DIR/alans-way.conf" ]; }; then
        log "alans-way already installed"
        return 0
    fi
    # Flags ride as real argv — folding $REPO_REF into a run_sh string would
    # let a quote or $(...) in it break out of the command.
    local setup_args=(--non-interactive)
    if [ "$needs_supervisor" = 1 ]; then
        setup_args+=(--skip-services)
    fi
    setup_args+=(--repo-ref "$REPO_REF")
    if [ "$DRY_RUN" = 1 ]; then
        log "would run: curl -fsSL $SETUP_URL_BASE/$REPO_REF/setup.sh | bash -s -- ${setup_args[*]}"
    else
        printf '+ %s\n' "curl -fsSL $SETUP_URL_BASE/$REPO_REF/setup.sh | bash -s -- ${setup_args[*]}" >>"$LOG_FILE"
        curl -fsSL "$SETUP_URL_BASE/$REPO_REF/setup.sh" 2>>"$LOG_FILE" \
            | bash -s -- "${setup_args[@]}" >>"$LOG_FILE" 2>&1
    fi
    if [ "$needs_supervisor" = 1 ]; then
        alans_way_conf
        run supervisorctl reread
        run supervisorctl update
    fi
}

# Mirrors /etc/supervisor/conf.d/alans-way.conf on Alex's Orgo computer: the
# two browser services setup.sh would install as systemd units on a normal
# VPS. mac-watch is left out — there is no user computer to watch yet.
alans_way_conf() {
    local conf="$SUPERVISOR_CONF_DIR/alans-way.conf"
    if [ -f "$conf" ]; then
        log "alans-way.conf already exists"
        return 0
    fi
    if [ "$DRY_RUN" = 1 ]; then
        log "would write $conf"
        return 0
    fi
    local node desktop_dir
    node="$(command -v node || echo /usr/bin/node)"
    if [ "$(id -u)" = 0 ]; then
        desktop_dir="/opt/hermes-alans-way/browser"
    else
        desktop_dir="$HOME/.local/share/hermes-alans-way/app"
    fi
    cat >"$conf" <<EOF
; Written by bootstrap-orgo.sh — Orgo has supervisord, not systemd, so the
; browser services setup.sh --skip-services skipped live here.
[program:alans-way-chromium]
command=$node $desktop_dir/desktop/scripts/vps-chromium-host.cjs
user=$(id -un)
environment=HOME="$HOME",DISPLAY=":99",HERMES_VPS_BROWSER_DATA="$HOME/.local/share/hermes-alans-way/browser"
priority=40
autorestart=unexpected
redirect_stderr=true
stdout_logfile=/var/log/alan-alans-way-chromium.log
stdout_logfile_maxbytes=10MB

[program:alans-way-browser]
command=$node $desktop_dir/desktop/scripts/vps-browser-host.cjs serve
user=$(id -un)
environment=HOME="$HOME",DISPLAY=":99",HERMES_VPS_BROWSER_DATA="$HOME/.local/share/hermes-alans-way/browser"
priority=41
autorestart=unexpected
exitcodes=78
redirect_stderr=true
stdout_logfile=/var/log/alan-alans-way-browser.log
stdout_logfile_maxbytes=10MB
EOF
    log "wrote $conf"
}

# --- step: tailscale -----------------------------------------------------

step_tailscale() {
    if have tailscale; then
        log "tailscale already installed: $(command -v tailscale)"
    else
        run_sh "curl -fsSL '$TAILSCALE_INSTALL_URL' | sh"
    fi
    tailscaled_conf
    sshd_conf
    tailnet_ssh_config
    if have supervisorctl; then
        run supervisorctl reread
        run supervisorctl update
    fi
    if tailscale_backend_running; then
        log "tailscale already connected"
        return 0
    fi
    capture_login_url
}

tailscaled_conf() {
    local conf cmd=""
    # Orgo VMs have no /dev/net/tun, so the daemon must run userspace — which
    # also means outbound tailnet traffic only works through its SOCKS5
    # server (ssh goes through the ProxyCommand added below), and the
    # tailscale CLI needs a fixed --socket to talk to it.
    local flags="--state=$TAILSCALE_STATE_DIR/tailscaled.state"
    if [ ! -e /dev/net/tun ]; then
        flags="--tun=userspace-networking --socks5-server=localhost:1055 --socket=$TAILSCALE_SOCKET $flags"
    fi
    conf="$(first_conf_defining tailscaled)"
    if [ -n "$conf" ]; then
        cmd="$(conf_program_command "$conf" tailscaled)"
        if [ -z "$cmd" ]; then
            fix_conf_command "$conf" tailscaled "tailscaled $flags"
            return 0
        fi
        if [ -x "$cmd" ] || have "${cmd##*/}"; then
            log "tailscaled already defined in $conf"
            return 0
        fi
        log "WARNING: $conf defines tailscaled but '$cmd' is missing"
    fi
    if [ "$DRY_RUN" = 1 ]; then
        log "would write $SUPERVISOR_CONF_DIR/tailscaled.conf (tailscaled $flags)"
        return 0
    fi
    mkdir -p "$TAILSCALE_STATE_DIR" "$(dirname "$TAILSCALE_SOCKET")"
    cat >"$SUPERVISOR_CONF_DIR/tailscaled.conf" <<EOF
; Written by bootstrap-orgo.sh — Orgo has no systemd unit for tailscaled.
[program:tailscaled]
command=tailscaled $flags
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/alan-tailscaled.log
stdout_logfile_maxbytes=10MB
EOF
    log "wrote $SUPERVISOR_CONF_DIR/tailscaled.conf"
}

# Inbound tailnet connections are forwarded to localhost ports when
# tailscaled runs userspace, so ssh lands on localhost:22 — an sshd must be
# running for `ssh user@alan-<id>` (and migrate.sh) to reach this computer.
# Orgo's hermes-agent template already supervises sshd; reuse any existing
# program and only install openssh-server when the binary is absent.
sshd_conf() {
    local conf cmd=""
    # A [program:sshd] section counts as defined even when its command= is
    # unparseable — a duplicate section breaks `supervisorctl reread`.
    conf="$(first_conf_defining sshd)"
    if [ -n "$conf" ]; then
        cmd="$(conf_program_command "$conf" sshd)"
        if [ -z "$cmd" ]; then
            log "WARNING: $conf defines sshd but has no command= line"
        elif [ ! -x "$cmd" ] && ! have "${cmd##*/}"; then
            log "WARNING: $conf defines sshd but '$cmd' is missing"
        fi
        log "sshd already defined under $SUPERVISOR_CONF_DIR"
        return 0
    fi
    conf="$(first_conf_running sshd)"
    if [ -n "$conf" ]; then
        log "sshd already supervised by $conf"
        return 0
    fi
    # A non-supervised sshd already bound to :22 (systemd on a DIY host)
    # works fine — adding a supervised one would just crash-loop on bind.
    if have ss && ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE '[:.]22$'; then
        log "port 22 is already served — not supervising a second sshd"
        return 0
    fi
    if [ "$DRY_RUN" = 1 ]; then
        log "would ensure openssh-server is installed and write $SUPERVISOR_CONF_DIR/sshd.conf"
        return 0
    fi
    if [ ! -x "$SSHD_BIN" ] && have apt-get; then
        run_sh "apt-get update && apt-get install -y openssh-server"
    fi
    if [ ! -x "$SSHD_BIN" ]; then
        log "WARNING: no sshd at $SSHD_BIN — inbound ssh to this computer will not work"
        return 0
    fi
    local keygen
    keygen="$(command -v ssh-keygen || echo ssh-keygen)"
    cat >"$BIN_DIR/alan-sshd" <<EOF
#!/bin/sh
# Written by bootstrap-orgo.sh.
mkdir -p /run/sshd
$keygen -A
exec $SSHD_BIN -D -e
EOF
    chmod 755 "$BIN_DIR/alan-sshd"
    cat >"$SUPERVISOR_CONF_DIR/sshd.conf" <<EOF
; Written by bootstrap-orgo.sh — inbound tailnet connections land on
; localhost:22, so sshd runs here the way Orgo's template supervises it.
[program:sshd]
command=$BIN_DIR/alan-sshd
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/alan-sshd.log
stdout_logfile_maxbytes=10MB
EOF
    log "wrote $SUPERVISOR_CONF_DIR/sshd.conf"
}

# With --tun=userspace-networking this computer cannot route to tailnet
# IPs, so outbound ssh to peers (e.g. back to the Mac) goes through
# tailscale nc. Managed block — the markers keep it idempotent.
tailnet_ssh_config() {
    local conf="$HOME/.ssh/config"
    if [ -f "$conf" ] && grep -q 'alan tailscale ssh' "$conf"; then
        log "tailnet ssh block already in $conf"
        return 0
    fi
    if [ "$DRY_RUN" = 1 ]; then
        log "would add a 'Host 100.*' ProxyCommand block to $conf"
        return 0
    fi
    mkdir -p "$HOME/.ssh"
    chmod 700 "$HOME/.ssh"
    cat >>"$conf" <<'EOF'

# >>> alan tailscale ssh >>>
# tailscaled runs with --tun=userspace-networking, so tailnet IPs are only
# reachable through tailscale nc.
Host 100.*
  ProxyCommand tailscale nc %h %p
# <<< alan tailscale ssh <<<
EOF
    chmod 600 "$conf"
    log "added the Host 100.* ProxyCommand block to $conf"
}

tailscale_backend_running() {
    tailscale status --json 2>/dev/null | python3 -c '
import json, sys
try:
    sys.exit(0 if json.load(sys.stdin).get("BackendState") == "Running" else 1)
except Exception:
    sys.exit(1)'
}

# `tailscale up` prints the login URL on stderr — sometimes only after a
# delay — and then blocks until the computer is paired. Run it in the
# background and grep its output for up to TAILSCALE_URL_TIMEOUT seconds.
capture_login_url() {
    local host="$ID"
    [ -n "$host" ] || host="$(hostname 2>/dev/null || echo orgo)"
    # The tailnet hostname is alan-<id> verbatim — lowercased, [a-z0-9-]
    # only, max 63 chars — never the OS hostname when --id was given.
    host="$(printf 'alan-%s' "$host" | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9-' | cut -c1-63)"
    [ "$host" = "alan-" ] && host="alan-orgo"
    if [ "$DRY_RUN" = 1 ]; then
        log "would run: tailscale up --hostname $host --timeout=0 (background, poll ${TAILSCALE_URL_TIMEOUT}s for a login URL)"
        if [ -n "$CALLBACK" ]; then
            log "would POST {id, secret, url} to $CALLBACK"
        else
            log "would print the login URL"
        fi
        return 0
    fi
    # A re-run can otherwise race a `tailscale up` from the previous attempt
    # that is still parked waiting for login.
    if have pkill; then
        run pkill -f 'tailscale up --hostname' || true
    fi
    local up_log="$STATE_DIR/.tailscale-up.$$.log"
    tailscale up --hostname "$host" --timeout=0 </dev/null >"$up_log" 2>&1 &
    local pid=$! deadline=$(( $(date +%s) + TAILSCALE_URL_TIMEOUT )) url=""
    while [ "$(date +%s)" -lt "$deadline" ]; do
        url="$(grep -oE "$LOGIN_URL_RE" "$up_log" 2>/dev/null | head -n 1 || true)"
        [ -n "$url" ] && break
        if ! kill -0 "$pid" 2>/dev/null; then
            sleep 1
            url="$(grep -oE "$LOGIN_URL_RE" "$up_log" 2>/dev/null | head -n 1 || true)"
            [ -n "$url" ] && break
            rm -f "$up_log"
            log "tailscale up exited without printing a login URL"
            return 1
        fi
        sleep 1
    done
    if [ -z "$url" ]; then
        kill "$pid" 2>/dev/null || true
        rm -f "$up_log"
        log "no Tailscale login URL within ${TAILSCALE_URL_TIMEOUT}s"
        return 1
    fi
    rm -f "$up_log"
    log "tailscale login URL: $url"
    if [ -n "$CALLBACK" ]; then
        local payload
        payload="$(python3 - "$ID" "$SECRET" "$url" <<'PY'
import json, sys
print(json.dumps({"id": sys.argv[1], "secret": sys.argv[2], "url": sys.argv[3]}))
PY
)"
        # The payload carries the provisioning secret — send it on stdin so
        # it lands neither in the log's `+ ...` line nor in argv for ps.
        printf '%s' "$payload" | run curl -fsSL -X POST \
            -H 'Content-Type: application/json' --data @- "$CALLBACK"
        log "posted the login URL to the callback"
    else
        printf '%s\n' "$url"
    fi
}

# --- step: ready ---------------------------------------------------------

step_ready() {
    state ready waiting_for_pairing
}

# --wait-paired: poll until the tailnet reports BackendState=Running, then
# record {state: ready, step: paired}.
wait_paired() {
    CURRENT_STEP="wait_paired"
    if [ "$DRY_RUN" = 1 ]; then
        log "would poll tailscale status --json until BackendState=Running"
        return 0
    fi
    if ! have tailscale; then
        log "tailscale is not installed — run the bootstrap first"
        return 1
    fi
    log "waiting for tailscale pairing"
    local deadline=0 now
    if [ "$WAIT_PAIRED_TIMEOUT" -gt 0 ]; then
        deadline=$(( $(date +%s) + WAIT_PAIRED_TIMEOUT ))
    fi
    while :; do
        if tailscale_backend_running; then
            state ready paired
            log "paired"
            return 0
        fi
        now="$(date +%s)"
        if [ "$deadline" -gt 0 ] && [ "$now" -ge "$deadline" ]; then
            log "timed out waiting for tailscale pairing"
            return 1
        fi
        sleep "$WAIT_PAIRED_INTERVAL"
    done
}

main() {
    if [ "$DRY_RUN" = 0 ]; then
        mkdir -p "$STATE_DIR" "$BIN_DIR" "$SUPERVISOR_CONF_DIR"
    fi
    if [ "$WAIT_PAIRED" = 1 ]; then
        wait_paired
        return 0
    fi
    local s
    for s in hermes alans-way tailscale ready; do
        run_step "$s"
    done
    log "done"
}

main
