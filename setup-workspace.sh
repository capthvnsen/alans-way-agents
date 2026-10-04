#!/bin/sh
# setup-workspace.sh — write (or print) the workspace_browser MCP server block
# for one bot profile in a Hermes config.yaml.
#
#   ./setup-workspace.sh --bot-id 123456789 --bot-name Scout \
#       --mac-ssh me@mymac --router /opt/alans-way/proactive-primary/scripts/workspace-router.cjs \
#       [--config ~/.hermes/config.yaml]
#
# Without --config the block is printed for manual review/paste. With --config
# the script replaces a previous managed block (markers below) or inserts one
# under the profile's existing mcp_servers key; everything else is untouched.
set -eu

BOT_ID="" BOT_NAME="" MAC_SSH="" ROUTER="" CONFIG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --bot-id) BOT_ID="$2"; shift 2;;
    --bot-name) BOT_NAME="$2"; shift 2;;
    --mac-ssh) MAC_SSH="$2"; shift 2;;
    --router) ROUTER="$2"; shift 2;;
    --config) CONFIG="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

[ -n "$BOT_ID" ] || { echo "setup-workspace: --bot-id is required" >&2; exit 2; }
case "$BOT_ID" in *[!0-9A-Za-z_-]*) echo "setup-workspace: bad --bot-id" >&2; exit 2;; esac
[ -n "$ROUTER" ] || ROUTER="$(cd "$(dirname "$0")/proactive-primary/scripts" && pwd)/workspace-router.cjs"

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
