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
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

# The same installer Alex's reference Orgo computer used: it git-clones
# NousResearch/hermes-agent and drops a shim on PATH.
HERMES_INSTALL_URL="https://hermes-agent.nousresearch.com/install.sh"
TAILSCALE_INSTALL_URL="https://tailscale.com/install.sh"
SETUP_URL_BASE="https://raw.githubusercontent.com/capthvnsen/alans-way-agents"
TAILSCALE_URL_TIMEOUT="${ALAN_TAILSCALE_URL_TIMEOUT:-120}"
WAIT_PAIRED_INTERVAL="${ALAN_WAIT_PAIRED_INTERVAL:-5}"
WAIT_PAIRED_TIMEOUT="${ALAN_WAIT_PAIRED_TIMEOUT:-0}"
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
    if grep -rl '^\[program:hermes-gateway\]' "$SUPERVISOR_CONF_DIR" >/dev/null 2>&1; then
        log "hermes-gateway already defined under $SUPERVISOR_CONF_DIR"
        return 0
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

# --- later steps ---------------------------------------------------------

step_alans_way() {
    log "(alans-way install not yet implemented)"
}

step_tailscale() {
    log "(tailscale install not yet implemented)"
}

step_ready() {
    state ready waiting_for_pairing
}

wait_paired() {
    CURRENT_STEP="wait_paired"
    log "waiting for tailscale pairing"
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
