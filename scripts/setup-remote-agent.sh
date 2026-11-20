#!/bin/sh
# setup-remote-agent.sh --bot-id ID [--bot-name NAME] [--user USER] [--remove] [--print]
# Install a dedicated SSH key restricted to the workspace router. Hermes config is read only.
# --print previews without changing SSH files; --probe also checks initialize + tools/list locally.
# Optional fallback settings: --mac-ssh USER@MAC --host-os mac|windows|linux --state-file PATH.
# --config PATH selects config.yaml; --router PATH overrides the installed plugin router.
# --user selects the SSH login shown in client JSON. Replace HOST and copy the private key to the client.
# The key is accepted only from Tailscale addresses unless --any-address is given. A re-run with neither flag keeps
# whatever source restriction (or lack of one) this bot's existing line has; --tailnet-only is the default for a new key.
# --host-key PATH is this machine's sshd host public key (default /etc/ssh/ssh_host_ed25519_key.pub); when readable, the
# printed client settings pin it (StrictHostKeyChecking=yes) and print the known_hosts line to add on the client.
set -eu

# setup.sh uses the same interpreter override on hosts without a working python3.
if [ -n "${ALANS_WAY_PYTHON:-}" ]; then python3() { "$ALANS_WAY_PYTHON" "$@"; }; fi
command -v python3 >/dev/null || { echo "setup-remote-agent: python3 is required" >&2; exit 1; }
ROUTER="${HERMES_HOME:-$HOME/.hermes}/plugins/alans-way/scripts/workspace-router.cjs"
python3 - "$0" "$ROUTER" "$@" <<'PY'
import argparse
from contextlib import contextmanager
import fcntl
import getpass
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

script, router = sys.argv[1:3]
parser = argparse.ArgumentParser(description="Set up a remote stdio MCP client over restricted SSH.")
parser.add_argument("--bot-id", required=True)
parser.add_argument("--bot-name")
parser.add_argument("--user", default=getpass.getuser(), help="SSH login in the printed client JSON")
parser.add_argument("--remove", action="store_true", help="remove only this bot's authorized_keys entry")
parser.add_argument("--print", dest="preview", action="store_true", help="preview without writing SSH files")
parser.add_argument("--probe", action="store_true", help="check the forced command locally")
parser.add_argument("--config", default=str(Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "config.yaml"))
parser.add_argument("--router", default=router)
parser.add_argument("--mac-ssh", default="")
parser.add_argument("--host-os", choices=("mac", "windows", "linux"), default="mac")
parser.add_argument("--state-file", default="")
parser.add_argument("--tailnet-only", action="store_true", help="accept this key only from Tailscale addresses (the default for a new key)")
parser.add_argument("--any-address", action="store_true", help="accept this key from any address")
parser.add_argument("--host-key", default="/etc/ssh/ssh_host_ed25519_key.pub", help="this machine's sshd host public key, pinned in the client settings")
args = parser.parse_args(sys.argv[3:])
if args.tailnet_only and args.any_address:
    parser.error("--tailnet-only and --any-address conflict")
if args.bot_id.startswith("-") or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", args.bot_id):
    parser.error("--bot-id must match [A-Za-z0-9._-]{1,64} and must not begin with '-'")
if args.bot_name is None:
    args.bot_name = args.bot_id
if args.bot_name.startswith("-") or any(c in args.bot_name for c in "\"'\r\n"):
    parser.error("--bot-name must not begin with '-' or contain quotes or newlines")
if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]*", args.user):
    parser.error("invalid --user")

ssh = Path.home() / ".ssh"
authorized = ssh / "authorized_keys"
key = ssh / f"alans-way-remote-agent-{args.bot_id}"
marker = f"alans-way-remote-agent:{args.bot_id}"
# Same ranges as setup.sh's TAILNET_FROM.
TAILNET = "100.64.0.0/10,fd7a:115c:a1e0::/48"


@contextmanager
def ssh_lock():
    ssh.mkdir(mode=0o700, exist_ok=True)
    ssh.chmod(0o700)
    # Lock a stable file: authorized_keys itself is atomically replaced below.
    with (ssh / ".alans-way-remote-agent.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def current_source():
    """This bot's existing from= value: None with no line, "" with a line that has none."""
    if not authorized.exists():
        return None
    for row in authorized.read_bytes().decode("utf-8", "surrogateescape").splitlines():
        if row.split()[-1:] == [marker]:
            found = re.match(r'(?:[\w-]+(?:="(?:[^"\\]|\\.)*")?,)*?from="((?:[^"\\]|\\.)*)"', row)
            return found[1] if found else ""
    return None


def update_keys(line=None):
    if authorized.is_symlink():
        parser.error("refusing to replace a symlinked authorized_keys")
    previous = authorized.read_bytes().decode("utf-8", "surrogateescape") if authorized.exists() else ""
    kept = "".join(row for row in previous.splitlines(keepends=True)
                   if row.split()[-1:] != [marker])
    if line is not None:
        kept = kept + ("\n" if kept and not kept.endswith("\n") else "") + line + "\n"
    if kept == previous:
        return
    if authorized.exists():
        shutil.copy2(authorized, ssh / f"authorized_keys.bak-{time.time_ns()}")
    fd, temporary = tempfile.mkstemp(dir=ssh, prefix=".authorized_keys-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as out:
            out.write(kept)
        os.replace(temporary, authorized)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if args.remove:
    if not args.preview:
        with ssh_lock():
            update_keys()
    print(f"{'Would remove' if args.preview else 'Removed'} {marker} (private key retained at {key})")
    sys.exit(0)

env = {"HERMES_WORKSPACE_MAC_SSH": args.mac_ssh, "HERMES_WORKSPACE_HOST_OS": args.host_os,
       "HERMES_MAC_STATE_FILE": args.state_file}
config = Path(args.config)
if config.exists():
    # shortcut: read setup-workspace.sh's indented scalar env; use YAML parsing if flow maps or aliases are needed.
    stack = []
    for line in config.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^( *)([\w.\"'-]+):\s*(.*?)\s*$", line)
        if not match:
            continue
        depth, name, value = len(match[1]), match[2].strip("\"'"), match[3]
        while stack and stack[-1][0] >= depth:
            stack.pop()
        stack.append((depth, name))
        if [k for _, k in stack] == ["mcp_servers", "workspace_browser", "env"] and value and not value.startswith("#"):
            parser.error("workspace_browser.env must use indented entries, as setup-workspace.sh writes")
        if [k for _, k in stack] != ["mcp_servers", "workspace_browser", "env", name] or name not in env:
            continue
        if value.startswith('"'):
            value, _ = json.JSONDecoder().raw_decode(value)
        elif value.startswith("'"):
            match = re.fullmatch(r"'((?:[^']|'')*)'\s*(?:#.*)?", value)
            if not match:
                parser.error(f"invalid quoted config value for {name}")
            value = match[1].replace("''", "'")
        else:
            if value.startswith(("|", ">", "*", "&", "{", "[")):
                parser.error(f"{name} must be a scalar string")
            value = re.split(r"\s+#", value, maxsplit=1)[0]
        env[name] = value
if env["HERMES_WORKSPACE_HOST_OS"] not in ("mac", "windows", "linux"):
    parser.error("HERMES_WORKSPACE_HOST_OS must be mac, windows or linux")
env["HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS"] = "1"
if any(c in value for value in [*env.values(), args.router] for c in "\r\n\0"):
    parser.error("router path and env values must not contain newlines or NUL")
if not Path(args.router).is_file():
    parser.error(f"router not found: {args.router}")
command = " ".join(f"{name}={shlex.quote(value)}" for name, value in env.items())
# SSH forced commands get sshd's short PATH, not this shell's, so pin the node the probe runs.
command += " exec " + shlex.join([shutil.which("node") or "node", args.router, "--bot-id", args.bot_id, "--bot-name", args.bot_name])
# A re-run keeps the earlier choice: it never turns a restriction off, or one on, by being run again.
previous = current_source()
if args.any_address:
    source = ""
elif args.tailnet_only or previous is None:
    source = TAILNET
else:
    source = previous
if not args.preview:
    with ssh_lock():
        if not key.exists():
            if key.with_suffix(key.suffix + ".pub").exists():
                parser.error(f"private key missing for {key}; move its orphaned .pub file before regenerating")
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", marker, "-f", str(key)], check=True)
        public = subprocess.check_output(["ssh-keygen", "-y", "-P", "", "-f", str(key)], text=True).split()
        if public[0] != "ssh-ed25519":
            parser.error(f"{key} must be an ed25519 key")
        public = " ".join(public[:2])
        escaped = command.replace("\\", "\\\\").replace('"', '\\"')
        restriction = f'from="{source}",' if source else ""
        update_keys(f'{restriction}restrict,command="{escaped}" {public} {marker}')
host_key = None
try:
    host_key = " ".join(Path(args.host_key).read_text().split()[:2])
    if not re.fullmatch(r"(?:ssh|ecdsa)-[\w@.-]+ [A-Za-z0-9+/=]+", host_key):
        host_key = None
except OSError:
    pass
print(json.dumps({"command": "ssh", "args": ["-T", "-i", str(key), "-o",
      "StrictHostKeyChecking=" + ("yes" if host_key else "accept-new"),
      "-o", "ServerAliveInterval=30", f"{args.user}@HOST"]}, indent=2))
print(f"\nForced command:\n{command}")
if source == TAILNET:
    print("\nKey accepted from: Tailscale addresses only (--any-address lifts this)")
elif source:
    print(f"\nKey accepted from: {source} (kept from this bot's existing line)")
else:
    print("\nKey accepted from: any address (--tailnet-only limits it)")
if host_key:
    fingerprint = subprocess.run(["ssh-keygen", "-l", "-f", args.host_key], text=True, capture_output=True).stdout.split()
    print("\nHost key is pinned. On the client, add this line to known_hosts with HOST replaced by the address it connects to:\n"
          f"HOST {host_key}\nFingerprint: {fingerprint[1] if len(fingerprint) > 1 else 'unknown'}")
else:
    print(f"\nHost key not pinned: {args.host_key} is not readable here, so the client trusts the first host key it sees "
          "(StrictHostKeyChecking=accept-new). Pass --host-key PATH to pin it.")
check = ["sh", str(Path(script).resolve()), *sys.argv[3:]]
check = [arg for arg in check if arg not in ("--probe", "--print")]
print("\nLocal self-check (initialize + tools/list):\n" + shlex.join([*check, "--print", "--probe"]))
if args.probe:
    proc = subprocess.Popen(["sh", "-c", command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            pending = b""
            for rid, method, params in ((1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                         "clientInfo": {"name": "remote-agent-check", "version": "1"}}),
                                        (2, "tools/list", {})):
                proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n")
                proc.stdin.flush()
                deadline = time.monotonic() + 30
                while True:
                    while b"\n" not in pending:
                        if not selector.select(max(0, deadline - time.monotonic())):
                            raise RuntimeError(f"{method} timed out")
                        chunk = os.read(proc.stdout.fileno(), 65536)
                        if not chunk:
                            raise RuntimeError(f"router exited during {method}")
                        pending += chunk
                    line, pending = pending.split(b"\n", 1)
                    reply = json.loads(line)
                    if reply.get("id") == rid:
                        if "error" in reply or "result" not in reply:
                            raise RuntimeError(f"{method} failed: {reply}")
                        break
                if rid == 1:
                    proc.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
                else:
                    print("Tools:", ", ".join(tool["name"] for tool in reply["result"]["tools"]))
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=3)
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
PY
