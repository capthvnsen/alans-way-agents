#!/bin/sh
# setup-workspace.sh — write (or print) the workspace_browser MCP server block
# for one bot profile in a Hermes config.yaml.
#
#   ./setup-workspace.sh --bot-id 123456789 --bot-name Scout \
#       --mac-ssh me@mymac --router /opt/alans-way/alans-way/scripts/workspace-router.cjs \
#       [--profile alan-local | --config ~/.hermes/config.yaml]
#
#   ./setup-workspace.sh --verify --mac-ssh me@mymac [--router PATH] [--profile NAME] [--config CFG]
#
# Without --config/--profile the block is printed for manual review/paste.
# --profile selects a Hermes profile and edits ~/.hermes/profiles/<name>/config.yaml;
# --config edits an explicit file directly. The script replaces a previous managed
# block (markers below) or inserts one under the selected profile's existing
# mcp_servers key; everything else is untouched.
# --verify checks the install instead of writing: router script, node, the
# host ssh hop and app API, the local VPS browser host, and the managed block.
set -eu

BOT_ID="" BOT_NAME="" MAC_SSH="" HOST_OS="" ROUTER="" CONFIG="" PROFILE="" VERIFY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --bot-id) BOT_ID="$2"; shift 2;;
    --bot-name) BOT_NAME="$2"; shift 2;;
    --mac-ssh) MAC_SSH="$2"; shift 2;;
    --host-os) HOST_OS="$2"; shift 2;;
    --router) ROUTER="$2"; shift 2;;
    --config) CONFIG="$2"; shift 2;;
    --profile) PROFILE="$2"; shift 2;;
    --verify) VERIFY=1; shift;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

if [ -n "$PROFILE" ] && [ -n "$CONFIG" ]; then
  echo "setup-workspace: --profile and --config are mutually exclusive" >&2
  exit 2
fi
case "${HOST_OS:-mac}" in mac|windows|linux) HOST_OS="${HOST_OS:-mac}";; *) echo "setup-workspace: --host-os must be mac, windows or linux" >&2; exit 2;; esac
# --mac-ssh reaches ssh as an argument: user@host or host, plain characters, never a leading '-'.
if [ -n "$MAC_SSH" ]; then
  _user=""; _host="$MAC_SSH"
  case "$MAC_SSH" in *@*) _user="${MAC_SSH%%@*}"; _host="${MAC_SSH#*@}";; esac
  _bad=0
  case "$MAC_SSH" in *@*@*) _bad=1;; esac
  case "$MAC_SSH" in *@*) [ -n "$_user" ] || _bad=1;; esac
  case "$_user" in -*|*[!A-Za-z0-9._-]*) _bad=1;; esac
  case "$_host" in ''|-*|.*|*[!A-Za-z0-9.:-]*) _bad=1;; esac
  [ "$_bad" = 0 ] || { echo "setup-workspace: invalid --mac-ssh '$MAC_SSH' (use user@host or host; no spaces, nothing may start with '-')" >&2; exit 2; }
fi
if [ -n "$PROFILE" ]; then
  case "$PROFILE" in
    *[!0-9A-Za-z_.-]*)
      echo "setup-workspace: bad --profile" >&2
      exit 2;;
  esac
  CONFIG="${HERMES_HOME:-$HOME/.hermes}/profiles/$PROFILE/config.yaml"
fi

[ -n "$ROUTER" ] || ROUTER="$(cd "$(dirname "$0")/alans-way/scripts" && pwd)/workspace-router.cjs"
command -v python3 >/dev/null || { echo "setup-workspace: python3 is required" >&2; exit 1; }

ok() { echo "  ok   $1"; }
bad() { echo "  FAIL $1"; FAILS=$((FAILS + 1)); }
warn() { echo "  warn $1"; }
skip() { echo "  skip $1"; }

# browser-mcp gives a browser action up to 90s; Hermes must wait longer or it
# abandons a batch that is still running and the agent retries on top of it.
TOOL_TIMEOUT=120

if [ "$VERIFY" = 1 ]; then
  FAILS=0
  echo "setup-workspace: verifying workspace browser wiring"
  [ -f "$ROUTER" ] && ok "router script: $ROUTER" || bad "router script missing: $ROUTER"
  if command -v node >/dev/null; then
    node --check "$ROUTER" >/dev/null 2>&1 && ok "router parses under node" || bad "router fails node --check"
  else
    bad "node not on PATH (router is a node script)"
  fi
  if [ -n "$MAC_SSH" ]; then
    if ssh -T -o BatchMode=yes -o ConnectTimeout=6 -o StrictHostKeyChecking=yes -- "$MAC_SSH" echo ok 2>/dev/null; then
      ok "host ssh reachable: $MAC_SSH"
      # Run the router's own probe — the exact code path connections take —
      # so a broken probe fails here at verify time, not mid-session.
      decision=$(HERMES_WORKSPACE_MAC_SSH="$MAC_SSH" HERMES_WORKSPACE_HOST_OS="$HOST_OS" node "$ROUTER" --probe 2>/dev/null || true)
      case "$decision" in
        "mac: "*|"windows: "*|"linux: "*) ok "router probe → $decision";;
        "vps ("*) warn "router probe → $decision (ok only if the host app is asleep/closed right now)";;
        *) bad "router probe returned no decision";;
      esac
    else
      bad "host ssh unreachable: $MAC_SSH (browser falls back to the VPS host when the host is asleep — this is only a failure if the host should be up)"
    fi
  else
    skip "host check (no --mac-ssh given; VPS-only routing)"
  fi
  case "$(uname -s 2>/dev/null)" in
    Darwin) CONN="$HOME/Library/Application Support/hermes-alans-way/browser/connection.json";;
    *) CONN="$HOME/.local/share/hermes-alans-way/browser/connection.json";;
  esac
  if [ -f "$CONN" ]; then
    ok "vps connection file: $CONN"
    port=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("port",9465))' "$CONN" 2>/dev/null || echo 9465)
    code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:${port:-9465}/v1/status" 2>/dev/null || true)
    case "$code" in
      401|403|200) ok "vps browser host answering on :$port (http $code)";;
      *) bad "vps browser host not answering on :$port (got '${code:-no response}')";;
    esac
  else
    skip "vps connection file absent at $CONN (only needed on the VPS host)"
  fi
  if [ -n "$CONFIG" ]; then
    if [ -f "$CONFIG" ] && grep -q '>>> alans-way workspace_browser managed block >>>' "$CONFIG"; then
      ok "managed workspace_browser block present in $CONFIG"
    elif [ -f "$CONFIG" ] && grep -q '^  workspace_browser:' "$CONFIG"; then
      ok "workspace_browser entry present in $CONFIG (unmanaged — re-run setup to manage it)"
    else
      bad "no workspace_browser block in $CONFIG"
    fi
    timeout=$(python3 - "$CONFIG" <<'PY' 2>/dev/null || true
import re, sys
inside = False
for line in open(sys.argv[1]):
    if re.match(r"^  workspace_browser:\s*$", line):
        inside = True
    elif inside and re.match(r"^ {0,2}\S", line):
        break
    elif inside and (m := re.match(r"^    timeout:\s*(\d+)\s*$", line)):
        print(m.group(1))
        break
PY
)
    if [ -z "$timeout" ]; then
      skip "workspace_browser timeout not set (Hermes default applies; ${TOOL_TIMEOUT}s recommended)"
    elif [ "$timeout" -lt "$TOOL_TIMEOUT" ]; then
      bad "workspace_browser timeout ${timeout}s is below ${TOOL_TIMEOUT}s — long browser actions get cut off; re-run setup or set timeout: $TOOL_TIMEOUT"
    else
      ok "workspace_browser timeout ${timeout}s"
    fi
  else
    skip "config check (no --config given)"
  fi
  [ "$FAILS" = 0 ] && { echo "setup-workspace: all checks passed"; exit 0; }
  echo "setup-workspace: $FAILS check(s) failed"; exit 1
fi

[ -n "$BOT_ID" ] || { echo "setup-workspace: --bot-id is required" >&2; exit 2; }
case "$BOT_ID" in *[!0-9A-Za-z_-]*) echo "setup-workspace: bad --bot-id" >&2; exit 2;; esac

MARK_BEGIN="# >>> alans-way workspace_browser managed block >>>"
MARK_END="# <<< alans-way workspace_browser managed block <<<"

# Emit a safe YAML double-quoted scalar. JSON string escapes are valid YAML,
# so any value containing spaces, quotes, colons or backslashes stays parsed.
yaml_quote() {
  python3 -c 'import json, sys; print(json.dumps(sys.argv[1]), end="")' "$1"
}

block() {
  BOT_NAME_BLOCK=""
  if [ -n "$BOT_NAME" ]; then
    BOT_NAME_BLOCK="$(printf '\n      - --bot-name\n      - %s' "$(yaml_quote "$BOT_NAME")")"
  fi
  cat <<EOF
$MARK_BEGIN
  workspace_browser:
    command: "node"
    args:
      - $(yaml_quote "$ROUTER")
      - --bot-id
      - $(yaml_quote "$BOT_ID")$BOT_NAME_BLOCK
    lazy: true
    connect_timeout: 12
    timeout: $TOOL_TIMEOUT
    env:
      HERMES_WORKSPACE_MAC_SSH: $(yaml_quote "${MAC_SSH:-}")
      HERMES_WORKSPACE_HOST_OS: $(yaml_quote "$HOST_OS")
$MARK_END
EOF
}

if [ -z "$CONFIG" ]; then
  echo "# Paste inside your profile's mcp_servers: in ~/.hermes/profiles/<name>/config.yaml"
  block | sed '1d;$d'
  exit 0
fi

if [ ! -f "$CONFIG" ]; then
  mkdir -p "$(dirname "$CONFIG")"
  : > "$CONFIG"
  chmod 600 "$CONFIG"
fi

cp "$CONFIG" "$CONFIG.bak-alans-way"
MARK_BEGIN="$MARK_BEGIN" MARK_END="$MARK_END" BLOCK="$(block)" python3 - "$CONFIG" <<'PY'
import os, sys
path, mark_b, mark_e, block = sys.argv[1], os.environ["MARK_BEGIN"], os.environ["MARK_END"], os.environ["BLOCK"]
lines = open(path).read().splitlines(keepends=True)
has_managed = any(l.rstrip("\n") == mark_b for l in lines)
out, skipping, inserted = [], False, False
in_servers, adopting = False, False
# Insert under the profile's own top-level mcp_servers key, never a nested or
# commented one. A top-level key has no leading whitespace and no trailing text.
for line in lines:
    if line.rstrip("\n") == mark_b:
        skipping = True
        out.append(block + "\n")
        continue
    if skipping:
        if line.rstrip("\n") == mark_e:
            skipping = False
        continue
    stripped = line.rstrip("\n")
    if stripped and not stripped.startswith((" ", "#")):
        in_servers = stripped == "mcp_servers:"
    # A hand-pasted, unmarked entry is replaced in place; a second
    # workspace_browser key would leave Hermes silently using one of them.
    if adopting:
        if not stripped or stripped.startswith("   "):
            continue
        adopting = False
    if not has_managed and in_servers and stripped == "  workspace_browser:":
        if not inserted:
            out.append(block + "\n")
            inserted = True
        adopting = True
        continue
    out.append(line)
    if not has_managed and not inserted:
        stripped = line.rstrip("\n")
        if stripped == "mcp_servers:":
            out.append(block + "\n")
            inserted = True
if not has_managed and not inserted:
    out.append("\nmcp_servers:\n" + block + "\n")
open(path, "w").writelines(out)
PY

echo "setup-workspace: wrote managed workspace_browser block to $CONFIG (backup: $CONFIG.bak-alans-way)"
echo "setup-workspace: restart the gateway to load it."
