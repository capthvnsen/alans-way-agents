#!/bin/sh
# setup-workspace.sh — write (or print) the workspace_browser MCP server block
# for one bot profile in a Hermes config.yaml.
#
#   ./setup-workspace.sh --bot-id 123456789 --bot-name Scout \
#       --mac-ssh me@mymac --router /opt/alans-way/alans-way/scripts/workspace-router.cjs \
#       [--profile alan-local | --config ~/.hermes/config.yaml] [--allow-desktop-actions]
#
#   ./setup-workspace.sh --verify --mac-ssh me@mymac [--router PATH] [--profile NAME] [--config CFG]
#
# Without --config/--profile the block is printed for manual review/paste.
# Re-running without --mac-ssh / --host-os keeps the values the managed block
# already configures; --mac-ssh none removes the configured computer.
# --profile selects a Hermes profile and edits ~/.hermes/profiles/<name>/config.yaml;
# --config edits an explicit file directly. The script replaces a previous managed
# block (markers below) or inserts one under the selected profile's existing
# mcp_servers key; everything else is untouched.
# The block always excludes the ungated workspace_computer_action tool, so
# desktop input only goes through Hermes's approval-gated computer_use.
# --allow-desktop-actions is the manual opt-out: it instead writes the env
# marker that lets the router expose and serve that tool.
# --verify checks the install instead of writing: router script, node, the
# host ssh hop and app API, the local VPS browser host, and the managed block.
set -eu

BOT_ID="" BOT_NAME="" MAC_SSH="" HOST_OS="" ROUTER="" CONFIG="" PROFILE="" VERIFY=0 ALLOW_DESKTOP=0
MAC_SSH_SET=0 HOST_OS_SET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --bot-id) BOT_ID="$2"; shift 2;;
    --bot-name) BOT_NAME="$2"; shift 2;;
    --mac-ssh) MAC_SSH="$2"; MAC_SSH_SET=1; shift 2;;
    --host-os) HOST_OS="$2"; HOST_OS_SET=1; shift 2;;
    --router) ROUTER="$2"; shift 2;;
    --config) CONFIG="$2"; shift 2;;
    --profile) PROFILE="$2"; shift 2;;
    --verify) VERIFY=1; shift;;
    --allow-desktop-actions) ALLOW_DESKTOP=1; shift;;
    -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

if [ -n "$PROFILE" ] && [ -n "$CONFIG" ]; then
  echo "setup-workspace: --profile and --config are mutually exclusive" >&2
  exit 2
fi
case "${HOST_OS:-mac}" in mac|windows|linux) HOST_OS="${HOST_OS:-mac}";; *) echo "setup-workspace: --host-os must be mac, windows or linux" >&2; exit 2;; esac

[ -n "$ROUTER" ] || ROUTER="$(cd "$(dirname "$0")/alans-way/scripts" && pwd)/workspace-router.cjs"
# Git Bash on native Windows: the router path goes into config.yaml for Hermes
# and node, which want C:/ paths, and ssh is the native OpenSSH the router uses.
SSH=ssh HERMES_HOME_DEFAULT="$HOME/.hermes"
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*)
    ROUTER="$(cygpath -m "$ROUTER")"
    HERMES_HOME_DEFAULT="$(cygpath -m "${LOCALAPPDATA:-$HOME/AppData/Local}")/hermes"
    _native="$(cygpath -u "${SYSTEMROOT:-${WINDIR:-C:/Windows}}")/System32/OpenSSH/ssh.exe"
    [ ! -x "$_native" ] || SSH="$_native";;
esac
# setup.sh hands over the Python it chose: Windows has python.exe, and python3 may be a Store stub.
if [ -n "${ALANS_WAY_PYTHON:-}" ]; then python3() { "$ALANS_WAY_PYTHON" "$@"; }; fi
command -v python3 >/dev/null || { echo "setup-workspace: python3 is required" >&2; exit 1; }
if [ -n "$PROFILE" ]; then
  case "$PROFILE" in
    *[!0-9A-Za-z_.-]*)
      echo "setup-workspace: bad --profile" >&2
      exit 2;;
  esac
  CONFIG="${HERMES_HOME:-$HERMES_HOME_DEFAULT}/profiles/$PROFILE/config.yaml"
fi

# The current value of env key $2 inside the managed workspace_browser block in
# config $1, else empty. setup.sh uses the same reader, so a re-run keeps what
# the block already configures.
managed_env_value() {
  [ -f "$1" ] || return 0
  sed -n '/>>> alans-way workspace_browser managed block >>>/,/<<< alans-way workspace_browser managed block <<</p' "$1" \
    | sed -n "s/^[[:space:]]*$2:[[:space:]]*//p" | head -1 \
    | sed -e 's/[[:space:]]*$//' -e 's/[[:space:]][[:space:]]*#.*$//' -e 's/^"\(.*\)"$/\1/'
}

# A re-run without --mac-ssh / --host-os keeps the values the managed block
# already configures; --mac-ssh none removes the computer (issue #62).
if [ "$MAC_SSH_SET" = 1 ]; then
  [ "$MAC_SSH" != none ] || MAC_SSH=""
elif [ -z "$MAC_SSH" ]; then
  MAC_SSH="$(managed_env_value "$CONFIG" HERMES_WORKSPACE_MAC_SSH)"
fi
if [ "$HOST_OS_SET" != 1 ]; then
  HOST_OS="$(managed_env_value "$CONFIG" HERMES_WORKSPACE_HOST_OS)"
fi
HOST_OS="${HOST_OS:-mac}"

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

ok() { echo "  ok   $1"; }
bad() { echo "  FAIL $1"; FAILS=$((FAILS + 1)); }
warn() { echo "  warn $1"; }
skip() { echo "  skip $1"; }

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
    if "$SSH" -T -o BatchMode=yes -o ConnectTimeout=6 -o StrictHostKeyChecking=yes -- "$MAC_SSH" echo ok 2>/dev/null; then
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
      bad "host ssh unreachable: $MAC_SSH (browser falls back to the VPS host when the host is asleep: this is only a failure if the host should be up)"
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
    elif [ -f "$CONFIG" ] && grep -q '^ \+workspace_browser:' "$CONFIG"; then
      ok "workspace_browser entry present in $CONFIG (unmanaged: re-run setup to manage it)"
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
      bad "workspace_browser timeout ${timeout}s is below ${TOOL_TIMEOUT}s: long browser actions get cut off; re-run setup or set timeout: $TOOL_TIMEOUT"
    else
      ok "workspace_browser timeout ${timeout}s"
    fi
    case "$(workspace_block_state "$CONFIG")" in
      opt-in) ok "workspace_computer_action exposed by explicit opt-in (--allow-desktop-actions)";;
      excluded) ok "ungated desktop input excluded from workspace_browser";;
      exposed) warn "workspace_browser does not exclude workspace_computer_action, an ungated desktop-input tool: re-run setup, or pass --allow-desktop-actions to keep it deliberately";;
    esac
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
  # MCP has no approval gate of its own, so the desktop-input tool is excluded
  # by default. The opt-in instead writes the marker env that lets the router
  # serve it; read-only computer tools stay exposed either way.
  DESKTOP_TOOLS_BLOCK=""
  DESKTOP_ALLOW_ENV=""
  if [ "$ALLOW_DESKTOP" = 1 ]; then
    DESKTOP_ALLOW_ENV="$(printf '\n      HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS: "1"')"
  else
    DESKTOP_TOOLS_BLOCK="$(printf '\n    tools:\n      exclude:\n        - workspace_computer_action')"
  fi
  # When setup.sh put the availability watcher's state file somewhere other
  # than the router default (a non-root supervisord program), the router that
  # serves requests must read the same file: it takes HERMES_MAC_STATE_FILE
  # from this env.
  MAC_STATE_ENV=""
  [ -z "${ALANS_WAY_MAC_STATE_FILE:-}" ] \
    || MAC_STATE_ENV="$(printf '\n      HERMES_MAC_STATE_FILE: %s' "$(yaml_quote "$ALANS_WAY_MAC_STATE_FILE")")"
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
    timeout: $TOOL_TIMEOUT$DESKTOP_TOOLS_BLOCK
    env:
      HERMES_WORKSPACE_MAC_SSH: $(yaml_quote "${MAC_SSH:-}")
      HERMES_WORKSPACE_HOST_OS: $(yaml_quote "$HOST_OS")$DESKTOP_ALLOW_ENV$MAC_STATE_ENV
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

MARK_BEGIN="$MARK_BEGIN" MARK_END="$MARK_END" BLOCK="$(block)" python3 - "$CONFIG" <<'PY'
import os, re, shutil, sys, time
path, mark_b, mark_e, block = sys.argv[1], os.environ["MARK_BEGIN"], os.environ["MARK_END"], os.environ["BLOCK"]
original = open(path, encoding="utf-8", newline="").read()
nl = "\r\n" if "\r\n" in original else "\n"
lines = re.findall(r"[^\n]*\n|[^\n]+", original)
text = lambda l: l.rstrip("\r\n")
indent = lambda l: len(l) - len(l.lstrip(" "))

def refuse(why):
    sys.stderr.write(f"setup-workspace: cannot tell how mcp_servers is indented in {path} ({why}); "
                     "nothing was changed. Add the block by hand: run this script without --config to print it.\n")
    sys.exit(3)

ROOT_KEY = re.compile(r"mcp_servers:(.*)$")
EMPTY_VALUES = ("{}", "[]", "null", "~", "Null", "NULL")
head, head_empty, head_comment = None, False, ""
for n, l in enumerate(lines):
    m = ROOT_KEY.match(text(l))
    if m:
        value = re.sub(r"(^|\s)#.*$", "", m.group(1)).strip()
        comment = re.search(r"(^|\s)(#.*)$", m.group(1))
        head, head_empty, head_comment = n, value in EMPTY_VALUES, (" " + comment.group(2)) if comment else ""
        if value and not head_empty:
            refuse("its value is written inline")
        break

# Children of mcp_servers keep the indent the file already uses (2 when there are none).
child = 2
if head is not None and not head_empty:
    for l in lines[head + 1:]:
        t = text(l)
        if not t.strip() or t.lstrip().startswith("#"):
            continue
        if not t.startswith(" "):
            if t.startswith("-"):
                refuse("it holds a list")
            break
        if not re.match(r" +[\w.\"'-]+:(\s|$)", t):
            refuse("the first entry is not a plain key")
        child = indent(t)
        break
shift = child - 2
reindent = lambda l: l if not l.startswith("  ") else (" " * shift + l if shift >= 0 else l[-shift:])
block = nl.join(reindent(l) for l in block.split("\n"))

# Earlier installs left a second router behind: a legacy managed block, or a
# hand-written mcp_servers entry that runs this plugin's router or browser-mcp
# under node. Either duplicates the tools, so each profile keeps exactly one
# workspace_browser.
LEGACY_B = "# >>> alans-way cua_alans_way managed block >>>"
LEGACY_E = "# <<< alans-way cua_alans_way managed block <<<"
OURS = ("workspace-router.cjs", "browser-mcp.cjs")
base = lambda value: re.split(r"[\\/]", value.strip().strip("\"'"))[-1]

def runs_our_script(entry):
    body = "".join(l for l in entry if not l.lstrip().startswith("#"))
    cmd = re.search(r"(?:^|[{,\s])command:\s*(\"[^\"]*\"|'[^']*'|[^\s,}#]+)", body)
    if not cmd or base(cmd.group(1)).lower() not in ("node", "node.exe"):
        return False
    flow = re.search(r"args:\s*\[(.*?)\]", body, re.S)
    if flow:
        items = re.findall(r"\"[^\"]*\"|'[^']*'|[^\s,]+", flow.group(1))
    else:
        items, args_indent = [], None
        for l in entry:
            t = text(l)
            if args_indent is None:
                m = re.match(r"( *)args:\s*$", t)
                args_indent = len(m.group(1)) if m else None
            elif t.strip() and not t.lstrip().startswith("-") and indent(t) <= args_indent:
                break
            elif t.lstrip().startswith("-"):
                items.append(t.lstrip()[1:].strip())
    return any(base(i) in OURS for i in items)

kept, removed, i, in_servers, in_managed = [], [], 0, False, False
while i < len(lines):
    line, t = lines[i], text(lines[i])
    if t == LEGACY_B:
        j = i
        while j < len(lines) and text(lines[j]) != LEGACY_E:
            j += 1
        if j < len(lines):
            removed.append("legacy managed block cua_alans_way")
            i = j + 1
            continue
    if t == mark_b:
        in_managed = True
    elif t == mark_e:
        in_managed = False
    if t and not t.startswith((" ", "#")):
        in_servers = bool(ROOT_KEY.match(t))
    elif in_servers and not in_managed and indent(t) == child and t.strip() and not t.lstrip().startswith("#"):
        name = re.match(r" *([\w.-]+|\"[^\"]+\"|'[^']+'):(\s.*)?$", t)
        if name and name.group(1) != "workspace_browser":
            j = i + 1
            while j < len(lines) and (not text(lines[j]).strip() or indent(text(lines[j])) > child):
                j += 1
            while not text(lines[j - 1]).strip():
                j -= 1
            if runs_our_script(lines[i:j]):
                removed.append("unmanaged mcp_servers entry " + name.group(1).strip("\"'"))
                i = j
                continue
    kept.append(line)
    i += 1
lines = kept
has_managed = any(text(l) == mark_b for l in lines)
out, skipping, inserted, adopting, blanks = [], False, False, False, []
in_servers = False
# Insert under the profile's own top-level mcp_servers key, never a nested or
# commented one. A top-level key has no leading whitespace.
for line in lines:
    stripped = text(line)
    if stripped == mark_b:
        skipping = True
        out.append(block + nl)
        continue
    if skipping:
        if stripped == mark_e:
            skipping = False
        continue
    if stripped and not stripped.startswith((" ", "#")):
        in_servers = bool(ROOT_KEY.match(stripped))
    # A hand-pasted, unmarked entry is replaced in place; a second
    # workspace_browser key would leave Hermes silently using one of them.
    if adopting:
        if not stripped:
            blanks.append(line)
            continue
        if indent(stripped) > child:
            blanks = []
            continue
        adopting = False
        out.extend(blanks)
        blanks = []
    if not has_managed and in_servers and indent(stripped) == child and re.match(r" *workspace_browser:", stripped):
        if not inserted:
            out.append(block + nl)
            inserted = True
        adopting = True
        continue
    if not has_managed and not inserted and ROOT_KEY.match(stripped):
        out.append("mcp_servers:" + head_comment + nl if head_empty else line)
        out.append(block + nl)
        inserted = True
        continue
    out.append(line)
out.extend(blanks)
if not has_managed and not inserted:
    out.append(nl + "mcp_servers:" + nl + block + nl)
result = "".join(out)
for what in removed:
    print("setup-workspace: removed " + what)
if result != original:
    if original:
        backup = path + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
        while os.path.exists(backup):
            backup += "x"
        shutil.copy2(path, backup)
        print("setup-workspace: backup: " + backup)
    open(path, "w", encoding="utf-8", newline="").write(result)
PY

echo "setup-workspace: wrote managed workspace_browser block to $CONFIG"
echo "setup-workspace: restart the gateway to load it."
