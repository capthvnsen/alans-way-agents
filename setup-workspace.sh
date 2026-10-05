#!/bin/sh
# setup-workspace.sh — write (or print) the workspace_browser MCP server block
# for one bot profile in a Hermes config.yaml.
#
#   ./setup-workspace.sh --bot-id 123456789 --bot-name Scout \
#       --mac-ssh me@mymac --router /opt/alans-way/alans-way/scripts/workspace-router.cjs \
#       [--config ~/.hermes/config.yaml]
#
#   ./setup-workspace.sh --verify --mac-ssh me@mymac [--router PATH] [--config CFG]
#
# Without --config the block is printed for manual review/paste. With --config
# the script replaces a previous managed block (markers below) or inserts one
# under the profile's existing mcp_servers key; everything else is untouched.
# --verify checks the install instead of writing: router script, node, the
# Mac ssh hop and app API, the local VPS browser host, and the managed block.
set -eu

BOT_ID="" BOT_NAME="" MAC_SSH="" ROUTER="" CONFIG="" VERIFY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --bot-id) BOT_ID="$2"; shift 2;;
    --bot-name) BOT_NAME="$2"; shift 2;;
    --mac-ssh) MAC_SSH="$2"; shift 2;;
    --router) ROUTER="$2"; shift 2;;
    --config) CONFIG="$2"; shift 2;;
    --verify) VERIFY=1; shift;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

[ -n "$ROUTER" ] || ROUTER="$(cd "$(dirname "$0")/alans-way/scripts" && pwd)/workspace-router.cjs"

ok() { echo "  ok   $1"; }
bad() { echo "  FAIL $1"; FAILS=$((FAILS + 1)); }
skip() { echo "  skip $1"; }

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
    if ssh -T -o BatchMode=yes -o ConnectTimeout=6 -o StrictHostKeyChecking=yes "$MAC_SSH" true 2>/dev/null; then
      ok "mac ssh reachable: $MAC_SSH"
      code=$(ssh -T -o BatchMode=yes -o ConnectTimeout=6 "$MAC_SSH" \
        'curl -s -o /dev/null -m 5 -w "%{http_code}" http://127.0.0.1:9464/v1/status' 2>/dev/null || true)
      case "$code" in
        401|403|200) ok "mac workspace API answering on :9464 (http $code)";;
        *) bad "mac workspace API not answering on :9464 (got '${code:-no response}')";;
      esac
    else
      bad "mac ssh unreachable: $MAC_SSH (browser falls back to the VPS host when the Mac is asleep — this is only a failure if the Mac should be up)"
    fi
  else
    skip "mac check (no --mac-ssh given; VPS-only routing)"
  fi
  CONN="$HOME/.local/share/hermes-alans-way/browser/connection.json"
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
    else
      bad "no managed workspace_browser block in $CONFIG"
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

block() {
  cat <<EOF
$MARK_BEGIN
  workspace_browser:
    command: node
    args:
      - $ROUTER
      - --bot-id
      - "$BOT_ID"$( [ -n "$BOT_NAME" ] && printf '\n      - --bot-name\n      - "%s"' "$BOT_NAME" )
    env:
      HERMES_WORKSPACE_MAC_SSH: "${MAC_SSH:-}"
$MARK_END
EOF
}

if [ -z "$CONFIG" ]; then
  echo "# Paste inside your profile's mcp_servers: in ~/.hermes/config.yaml"
  block | sed '1d;$d'
  exit 0
fi

[ -f "$CONFIG" ] || { echo "setup-workspace: no such config: $CONFIG" >&2; exit 1; }
command -v python3 >/dev/null || { echo "setup-workspace: python3 is required" >&2; exit 1; }

cp "$CONFIG" "$CONFIG.bak-alans-way"
MARK_BEGIN="$MARK_BEGIN" MARK_END="$MARK_END" BLOCK="$(block)" python3 - "$CONFIG" <<'PY'
import os, sys
path, mark_b, mark_e, block = sys.argv[1], os.environ["MARK_BEGIN"], os.environ["MARK_END"], os.environ["BLOCK"]
lines = open(path).read().splitlines(keepends=True)
has_managed = any(l.rstrip("\n") == mark_b for l in lines)
out, skipping, inserted = [], False, False
for line in lines:
    if line.rstrip("\n") == mark_b:
        skipping = True
        out.append(block + "\n")
        continue
    if skipping:
        if line.rstrip("\n") == mark_e:
            skipping = False
        continue
    out.append(line)
    if not has_managed and not inserted and line.rstrip("\n") == "mcp_servers:":
        out.append(block + "\n")
        inserted = True
if not has_managed and not inserted:
    out.append("\nmcp_servers:\n" + block + "\n")
open(path, "w").writelines(out)
PY

echo "setup-workspace: wrote managed workspace_browser block to $CONFIG (backup: $CONFIG.bak-alans-way)"
echo "setup-workspace: restart the gateway to load it."
