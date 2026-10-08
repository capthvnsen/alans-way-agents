#!/bin/sh
# setup.sh — one-command Alan's Way bootstrap for the host running your Hermes
# gateway (usually a VPS). Detects what's missing, installs what it can, and
# prints exact guidance for what it can't.
#
#   curl -fsSL https://raw.githubusercontent.com/capthvnsen/alans-way-agents/main/setup.sh | bash -s -- --bot-id 123456789 --mac-ssh me@mymac
#   ./setup.sh --bot-id 123456789 --mac-ssh me@mymac            # from a clone
#   ./setup.sh --verify                                       # re-check an install
#
# On native Windows run it from Git Bash (the shell Hermes' terminal tool uses); WSL2 counts as Linux.
# Flags: --bot-id ID --bot-name NAME --mac-ssh HOST --profile NAME
#        --hermes-home DIR --desktop-dir DIR --repo-ref SHA --desktop-ref SHA
#        --host-os mac|windows|linux --mac-key KEY --mac-host-key KEY
#        --skip-browser --skip-plugin --skip-services --keep-browser --keep-computer-use --allow-desktop-actions
#        --cdp-port PORT --dev-plugin-install --bind --proactive yes|no --timezone IANA
#        --restart --non-interactive --verify
set -eu

REPO_URL="https://github.com/capthvnsen/alans-way-agents"
DESKTOP_REPO_URL="https://github.com/capthvnsen/alans-way"
PLUGIN_NAME="alans-way"

BOT_ID="" BOT_NAME="" MAC_SSH="" HOST_OS="" PROFILE="" CONFIG="" TIMEZONE="" PROACTIVE=""
MAC_KEY="" MAC_HOST_KEY="" DESKTOP_DIR="" REPO_REF="" DESKTOP_REF=""
ONLY_PROFILE=0
SKIP_BROWSER=0 SKIP_SERVICES=0 SKIP_PLUGIN=0 KEEP_BROWSER=0 KEEP_COMPUTER=0 ALLOW_DESKTOP=0 DO_BIND=0 DO_RESTART=0 NON_INTERACTIVE=0 VERIFY=0 DEV_PLUGIN=0
CDP_PORT_FLAG=""
MIN_HERMES="0.21.5"

while [ $# -gt 0 ]; do
  case "$1" in
    --bot-id) BOT_ID="$2"; shift 2;;
    --bot-name) BOT_NAME="$2"; shift 2;;
    --mac-ssh) MAC_SSH="$2"; shift 2;;
    --mac-key) MAC_KEY="$2"; shift 2;;
    --mac-host-key) MAC_HOST_KEY="$2"; shift 2;;
    --host-os) HOST_OS="$2"; shift 2;;
    --profile) PROFILE="$2"; ONLY_PROFILE=1; shift 2;;
    --config) CONFIG="$2"; shift 2;;
    --hermes-home) HERMES_HOME_FLAG="$2"; shift 2;;
    --desktop-dir) DESKTOP_DIR="$2"; shift 2;;
    --repo-ref) REPO_REF="$2"; shift 2;;
    --desktop-ref) DESKTOP_REF="$2"; shift 2;;
    --cdp-port) CDP_PORT_FLAG="$2"; shift 2;;
    --skip-browser) SKIP_BROWSER=1; shift;;
    --skip-plugin) SKIP_PLUGIN=1; shift;;
    --skip-services) SKIP_SERVICES=1; shift;;
    --keep-browser) KEEP_BROWSER=1; shift;;
    --keep-computer-use) KEEP_COMPUTER=1; shift;;
    --allow-desktop-actions) ALLOW_DESKTOP=1; shift;;
    --dev-plugin-install) DEV_PLUGIN=1; shift;;
    --bind) DO_BIND=1; shift;;
    --proactive) PROACTIVE="$2"; shift 2;;
    --timezone) TIMEZONE="$2"; shift 2;;
    --restart) DO_RESTART=1; shift;;
    --non-interactive) NON_INTERACTIVE=1; shift;;
    --verify) VERIFY=1; shift;;
    -h|--help)
      cat <<'EOF'
setup.sh: Alan's Way bootstrap for the Hermes gateway host (usually a VPS).
  --bot-id ID      numeric Telegram bot ID that owns browser tabs
  --bot-name NAME  display name on the agent cursor
  --mac-ssh HOST   how this host reaches your computer over ssh (Tailscale name/IP)
  --host-os OS     OS of that computer: mac (default), windows or linux
  --mac-key KEY    that computer's public key line (MAC_KEY); added to authorized_keys
  --mac-host-key K that computer's host key (MAC_HOST_KEY, "ssh-ed25519 AAAA..."); pinned in known_hosts
  --profile NAME   configure only this Hermes profile (default: the main config and
                   every profile that has a Telegram bot, each with its own bot ID)
  --bind           bind proactivity to a Telegram DM route (prompted; with
                   --non-interactive, binds the --profile's route, default main)
  --proactive yes|no  keep proactivity on (default) or pause it after binding
  --timezone IANA  your local zone for check-in hours, e.g. Europe/Berlin
  --restart        restart the gateway last, detached, once setup has finished
  --verify         check an existing install without changing anything
  --config FILE    edit this Hermes config.yaml instead of the profile's
  --hermes-home D  Hermes home directory (default: ~/.hermes)
  --desktop-dir D  where the alans-way app checkout lives (cloned if missing)
  --repo-ref SHA   pin this repo's clone/update to a reviewed commit or tag
  --desktop-ref SHA  pin the alans-way desktop repo clone/update the same way
  --cdp-port PORT  the managed browser's CDP port (default: keep the configured
                   one, else the first free port from 9223 up; ALANS_WAY_CDP_PORT
                   sets it too)
  --skip-plugin    leave an already installed plugin in place (catalog installs)
  --keep-browser   leave Hermes' built-in browser toolset on (setup turns it off
                   for Telegram and cron once the workspace browser is configured)
  --keep-computer-use  deprecated no-op kept for compatibility: setup never disables
                   the approval-gated computer_use toolset
  --allow-desktop-actions  manual opt-in only: stop Telegram approval prompts for
                   desktop control (click, type, key, scroll...) by adding them to
                   command_allowlist. On a Hermes without the computer-use provider
                   API it also exposes the ungated workspace_computer_action tool
  --dev-plugin-install  developer only: install the computer-use provider from this
                   clone (file://) instead of the Hermes catalog; the setup skill
                   and docs never pass it
  --skip-browser / --skip-services / --non-interactive for constrained runs
EOF
      exit 0;;
    *) echo "setup: unknown arg: $1" >&2; exit 2;;
  esac
done

case "$PROACTIVE" in ""|yes|no) ;; *) echo "setup: --proactive must be yes or no" >&2; exit 2;; esac
for _port in "$CDP_PORT_FLAG" "${ALANS_WAY_CDP_PORT:-}"; do
  [ -z "$_port" ] && continue
  case "$_port" in *[!0-9]*|'') _port=bad;; esac
  [ "$_port" != bad ] && [ "$_port" -ge 1 ] 2>/dev/null && [ "$_port" -le 65535 ] \
    || { echo "setup: --cdp-port must be a port number 1-65535" >&2; exit 2; }
done

# The guest is the machine setup.sh runs on (Hermes' home); the host is the
# user's computer reached over --mac-ssh. Git Bash, MSYS2 and Cygwin are a
# native-Windows guest; WSL reports Linux and is treated as one.
GUEST_RAW="$(uname -s 2>/dev/null || echo Linux)"
case "$GUEST_RAW" in
  Darwin) GUEST_OS=Darwin;;
  MINGW*|MSYS*|CYGWIN*) GUEST_OS=Windows;;
  *) GUEST_OS=Linux;;
esac
# Native Windows tools (node, hermes, python, git clone URLs) want C:/ paths, not
# /c/ ones. MSYS must not rewrite the strings handed to ssh and icacls either.
wpath() { if [ "$GUEST_OS" = Windows ]; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
[ "$GUEST_OS" != Windows ] || export MSYS2_ARG_CONV_EXCL='*' MSYS_NO_PATHCONV=1

# An exported HERMES_HOME is the operator's choice; --hermes-home overrides it.
# Exported so every hermes call below sees the home this script writes to.
[ -z "${HERMES_HOME_FLAG:-}" ] || HERMES_HOME="$HERMES_HOME_FLAG"
if [ "$GUEST_OS" = Windows ]; then
  # Hermes' own default is %LOCALAPPDATA%\hermes.
  [ -z "${HERMES_HOME:-}" ] || HERMES_HOME="$(wpath "$HERMES_HOME")"
  HERMES_HOME="${HERMES_HOME:-$(wpath "${LOCALAPPDATA:-$HOME/AppData/Local}")/hermes}"
else
  HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
fi
# Inside a profile's gateway HERMES_HOME is <root>/profiles/<name> (hermes_cli
# profile_root_for_env_home): the root is two levels up and that profile is the
# one to configure unless --profile names another.
case "$HERMES_HOME" in
  */profiles/*)
    _env_profile="${HERMES_HOME##*/profiles/}"
    case "$_env_profile" in
      ''|*/*) ;;
      *) HERMES_HOME="${HERMES_HOME%/profiles/*}"; [ -n "$PROFILE" ] || PROFILE="$_env_profile";;
    esac;;
esac
export HERMES_HOME
[ -z "$PROFILE" ] && [ -z "$CONFIG" ] || ONLY_PROFILE=1
[ "$PROFILE" != default ] || PROFILE=""
case "$PROFILE" in
  -*|.*|*[!0-9A-Za-z_.-]*) echo "setup: invalid --profile '$PROFILE' (letters, digits, dots, dashes and underscores only)" >&2; exit 2;;
esac
# Plugins, their install metadata and the profile's hooks live under the
# profile's own home once hermes is told which profile to act on. The default
# profile is named too, so a sticky active_profile can never redirect a call.
PROFILE_HOME="${PROFILE:+$HERMES_HOME/profiles/$PROFILE}"; PROFILE_HOME="${PROFILE_HOME:-$HERMES_HOME}"
hermes_p() { hermes -p "${PROFILE:-default}" "$@"; }
# Whole-name match: "alans-way" must not be satisfied by "alans-way-computer".
plugin_listed() { hermes_p plugins list 2>/dev/null | grep -qE "(^|[^A-Za-z0-9_-])$1([^A-Za-z0-9_-]|\$)"; }

# Refs drive git fetch/checkout — reject anything that isn't a plain ref.
for _ref in "$REPO_REF" "$DESKTOP_REF"; do
  [ -z "$_ref" ] && continue
  case "$_ref" in -*|*:*|*..*|*[!A-Za-z0-9._/-]*)
    echo "setup: invalid ref '$_ref'" >&2; exit 2;;
  esac
done

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
ok()   { printf '  ok   %s\n' "$*"; }
warn() { printf '  warn %s\n' "$*"; }
skip() { printf '  skip %s\n' "$*"; }
bad()  { printf '  FAIL %s\n' "$*"; FAILS=$((FAILS + 1)); }
FAILS=0

# Agent shells often have a readable /dev/tty node but no terminal behind it;
# only an open that succeeds means a human can answer.
# dash (Ubuntu's /bin/sh) exits the whole script under set -e when a function's
# last command fails, even if the caller is inside `if`. Keep every check in
# an if so a missing terminal returns 1 instead of aborting setup.
has_tty() {
  if [ "$NON_INTERACTIVE" = 1 ]; then return 1; fi
  if (: < /dev/tty) 2>/dev/null; then return 0; fi
  return 1
}
ask() { # ask <prompt> <default>: reads /dev/tty so curl|bash still prompts
  if ! has_tty; then printf '%s' "$2"; return; fi
  printf '%s [%s] ' "$1" "$2" > /dev/tty
  read -r reply < /dev/tty || reply=""
  printf '%s' "${reply:-$2}"
}

confirm() { # confirm <prompt>: empty means no
  reply="$(ask "$1 [y/N]" "n")"
  case "$reply" in y|Y|yes) return 0;; *) return 1;; esac
}

# ALANS_WAY_MISSING lets a test pretend a binary is absent: fakes can add
# commands but cannot remove real ones from PATH.
have() {
  case " ${ALANS_WAY_MISSING:-} " in *" $1 "*) return 1;; esac
  command -v "$1" >/dev/null 2>&1
}

# write_if_changed <file> [backup]: content on stdin; sets WROTE=1 only when the
# file's content actually changed, so an upgrade refreshes stale paths and an
# unchanged re-run touches nothing.
write_if_changed() {
  _new="$(cat)"
  WROTE=0
  if [ -f "$1" ] && [ "$(cat "$1")" = "$_new" ]; then return 0; fi
  if [ -f "$1" ] && [ -n "${2:-}" ]; then cp "$1" "$1.bak"; fi
  printf '%s\n' "$_new" > "$1" || return 1
  WROTE=1
}

# A VM image can ship the systemctl binary while PID 1 is something else (an
# init shim, supervisord, a container). Units written on such a host are dead:
# only call systemctl when systemd is actually running. /run/systemd/system is
# systemd's own booted marker (sd_booted); is-system-running answers "offline"
# on the dead case and "running"/"degraded" on a live one.
systemd_live() {
  have systemctl || return 1
  case "$(systemctl is-system-running 2>/dev/null || true)" in
    running|degraded|starting|initializing|maintenance) return 0;;
    # No answer at all: fall back to systemd's own booted marker (sd_booted).
    '') [ -d /run/systemd/system ] && return 0;;
  esac
  return 1
}

# Userspace-networking Tailscale (common on cloud VMs that can't load kernel
# modules) has no tailscale0 interface, so the ssh client cannot route to
# tailnet addresses: those hosts need `tailscale nc` as a ProxyCommand. Kernel
# Tailscale sets TUN=true in `tailscale status --json` and has the interface.
tailscale_userspace() {
  [ "$GUEST_OS" = Linux ] || return 1
  have "$TAILSCALE" || return 1
  [ ! -e "${ALANS_WAY_SYS_CLASS_NET:-/sys/class/net}/tailscale0" ] || return 1
  "$TAILSCALE" status --json 2>/dev/null | python3 -c 'import json, sys
try: s = json.load(sys.stdin)
except Exception: sys.exit(1)
sys.exit(0 if s.get("BackendState") == "Running" and s.get("TUN") is False else 1)'
}

# The display the browser services should export. A running X/VNC server's own
# display wins (that is the desktop the user actually sees; a bare socket may
# belong to a console X), then a live X socket, then the conventional fallback
# (:99) so the units and the install docs below stay consistent.
detect_display() {
  _line="$(pgrep -af 'Xtigervnc|Xvfb|Xvnc|x0vncserver|x11vnc|Xephyr' 2>/dev/null | head -1 || true)"
  _d="$(printf '%s\n' "$_line" | grep -oE '[[:space:]]:[0-9]+' | head -1 | tr -d ' ')"
  [ -n "$_d" ] && { printf '%s' "$_d"; return 0; }
  for _sock in "${ALANS_WAY_X11_DIR:-/tmp/.X11-unix}"/X[0-9]*; do
    [ -S "$_sock" ] || continue
    _n="${_sock##*X}"
    case "$_n" in ''|*[!0-9]*) continue;; esac
    echo ":$_n"; return 0
  done
  printf '%s' "${1:-:99}"
}

# A display stack the browser can run on: a live X socket, a running X/VNC
# server, websockify bridging one over noVNC, or a server binary on PATH.
display_stack_present() {
  for _sock in "${ALANS_WAY_X11_DIR:-/tmp/.X11-unix}"/X[0-9]*; do
    [ -S "$_sock" ] && return 0
  done
  pgrep -f 'Xtigervnc|Xvfb|Xvnc|x0vncserver|x11vnc|Xephyr|websockify' >/dev/null 2>&1 && return 0
  have Xvfb || have x11vnc || have Xtigervnc || have x0vncserver || have Xvnc || have websockify
}

# The noVNC listen port of a running websockify, else nothing. websockify argv
# is "websockify [opts] [listen_addr:]port target" — the first bare port or
# addr:port token is the listener.
websockify_port() {
  _line="$(pgrep -af websockify 2>/dev/null | head -1)"
  [ -n "$_line" ] || return 1
  for _tok in ${_line#* }; do
    case "$_tok" in
      *:*) case "${_tok%%:*}" in ''|*[!0-9.]*) continue;; esac; _p="${_tok##*:}";;
      *) _p="$_tok";;
    esac
    case "$_p" in ''|*[!0-9]*) continue;; esac
    [ "$_p" -gt 0 ] 2>/dev/null && [ "$_p" -le 65535 ] 2>/dev/null || continue
    echo "$_p"; return 0
  done
  return 1
}

# supervisord that is actually answering, not just installed. `status` cannot
# prove that: it exits nonzero whenever any program is not RUNNING (an EXITED
# or FATAL entry makes a healthy daemon look dead). `pid` prints the daemon's
# own pid whenever it answers.
supervisord_usable() {
  have supervisorctl || return 1
  case "$(supervisorctl pid 2>/dev/null)" in ''|*[!0-9]*|0) return 1;; esac
}

# The directory a [program:*] drop-in goes in: the include glob of the running
# daemon's own conf (a host can carry a stock conf it never reads; relative
# `files` globs resolve against that file's directory), then the stock confs,
# then the Debian and CentOS conventions.
supervisor_conf_dir() {
  [ -z "${ALANS_WAY_SUPERVISOR_CONF_DIR:-}" ] || { printf '%s' "$ALANS_WAY_SUPERVISOR_CONF_DIR"; return 0; }
  _confs="/etc/supervisor/supervisord.conf /etc/supervisord.conf"
  _live="$(pgrep -af supervisord 2>/dev/null | sed -n 's/.* -c  *\([^ ]*\).*/\1/p' | head -1)"
  [ -z "$_live" ] || _confs="$_live $_confs"
  for _f in $_confs; do
    for _d in $(sed -n 's/^ *files *= *//p' "$_f" 2>/dev/null); do
      case "$_d" in
        /*) printf '%s' "${_d%/*}"; return 0;;
        */*) printf '%s' "${_f%/*}/${_d%/*}"; return 0;;
        *) printf '%s' "${_f%/*}"; return 0;;
      esac
    done
  done
  for _d in /etc/supervisor/conf.d /etc/supervisord.d; do
    [ -d "$_d" ] && { printf '%s' "$_d"; return 0; }
  done
  [ "$(id -u)" = 0 ] && { printf '%s' /etc/supervisor/conf.d; return 0; }
  return 1
}

# The supervisor program whose command line (or a child's, for wrapper
# scripts) runs `hermes gateway run`. The name is discovered, never assumed,
# and a non-Hermes "gateway run" is never touched. With several gateway
# programs, the one serving the profile being configured wins: -p <profile>,
# or an argv with no -p when the default profile is the target.
supervisor_gateway_program() {
  [ "$GUEST_OS" = Linux ] || return 1
  have supervisorctl && have ps || return 1
  _any=""
  for _prog in $(supervisorctl status 2>/dev/null | awk '$2 == "RUNNING" {print $1}'); do
    _pid="$(supervisorctl pid "$_prog" 2>/dev/null || true)"
    case "$_pid" in ''|*[!0-9]*|0) continue;; esac
    for _cand in "$_pid" $(pgrep -P "$_pid" 2>/dev/null); do
      _args="$(ps -o args= -p "$_cand" 2>/dev/null || true)"
      case "$_args" in
        *hermes*"-p ${PROFILE:-default} "*"gateway run"*) echo "$_prog"; return 0;;
        *"-p "*"gateway run"*) :;;   # another profile's gateway
        *hermes*"gateway run"*) [ -n "$_any" ] || _any="$_prog";;
      esac
    done
  done
  [ -z "$_any" ] || { echo "$_any"; return 0; }
  return 1
}

# GNU stat -c %Y, BSD stat -f %m.
file_mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0; }

# True when nothing listens on 127.0.0.1:$1: the managed browser's debugging
# socket must not collide with another browser or service.
port_free() {
  python3 - "$1" <<'PY'
import socket, sys
sock = socket.socket()
try:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
except (OSError, ValueError):
    sys.exit(1)
finally:
    sock.close()
PY
}

# The cdpUrl port an existing config.json already uses, else empty.
configured_cdp_port() {
  python3 - "$1" 2>/dev/null <<'PY'
import json, re, sys
try:
    cfg = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
m = re.search(r":(\d+)(?:[/][^\s]*)?$", str(cfg.get("cdpUrl") or ""))
if m:
    print(m.group(1))
PY
}

# Where the availability watcher's state file lives on this guest, matching
# the router's own default chain (workspace-router.cjs macStateFile). On Linux
# the router default is /var/lib/hermes-alans-way; a non-root watcher can't
# write there, so setup points both processes at a user path instead.
mac_state_path() {
  if [ -n "${HERMES_MAC_STATE_FILE:-}" ]; then
    printf '%s' "$HERMES_MAC_STATE_FILE"; return 0
  fi
  case "$GUEST_OS" in
    Darwin) printf '%s' "$HOME/Library/Application Support/hermes-alans-way/mac-state.json";;
    Windows) printf '%s' "$BROWSER_HOME/.local/share/hermes-alans-way/mac-state.json";;
    *) if [ "$(id -u)" = 0 ] || [ -f /var/lib/hermes-alans-way/mac-state.json ]; then
         printf '%s' /var/lib/hermes-alans-way/mac-state.json
       else
         printf '%s' "$BROWSER_HOME/.local/share/hermes-alans-way/mac-state.json"
       fi;;
  esac
}


# The state of the workspace_browser block's desktop-input gate in config $1:
#   opt-in    the --allow-desktop-actions marker env is present
#   excluded  workspace_computer_action sits under the block's tools.exclude
#   exposed   a workspace_browser block exists without either
#   absent    no workspace_browser block at all
# Anchored on the managed markers when they exist (a bare grep would accept the
# tool name in a comment or under another server's exclude); without markers
# the bare workspace_browser entry is audited instead.
workspace_block_state() {
  [ -f "$1" ] || { echo absent; return 0; }
  python3 - "$1" <<'PY'
import re, sys
MARK_B = "# >>> alans-way workspace_browser managed block >>>"
MARK_E = "# <<< alans-way workspace_browser managed block <<<"
try:
    raw = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
except OSError:
    print("absent")
    sys.exit(0)
lines, inside, saw = [], False, False
for line in raw:
    text = line.strip()
    if text == MARK_B:
        inside, saw = True, True
        continue
    if text == MARK_E:
        inside = False
        continue
    if inside:
        lines.append(line)
if not saw:
    lines = raw
if not any(not l.lstrip().startswith("#") and re.match(r"\s*workspace_browser\s*:", l) for l in lines):
    print("absent")
    sys.exit(0)
if any(not l.lstrip().startswith("#") and re.match(
        r"\s*HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS\s*:", l) for l in lines):
    print("opt-in")
    sys.exit(0)
stack, excl = [], None
for line in lines:
    text = line.strip()
    if not text or text.startswith("#"):
        continue
    item = re.match(r"^(\s*)-\s+(\S+)", line)
    if excl is not None:
        if item and len(item.group(1)) > excl:
            if item.group(2).strip("\"'").rstrip(",") == "workspace_computer_action":
                print("excluded")
                sys.exit(0)
            continue
        excl = None
    key = re.match(r"^(\s*)([\w.\"'-]+):\s*(.*?)\s*$", line)
    if not key:
        continue
    depth = len(key.group(1))
    while stack and stack[-1][0] >= depth:
        stack.pop()
    stack.append((depth, key.group(2).strip("\"'")))
    keys = [k for _, k in stack]
    value = key.group(3)
    if keys[-3:] == ["workspace_browser", "tools", "exclude"]:
        if re.search(r"\bworkspace_computer_action\b", value):
            print("excluded")
            sys.exit(0)
        if not value:
            excl = depth
    elif keys[-2:] == ["workspace_browser", "tools"] and re.search(
            r"exclude[^\n]*\bworkspace_computer_action\b", value):
        print("excluded")
        sys.exit(0)
print("exposed")
PY
}

# True when the computer-use provider is installed for the profile in scope.
computer_provider_present() {
  plugin_listed alans-way-computer && return 0
  _home="$HERMES_HOME"
  [ -z "$PROFILE" ] || _home="$HERMES_HOME/profiles/$PROFILE"
  [ -d "$_home/plugins/alans-way-computer" ]
}

# The provider's fallback computer path on this host needs a few desktop
# pieces on Linux; missing ones are warnings, not silent skips.
check_linux_desktop_deps() {
  [ "$GUEST_OS" = Linux ] || return 0
  computer_provider_present || return 0
  have xdotool \
    || warn "xdotool missing: keyboard and pointer control on this host needs it (install: apt-get install xdotool)"
  have scrot || have import || have maim \
    || warn "no screenshot tool (scrot, maim or ImageMagick's import): desktop screenshots from this host need one (install: apt-get install scrot)"
  have at-spi-bus-launcher || pgrep -f at-spi-bus >/dev/null 2>&1 \
    || warn "AT-SPI accessibility bus not found: app and UI-element listing on this host needs it (install: apt-get install at-spi2-core)"
  python3 -c 'import gi' >/dev/null 2>&1 \
    || warn "python3-gi missing: the accessibility tree on this host needs PyGObject (install: apt-get install python3-gi)"
}

# The managed block's desktop-input exclusion is audited on every run: a block
# that predates this setup or was hand-edited keeps the ungated tool registered
# even when the provider is the selected backend. When the provider is
# selected, its own doctor runs too; otherwise the built-in toolset stays on
# (it is approval-gated).
check_computer_provider() {
  _cfg="$HERMES_HOME/config.yaml"
  if [ -n "$PROFILE" ]; then
    _cfg="$HERMES_HOME/profiles/$PROFILE/config.yaml"
  elif [ -n "$CONFIG" ]; then
    _cfg="$CONFIG"
  fi
  case "$(workspace_block_state "$_cfg")" in
    opt-in) ok "workspace_computer_action exposed by explicit opt-in (--allow-desktop-actions)${PROFILE:+ in profile $PROFILE}";;
    excluded) ok "ungated desktop input excluded from workspace_browser${PROFILE:+ in profile $PROFILE}";;
    exposed) warn "workspace_browser in $_cfg does not exclude workspace_computer_action, an ungated desktop-input tool: re-run setup, or pass --allow-desktop-actions to keep it deliberately";;
  esac
  have hermes || return 0
  if [ "$(hermes_p config get computer_use.backend 2>/dev/null | tail -1)" != alans-way-computer ]; then
    computer_provider_present \
      && warn "alans-way-computer is installed but not the configured backend: computer use stays on Hermes' built-in path (run: hermes${PROFILE:+ -p $PROFILE} config set computer_use.backend alans-way-computer)"
    return 0
  fi
  if hermes_p computer-use doctor >/dev/null 2>&1; then
    ok "computer-use provider passes hermes computer-use doctor"
  else
    bad "computer-use doctor reports a problem: run hermes${PROFILE:+ -p $PROFILE} computer-use doctor"
  fi
}

# The numeric bot id of a profile's Telegram bot, read the way Hermes does: the
# profile's .env TELEGRAM_BOT_TOKEN wins over config.yaml platforms.telegram.token
# (or botToken). `token_bot_id home DIR` reads both, `token_bot_id env FILE` one
# .env file. Prints one line, never a token:
#   ok ID [OTHER]   OTHER is the config.yaml bot when it differs from the .env one
#   none            no bot here
#   unreadable FILE the file is not valid UTF-8 text
token_bot_id() {
  python3 - "$1" "$(wpath "$2")" <<'PY'
import os, re, sys
mode, path = sys.argv[1], sys.argv[2]
def clean(value):
    m = re.match(r"""("([^"]*)"|'([^']*)'|[^\s#]+)""", value.strip())
    return (m.group(2) or m.group(3) or m.group(1)) if m else ""
def bot(token):
    m = re.match(r"(\d+):", token)
    return m.group(1) if m else None
def lines(file):
    try:
        with open(file, encoding="utf-8-sig") as handle:
            return handle.read().splitlines()
    except FileNotFoundError:
        return []
    except (UnicodeDecodeError, OSError):
        print("unreadable " + os.path.basename(file))
        sys.exit(0)
def env_id(file):
    found = None
    for line in lines(file):
        m = re.match(r"\s*(?:export\s+)?TELEGRAM_BOT_TOKEN\s*=\s*(.*)$", line)
        if m:
            found = bot(clean(m.group(1))) or found
    return found
def config_id(file):
    path_keys = []
    for line in lines(file):
        m = re.match(r"( *)([A-Za-z_][\w-]*):(.*)$", line)
        if not m:
            continue
        depth, key, rest = len(m.group(1)), m.group(2), m.group(3).strip()
        while path_keys and path_keys[-1][0] >= depth:
            path_keys.pop()
        names = [k for _, k in path_keys]
        if not rest or rest.startswith("#"):
            path_keys.append((depth, key))
        elif names == ["platforms", "telegram"] and key in ("token", "botToken"):
            if bot(clean(rest)):
                return bot(clean(rest))
        elif names == ["platforms"] and key == "telegram" and rest.startswith("{"):
            for t in re.findall(r"\b(?:token|botToken)\s*:\s*(\"[^\"]*\"|'[^']*'|[^\s,}]+)", rest):
                if bot(clean(t)):
                    return bot(clean(t))
    return None
if mode == "env":
    found, other = env_id(path), None
else:
    found, other = env_id(os.path.join(path, ".env")), config_id(os.path.join(path, "config.yaml"))
if not (found or other):
    print("none")
else:
    print("ok %s%s" % (found or other, " " + other if found and other and other != found else ""))
PY
}

# True when $1 >= $2, comparing dotted numbers part by part.
version_ge() {
  awk -v a="$1" -v b="$2" 'BEGIN { n = split(a, x, "."); m = split(b, y, "."); if (m > n) n = m
    for (i = 1; i <= n; i++) { p = x[i] + 0; q = y[i] + 0; if (p > q) exit 0; if (p < q) exit 1 }; exit 0 }'
}

# The browser services run as the account that runs Hermes: the router reads the
# browser host's connection.json from that account's home. When setup is run as root
# for a Hermes that a normal account owns, the services drop to that account.
BROWSER_USER="$(id -un)"; BROWSER_HOME="$HOME"
if [ "$GUEST_OS" = Windows ]; then
  BROWSER_USER="${USERNAME:-$BROWSER_USER}"
  BROWSER_HOME="$(cygpath -u "${USERPROFILE:-$HOME}")"
elif [ "$(id -u)" = 0 ] && [ -d "$HERMES_HOME" ]; then
  _owner="$(stat -c '%U' "$HERMES_HOME" 2>/dev/null || stat -f '%Su' "$HERMES_HOME" 2>/dev/null || true)"
  case "$_owner" in
    ''|root|*[!A-Za-z0-9._-]*) ;;
    *)
      BROWSER_USER="$_owner"
      BROWSER_HOME="$(getent passwd "$_owner" 2>/dev/null | cut -d: -f6 || true)"
      [ -n "$BROWSER_HOME" ] || BROWSER_HOME="$(eval echo "~$_owner")"
      case "$BROWSER_HOME" in /*) ;; *) BROWSER_HOME="$HOME";; esac;;
  esac
fi

# The availability watcher and the serving router must agree on the state file:
# carry the resolved path into the managed block env on every run so a non-root
# install does not strand the router on the /var/lib default while the watcher
# writes a user path. Windows resolves its own default and a cygpath value
# would not parse for the native router, so it is skipped.
if [ -n "$MAC_SSH" ] && [ "$GUEST_OS" != Windows ]; then
  ALANS_WAY_MAC_STATE_FILE="$(mac_state_path)"; export ALANS_WAY_MAC_STATE_FILE
fi

# Resolve the plugin repo: beside this script when run from a clone, else clone.
SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo "")"
if [ -f "$SCRIPT_DIR/setup-workspace.sh" ] && [ -d "$SCRIPT_DIR/alans-way" ]; then
  REPO_DIR="$SCRIPT_DIR"
else
  REPO_DIR=""
fi

case "$GUEST_RAW" in
  Darwin|Linux|MINGW*|MSYS*|CYGWIN*) ;;
  *) warn "guest OS '$GUEST_RAW' untested: assuming Linux paths";;
esac
case "${HOST_OS:-mac}" in
  mac|windows|linux) HOST_OS="${HOST_OS:-mac}";;
  *) echo "setup: --host-os must be mac, windows or linux" >&2; exit 2;;
esac

# --mac-ssh lands in ssh/scp argv and in unit files: user@host or host, plain characters only.
MAC_USER="" MAC_HOST="$MAC_SSH"
case "$MAC_SSH" in *@*) MAC_USER="${MAC_SSH%%@*}"; MAC_HOST="${MAC_SSH#*@}";; esac
if [ -n "$MAC_SSH" ]; then
  _bad=0
  case "$MAC_SSH" in *@*@*) _bad=1;; esac
  case "$MAC_SSH" in *@*) [ -n "$MAC_USER" ] || _bad=1;; esac
  case "$MAC_USER" in -*|*[!A-Za-z0-9._-]*) _bad=1;; esac
  case "$MAC_HOST" in ''|-*|.*|*[!A-Za-z0-9.:-]*) _bad=1;; esac
  [ "$_bad" = 0 ] || { echo "setup: invalid --mac-ssh '$MAC_SSH' (use user@host or host: letters, digits, dots, dashes, underscores; no spaces, and nothing may start with '-')" >&2; exit 2; }
fi

# A pasted public key line becomes a line in authorized_keys or known_hosts. Accept exactly
# one plain key line, never an option prefix, and refuse anything else untouched.
KEY_TYPES='(ssh-ed25519|sk-ssh-ed25519@openssh[.]com|ecdsa-sha2-nistp(256|384|521)|sk-ecdsa-sha2-nistp256@openssh[.]com|ssh-rsa)'
KEY_BLOB='[A-Za-z0-9+/]{20,}={0,3}'
is_one_line() { [ "$(printf '%s\n' "$1" | wc -l | tr -d ' ')" = 1 ]; }
if [ -n "$MAC_KEY" ]; then
  if is_one_line "$MAC_KEY" && printf '%s\n' "$MAC_KEY" | grep -Eq "^$KEY_TYPES $KEY_BLOB( [^[:cntrl:]]*)?\$"; then :; else
    echo "setup: invalid --mac-key: expected one public key line such as 'ssh-ed25519 AAAA... comment' (no options, no extra lines)" >&2; exit 2
  fi
fi
if [ -n "$MAC_HOST_KEY" ]; then
  [ -n "$MAC_SSH" ] || { echo "setup: --mac-host-key needs --mac-ssh (it pins that computer's address)" >&2; exit 2; }
  if is_one_line "$MAC_HOST_KEY" && printf '%s\n' "$MAC_HOST_KEY" | grep -Eq "^$KEY_TYPES $KEY_BLOB\$"; then :; else
    echo "setup: invalid --mac-host-key: expected 'ssh-ed25519 AAAA...' (the host key only, no address)" >&2; exit 2
  fi
fi

# ---------------------------------------------------------------- preflight
step "Preflight"
if ! have hermes; then
  bad "hermes not on PATH: install Hermes >= $MIN_HERMES first: https://github.com/NousResearch/hermes-agent"
else
  HERMES_V="$(hermes --version 2>/dev/null | grep -o '[0-9][0-9.]*' | head -1 || true)"
  if [ -z "$HERMES_V" ]; then
    warn "could not read the hermes version (this plugin needs $MIN_HERMES or newer)"
  elif version_ge "$HERMES_V" "$MIN_HERMES"; then
    ok "hermes $HERMES_V"
  else
    bad "hermes $HERMES_V is older than $MIN_HERMES, which this plugin requires. Update Hermes (hermes update), then run setup again."
    say "setup: stopped."
    exit 1
  fi
fi
if [ "$GUEST_OS" = Windows ]; then
  # Windows ships python.exe, and python3 is often a Microsoft Store stub that is
  # not Python. The first real Python 3 wins; HERMES_PYTHON is the last resort.
  for _py in python3 python "${HERMES_PYTHON:-}"; do
    [ -n "$_py" ] || continue
    "$_py" -c 'import sys; sys.exit(sys.version_info[0] != 3)' >/dev/null 2>&1 || continue
    ALANS_WAY_PYTHON="$(command -v "$_py")"; export ALANS_WAY_PYTHON
    python3() { "$ALANS_WAY_PYTHON" "$@"; }
    break
  done
  have python3 || bad "python 3 required: install it (winget install Python.Python.3.12) or set HERMES_PYTHON to a python.exe"
fi
have python3 || bad "python3 required"
MIN_NODE_MAJOR=22
if have node; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || true)"
  if [ -n "$NODE_MAJOR" ] && [ "$NODE_MAJOR" -ge "$MIN_NODE_MAJOR" ] 2>/dev/null; then
    ok "node $(node --version 2>/dev/null | sed 's/^v//') (>= $MIN_NODE_MAJOR required for browser connector scripts)"
  else
    bad "node $(node --version 2>/dev/null | sed 's/^v//') is below $MIN_NODE_MAJOR: upgrade Node before running setup (browser host and router scripts need fetch/AbortSignal.timeout)"
  fi
else
  bad "node not on PATH: Node $MIN_NODE_MAJOR+ required for the browser connector"
fi
[ -d "$HERMES_HOME" ] && ok "HERMES_HOME: $HERMES_HOME" || warn "HERMES_HOME $HERMES_HOME does not exist yet (created on first hermes run)"

if [ "$VERIFY" = 1 ]; then
  # --verify: report state without changing anything
  step "Install state"
  have hermes && plugin_listed "$PLUGIN_NAME" \
    && ok "plugin '$PLUGIN_NAME' installed" || bad "plugin '$PLUGIN_NAME' not in hermes plugins list"
  CFG_HOME="${PROFILE:+$HERMES_HOME/profiles/$PROFILE}"; CFG_HOME="${CFG_HOME:-$HERMES_HOME}"
  if have hermes; then
    # Hermes resolves presets and flow/block YAML itself; grepping the config
    # misreads both and matches other sections' telegram lists.
    TOOLS="$(hermes_p tools list --platform telegram 2>/dev/null || true)"
    if printf '%s\n' "$TOOLS" | grep -Eq "enabled[[:space:]]+proactivity([[:space:]]|$)"; then
      ok "proactivity toolset enabled for telegram"
    else
      bad "proactivity toolset not enabled for telegram: the proactivity tool won't be callable in those sessions (run: hermes tools enable proactivity --platform telegram)"
    fi
    if [ "$KEEP_BROWSER" = 1 ]; then
      skip "built-in browser toolset check (--keep-browser)"
    else
      for platform in telegram cron; do
        _platform_tools="$TOOLS"
        [ "$platform" = telegram ] || _platform_tools="$(hermes_p tools list --platform "$platform" 2>/dev/null || true)"
        if printf '%s\n' "$_platform_tools" | grep -Eq "enabled[[:space:]]+browser([[:space:]]|$)"; then
          warn "built-in 'browser' toolset still enabled for $platform: the agent may bypass the workspace browser (run: hermes tools disable browser --platform $platform)"
        else
          ok "built-in browser toolset disabled for $platform"
        fi
      done
    fi
  fi
  if have hermes; then
    PSTATE="$(hermes_p proactivity status 2>/dev/null | python3 -c 'import json,sys
try: s=json.load(sys.stdin)
except Exception: s={}
print("bound" if s.get("bound") else "unbound", "paused" if s.get("paused") is True else "on",
      "tz-missing" if s.get("timezone_known") is False else "tz-known")' 2>/dev/null)"
    case "$PSTATE" in
      "bound on "*) ok "proactivity on for the bound primary route";;
      "bound paused "*) warn "proactivity bound but paused: the bot never messages first (send /proactivity resume in the bound chat)";;
      *) warn "no primary route bound: proactivity is off (run: setup.sh --bind)";;
    esac
    case "$PSTATE" in
      *tz-missing) warn "proactivity does not know your timezone: check-in hours may fire at the wrong time (set it: hermes proactivity set --timezone <IANA zone>, or re-run setup with --bind)";;
    esac
    [ "$(hermes_p config get "plugins.entries.$PLUGIN_NAME.allow_gateway_injection" 2>/dev/null | tail -1)" = true ] \
      && ok "gateway injection allowed for $PLUGIN_NAME" \
      || warn "gateway injection not allowed: check-in prompts are dropped (run: hermes config set plugins.entries.$PLUGIN_NAME.allow_gateway_injection true)"
  fi
  case "$(uname -s 2>/dev/null)" in
    Darwin) CONN_DIR="$HOME/Library/Application Support/hermes-alans-way/browser";;
    *) CONN_DIR="$BROWSER_HOME/.local/share/hermes-alans-way/browser";;
  esac
  [ -f "$CONN_DIR/connection.json" ] && ok "browser host connection file present" \
    || warn "browser host connection file absent (browser host not started?)"
  # The availability watcher rewrites its state file every --interval seconds;
  # a stale or missing one means the watcher is not running.
  _watch_state="$(mac_state_path)"
  if [ -n "$MAC_SSH" ] || [ -f "$_watch_state" ]; then
    if [ -f "$_watch_state" ]; then
      _age=$(( $(date +%s) - $(file_mtime "$_watch_state") ))
      if [ "$_age" -le 300 ]; then
        ok "host availability watcher state is fresh"
      else
        warn "host availability watcher state is stale (${_age}s old): the watcher service is not running or cannot reach the host"
      fi
    else
      warn "no host availability watcher state at $_watch_state: the watcher service is not running (re-run setup so it is installed)"
    fi
  fi
  check_linux_desktop_deps
  PROFS="$HERMES_HOME ${PROFILE:+$HERMES_HOME/profiles/$PROFILE}"
  OTHER_PROFILES=""
  if [ "$ONLY_PROFILE" = 0 ]; then
    for _dir in "$HERMES_HOME"/profiles/*/; do
      [ -d "$_dir" ] || continue
      _name="$(basename "$_dir")"
      case "$_name" in default|''|-*|.*|*[!0-9A-Za-z_.-]*) continue;; esac
      _r="$(token_bot_id home "${_dir%/}")"
      case "$_r" in
        ok*) PROFS="$PROFS ${_dir%/}"; OTHER_PROFILES="$OTHER_PROFILES $_name";;
        unreadable*) warn "profile $_name was not checked: ${_r#* } is not valid UTF-8 text";;
        *) skip "profile $_name has no Telegram bot of its own";;
      esac
    done
  fi
  for home in $PROFS; do
    cfg="$home/config.yaml"
    if [ "$SKIP_BROWSER" = 1 ]; then
      skip "workspace_browser block in $cfg (--skip-browser)"
    elif [ -f "$cfg" ] && grep -q '>>> alans-way workspace_browser managed block >>>' "$cfg"; then
      ok "workspace_browser block in $cfg"
    elif [ -f "$cfg" ] && grep -q '^ \+workspace_browser:' "$cfg"; then
      bad "workspace_browser entry in $cfg is unmanaged: re-run setup to install the managed block"
    else
      bad "no workspace_browser block in $cfg"
    fi
  done
  check_computer_provider
  for _name in $OTHER_PROFILES; do
    PROFILE="$_name"
    if have hermes; then
      if [ "$KEEP_BROWSER" = 1 ]; then
        skip "built-in browser toolset check for profile $_name (--keep-browser)"
      else
        for platform in telegram cron; do
          if hermes_p tools list --platform "$platform" 2>/dev/null | grep -Eq "enabled[[:space:]]+browser([[:space:]]|$)"; then
            warn "built-in 'browser' toolset still enabled for $platform in profile $_name: its agent may bypass the workspace browser (run: hermes -p $_name tools disable browser --platform $platform)"
          else
            ok "built-in browser toolset disabled for $platform in profile $_name"
          fi
        done
      fi
    fi
    check_computer_provider
  done
  PROFILE=""
  [ "$FAILS" = 0 ] && say "setup: all required checks passed" || say "setup: $FAILS check(s) failed"
  exit "$([ "$FAILS" = 0 ] && echo 0 || echo 1)"
fi

# ---------------------------------------------------------------- host path
# Hermes reaches the user's computer only over their Tailscale network. Public
# addresses are refused before anything is changed.
tailnet_refuse() {
  printf 'setup: %s\n' "$1" >&2
  printf '%s\n' "setup: Install Tailscale (https://tailscale.com/download) on this machine and on your computer, sign in to the same account on both, then pass your computer's Tailscale name (it ends in .ts.net) or IP (it starts with 100.) as --mac-ssh." >&2
  exit 1
}
TAILSCALE=tailscale
if [ "$GUEST_OS" = Windows ] && ! have tailscale; then
  _ts="$(cygpath -u "${PROGRAMFILES:-C:/Program Files}")/Tailscale/tailscale.exe"
  [ ! -x "$_ts" ] || TAILSCALE="$_ts"
fi
check_tailnet() {
  have "$TAILSCALE" || tailnet_refuse "Tailscale is not installed on this machine."
  # Through a file, not argv: a big tailnet's status exceeds a Windows command line.
  _tsf="$(mktemp)"
  "$TAILSCALE" status --json >"$_tsf" 2>/dev/null || true
  python3 - "$MAC_HOST" "$(wpath "$_tsf")" <<'PY' || _rc=$?
import ipaddress, json, sys
host = sys.argv[1].lower()
try:
    with open(sys.argv[2], encoding="utf-8") as handle:
        status = json.load(handle)
except (OSError, ValueError):
    status = {}
if status.get("BackendState") != "Running":
    sys.exit(3)
try:
    address = ipaddress.ip_address(host)
except ValueError:
    address = None
if address is not None:
    nets = [ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48")]
    sys.exit(0 if any(address.version == n.version and address in n for n in nets) else 4)
if host.endswith(".ts.net"):
    sys.exit(0)
names = set()
for node in [status.get("Self") or {}] + list((status.get("Peer") or {}).values()):
    names.add(str(node.get("HostName", "")).lower())
    dns = str(node.get("DNSName", "")).lower().rstrip(".")
    names.update([dns, dns.split(".")[0]])
sys.exit(0 if host in names - {""} else 4)
PY
  rm -f "$_tsf"
  case "${_rc:-0}" in
    0) return 0;;
    3) tailnet_refuse "Tailscale is not running on this machine ($([ "$GUEST_OS" = Linux ] && echo 'try: sudo tailscale up' || echo 'open the Tailscale app and sign in'))." ;;
    *) tailnet_refuse "'$MAC_HOST' is not a Tailscale address, and Alan's Way does not connect over the public internet.";;
  esac
}
if [ -n "$MAC_SSH" ]; then
  step "Tailscale"
  _rc=0
  check_tailnet
  ok "$MAC_HOST is on your tailnet"
fi

# ssh must never read this script's stdin (curl | bash); only the tar stream takes stdin.
# Setup run as root for a Hermes that a normal account owns still reaches the host
# as that account: its keys and known_hosts are the ones the router and watcher use.
as_owner() {
  if [ "$GUEST_OS" != Windows ] && [ "$(id -u)" = 0 ] && [ "$BROWSER_USER" != "$(id -un)" ] && have runuser; then runuser -u "$BROWSER_USER" -- "$@"; else "$@"; fi
}
# A Windows guest uses the native OpenSSH client, the one the router runs: it
# shares the user's keys, agent and known_hosts, and Git's bundled ssh may differ.
SSH_BIN=ssh SCP_BIN=scp
if [ "$GUEST_OS" = Windows ]; then
  _ossh="$(cygpath -u "${SYSTEMROOT:-${WINDIR:-C:/Windows}}")/System32/OpenSSH"
  [ ! -x "$_ossh/ssh.exe" ] || SSH_BIN="$_ossh/ssh.exe"
  [ ! -x "$_ossh/scp.exe" ] || SCP_BIN="$_ossh/scp.exe"
fi
host_ssh() { as_owner "$SSH_BIN" -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes -- "$MAC_SSH" "$@" </dev/null; }
host_ssh_stdin() { as_owner "$SSH_BIN" -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes -- "$MAC_SSH" "$@"; }
host_scp() { as_owner "$SCP_BIN" -q -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes "$@"; }

# Pinned keys, appended once, and only after the format checks above.
add_line_once() { # add_line_once <file> <line>
  mkdir -p "$(dirname "$1")" && chmod 700 "$(dirname "$1")"
  [ -f "$1" ] || { : > "$1"; chmod 600 "$1"; }
  grep -qxF "$2" "$1" 2>/dev/null || printf '%s\n' "$2" >> "$1"
  if [ "$(id -u)" = 0 ] && [ "$BROWSER_USER" != root ]; then chown "$BROWSER_USER" "$(dirname "$1")" "$1" 2>/dev/null || true; fi
}
if [ -n "$MAC_KEY" ] || [ -n "$MAC_HOST_KEY" ]; then
  step "Trust your computer"
  if [ -n "$MAC_HOST_KEY" ]; then
    add_line_once "$BROWSER_HOME/.ssh/known_hosts" "$MAC_HOST $MAC_HOST_KEY" && ok "pinned the host key for $MAC_HOST"
  fi
  if [ -n "$MAC_KEY" ]; then
    add_line_once "$BROWSER_HOME/.ssh/authorized_keys" "$MAC_KEY" && ok "your computer's key can log in to this machine"
  fi
fi

# The agent's own ssh commands to the computer (not the router's, which already
# multiplexes) pay a fresh handshake every time. A managed block in the Hermes
# user's ssh config makes them share one connection. A Host entry the user wrote
# for that host is theirs and stays as it is.
write_agent_ssh_config() {
  [ -n "$MAC_SSH" ] || return 0
  step "Agent ssh connection reuse"
  if [ "$GUEST_OS" = Windows ]; then
    skip "ssh connection reuse (Windows OpenSSH has no ControlMaster)"
    return 0
  fi
  mkdir -p "$BROWSER_HOME/.ssh" && chmod 700 "$BROWSER_HOME/.ssh"
  _cfg="$BROWSER_HOME/.ssh/config"
  # Userspace-networking Tailscale has no tailscale0 interface, so ssh cannot
  # reach tailnet addresses directly: it must tunnel through `tailscale nc`.
  _proxy=""
  tailscale_userspace && _proxy="$TAILSCALE nc %h %p"
  _state="$(ALANS_WAY_SSH_PROXY="$_proxy" python3 - "$_cfg" "$MAC_HOST" <<'PY'
import os, sys
path, host = sys.argv[1], sys.argv[2]
proxy = os.environ.get("ALANS_WAY_SSH_PROXY", "")
proxy = ("  ProxyCommand %s\n" % proxy) if proxy else ""
begin, end = "# >>> alans-way >>>\n", "# <<< alans-way <<<\n"
block = (begin + f"Host {host}\n" + proxy + "  ControlMaster auto\n  ControlPath ~/.ssh/cm-%C\n  ControlPersist 10m\n"
         "  ServerAliveInterval 15\n  ServerAliveCountMax 3\n" + end)
try:
    text = open(path, encoding="utf-8", newline="").read()
except OSError:
    text = ""
a = text.find(begin)
b = text.find(end, a) if a >= 0 else -1
rest = text[:a] + text[b + len(end):] if b >= 0 else text
for line in rest.splitlines():
    words = line.split("#")[0].split()
    if len(words) > 1 and words[0].lower() == "host" and host.lower() in (w.lower() for w in words[1:]):
        print("user")
        sys.exit(0)
if b >= 0:
    new = text[:a] + block + text[b + len(end):]
else:
    new = text + ("" if not text or text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n") + block
if new != text:
    open(path, "w", encoding="utf-8", newline="").write(new)
print("written" if new != text else "unchanged")
PY
)" || _state=""
  case "$_state" in
    written|unchanged)
      chmod 600 "$_cfg"
      if [ "$(id -u)" = 0 ] && [ "$BROWSER_USER" != root ]; then chown "$BROWSER_USER" "$BROWSER_HOME/.ssh" "$_cfg" 2>/dev/null || true; fi
      [ "$_state" = written ] && ok "ssh connection reuse for $MAC_HOST set in $_cfg" || ok "ssh connection reuse for $MAC_HOST already set";;
    user) warn "$_cfg already has a Host entry for $MAC_HOST, so it was left as it is. Add ControlMaster auto, ControlPath ~/.ssh/cm-%C and ControlPersist 10m to it so the agent's own ssh commands share one connection";;
    *) warn "could not update $_cfg";;
  esac
}
write_agent_ssh_config

# The app reaches this machine over ssh too (mirror push, tab restore). On Windows
# that needs OpenSSH Server running, PowerShell as its shell, and, for an
# administrator account, the key in administrators_authorized_keys instead of
# ~/.ssh/authorized_keys.
windows_inbound_ssh() {
  have powershell || { warn "powershell not found: cannot check this machine's OpenSSH Server"; return 0; }
  _state="$(powershell -NoProfile -NonInteractive -Command - 2>/dev/null <<'PS' | tr -d '\r'
$svc = Get-Service sshd -ErrorAction SilentlyContinue
if (-not $svc) { 'missing'; exit 0 }
$admin = [Security.Principal.WindowsIdentity]::GetCurrent().Groups.Value -contains 'S-1-5-32-544'
$shell = (Get-ItemProperty 'HKLM:\SOFTWARE\OpenSSH' -ErrorAction SilentlyContinue).DefaultShell
"$($svc.Status.ToString().ToLower()) $(if ($admin) {'admin'} else {'user'}) $(if ($shell -match 'powershell|pwsh') {'shell-ps'} else {'shell-other'})"
PS
)" || _state=""
  read -r _svc _role _shell <<EOF
$_state
EOF
  case "$_svc" in
    running) ok "OpenSSH Server (sshd) is running";;
    missing|'') warn "OpenSSH Server is not installed, so the app cannot reach this machine. In an elevated PowerShell run: Add-WindowsCapability -Online -Name (Get-WindowsCapability -Online -Name 'OpenSSH.Server*').Name; Set-Service sshd -StartupType Automatic; Start-Service sshd";;
    *) warn "OpenSSH Server is $_svc. In an elevated PowerShell run: Set-Service sshd -StartupType Automatic; Start-Service sshd";;
  esac
  if [ "$_shell" = shell-other ]; then
    warn "sshd's DefaultShell is not PowerShell, which the app's commands need. In an elevated PowerShell run: New-ItemProperty -Path HKLM:\SOFTWARE\OpenSSH -Name DefaultShell -Value C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -PropertyType String -Force"
  fi
  if [ "$_role" = admin ] && [ -n "$MAC_KEY" ]; then
    _adm="$(cygpath -u "${PROGRAMDATA:-C:/ProgramData}")/ssh/administrators_authorized_keys"
    if [ -d "$(dirname "$_adm")" ] && { grep -qxF "$MAC_KEY" "$_adm" 2>/dev/null \
        || { printf '%s\n' "$MAC_KEY" >> "$_adm" 2>/dev/null \
             && icacls "$(cygpath -w "$_adm")" /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' >/dev/null 2>&1; }; }; then
      ok "your computer's key can log in to this administrator account"
    else
      warn "this account is an administrator, so sshd reads C:\ProgramData\ssh\administrators_authorized_keys, not ~/.ssh/authorized_keys. In an elevated PowerShell run: Add-Content -Path \"\$env:ProgramData\ssh\administrators_authorized_keys\" -Value '$MAC_KEY'; icacls \"\$env:ProgramData\ssh\administrators_authorized_keys\" /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F'"
    fi
  fi
}
if [ "$GUEST_OS" = Windows ] && [ "$SKIP_BROWSER" = 0 ]; then
  step "Inbound ssh (for the app)"
  windows_inbound_ssh
fi

# Fetch the repo when running via curl|bash. A --repo-ref pin checks out a
# reviewed commit instead of tracking main.
# A ref can be a branch or tag, so the check compares the clone's HEAD with
# the commit the ref resolves to, not the ref's own name. A mismatch stops
# setup: continuing on the wrong tree defeats the review boundary.
check_repo_pin() {
  [ -n "$REPO_REF" ] || return 0
  _want="$(git -C "$REPO_DIR" rev-parse --verify -q "$REPO_REF^{commit}" 2>/dev/null || true)"
  _head="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)"
  if [ -n "$_want" ] && [ "$_head" = "$_want" ]; then return 0; fi
  if [ -n "$_want" ]; then
    bad "$REPO_DIR is not at --repo-ref $REPO_REF (git checkout $REPO_REF there, or run setup from a fresh download)"
  else
    bad "cannot resolve --repo-ref $REPO_REF to a commit in $REPO_DIR (a release tag must be pushed to exist; check the ref or fetch the remote)"
  fi
  exit 1
}
# A catalog install records the commit it was checked out at in the profile's
# plugins/.install-metadata.json (installer-owned, so a repo cannot forge it).
# That sha is this clone's only legitimate pin and outranks --repo-ref: a tag
# can be re-pointed upstream, the recorded commit cannot move. Without a
# catalog record --repo-ref stays the pin; the skill passes the release tag.
catalog_repo_sha() {
  [ -f "$PROFILE_HOME/plugins/.install-metadata.json" ] || return 0
  python3 - "$PROFILE_HOME" "$PLUGIN_NAME" <<'PY'
import json, re, sys
try:
    rows = json.load(open(sys.argv[1] + "/plugins/.install-metadata.json"))
except Exception:
    sys.exit(0)
row = rows.get(sys.argv[2])
if not isinstance(row, dict):
    sys.exit(0)
cat = row.get("catalog")
if isinstance(cat, dict):
    sha = str(cat.get("sha") or cat.get("pin") or "")
elif row.get("catalog_name"):
    sha = str(row.get("revision") or "")
else:
    sha = ""
sys.stdout.write(sha if re.fullmatch(r"[0-9a-fA-F]{40}", sha) else "")
PY
}
_catalog_sha="$(catalog_repo_sha || true)"
if [ -n "$_catalog_sha" ]; then
  if [ -n "$REPO_REF" ] && [ "$REPO_REF" != "$_catalog_sha" ]; then
    warn "--repo-ref $REPO_REF ignored: the catalog-installed plugin pins this repo to $_catalog_sha"
  fi
  REPO_REF="$_catalog_sha"
fi
if [ -z "$REPO_DIR" ]; then
  step "Fetching alans-way-agents"
  REPO_DIR="$BROWSER_HOME/.local/share/alans-way-agents"
  if [ -d "$REPO_DIR/.git" ]; then
    if [ -n "$REPO_REF" ]; then
      # A requested pin that can't be applied is a stop, not a fallback.
      # Fetch only when the local objects don't already satisfy the ref.
      if git -C "$REPO_DIR" checkout -q "$REPO_REF" 2>/dev/null \
          || { git -C "$REPO_DIR" fetch -q origin && git -C "$REPO_DIR" checkout -q "$REPO_REF"; }; then
        check_repo_pin && ok "pinned $REPO_DIR to $REPO_REF"
      else
        bad "could not pin $REPO_DIR to $REPO_REF"; exit 1
      fi
    else
      git -C "$REPO_DIR" pull --ff-only -q && ok "updated $REPO_DIR" || warn "could not update $REPO_DIR: using existing checkout"
    fi
  else
    git clone -q "$REPO_URL" "$REPO_DIR" \
      && { [ -z "$REPO_REF" ] || git -C "$REPO_DIR" checkout -q "$REPO_REF"; } \
      && check_repo_pin \
      && ok "cloned to $REPO_DIR${REPO_REF:+ at $REPO_REF}" \
      || { bad "git clone or pin failed"; exit 1; }
  fi
elif [ -n "$REPO_REF" ]; then
  # Running from a clone: setup never moves the user's checkout, so the pin must already hold.
  check_repo_pin
  ok "$REPO_DIR is at $REPO_REF"
fi

# hermes plugins install clones this URL: file:///C:/... on Windows.
REPO_FILE_URL="file://$REPO_DIR"
if [ "$GUEST_OS" = Windows ]; then
  _p="$(wpath "$REPO_DIR")"
  case "$_p" in /*) ;; *) _p="/$_p";; esac
  REPO_FILE_URL="file://$_p"
fi

# Both set BOT_ID and return 0 when the profile has a bot, 1 when it has none and
# 2 (after saying why) when a file cannot be read.
derive_bot_id_from() {
  _r="$(token_bot_id "$1" "$2")"
  _rest="${_r#* }"
  case "$_r" in
    ok*)
      BOT_ID="${_rest%% *}"
      ok "using bot id $BOT_ID from $2 (token not printed)"
      case "$_rest" in *" "*) warn "$2: .env and config.yaml name different bots (bot id $BOT_ID in .env, ${_rest#* } in config.yaml). Hermes uses the .env one, so setup does too";; esac
      return 0;;
    unreadable*) warn "$2: $_rest is not valid UTF-8 text, so this profile was skipped"; return 2;;
  esac
  return 1
}
derive_bot_id() { derive_bot_id_from home "$1"; }
derive_bot_id_from_env() { derive_bot_id_from env "$1"; }

# The proactivity timezone is the user's, not the VM's: ask their computer.
valid_iana() {
  case "$1" in UTC|GMT) return 0;; [A-Z]*/??*) ;; *) return 1;; esac
  case "$1" in *[!A-Za-z0-9_/+-]*|/*|*/|*..*) return 1;; esac
  return 0
}
detect_host_timezone() {
  [ -z "$TIMEZONE" ] && [ -n "$MAC_SSH" ] || return 0
  # The router builds the host-OS-specific node command; ssh runs it on the computer.
  _cmd="$(node "$(wpath "$(router_script)")" --host-timezone-command --host-os "${HOST_OS:-mac}" 2>/dev/null || true)"
  _tz=""
  [ -z "$_cmd" ] || _tz="$(host_ssh "$_cmd" 2>/dev/null | head -1 || true)"
  _tz="$(printf '%s' "$_tz" | tr -d ' \r\n')"
  if ! valid_iana "$_tz"; then
    warn "could not read your computer's timezone over ssh"
    return 0
  fi
  TIMEZONE="$_tz"
  ok "using timezone $TIMEZONE from your computer ($HOST_OS) for check-in hours"
}
ask_timezone() {
  [ -z "$TIMEZONE" ] && has_tty || return 0
  _tz="$(ask "  Your timezone for check-in hours (IANA, e.g. Europe/Berlin; empty to skip)" "")"
  valid_iana "$_tz" || return 0
  TIMEZONE="$_tz"
}

# ---------------------------------------------------------------- telegram
step "Telegram gateway"
ENV_FILE="$HERMES_HOME/.env"
if [ -n "$PROFILE" ]; then ENV_FILE="$HERMES_HOME/profiles/$PROFILE/.env"; fi
if [ -f "$ENV_FILE" ] && grep -q '^TELEGRAM_BOT_TOKEN=.\+' "$ENV_FILE" 2>/dev/null; then
  ok "TELEGRAM_BOT_TOKEN configured in $ENV_FILE"
elif [ -f "$HERMES_HOME/.env" ] && grep -q '^TELEGRAM_BOT_TOKEN=.\+' "$HERMES_HOME/.env" 2>/dev/null; then
  ok "TELEGRAM_BOT_TOKEN configured in $HERMES_HOME/.env"
else
  warn "No TELEGRAM_BOT_TOKEN found: the gateway has no bot to answer yet."
  say "  Hermes can create one without BotFather: run"
  say "      hermes gateway setup"
  say "  choose Telegram → 'Automatic' → scan the QR code in Telegram."
  if confirm "  Run 'hermes gateway setup' now?"; then
    hermes_p gateway setup || warn "gateway setup exited non-zero: re-run setup.sh after configuring"
  else
    say "  Skipping. Re-run setup.sh once Telegram is configured."
  fi
fi

# A catalog install records provenance in the plugins dir's
# .install-metadata.json (a ``catalog`` block naming the reviewed pin) and
# drops a .hermes-catalog.json convenience copy inside the plugin. Either
# marker means the catalog pin is the install's only legitimate source.
plugin_is_catalog_installed() {
  _cat_name="${1:-$PLUGIN_NAME}"
  [ -f "$PROFILE_HOME/plugins/$_cat_name/.hermes-catalog.json" ] && return 0
  [ -f "$PROFILE_HOME/plugins/.install-metadata.json" ] || return 1
  python3 - "$PROFILE_HOME" "$_cat_name" <<'PY'
import json, sys
try:
    rows = json.load(open(sys.argv[1] + "/plugins/.install-metadata.json"))
except Exception:
    sys.exit(1)
row = rows.get(sys.argv[2])
sys.exit(0 if isinstance(row, dict) and isinstance(row.get("catalog"), dict) else 1)
PY
}

# The router and mac-watch run the copy Hermes actually loaded: under
# --skip-plugin or a catalog install that is the profile's plugins dir, not a
# possibly newer clone of this repo. The hook setup does the same.
router_script() {
  _rs="$REPO_DIR/$PLUGIN_NAME/scripts/workspace-router.cjs"
  if { [ "$SKIP_PLUGIN" = 1 ] || plugin_is_catalog_installed; } \
      && [ -f "$PROFILE_HOME/plugins/$PLUGIN_NAME/scripts/workspace-router.cjs" ]; then
    _rs="$PROFILE_HOME/plugins/$PLUGIN_NAME/scripts/workspace-router.cjs"
  fi
  printf '%s' "$_rs"
}

# ---------------------------------------------------------------- plugin
step "Plugin"
if [ "$SKIP_PLUGIN" = 1 ]; then
  if plugin_listed "$PLUGIN_NAME"; then
    ok "plugin already installed; not replacing it"
  else
    bad "no $PLUGIN_NAME plugin installed. Install it from the Hermes catalog, or re-run without --skip-plugin."
  fi
elif plugin_listed "$PLUGIN_NAME"; then
  if plugin_is_catalog_installed; then
    # Never install --force over the catalog pin: the reviewed build stays
    # the only plugin source, updated only through the catalog itself.
    ok "plugin installed from the Hermes catalog: leaving its pin in place"
    say "  to move it forward: hermes${PROFILE:+ -p $PROFILE} plugins update $PLUGIN_NAME"
  elif diff -rq -x __pycache__ "$REPO_DIR/$PLUGIN_NAME" "$PROFILE_HOME/plugins/$PLUGIN_NAME" >/dev/null 2>&1; then
    ok "plugin already installed and current"
  else
    hermes_p plugins install --force "$REPO_FILE_URL#$PLUGIN_NAME" >/dev/null 2>&1 \
      && ok "plugin updated from $REPO_DIR (restart the gateway to load it)" \
      || warn "could not update the installed plugin: run: hermes${PROFILE:+ -p $PROFILE} plugins install --force $REPO_FILE_URL#$PLUGIN_NAME"
  fi
else
  hermes_p plugins install "$REPO_FILE_URL#$PLUGIN_NAME" && ok "plugin installed from $REPO_DIR" \
    || { bad "plugin install failed"; exit 1; }
fi
hermes_p plugins enable "$PLUGIN_NAME" >/dev/null 2>&1 || true
# The plugin's gateway-injection capability is granted at enable time — it is
# inert until a route is bound, and a later manual bind then just works.
hermes_p config set "plugins.entries.$PLUGIN_NAME.allow_gateway_injection" true >/dev/null 2>&1 \
  && ok "gateway injection allowed for $PLUGIN_NAME" \
  || warn "could not allow gateway injection: run: hermes${PROFILE:+ -p $PROFILE} config set plugins.entries.$PLUGIN_NAME.allow_gateway_injection true"
# The tool must be loaded into each messaging session's platform —
# plugin toolsets are skipped when the platform's saved list predates the
# plugin (recorded under known_plugin_toolsets). Enabling is idempotent.
enable_proactivity_toolsets() {
  for platform in telegram; do
    hermes_p tools enable proactivity --platform "$platform" >/dev/null 2>&1 \
      && ok "proactivity toolset enabled for $platform" \
      || warn "could not enable the proactivity toolset for $platform: the proactivity tool will not be callable in those sessions (run: hermes${PROFILE:+ -p $PROFILE} tools enable proactivity --platform $platform)"
  done
}
enable_proactivity_toolsets

# ------------------------------------------------- computer-use provider (optional)
# Offered only when this Hermes has the pluggable computer-use API; feature-probed
# with Hermes' own interpreter, never by version.
COMPUTER_PLUGIN="alans-way-computer" COMPUTER_READY=0 COMPUTER_SELECTED=0
# Hermes 0.21.5's `hermes` is often a bash shim (cd <dir> && source venv/bin/activate
# && python hermes), so the shebang is not its python: take a python* shebang as is,
# else the venv the shim activates, else the standard install location.
find_hermes_python() {
  _hbin="$(command -v hermes 2>/dev/null || true)"
  _line1="$(head -1 "$_hbin" 2>/dev/null | sed -n 's/^#! *//p')"
  _interp="${_line1%% *}"
  [ "$_interp" != /usr/bin/env ] || { _interp="$(command -v "$(printf '%s' "$_line1" | cut -d' ' -f2)" 2>/dev/null || true)"; }
  case "$(basename "${_interp:-x}")" in python*) [ -x "$_interp" ] && { echo "$_interp"; return 0; };; esac
  _src="$(grep -m1 'source .*activate' "$_hbin" 2>/dev/null || true)"
  _dir="$(printf '%s' "$_src" | sed -n 's/.*cd  *\([^ ;&]*\).*/\1/p' | tr -d "\"'")"
  _act="$(printf '%s' "$_src" | sed -n 's/.*source  *\([^ ;&]*activate\).*/\1/p' | tr -d "\"'")"
  if [ -n "$_act" ]; then
    case "$_act" in /*) ;; *) _act="${_dir:+$_dir/}$_act";; esac
    [ -x "$(dirname "$_act")/python" ] && { echo "$(dirname "$_act")/python"; return 0; }
  fi
  [ -x "$HERMES_HOME/hermes-agent/venv/bin/python" ] && { echo "$HERMES_HOME/hermes-agent/venv/bin/python"; return 0; }
  return 1
}
if [ -z "${HERMES_PYTHON:-}" ] && [ "$GUEST_OS" != Windows ]; then
  HERMES_PYTHON="$(find_hermes_python || true)"
fi
# Probed through that interpreter only (never a shell), under a hard limit: python3
# is already required, and macOS has no `timeout`. Exit 124 means it timed out.
COMPUTER_API=0 _probe_rc=0
if [ -n "${HERMES_PYTHON:-}" ]; then
  python3 -c 'import subprocess, sys
try:
    sys.exit(subprocess.run(sys.argv[2:], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=float(sys.argv[1])).returncode)
except subprocess.TimeoutExpired:
    sys.exit(124)' "${ALANS_WAY_PROBE_TIMEOUT:-30}" "$HERMES_PYTHON" -c 'import tools.computer_use.backend as b; b.ComputerUseProvider' || _probe_rc=$?
  case "$_probe_rc" in
    0) COMPUTER_API=1;;
    124) warn "the computer-use API probe timed out: skipping the computer-use provider";;
  esac
fi
ensure_computer_provider() {
  COMPUTER_READY=0
  if [ "$SKIP_PLUGIN" = 1 ]; then
    # Catalog flow: plugin installs stay with the catalog, so the provider is
    # the operator's own `hermes plugins install alans-way-computer`.
    skip "computer-use provider (--skip-plugin leaves plugin installs to the catalog)"
    return 0
  fi
  if plugin_listed "$COMPUTER_PLUGIN" || plugin_is_catalog_installed "$COMPUTER_PLUGIN"; then
    ok "computer-use provider already installed; leaving it as it is"
    COMPUTER_READY=1
  elif [ "$DEV_PLUGIN" = 1 ]; then
    # Developer path only: from this clone instead of the catalog. Nothing in
    # the skill or docs passes --dev-plugin-install, so catalog users never
    # land here.
    if hermes_p plugins install --force "$REPO_FILE_URL#$COMPUTER_PLUGIN" >/dev/null 2>&1; then
      hermes_p plugins enable "$COMPUTER_PLUGIN" >/dev/null 2>&1 || true
      ok "computer-use provider installed from $REPO_DIR"
      COMPUTER_READY=1
    else
      warn "could not install the computer-use provider from $REPO_DIR (is $COMPUTER_PLUGIN in this checkout?). Desktop control keeps using Hermes' built-in backend"
    fi
  elif hermes_p plugins install "$COMPUTER_PLUGIN" >/dev/null 2>&1; then
    hermes_p plugins enable "$COMPUTER_PLUGIN" >/dev/null 2>&1 || true
    ok "computer-use provider installed from the Hermes catalog"
    COMPUTER_READY=1
  else
    warn "could not install the computer-use provider: run: hermes${PROFILE:+ -p $PROFILE} plugins install $COMPUTER_PLUGIN. Desktop control keeps using Hermes' built-in backend"
  fi
}
if [ "$COMPUTER_API" = 1 ]; then
  ensure_computer_provider
elif [ "$GUEST_OS" = Windows ] && [ -z "${HERMES_PYTHON:-}" ]; then
  skip "computer-use provider (set HERMES_PYTHON to Hermes' python.exe to let setup look for the pluggable computer-use API)"
else
  skip "computer-use provider (this Hermes has no pluggable computer-use API yet)"
fi

# ---------------------------------------------------------------- old hook
# 0.6 armed proactivity with a gateway:startup hook; the idle nudge detects the
# gateway itself, so remove only the hook this plugin installed.
for hook_dir in "$HERMES_HOME/hooks/$PLUGIN_NAME" "$HERMES_HOME"/profiles/*/hooks/"$PLUGIN_NAME"; do
  if [ -f "$hook_dir/HOOK.yaml" ] && grep -q "alans-way-gateway" "$hook_dir/HOOK.yaml"; then
    rm -rf "$hook_dir" && ok "removed the old proactivity hook from $hook_dir" \
      || warn "could not remove the old proactivity hook at $hook_dir"
  fi
done

# --------------------------------------------- Windows services (Scheduled Tasks)
# The Windows counterpart of the systemd units: a task per service that starts at
# logon like Hermes' own gateway task (Chrome needs the signed-in desktop) and
# restarts on failure every minute. win_task registers the task only when its
# action changed, then starts it, and prints registered, updated or unchanged.
# "once" tasks have no trigger and are started immediately (the gateway restart).
win_task_script() {
  cat <<'PS'
$ErrorActionPreference = 'Stop'
$name = $env:AW_TASK; $exe = $env:AW_EXE; $arg = $env:AW_ARGS
$me = "$env:USERDOMAIN\$env:USERNAME"
$old = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
$same = $env:AW_TRIGGER -eq 'logon' -and $old -and $old.Actions.Count -eq 1 -and $old.Actions[0].Execute -eq $exe -and $old.Actions[0].Arguments -eq $arg
if (-not $same) {
  $action = New-ScheduledTaskAction -Execute $exe -Argument $arg
  $principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
  if ($env:AW_TRIGGER -eq 'logon') {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
    $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
  } else {
    Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Force | Out-Null
  }
}
$running = (Get-ScheduledTask -TaskName $name).State -eq 'Running'
$restart = $env:AW_RESTART -eq '1'
if (($restart -or -not $same) -and $running) { Stop-ScheduledTask -TaskName $name }
if ($restart -or -not $same -or -not $running) { Start-ScheduledTask -TaskName $name }
if ($same) { 'unchanged' } elseif ($old) { 'updated' } else { 'registered' }
PS
}
psq() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/''/g")"; }
# win_task <name> <powershell command> <logon|once> [restart]
win_task() {
  have powershell || { warn "powershell not found: could not schedule $1"; return 1; }
  WIN_TASK_OUT="$(win_task_script | AW_TASK="$1" AW_EXE=powershell.exe AW_TRIGGER="$3" AW_RESTART="${4:-0}" \
      AW_ARGS="-NoProfile -WindowStyle Hidden -Command \"$2\"" \
      powershell -NoProfile -NonInteractive -Command - 2>&1 | tr -d '\r')" || WIN_TASK_OUT=""
  WIN_TASK_RESULT="$(printf '%s\n' "$WIN_TASK_OUT" | tail -1)"
  case "$WIN_TASK_RESULT" in
    registered|updated|unchanged) return 0;;
    *) warn "could not schedule $1 (group policy may block logon tasks): $(printf '%s' "${WIN_TASK_OUT:-no answer from powershell}" | tr '\n' ' ' | cut -c1-240)"; return 1;;
  esac
}
# win_service <task> <script path> [args...]: node runs the script, its exit code is the task's.
win_service() {
  _name="$1"; _script="$(cygpath -w "$2")"; shift 2
  _cmd="${WIN_DELAY:+Start-Sleep -Seconds $WIN_DELAY; }\$env:HERMES_VPS_BROWSER_DATA=$(psq "$(wpath "$DATA_DIR")"); & $(psq "$WIN_NODE") $(psq "$_script")"
  for _a in "$@"; do _cmd="$_cmd $_a"; done
  win_task "$_name" "$_cmd; exit \$LASTEXITCODE" logon "${WIN_RESTART:-0}" || return 0
  case "$WIN_TASK_RESULT" in
    registered) ok "scheduled task $_name registered (starts at logon, restarts on failure)";;
    updated) ok "scheduled task $_name updated and restarted";;
    *) if [ "${WIN_RESTART:-0}" = 1 ]; then ok "scheduled task $_name restarted on the new scripts"; else ok "scheduled task $_name already current"; fi;;
  esac
}
install_windows_tasks() {
  WIN_NODE="$(node -p process.execPath 2>/dev/null || command -v node)"
  win_service AlansWay_Chromium "$DESKTOP_DIR/desktop/scripts/vps-chromium-host.cjs"
  # Chromium keeps running so open tabs and sign-ins survive an update; only the broker restarts.
  # The broker waits for the Chromium task to bring the browser up: started together, it would
  # launch a second Chrome of its own that dies with the broker's task.
  WIN_DELAY=5; WIN_RESTART="${BROWSER_UPDATED:-0}"
  win_service AlansWay_Browser "$DESKTOP_DIR/desktop/scripts/vps-browser-host.cjs" serve
  WIN_DELAY=""; WIN_RESTART=0
  if [ "$CONFIG_CHANGED" = 1 ] && [ "$CFG_EXISTED" = 1 ]; then
    say "  browser settings changed: restart the AlansWay_Chromium task to apply them (open tabs close)"
  fi
  if [ -n "$MAC_SSH" ]; then
    # The router's default state file on Windows is the one the watcher writes.
    win_service AlansWay_MacWatch "$(router_script)" \
      --watch --interval 10 --mac-ssh "$(psq "$MAC_SSH")" --host-os "$(psq "$HOST_OS")"
  fi
}

# ------------------------------------------------------- browser host (VPS)
if [ "$SKIP_BROWSER" = 0 ]; then
  step "VPS browser host"
  [ -n "$DESKTOP_DIR" ] || DESKTOP_DIR="$([ "$GUEST_OS" != Windows ] && [ "$(id -u)" = 0 ] && echo /opt/hermes-alans-way/browser || echo "$BROWSER_HOME/.local/share/hermes-alans-way/app")"
  if [ -f "$DESKTOP_DIR/desktop/scripts/browser-mcp.cjs" ]; then
    if [ -d "$DESKTOP_DIR/.git" ]; then
      OLD_LOCK="$(cksum < "$DESKTOP_DIR/desktop/package-lock.json" 2>/dev/null || true)"
      OLD_REV="$(git -C "$DESKTOP_DIR" rev-parse HEAD 2>/dev/null || true)"
      DESKTOP_SYNCED=0
      if [ -n "$DESKTOP_REF" ]; then
        # A requested pin that can't be applied is a stop, not a fallback —
        # updating anyway would run unreviewed code. Fetch only when the
        # local objects don't already satisfy the ref.
        if git -C "$DESKTOP_DIR" checkout -q "$DESKTOP_REF" 2>/dev/null \
            || { git -C "$DESKTOP_DIR" fetch -q origin 2>/dev/null \
                 && git -C "$DESKTOP_DIR" checkout -q "$DESKTOP_REF" 2>/dev/null; }; then
          DESKTOP_SYNCED=1
        else
          bad "could not pin $DESKTOP_DIR to $DESKTOP_REF"; exit 1
        fi
      elif git -C "$DESKTOP_DIR" pull --ff-only -q 2>/dev/null; then
        DESKTOP_SYNCED=1
      else
        warn "could not update $DESKTOP_DIR (local changes?): using it as is"
      fi
      if [ "$DESKTOP_SYNCED" = 1 ]; then
        if [ "$OLD_REV" != "$(git -C "$DESKTOP_DIR" rev-parse HEAD 2>/dev/null || true)" ]; then
          BROWSER_UPDATED=1; ok "updated browser scripts in $DESKTOP_DIR${DESKTOP_REF:+ to $DESKTOP_REF}"
          [ "$OLD_LOCK" = "$(cksum < "$DESKTOP_DIR/desktop/package-lock.json" 2>/dev/null || true)" ] \
            || rm -rf "$DESKTOP_DIR/desktop/node_modules"
        else
          ok "browser scripts at $DESKTOP_DIR are current"
        fi
      fi
    else
      if [ -n "$DESKTOP_REF" ]; then
        bad "$DESKTOP_DIR is not a git checkout, so --desktop-ref $DESKTOP_REF can't be applied: move it aside and re-run"; exit 1
      fi
      warn "browser scripts at $DESKTOP_DIR are not a git checkout, so setup can't update them: move it aside and re-run to reinstall"
    fi
  else
    mkdir -p "$(dirname "$DESKTOP_DIR")"
    SIBLING=""
    # A pinned ref means "exactly this reviewed tree" — clone it rather than
    # trusting whatever sibling checkout happens to be lying nearby.
    if [ -z "$DESKTOP_REF" ]; then
      for d in "$SCRIPT_DIR/../alans-way" "$SCRIPT_DIR/../hermes-companion"; do
        [ -d "$d/desktop/scripts" ] && { SIBLING="$d"; break; }
      done
    fi
    if [ -n "$SIBLING" ]; then
      mkdir -p "$DESKTOP_DIR"
      cp -R "$SIBLING/desktop" "$DESKTOP_DIR/" && ok "copied desktop checkout to $DESKTOP_DIR"
    else
      rm -rf "$DESKTOP_DIR.tmp"
      if [ -n "$DESKTOP_REF" ]; then
        git clone -q "$DESKTOP_REPO_URL" "$DESKTOP_DIR.tmp" \
          && git -C "$DESKTOP_DIR.tmp" checkout -q "$DESKTOP_REF" \
          && mv "$DESKTOP_DIR.tmp" "$DESKTOP_DIR" \
          && ok "cloned companion repo to $DESKTOP_DIR at $DESKTOP_REF" \
          || { rm -rf "$DESKTOP_DIR.tmp"; warn "could not fetch desktop repo at $DESKTOP_REF: browser host skipped"; }
      else
        git clone -q --depth 1 "$DESKTOP_REPO_URL" "$DESKTOP_DIR.tmp" \
          && mv "$DESKTOP_DIR.tmp" "$DESKTOP_DIR" && ok "cloned companion repo to $DESKTOP_DIR" \
          || { rm -rf "$DESKTOP_DIR.tmp"; warn "could not fetch desktop repo: browser host skipped"; }
      fi
    fi
  fi
  if [ -n "$MAC_SSH" ] && [ -f "$DESKTOP_DIR/desktop/scripts/browser-mcp.cjs" ] && [ -f "$DESKTOP_DIR/desktop/src/computer.cjs" ]; then
    # The running app keeps its own copy of the connector. A newer copy in
    # the user's app-data directory is what the router prefers, so computer use
    # reaches the host machine without waiting for an app rebuild. The copy must
    # be self-contained: every src/ module plus installed package deps, because
    # a bare `node` fallback has no NODE_PATH and a MODULE_NOT_FOUND child
    # stalls each profile's MCP connect for the full timeout.
    # "--" ends option parsing before the host; remote paths never reach scp
    # (legacy scp splits them on spaces, SFTP-mode scp does not unquote them).
    SCP_TARGET="$MAC_SSH"
    case "$MAC_HOST" in *:*) SCP_TARGET="${MAC_USER:+$MAC_USER@}[$MAC_HOST]";; esac
    stage_connector() { # stage_connector <dir>: the layout the connector directory gets
      mkdir -p "$1/connector/scripts" "$1/connector/src" || return 1
      cp "$DESKTOP_DIR/desktop/scripts/browser-mcp.cjs" "$1/connector/scripts/" || return 1
      cp "$DESKTOP_DIR"/desktop/src/*.cjs "$1/connector/src/" || return 1
      if [ "$HOST_OS" = mac ]; then cp "$DESKTOP_DIR/desktop/scripts/mac-computer.swift" "$1/connector/scripts/" || return 1; fi
      if [ "$HOST_OS" = linux ] && [ -f "$DESKTOP_DIR/desktop/scripts/vps-computer.py" ]; then
        cp "$DESKTOP_DIR/desktop/scripts/vps-computer.py" "$1/connector/scripts/" || return 1
      fi
      if [ "$HOST_OS" != windows ]; then
        cp "$DESKTOP_DIR/desktop/package.json" "$DESKTOP_DIR/desktop/package-lock.json" "$1/connector/" || return 1
      fi
    }
    CONN_STAGE="$(mktemp -d)" || CONN_STAGE=""
    [ -z "$CONN_STAGE" ] || chmod 755 "$CONN_STAGE"
    CONN_OK=0
    if [ -n "$CONN_STAGE" ] && stage_connector "$CONN_STAGE" && chmod -R a+rX "$CONN_STAGE"; then
      case "$HOST_OS" in
        windows)
          # Windows sshd defaults to PowerShell (connect-windows.ps1 sets it), which
          # can't take a binary tar on stdin: scp to a space-free staging dir, then
          # copy into the app-data folder remotely. The backend command sets NODE_PATH
          # to the installed app's node_modules, so no npm install happens there.
          if host_ssh 'Remove-Item -Recurse -Force "$HOME\.alans-way-stage" -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force "$HOME\.alans-way-stage" | Out-Null' \
              && host_scp -r -- "$(wpath "$CONN_STAGE")/connector" "$SCP_TARGET:.alans-way-stage/" \
              && host_ssh 'New-Item -ItemType Directory -Force "$env:APPDATA\Hermes Workspace\connector" | Out-Null; Copy-Item -Recurse -Force "$HOME\.alans-way-stage\connector\*" "$env:APPDATA\Hermes Workspace\connector\"; Remove-Item -Recurse -Force "$HOME\.alans-way-stage"' >/dev/null 2>&1; then
            CONN_OK=1
            ok "Windows connector updated: computer use runs through the app's local API"
          fi;;
        linux)
          if COPYFILE_DISABLE=1 tar -C "$CONN_STAGE" -cf - connector \
                | host_ssh_stdin "sh -c 'P=\"\${XDG_CONFIG_HOME:-\$HOME/.config}/Hermes Workspace\"; mkdir -p \"\$P\" && tar -xf - -C \"\$P\"'" \
              && host_ssh "bash -lc 'cd \"\${XDG_CONFIG_HOME:-\$HOME/.config}/Hermes Workspace/connector\" && npm ci --omit=dev --ignore-scripts'" >/dev/null 2>&1; then
            CONN_OK=1
            ok "Linux connector updated for browser and computer use"
          fi;;
        *)
          if COPYFILE_DISABLE=1 tar -C "$CONN_STAGE" -cf - connector \
                | host_ssh_stdin "sh -c 'mkdir -p \"\$1\" && tar -xf - -C \"\$1\"' sh \"\$HOME/Library/Application Support/Hermes Workspace\"" \
              && host_ssh "zsh -lc 'cd \"\$HOME/Library/Application Support/Hermes Workspace/connector\" && npm ci --omit=dev --ignore-scripts'" >/dev/null 2>&1; then
            CONN_OK=1
            host_ssh 'swiftc -O -o "$HOME/Library/Application Support/Hermes Workspace/connector/scripts/mac-computer" "$HOME/Library/Application Support/Hermes Workspace/connector/scripts/mac-computer.swift"' >/dev/null 2>&1 \
              || true
            ok "Mac connector updated for browser and computer use"
          fi;;
      esac
    fi
    [ -z "$CONN_STAGE" ] || rm -rf "$CONN_STAGE"
    [ "$CONN_OK" = 1 ] || warn "could not copy the $HOST_OS connector: the installed app's scripts stay in use"
  fi
  if [ -f "$DESKTOP_DIR/desktop/scripts/browser-mcp.cjs" ] && [ ! -d "$DESKTOP_DIR/desktop/node_modules/@modelcontextprotocol" ]; then
    say "  installing connector dependencies (npm ci --omit=dev)"
    (cd "$DESKTOP_DIR/desktop" && npm ci --omit=dev --ignore-scripts >/dev/null 2>&1) \
      && ok "dependencies installed" || warn "npm ci failed: connector may not start"
  fi

  if [ "$GUEST_OS" = Darwin ]; then
    if [ "$SKIP_SERVICES" = 0 ]; then
      # The shared script writes config.json (Chromium.app discovery) and the
      # two LaunchAgents that replace the Linux systemd units — no X11 on macOS.
      if [ -f "$DESKTOP_DIR/scripts/mac-guest-services.sh" ]; then
        sh "$DESKTOP_DIR/scripts/mac-guest-services.sh" \
          && ok "browser services installed via launchd" \
          || warn "mac-guest-services.sh failed: see docs/mac-vm-guest.md in the alans-way repo"
      else
        warn "$DESKTOP_DIR/scripts/mac-guest-services.sh missing: update the desktop repo checkout"
      fi
    fi
  else
  DATA_DIR="${HERMES_VPS_BROWSER_DATA:-$BROWSER_HOME/.local/share/hermes-alans-way/browser}"
  mkdir -p "$DATA_DIR" && chmod 700 "$DATA_DIR"

  # Snap's chromium can't open a profile outside ~/snap/chromium/common and a
  # snap stub can't be told apart by name alone, so prefer a real Chrome/Chromium.
  is_snap_browser() {
    _bp="$(readlink -f "$1" 2>/dev/null || echo "$1")"
    case "$_bp" in /snap/*|*/snap/*) return 0;; esac
    if [ "$(head -c 2 "$_bp" 2>/dev/null)" = '#!' ] && grep -q snap "$_bp" 2>/dev/null; then return 0; fi
    return 1
  }
  _want="${CHROMIUM:-}"
  CHROMIUM="" SNAP_CHROMIUM="" CHROMIUM_IS_SNAP=0
  if [ "$GUEST_OS" = Windows ]; then
    # Chrome first, then Chromium, then Edge (always installed on Windows 10/11 and
    # CDP-compatible). The profile is a dedicated directory, never the user's own.
    _pf="$(cygpath -u "${PROGRAMFILES:-C:/Program Files}")"
    _la="$(cygpath -u "${LOCALAPPDATA:-$HOME/AppData/Local}")"
    for _cand in "$_want" \
        "$_pf/Google/Chrome/Application/chrome.exe" "$_pf (x86)/Google/Chrome/Application/chrome.exe" \
        "$_la/Google/Chrome/Application/chrome.exe" "$_la/Chromium/Application/chrome.exe" \
        "$_pf (x86)/Microsoft/Edge/Application/msedge.exe" "$_pf/Microsoft/Edge/Application/msedge.exe"; do
      if [ -n "$_cand" ] && [ -f "$_cand" ]; then CHROMIUM="$_cand"; break; fi
    done
    if [ -z "$CHROMIUM" ]; then
      CHROMIUM="$_pf/Google/Chrome/Application/chrome.exe"
      warn "no Chrome or Edge found; install Chrome (winget install Google.Chrome) and re-run setup"
    fi
  else
  for _name in google-chrome google-chrome-stable chromium chromium-browser; do
    _found="$(PATH="${ALANS_WAY_BROWSER_PATH:-$PATH}" command -v "$_name" 2>/dev/null || true)"
    [ -n "$_found" ] || continue
    if is_snap_browser "$_found"; then
      [ -n "$SNAP_CHROMIUM" ] || SNAP_CHROMIUM="$_found"
    else
      CHROMIUM="$_found"; break
    fi
  done
  if [ -z "$CHROMIUM" ]; then
    for _found in "$BROWSER_HOME"/.cache/ms-playwright/chromium-*/chrome-linux*/chrome; do
      [ -x "$_found" ] && CHROMIUM="$_found"
    done
  fi
  if [ -z "$CHROMIUM" ] && [ -n "$SNAP_CHROMIUM" ]; then
    CHROMIUM="$SNAP_CHROMIUM"; CHROMIUM_IS_SNAP=1
    warn "only snap Chromium found; using a profile under ~/snap/chromium/common. A deb Chrome or Chromium is more reliable (apt-get install chromium, or google-chrome-stable)"
  elif [ -z "$CHROMIUM" ]; then
    CHROMIUM=/usr/bin/google-chrome
    warn "no Chrome or Chromium found; install one (apt-get install chromium, or google-chrome-stable, or: npx playwright install chromium) and re-run setup"
  fi
  fi
  PROFILE_DIR="$DATA_DIR/chromium"
  [ "$CHROMIUM_IS_SNAP" = 0 ] || PROFILE_DIR="$BROWSER_HOME/snap/chromium/common/hermes-alans-way-chromium"
  # Chromium refuses to start as root without --no-sandbox. Root is only used when
  # Hermes itself runs as root; otherwise the services run as the Hermes account.
  NO_SANDBOX=""
  if [ "$BROWSER_USER" = root ]; then
    NO_SANDBOX='    "--no-sandbox",
'
    if [ "$SKIP_SERVICES" = 0 ]; then
      warn "Hermes runs as root here, so the browser runs as root with --no-sandbox. Running Hermes under a normal user account avoids that"
    fi
  fi
  # X11 and /dev/shm flags mean nothing on Windows (the browser opens on the signed-in desktop).
  LINUX_FLAGS='    "--disable-dev-shm-usage",
    "--ozone-platform=x11",
'
  [ "$GUEST_OS" != Windows ] || LINUX_FLAGS=""
  # The CDP port is settled once and then kept: an explicit --cdp-port or
  # ALANS_WAY_CDP_PORT wins, else a port already configured in config.json is
  # preserved on re-run, else the first free loopback port from 9223 up (the
  # default may be owned by another browser on a shared host).
  CDP_PORT="${CDP_PORT_FLAG:-${ALANS_WAY_CDP_PORT:-}}"
  if [ -z "$CDP_PORT" ]; then
    CDP_PORT="$(configured_cdp_port "$DATA_DIR/config.json")"
  fi
  if [ -z "$CDP_PORT" ]; then
    _probe=9223 _tries=0
    while ! port_free "$_probe"; do
      _probe=$((_probe + 1)); _tries=$((_tries + 1))
      [ "$_tries" -le 200 ] || { _probe=""; break; }
    done
    if [ -n "$_probe" ]; then
      [ "$_probe" = 9223 ] || warn "CDP port 9223 is already in use by another process: using $_probe instead"
      CDP_PORT="$_probe"
    else
      CDP_PORT=9223
      warn "no free CDP port within 200 of 9223: pass --cdp-port PORT"
    fi
  fi
  if [ -n "${CDP_PORT_FLAG:-${ALANS_WAY_CDP_PORT:-}}" ] && ! port_free "$CDP_PORT"; then
    warn "CDP port $CDP_PORT is already in use: if that listener is not the managed browser itself, choose a different port"
  fi
  CFG_EXISTED=0; [ ! -f "$DATA_DIR/config.json" ] || CFG_EXISTED=1
  write_if_changed "$DATA_DIR/config.json" backup <<EOF
{
  "port": 9465,
  "cdpUrl": "http://127.0.0.1:$CDP_PORT",
  "browserCommand": "$(wpath "$CHROMIUM")",
  "browserArgs": [
$NO_SANDBOX    "--user-data-dir=$(wpath "$PROFILE_DIR")",
    "--remote-debugging-port=$CDP_PORT",
    "--remote-debugging-address=127.0.0.1",
    "--no-first-run",
    "--start-maximized",
$LINUX_FLAGS    "about:blank"
  ]
}
EOF
  chmod 600 "$DATA_DIR/config.json"
  if [ "$WROTE" = 1 ]; then
    ok "wrote $DATA_DIR/config.json (chromium: $CHROMIUM)"
    CONFIG_CHANGED=1
  else
    ok "config.json already current"
    CONFIG_CHANGED=0
  fi
  if [ "$(id -u)" = 0 ] && [ "$BROWSER_USER" != root ]; then
    chown -R "$BROWSER_USER" "$DATA_DIR" 2>/dev/null || warn "could not give $BROWSER_USER ownership of $DATA_DIR"
    case "$DATA_DIR" in
      "$BROWSER_HOME"/*)
        _dir="$DATA_DIR"
        while [ "$_dir" != "$BROWSER_HOME" ] && [ "$_dir" != / ]; do
          chown "$BROWSER_USER" "$_dir" 2>/dev/null || true
          _dir="$(dirname "$_dir")"
        done;;
    esac
  fi

  if [ "$GUEST_OS" = Windows ]; then
    [ "$SKIP_SERVICES" = 1 ] || install_windows_tasks
  else
  BROWSER_DISPLAY="$(detect_display :99)"
  SYSTEMD_USABLE=0 SYSTEMD_WARNED=0
  if [ "$SKIP_SERVICES" = 0 ] && systemd_live; then
    if [ "$(id -u)" = 0 ] || systemctl --user list-units >/dev/null 2>&1; then
      SYSTEMD_USABLE=1
    else
      SYSTEMD_WARNED=1
      warn "no systemd user session here (not root, and systemctl --user is unavailable), so the browser services were not installed. Start them yourself after logging in with a full session, or run setup as root. See desktop/docs/vps-browser.md in the alans-way repo"
    fi
  fi
  # The supervisord counterpart of the systemd units: same programs, same
  # environment, RestartPreventExitStatus mapped to exitcodes (with
  # autorestart=unexpected, listing a code keeps its exit down; a clean exit 0
  # must be listed too, or it would read as a crash and restart, unlike
  # Restart=on-failure).
  install_supervisor_programs() {
    _confdir="$(supervisor_conf_dir)" || {
      warn "supervisord is running but has no conf.d include dir: add the alans-way programs by hand"
      return 0
    }
    NODE_BIN="$(command -v node || echo /usr/bin/node)"
    SUP_LOG_DIR="$BROWSER_HOME/.local/state/hermes-alans-way"
    mkdir -p "$_confdir" "$SUP_LOG_DIR" || { warn "cannot write $_confdir or $SUP_LOG_DIR: service install skipped"; return 0; }
    _sup_user=""
    if [ "$(id -u)" = 0 ] && [ "$BROWSER_USER" != root ]; then
      _sup_user="user=$BROWSER_USER"
      mkdir -p /var/lib/hermes-alans-way 2>/dev/null \
        && chown "$BROWSER_USER" /var/lib/hermes-alans-way 2>/dev/null || true
      chown -R "$BROWSER_USER" "$SUP_LOG_DIR" 2>/dev/null || true
    elif [ "$(id -u)" = 0 ]; then
      mkdir -p /var/lib/hermes-alans-way 2>/dev/null || true
    fi
    # HERMES_OVERSEER_BOT_IDS rides along when configured: this environment
    # first, then a value a previous run already wrote into the conf.
    _overseer="${HERMES_OVERSEER_BOT_IDS:-}"
    if [ -z "$_overseer" ] && [ -f "$_confdir/alans-way.conf" ]; then
      _overseer="$(sed -n 's/.*HERMES_OVERSEER_BOT_IDS="\([^"]*\)".*/\1/p' "$_confdir/alans-way.conf" | head -1)"
    fi
    _overseer_env=""; [ -z "$_overseer" ] || _overseer_env=",HERMES_OVERSEER_BOT_IDS=\"$_overseer\""
    _env_browser="HOME=\"$BROWSER_HOME\",PATH=\"$(dirname "$NODE_BIN"):/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\",DISPLAY=\"$BROWSER_DISPLAY\",HERMES_VPS_BROWSER_DATA=\"$DATA_DIR\""
    WATCH_SECTION=""
    if [ -n "$MAC_SSH" ]; then
      _watch_state="$(mac_state_path)"
      mkdir -p "$(dirname "$_watch_state")" 2>/dev/null || true
      if [ "$(id -u)" = 0 ] && [ "$BROWSER_USER" != root ]; then
        chown "$BROWSER_USER" "$(dirname "$_watch_state")" 2>/dev/null || true
      fi
      # The serving router resolves the same path: the managed block carries
      # HERMES_MAC_STATE_FILE (exported near the top of this script on every
      # run) so both processes agree.
      WATCH_SECTION="$(cat <<EOFW

[program:alans-way-mac-watch]
command=$NODE_BIN $(router_script) --watch --interval 10
$_sup_user
environment=HOME="$BROWSER_HOME",PATH="$(dirname "$NODE_BIN"):/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",HERMES_WORKSPACE_MAC_SSH="$MAC_SSH",HERMES_WORKSPACE_HOST_OS="$HOST_OS",HERMES_MAC_STATE_FILE="$_watch_state"
directory=$BROWSER_HOME
autorestart=unexpected
exitcodes=2
stdout_logfile=$SUP_LOG_DIR/mac-watch.log
stderr_logfile=$SUP_LOG_DIR/mac-watch.err.log
EOFW
)"
    fi
    _conf="$_confdir/alans-way.conf"
    write_if_changed "$_conf" <<EOF || { warn "could not write $_conf: service install skipped"; return 0; }
[program:alans-way-chromium]
command=$NODE_BIN $DESKTOP_DIR/desktop/scripts/vps-chromium-host.cjs
$_sup_user
environment=$_env_browser
directory=$BROWSER_HOME
autorestart=unexpected
exitcodes=0
stdout_logfile=$SUP_LOG_DIR/chromium.log
stderr_logfile=$SUP_LOG_DIR/chromium.err.log

[program:alans-way-browser]
command=$NODE_BIN $DESKTOP_DIR/desktop/scripts/vps-browser-host.cjs serve
$_sup_user
environment=$_env_browser$_overseer_env
directory=$BROWSER_HOME
autorestart=unexpected
exitcodes=0,78
stdout_logfile=$SUP_LOG_DIR/browser.log
stderr_logfile=$SUP_LOG_DIR/browser.err.log
$WATCH_SECTION
EOF
    if [ "$WROTE" = 1 ]; then
      ok "wrote $_conf"
      supervisorctl reread >/dev/null 2>&1 && supervisorctl update >/dev/null 2>&1 \
        && ok "supervisord picked up the service definitions" \
        || warn "supervisorctl reread or update failed: the programs may not be loaded"
    else
      ok "$_conf already current"
    fi
    # `update` restarts programs whose conf changed; start whatever is still
    # stopped (a fresh install, or a program that exited cleanly).
    for _p in alans-way-chromium alans-way-browser ${MAC_SSH:+alans-way-mac-watch}; do
      case "$(supervisorctl status "$_p" 2>/dev/null || true)" in
        *" RUNNING "*) ok "$_p running under supervisord";;
        *) supervisorctl start "$_p" >/dev/null 2>&1 \
             && ok "$_p started under supervisord" \
             || warn "could not start $_p via supervisorctl: start it once the desktop stack is up (needs DISPLAY=$BROWSER_DISPLAY)";;
      esac
    done
    if [ "${BROWSER_UPDATED:-0}" = 1 ]; then
      supervisorctl restart alans-way-browser >/dev/null 2>&1 \
        && ok "browser host restarted on the new scripts" \
        || warn "could not restart alans-way-browser: run supervisorctl restart alans-way-browser"
    fi
    if [ "$CONFIG_CHANGED" = 1 ] && [ "$CFG_EXISTED" = 1 ]; then
      say "  browser settings changed: restart the alans-way-chromium program to apply them (open tabs close)"
    fi
  }
  if [ "$SYSTEMD_USABLE" = 1 ]; then
    NODE_BIN="$(command -v node || echo /usr/bin/node)"
    UNIT_DIR="/etc/systemd/system"; SYSCTL="systemctl"; UNIT_USER="User=$BROWSER_USER"
    if [ "$(id -u)" != 0 ] && systemctl --user list-units >/dev/null 2>&1; then
      UNIT_DIR="$HOME/.config/systemd/user"; SYSCTL="systemctl --user"; UNIT_USER=""
    fi
    [ -z "${ALANS_WAY_UNIT_DIR:-}" ] || UNIT_DIR="$ALANS_WAY_UNIT_DIR"
    mkdir -p "$UNIT_DIR"
    # The desktop scripts read HERMES_OVERSEER_BOT_IDS when it is configured;
    # it rides along in the environment, same as the supervisord path.
    OVERSEER_UNIT_ENV=""
    [ -z "${HERMES_OVERSEER_BOT_IDS:-}" ] || OVERSEER_UNIT_ENV="Environment=HERMES_OVERSEER_BOT_IDS=$HERMES_OVERSEER_BOT_IDS"
    UNITS_CHANGED="" UNITS_UPDATED=""
    write_unit() { # write_unit <name> <exec> <extra>
      _f="$UNIT_DIR/$1"
      _existed=0; [ -f "$_f" ] && _existed=1
      write_if_changed "$_f" <<EOF
[Unit]
Description=Hermes Alan's Way $1
After=network.target

[Service]
Type=simple
$UNIT_USER
Environment=DISPLAY=$BROWSER_DISPLAY
Environment=HERMES_VPS_BROWSER_DATA=$DATA_DIR
${OVERSEER_UNIT_ENV}
$3
ExecStart=$NODE_BIN $2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=$([ "$SYSCTL" = "systemctl" ] && echo multi-user.target || echo default.target)
EOF
      if [ "$WROTE" = 1 ]; then
        ok "wrote $_f"
        UNITS_CHANGED="$UNITS_CHANGED $1"
        [ "$_existed" = 0 ] || UNITS_UPDATED="$UNITS_UPDATED $1"
      fi
    }
    write_unit hermes-alans-way-chromium.service "$DESKTOP_DIR/desktop/scripts/vps-chromium-host.cjs" ""
    write_unit hermes-alans-way-browser.service "$DESKTOP_DIR/desktop/scripts/vps-browser-host.cjs serve" "RestartPreventExitStatus=78"
    [ -z "$UNITS_CHANGED" ] || $SYSCTL daemon-reload 2>/dev/null || true
    $SYSCTL enable --now hermes-alans-way-chromium.service hermes-alans-way-browser.service >/dev/null 2>&1 \
      && ok "browser services enabled" \
      || warn "units written but not started: start them after your X11/VNC desktop is up (needs DISPLAY=$BROWSER_DISPLAY)"
    # User units stop at logout unless the account is allowed to linger.
    if [ "$SYSCTL" != systemctl ] && have loginctl; then
      loginctl enable-linger "$(id -un)" >/dev/null 2>&1 \
        && ok "lingering enabled so the browser services survive logout" \
        || warn "could not enable lingering: the browser services stop when you log out. Run: sudo loginctl enable-linger $(id -un)"
    fi
    # A unit that changed while its service was running needs a restart to
    # pick up the new paths or user.
    for _unit in $UNITS_UPDATED; do
      $SYSCTL restart "$_unit" >/dev/null 2>&1 \
        && ok "restarted $_unit on its refreshed unit file" \
        || warn "could not restart $_unit: restart it to load the refreshed unit"
    done
    # Chromium keeps running so open tabs and sign-ins survive an update.
    if [ "${BROWSER_UPDATED:-0}" = 1 ]; then
      $SYSCTL restart hermes-alans-way-browser.service >/dev/null 2>&1 \
        && ok "browser host restarted on the new scripts" \
        || warn "could not restart hermes-alans-way-browser.service: restart it to load the update"
    fi
    if [ "$CONFIG_CHANGED" = 1 ] && [ "$CFG_EXISTED" = 1 ]; then
      case " $UNITS_UPDATED " in
        *" hermes-alans-way-chromium.service "*) ;;
        *) say "  browser settings changed: restart hermes-alans-way-chromium.service to apply them (open tabs close)";;
      esac
    fi
    # The router reads the watcher's default state file under
    # /var/lib, which only a root system unit's StateDirectory provides.
    if [ -n "$MAC_SSH" ] && [ "$SYSCTL" = "systemctl" ] && [ "$(id -u)" = 0 ]; then
      WATCH_ENV_DIR="${ALANS_WAY_ENV_DIR:-/etc/hermes-alans-way}"
      MAC_WATCH_USER="$BROWSER_USER"
      mkdir -p "$WATCH_ENV_DIR"
      write_if_changed "$WATCH_ENV_DIR/mac-watch.env" <<EOF
HERMES_WORKSPACE_MAC_SSH=$MAC_SSH
HERMES_WORKSPACE_HOST_OS=$HOST_OS
EOF
      WATCH_CHANGED=$WROTE
      write_if_changed "$UNIT_DIR/mac-watch.service" <<EOF
[Unit]
Description=Hermes Alan's Way Mac availability watcher
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$MAC_WATCH_USER
Environment=PATH=$(dirname "$NODE_BIN"):/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EnvironmentFile=$WATCH_ENV_DIR/mac-watch.env
ExecStart=$NODE_BIN $(router_script) --watch --interval 10
Restart=always
RestartSec=5
RestartPreventExitStatus=2
StateDirectory=hermes-alans-way

[Install]
WantedBy=multi-user.target
EOF
      [ "$WROTE" = 0 ] || { WATCH_CHANGED=1; ok "wrote $UNIT_DIR/mac-watch.service"; systemctl daemon-reload 2>/dev/null || true; }
      systemctl enable --now mac-watch.service >/dev/null 2>&1 \
        && ok "Mac availability watcher enabled" \
        || warn "could not start mac-watch.service: the bot won't notice the Mac going on or offline"
      [ "$WATCH_CHANGED" = 0 ] || systemctl restart mac-watch.service >/dev/null 2>&1 || true
    elif [ -n "$MAC_SSH" ]; then
      warn "Mac availability watcher not installed (needs root + systemd): see README 'mac-watch'"
    fi
  elif [ "$SKIP_SERVICES" = 0 ] && [ "$GUEST_OS" = Linux ] && supervisord_usable; then
    install_supervisor_programs
  else
    [ "$SKIP_SERVICES" = 1 ] || [ "$SYSTEMD_WARNED" = 1 ] || warn "no live systemd or supervisord here, so the browser services were not installed: see desktop/docs/vps-browser.md in the alans-way repo for manual setup"
  fi
  fi
  fi

  # mac-watch as a per-user LaunchAgent on a macOS guest. The router's darwin
  # default state file matches the --state-file below.
  if [ "$GUEST_OS" = Darwin ] && [ "$SKIP_SERVICES" = 0 ] && [ -n "$MAC_SSH" ]; then
    WATCH_STATE="$HOME/Library/Application Support/hermes-alans-way/mac-state.json"
    WATCH_PLIST="$HOME/Library/LaunchAgents/com.alans-way.mac-watch.plist"
    mkdir -p "$(dirname "$WATCH_STATE")" "$HOME/Library/LaunchAgents"
    cat > "$WATCH_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>com.alans-way.mac-watch</string>
	<key>ProgramArguments</key>
	<array>
		<string>$(command -v node || echo /usr/local/bin/node)</string>
		<string>$(router_script)</string>
		<string>--watch</string>
		<string>--interval</string>
		<string>10</string>
		<string>--state-file</string>
		<string>$WATCH_STATE</string>
	</array>
	<key>EnvironmentVariables</key>
	<dict>
		<key>HERMES_WORKSPACE_MAC_SSH</key>
		<string>$MAC_SSH</string>
		<key>HERMES_WORKSPACE_HOST_OS</key>
		<string>$HOST_OS</string>
		<key>PATH</key>
		<string>$(dirname "$(command -v node || echo /usr/local/bin/node)"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
	</dict>
	<key>KeepAlive</key>
	<true/>
	<key>RunAtLoad</key>
	<true/>
</dict>
</plist>
EOF
    launchctl bootout "gui/$(id -u)/com.alans-way.mac-watch" 2>/dev/null || true
    if launchctl bootstrap "gui/$(id -u)" "$WATCH_PLIST" 2>/dev/null \
      || launchctl load -w "$WATCH_PLIST" 2>/dev/null; then
      ok "host availability watcher installed (launchd)"
    else
      warn "could not load mac-watch agent: the bot won't notice the host going on or offline"
    fi
  fi
fi

# ------------------------------------------------------------- desktop prereqs (guided)
if [ "$SKIP_BROWSER" = 0 ]; then
  step "Desktop prerequisites (guided)"
  if [ "$GUEST_OS" = Darwin ]; then
    say "  macOS guest needs no X11 stack. Grant the console user Accessibility and"
    say "  Screen Recording for the connector once, then the LaunchAgents run the"
    say "  browser host in the window session. Guide: docs/mac-vm-guest.md in the"
    say "  alans-way repo. Preview: scripts/mac-vm-preview.sh on the host."
  elif [ "$GUEST_OS" = Windows ]; then
    say "  Windows guest needs no X11 stack: Chrome opens on the signed-in desktop. Keep this"
    say "  PC awake and signed in (the browser and watcher start at logon), and turn on"
    say "  automatic sign-in (run netplwiz) so a reboot brings everything back."
  elif display_stack_present; then
    ok "a display stack is present (DISPLAY=${BROWSER_DISPLAY:-:99})"
    _wsport="$(websockify_port || true)"
    if [ -n "$_wsport" ]; then
      _tsip="$(have "$TAILSCALE" && "$TAILSCALE" ip -4 2>/dev/null | head -1 || true)"
      say "  remote desktop is already serving: http://${_tsip:-<this-host>}:$_wsport/vnc.html"
    fi
  else
    say "  no display stack detected (Xvfb, x11vnc, TigerVNC, or websockify): for the VPS"
    say "  desktop, install one:"
    say "    apt-get install xvfb x11vnc websockify chromium-browser"
    say "    (or tigervnc-standalone-server for a TigerVNC + noVNC stack)"
    say "  then start the server on DISPLAY=${BROWSER_DISPLAY:-:99} and a noVNC viewer."
    say "  Full guide: desktop/docs/vps-browser.md in the alans-way repo."
  fi
fi

# ------------------------------------------------------------- workspace config
step "Workspace browser config"
# A user-added cua-driver MCP server (named so, or a command/args mentioning it)
# is the user's to keep, but it is a second computer-use path next to ours.
warn_user_cua_driver() {
  if [ -n "$PROFILE" ]; then _cfg="$HERMES_HOME/profiles/$PROFILE/config.yaml"
  else _cfg="${CONFIG:-$HERMES_HOME/config.yaml}"; fi
  [ -f "$_cfg" ] || return 0
  _name="$(python3 - "$_cfg" <<'PY'
import re, sys
try:
    lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
except Exception:
    sys.exit(0)
inside, indent, name = False, None, None
for line in lines:
    if not inside:
        inside = line.startswith("mcp_servers:")
        continue
    if not line.strip() or line.lstrip().startswith("#"):
        continue
    depth = len(line) - len(line.lstrip())
    if depth == 0:
        break
    indent = depth if indent is None else indent
    if depth == indent:
        entry = re.match(r"\s*([^\s#:][^:]*):", line)
        name = entry.group(1).strip("\"'") if entry else None
    if name and "cua-driver" in line:
        print(name)
        break
PY
)"
  [ -n "$_name" ] || return 0
  warn "profile ${PROFILE:-default} has a cua-driver MCP server of its own: the agent sees two computer-use paths (it was left in place). To remove it: hermes${PROFILE:+ -p $PROFILE} mcp remove $_name"
}

# One profile: its workspace_browser block under its own bot id, then the
# per-profile switches that go with it.
workspace_for_profile() {
  set -- --bot-id "$BOT_ID"
  [ -n "$BOT_NAME" ] && set -- "$@" --bot-name "$BOT_NAME"
  [ -n "$MAC_SSH" ] && set -- "$@" --mac-ssh "$MAC_SSH"
  set -- "$@" --host-os "$HOST_OS"
  # The router runs the copy Hermes loaded (the catalog install's own script),
  # not a possibly newer clone of this repo.
  set -- "$@" --router "$(router_script)"
  # Exposing the raw desktop-input tool is the manual opt-in for a Hermes
  # without the computer-use provider API. With the API, desktop input goes
  # only through the gated computer_use provider, so the tool stays excluded.
  [ "$ALLOW_DESKTOP" = 1 ] && [ "$COMPUTER_API" != 1 ] && set -- "$@" --allow-desktop-actions
  if [ -n "$PROFILE" ]; then set -- "$@" --profile "$PROFILE"
  elif [ -n "$CONFIG" ]; then set -- "$@" --config "$CONFIG"
  else set -- "$@" --config "$HERMES_HOME/config.yaml"; fi
  if sh "$REPO_DIR/setup-workspace.sh" "$@"; then
    ok "workspace_browser configured${PROFILE:+ for profile $PROFILE}"
    if [ "$COMPUTER_READY" = 1 ]; then
      # Read back what was set: a stale write or an overruled value leaves the
      # provider installed but unselected, which must be loud, not silent.
      if hermes_p config set computer_use.backend "$COMPUTER_PLUGIN" >/dev/null 2>&1 \
          && [ "$(hermes_p config get computer_use.backend 2>/dev/null | tail -1)" = "$COMPUTER_PLUGIN" ]; then
        COMPUTER_SELECTED=1
        ok "computer use runs through $COMPUTER_PLUGIN"
      else
        warn "the computer-use provider is installed but could not be selected: run hermes${PROFILE:+ -p $PROFILE} config set computer_use.backend $COMPUTER_PLUGIN"
      fi
      # The gated toolset is now the only desktop-input path: undo an older
      # setup's tools disable so the provider can serve it.
      for platform in telegram cron; do
        hermes_p tools enable computer_use --platform "$platform" >/dev/null 2>&1 \
          && ok "computer_use toolset enabled for $platform (approval-gated; actions run through $COMPUTER_PLUGIN)" \
          || warn "could not enable computer_use for $platform: desktop input stays unavailable there (run: hermes${PROFILE:+ -p $PROFILE} tools enable computer_use --platform $platform)"
      done
    else
      # No provider to select (this Hermes lacks the pluggable API, or the
      # install was skipped): the built-in computer_use toolset is the desktop
      # input path and stays approval-gated, so it should be on. Setup <=0.6.0
      # disabled it for every configured profile, and nothing records whose
      # disable it was, so a profile carrying our workspace block gets it back
      # exactly once per platform; the ledger keeps a user's later disable from
      # being fought on every rerun.
      if [ -n "$PROFILE" ]; then _cfg="$HERMES_HOME/profiles/$PROFILE/config.yaml"
      else _cfg="${CONFIG:-$HERMES_HOME/config.yaml}"; fi
      if [ "$(workspace_block_state "$_cfg")" != absent ]; then
        _restored="$PROFILE_HOME/.alans-way-computer-use-restored"
        for platform in telegram cron; do
          if ! grep -qx "$platform" "$_restored" 2>/dev/null \
              && hermes_p tools list --platform "$platform" 2>/dev/null \
                 | grep -Eq "disabled[[:space:]]+computer_use([[:space:]]|$)"; then
            if hermes_p tools enable computer_use --platform "$platform" >/dev/null 2>&1; then
              printf '%s\n' "$platform" >> "$_restored" 2>/dev/null || true
              ok "re-enabled computer_use for $platform (turn it off with: hermes${PROFILE:+ -p $PROFILE} tools disable computer_use --platform $platform)"
            else
              warn "computer_use is disabled for $platform but could not be re-enabled (run: hermes${PROFILE:+ -p $PROFILE} tools enable computer_use --platform $platform)"
            fi
          fi
        done
      fi
    fi
    warn_user_cua_driver
    # The workspace browser replaces Hermes' built-in browser tool: leaving both
    # enabled lets the agent pick a different browser than the user's app. Cron
    # sessions see the same workspace tools, so the stock toolset goes off there
    # too (a cron-run agent has reached for the built-in browser first).
    if [ "$KEEP_BROWSER" = 1 ]; then
      say "  keeping the built-in browser toolset on (--keep-browser); the agent may pick it instead of your workspace browser"
    else
      for platform in telegram cron; do
        hermes_p tools disable browser --platform "$platform" >/dev/null 2>&1 \
          && ok "built-in browser toolset disabled for $platform so the agent uses your workspace browser. To keep it on, re-run with --keep-browser or run: hermes${PROFILE:+ -p $PROFILE} tools enable browser --platform $platform" \
          || warn "could not disable the built-in browser toolset for $platform: the agent may bypass the workspace browser (run: hermes${PROFILE:+ -p $PROFILE} tools disable browser --platform $platform)"
      done
    fi
  else
    bad "setup-workspace.sh failed"
  fi
}
if [ -z "$BOT_ID" ]; then
  _rc=0
  derive_bot_id "$PROFILE_HOME" || _rc=$?
  [ "$_rc" != 1 ] || derive_bot_id_from_env "$HERMES_HOME/.env" || true
fi
if [ -z "$BOT_ID" ] && has_tty; then
  BOT_ID="$(ask "  Numeric Telegram bot ID for this agent (empty to skip)" "")"
fi
if [ -n "$BOT_ID" ]; then
  workspace_for_profile
else
  say "  skipped (no --bot-id). Re-run with --bot-id <numeric-telegram-bot-id>."
fi

# Every other profile with a Telegram bot of its own gets the plugin (for the
# workspace skills; proactivity is the primary's alone) and the same workspace
# setup under that bot's id.
install_plugin_for_bot_profile() {
  if plugin_listed "$PLUGIN_NAME" || plugin_is_catalog_installed; then
    ok "plugin already installed in profile $PROFILE; leaving it as it is"
    say "  to move it forward: hermes -p $PROFILE plugins update $PLUGIN_NAME"
  elif [ "$SKIP_PLUGIN" = 1 ]; then
    warn "no $PLUGIN_NAME plugin in profile $PROFILE (--skip-plugin): install it from the Hermes catalog: hermes -p $PROFILE plugins install $PLUGIN_NAME"
  elif hermes_p plugins install --force "$REPO_FILE_URL#$PLUGIN_NAME" >/dev/null 2>&1; then
    hermes_p plugins enable "$PLUGIN_NAME" >/dev/null 2>&1 || true
    ok "plugin installed in profile $PROFILE"
  else
    warn "could not install the plugin in profile $PROFILE: run: hermes -p $PROFILE plugins install --force $REPO_FILE_URL#$PLUGIN_NAME"
  fi
}
if [ "$ONLY_PROFILE" = 0 ]; then
  _primary_bot="$BOT_ID" _primary_name="$BOT_NAME" _primary_ready="$COMPUTER_READY"
  for _dir in "$HERMES_HOME"/profiles/*/; do
    [ -d "$_dir" ] || continue
    _name="$(basename "$_dir")"
    case "$_name" in default|''|-*|.*|*[!0-9A-Za-z_.-]*) continue;; esac
    BOT_ID="" BOT_NAME="" _rc=0
    derive_bot_id "${_dir%/}" || _rc=$?
    if [ "$_rc" != 0 ]; then
      [ "$_rc" = 2 ] || say "  profile $_name: no Telegram bot of its own, skipped"
      continue
    fi
    PROFILE="$_name" PROFILE_HOME="${_dir%/}"
    install_plugin_for_bot_profile
    COMPUTER_READY=0
    if [ "$COMPUTER_API" = 1 ]; then ensure_computer_provider; fi
    workspace_for_profile
  done
  BOT_ID="$_primary_bot" BOT_NAME="$_primary_name" PROFILE="" PROFILE_HOME="$HERMES_HOME" COMPUTER_READY="$_primary_ready"
fi

# Desktop actions ask for approval in Telegram each time. Seeded only when asked.
if [ "$ALLOW_DESKTOP" = 1 ]; then
  _current="$(hermes_p config get command_allowlist --json 2>&1 || true)"
  _merged="$(printf '%s' "$_current" | python3 -c '
import json, sys
text = sys.stdin.read().strip()
new = ["cua:%s:background" % a for a in ("click", "double_click", "right_click", "middle_click", "drag",
                                          "scroll", "type", "key", "set_value", "focus_app")]
if "not set" in text or text in ("", "null", "None"):
    current = []
else:
    try:
        current = json.loads(text)
    except ValueError:
        current = None
    if not (isinstance(current, list) and all(isinstance(x, str) for x in current)):
        sys.exit(1)
print(json.dumps(current + [x for x in new if x not in current], separators=(",", ":")))' 2>/dev/null)" || _merged=""
  if [ -z "$_merged" ]; then
    warn "could not read the existing command_allowlist, so it was left alone"
  elif hermes_p config set command_allowlist "$_merged" >/dev/null 2>&1; then
    ok "desktop actions (click, type, key, scroll and similar, background only) no longer ask for approval"
  else
    warn "could not write command_allowlist"
  fi
elif [ "$COMPUTER_SELECTED" = 1 ]; then
  say "  Desktop control asks for approval in Telegram for each action. To stop those prompts, re-run setup with --allow-desktop-actions; leave it off to keep approving each one."
fi

# The gateway CLI derives its restart-wait budget from TimeoutStartSec, and a
# multi-profile boot (several platform adapters + MCP connects) routinely
# exceeds the 90s default — the service keeps booting fine while the CLI
# reports a timeout. Widen it where systemd owns the unit; never clobber an
# operator-set drop-in.
GW_SERVICE="hermes-gateway${PROFILE:+-$PROFILE}"
if systemd_live; then
  for scope in "--user" ""; do
    if systemctl $scope cat "$GW_SERVICE.service" >/dev/null 2>&1; then
      if [ -n "$scope" ]; then
        drop_dir="$HOME/.config/systemd/user/$GW_SERVICE.service.d"
      elif [ "$(id -u)" = 0 ]; then
        drop_dir="/etc/systemd/system/$GW_SERVICE.service.d"
      else
        break
      fi
      if [ ! -f "$drop_dir/timeout.conf" ]; then
        mkdir -p "$drop_dir" \
          && printf '[Service]\nTimeoutStartSec=180\n' > "$drop_dir/timeout.conf" \
          && systemctl $scope daemon-reload >/dev/null 2>&1 \
          && ok "$GW_SERVICE restart patience widened (TimeoutStartSec=180)" \
          || warn "could not write $drop_dir/timeout.conf: long restarts may report a timeout"
      fi
      break
    fi
  done
fi

detect_host_timezone
ask_timezone

# ------------------------------------------------------------- bind proactivity
step "Primary bot binding"
ROUTES="$(python3 - "$HERMES_HOME" <<'PY'
import json, sys, pathlib, sqlite3
home = pathlib.Path(sys.argv[1])
seen = set()

def emit(file_profile, key, entry):
    if (isinstance(entry, dict) and key not in seen
            and entry.get("platform") == "telegram"
            and entry.get("chat_type") == "dm" and entry.get("suspended") is not True):
        seen.add(key)
        agent = key.split(":")[1] if key.count(":") >= 2 else file_profile
        print(f"{file_profile}\t{agent}\t{key}")

profiles = [home] + (sorted((home / "profiles").glob("*"))
                     if (home / "profiles").is_dir() else [])
for prof_dir in profiles:
    file_profile = "default" if prof_dir == home else prof_dir.name
    # Authoritative store first — gateway_routing rows are namespaced by the
    # resolved sessions dir ('' covers pre-scoping rows); the sessions.json
    # mirror then fills keys the DB lacks, same order Hermes loads them in.
    db_path = prof_dir / "state.db"
    try:
        if db_path.is_file() and not db_path.is_symlink():
            scope = str((prof_dir / "sessions").resolve())
            db = sqlite3.connect(f"{db_path.absolute().as_uri()}?mode=ro", uri=True, timeout=5)
            try:
                rows = db.execute(
                    "SELECT session_key, entry_json FROM gateway_routing"
                    " WHERE scope IN (?, '')", (scope,)).fetchall()
            finally:
                db.close()
            for key, entry_json in rows:
                try:
                    emit(file_profile, key, json.loads(entry_json))
                except ValueError:
                    continue
    except Exception:
        pass
    try:
        data = json.loads((prof_dir / "sessions" / "sessions.json").read_text(encoding="utf-8"))
        for key, entry in (data.items() if isinstance(data, dict) else []):
            emit(file_profile, key, entry)
    except Exception:
        pass
PY
)"
# An already bound profile keeps its binding across re-runs: without --bind,
# say so instead of listing routes or claiming check-ins stay silent.
ALREADY_BOUND=0
if [ "$DO_BIND" = 0 ] && have hermes \
    && hermes_p proactivity status 2>/dev/null | python3 -c 'import json, sys
try: s = json.load(sys.stdin)
except Exception: s = {}
sys.exit(0 if s.get("bound") else 1)'; then
  ALREADY_BOUND=1
fi
if [ "$ALREADY_BOUND" = 1 ]; then
  ok "proactivity is already bound to a primary route: keeping the existing binding (to change it, re-run: setup.sh --bind${PROFILE:+ --profile $PROFILE})"
elif [ -z "$ROUTES" ]; then
  say "  no Telegram DM sessions yet. Message your bot once on Telegram,"
  say "  then re-run:  setup.sh --bind${PROFILE:+ --profile $PROFILE}"
else
  say "  existing Telegram routes (pick which bot is the primary):"
  echo "$ROUTES" | python3 -c 'import sys
for i, line in enumerate(sys.stdin, 1):
    p, a, k = line.rstrip("\n").split("\t", 2)
    print(f"    [{i}] {a}  (home profile: {p})")'
  if [ "$DO_BIND" = 1 ] && ! has_tty; then
    WANT="${PROFILE:-main}"
    SEL="$(echo "$ROUTES" | awk -F '\t' -v want="$WANT" '$2 == want { print NR }')"
    if [ "$(echo "$ROUTES" | wc -l)" = 1 ]; then
      SEL=1
    elif [ "$(printf '%s\n' "$SEL" | grep -c .)" != 1 ]; then
      bad "--bind found no single Telegram DM route for profile '$WANT'. Message that bot once, or bind manually with: hermes${PROFILE:+ -p $PROFILE} proactivity bind --session-key <key>"
      SEL=""
    fi
  else
    SEL="$(ask "  Bind a primary route? [1..N/N]" "N")"
  fi
  case "$SEL" in
    ''|n|N|no) say "  skipped binding: proactivity stays silent until you bind a route.";;
    *[!0-9]*) warn "invalid selection: bind manually with: hermes proactivity bind --session-key <key>";;
    *) SEL_KEY="$(echo "$ROUTES" | sed -n "${SEL}p" | cut -f3)"
       SEL_PROF="$(echo "$ROUTES" | sed -n "${SEL}p" | cut -f1)"
       SEL_AGENT="$(echo "$ROUTES" | sed -n "${SEL}p" | cut -f2)"
       if [ -n "$SEL_KEY" ]; then
         # A multiplexed gateway indexes every profile's sessions at the root;
         # the route's agent segment names the profile that owns it.
         [ "$SEL_PROF" != default ] || [ ! -d "$HERMES_HOME/profiles/$SEL_AGENT" ] || SEL_PROF="$SEL_AGENT"
         BIND_PROF="$SEL_PROF"
         # The timezone rides on bind; a plugin whose bind has no --timezone gets a second call.
         BOUND=0 TZ_SET=0
         if [ -n "$TIMEZONE" ] && hermes -p "$BIND_PROF" proactivity bind --session-key "$SEL_KEY" --timezone "$TIMEZONE" >/dev/null 2>&1; then
           BOUND=1 TZ_SET=1
         elif hermes -p "$BIND_PROF" proactivity bind --session-key "$SEL_KEY" >/dev/null 2>&1; then
           BOUND=1
         fi
         if [ "$BOUND" = 1 ]; then
           ok "bound primary route: $SEL_AGENT"
           if [ -z "$TIMEZONE" ]; then
             warn "no timezone known: the bot will ask you for it. Or set it with: hermes -p $BIND_PROF proactivity set --timezone <IANA zone>"
           elif [ "$TZ_SET" != 1 ]; then
             hermes -p "$BIND_PROF" proactivity set --timezone "$TIMEZONE" >/dev/null 2>&1 \
               && ok "check-in hours use $TIMEZONE" \
               || warn "could not set timezone $TIMEZONE"
           else
             ok "check-in hours use $TIMEZONE"
           fi
           if [ "${PROACTIVE:-yes}" = no ]; then
             hermes -p "$BIND_PROF" proactivity set --settings '{"paused_until": "off"}' >/dev/null 2>&1 \
               && say "  check-ins bound but paused: send /proactivity resume to turn them on" \
               || warn "could not pause: check-ins stay on"
           else
             ok "proactivity on by default: tell your bot \"stop checking in\" to pause"
           fi
         else
           bad "bind failed: run manually: hermes -p "$BIND_PROF" proactivity bind --session-key <key>"
         fi
       else
         warn "invalid selection: bind manually with: hermes proactivity bind --session-key <key>"
       fi;;
  esac
fi

# ---------------------------------------------------------------- verify
step "Verify"
have hermes && plugin_listed "$PLUGIN_NAME" && ok "plugin enabled" || bad "plugin missing"
if [ -n "$BOT_ID" ]; then
  CFG="$CONFIG"; [ -n "$CFG" ] || { [ -n "$PROFILE" ] && CFG="$HERMES_HOME/profiles/$PROFILE/config.yaml" || CFG="$HERMES_HOME/config.yaml"; }
  [ -f "$CFG" ] && { grep -q '>>> alans-way workspace_browser managed block >>>' "$CFG" \
    || grep -q '^ \+workspace_browser:' "$CFG"; } \
    && ok "workspace_browser block in $CFG" || warn "workspace_browser block not found in $CFG"
fi
if [ "$GUEST_OS" = Darwin ]; then
  VCONN="$HOME/Library/Application Support/hermes-alans-way/browser/connection.json"
else
  VCONN="$BROWSER_HOME/.local/share/hermes-alans-way/browser/connection.json"
fi
[ -f "$VCONN" ] && ok "browser host running" \
  || warn "browser host not running yet (start the service or desktop session)"
check_computer_provider

# The restart runs last and detached. It can end the very session that is running
# this script (an agent driving setup from Telegram lives inside the gateway), so
# nothing may follow it and the caller gets time to send its final message first.
# The decision is made here, the action after the summary.
step "Gateway restart"
GW_HINT="A running gateway holds already-imported code, so restart it to load the plugin."
WANT_RESTART=0
if [ "$DO_RESTART" = 1 ] || { has_tty && confirm "  Restart the Hermes gateway when setup finishes?"; }; then
  WANT_RESTART=1
else
  say "  $GW_HINT"
fi

schedule_gateway_restart() {
  GW_DELAY="${ALANS_WAY_RESTART_DELAY:-10}"
  GW_LOG="$(mktemp "${TMPDIR:-/tmp}/alans-way-gateway-restart.XXXXXX" 2>/dev/null)" || GW_LOG=/dev/null
  GW_HERMES="$(command -v hermes || echo hermes)"
  if [ "$GUEST_OS" = Windows ]; then
    # Task Scheduler starts the restarter outside this shell's and the gateway's
    # process tree (and job object), so stopping the gateway cannot kill it. It
    # waits, runs hermes gateway restart, then removes itself.
    case "$GW_HERMES" in *.exe|*.cmd|*.bat) ;; *) [ ! -f "$GW_HERMES.exe" ] || GW_HERMES="$GW_HERMES.exe";; esac
    win_task AlansWay_GatewayRestart "Start-Sleep -Seconds $GW_DELAY; \$env:HERMES_HOME=$(psq "$HERMES_HOME"); & $(psq "$(cygpath -w "$GW_HERMES")") -p $(psq "${PROFILE:-default}") gateway restart *> $(psq "$(cygpath -w "$GW_LOG")"); Unregister-ScheduledTask -TaskName 'AlansWay_GatewayRestart' -Confirm:\$false" once \
      || warn "could not schedule the restart: run hermes${PROFILE:+ -p $PROFILE} gateway restart yourself"
    return 0
  fi
  # $1 hermes, $2 profile, $3 systemd unit, $4 seconds to wait first,
  # $5 supervisor program name when the gateway is one of supervisord's
  # (restarting that program is the safe path: `hermes gateway restart`
  # races with supervisord's own respawn of the same process), $6 the
  # resolved supervisorctl path (a detached restarter may not share our PATH).
  GW_SUP="$(supervisor_gateway_program || true)"
  GW_SUPCTL="$(command -v supervisorctl 2>/dev/null || echo supervisorctl)"
  _restart='sleep "$4"
    if [ -n "$5" ]; then
      "$6" restart "$5" && echo "restarted: $6 restart $5" \
        || echo "$6 restart $5 failed: restart that program by hand"
    elif "$1" -p "$2" gateway restart; then echo "restarted: hermes gateway restart"
    elif systemctl is-active --quiet "$3"; then systemctl restart "$3" && echo "restarted: systemctl restart $3"
    elif systemctl --user is-active --quiet "$3"; then systemctl --user restart "$3" && echo "restarted: systemctl --user restart $3"
    elif pgrep -f "gateway run" >/dev/null 2>&1; then echo "a supervisor-managed gateway is running: restart it through its owner (PM/launchd), not here"
    else echo "no live gateway found: start it with hermes gateway run"
    fi'
  # On systemd a transient timer unit keeps the restarter out of the gateway's own
  # cgroup, so stopping the gateway cannot take it down mid-restart.
  if [ "$GUEST_OS" = Linux ] && have systemd-run; then
    _scope="--user"; [ "$(id -u)" != 0 ] || _scope=""
    # shellcheck disable=SC2086
    if systemd-run $_scope --collect --quiet --on-active="${GW_DELAY}s" \
        --setenv=HERMES_HOME="$HERMES_HOME" --setenv=HOME="$HOME" \
        /bin/sh -c "$_restart" sh "$GW_HERMES" "${PROFILE:-default}" "$GW_SERVICE" 0 "$GW_SUP" "$GW_SUPCTL" >"$GW_LOG" 2>&1; then
      return 0
    fi
  fi
  # Elsewhere: a new session (macOS has no setsid command) so closing the caller's
  # session or killing its process group does not reach the restarter.
  # The launcher touches a file once it has its own session; waiting for it closes
  # the gap in which the caller could still kill the restarter along with itself.
  GW_READY="${TMPDIR:-/tmp}/alans-way-restart-ready.$$"
  python3 -c 'import os, sys; os.setsid(); open(sys.argv[1], "w").close(); os.execvp(sys.argv[2], sys.argv[2:])' \
    "$GW_READY" nohup /bin/sh -c "$_restart" sh "$GW_HERMES" "${PROFILE:-default}" "$GW_SERVICE" "$GW_DELAY" "$GW_SUP" "$GW_SUPCTL" </dev/null >"$GW_LOG" 2>&1 &
  _tries=0
  while [ ! -e "$GW_READY" ] && [ "$_tries" -lt 50 ]; do sleep 0.1; _tries=$((_tries + 1)); done
  rm -f "$GW_READY"
}

step "Done"
cat <<EOF
  Next:
  • On your computer: open Hermes: Alan's Way → Settings → Agent setup → save this
    machine's SSH address → Test agent path.
  • In Telegram: message your primary bot: check-ins are on once bound, and are
    tuned by talking to the bot ("stop checking in" pauses them).
  • Browser work routes to your ${HOST_OS} computer while it's reachable, else this host.
EOF
[ "$GUEST_OS" != Windows ] || say "  • This PC: keep it awake and signed in; the browser and watcher start at logon. Automatic sign-in (netplwiz) brings them back after a reboot."
if [ "$FAILS" != 0 ]; then
  say "setup: $FAILS check(s) failed: see above."
  [ "$WANT_RESTART" = 0 ] || say "  The gateway restart was skipped because a check failed. Fix it, then restart: hermes${PROFILE:+ -p $PROFILE} gateway restart"
  exit 1
fi
if [ "$WANT_RESTART" = 1 ]; then
  schedule_gateway_restart
  say ""
  say "  Restarting the gateway in ${GW_DELAY}s, detached (log: $GW_LOG). If you are reading this inside a chat on that gateway, the chat pauses for a moment; send your last message now."
fi
exit 0
