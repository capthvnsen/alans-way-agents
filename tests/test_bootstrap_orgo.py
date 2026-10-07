"""bootstrap-orgo.sh: JSON state file, step runner, and Orgo install steps."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bootstrap-orgo.sh"
BASH = shutil.which("bash") or "/bin/bash"


def run(*args, env=None, check=True):
    result = subprocess.run(
        [BASH, str(SCRIPT)] + list(args), capture_output=True, text=True, env=env)
    if check and result.returncode != 0:
        raise AssertionError(f"exit {result.returncode}: {result.stderr}\n{result.stdout}")
    return result


def stub(bin_dir: Path, name: str, body: str):
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def fixture(directory: Path):
    """An Orgo-like filesystem in a temp dir plus the env to point the script at it."""
    home = directory / "home"
    home.mkdir()
    bin_dest = directory / "sbin"
    bin_dest.mkdir()
    svconf = directory / "svconf"
    svconf.mkdir()
    stub_bin = directory / "stubbin"
    stub_bin.mkdir()
    log = directory / "calls.log"
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "HERMES_HOME": str(home / ".hermes"),
        "ALAN_STATE_DIR": str(directory / "state"),
        "ALAN_BIN_DIR": str(bin_dest),
        "SUPERVISOR_CONF_DIR": str(svconf),
        # System dirs only: the real hermes/curl/tailscale on this machine
        # must not leak into the script's view of the world.
        "PATH": os.pathsep.join([str(stub_bin), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]),
        "STUB_LOG": str(log),
    })
    stub(stub_bin, "supervisorctl", 'echo "supervisorctl $*" >> "$STUB_LOG"\n')
    stub(stub_bin, "tailscaled", 'echo "tailscaled $*" >> "$STUB_LOG"\n')
    return env, log, stub_bin


def curl_stub(stub_bin: Path, fail_on=""):
    """A curl that plays both installers: it prints a no-op script for the
    `| bash` pipe and lands the side effects a real install would."""
    fail_case = f'*{fail_on}*) echo "stub: network dropped mid-install" >&2; exit 1;;' if fail_on else ""
    stub(stub_bin, "curl", f'''
echo "curl $*" >> "$STUB_LOG"
case "$*" in
  {fail_case}
esac
case "$*" in
  *hermes-agent.nousresearch.com/install.sh*)
    cat > "{stub_bin}/hermes" <<'EOF'
#!/bin/sh
echo "hermes $*" >> "$STUB_LOG"
EOF
    chmod +x "{stub_bin}/hermes"
    printf ':\\n'
    ;;
  *setup.sh*)
    mkdir -p "$HERMES_HOME/plugins/alans-way"
    printf ':\\n'
    ;;
  *) printf ':\\n';;
esac
''')


def tailscale_stub(stub_bin: Path, url="", backend="NeedsLogin", url_stream="stderr", up_extra=""):
    stub(stub_bin, "tailscale", f'''
case "$1" in
  status)
    printf '{{"BackendState":"{backend}"}}\\n'
    ;;
  up)
    echo "tailscale $*" >> "$STUB_LOG"
    {up_extra}
    if [ -n "{url}" ]; then
      if [ "{url_stream}" = stderr ]; then
        echo "To authenticate, visit:" >&2
        echo "{url}" >&2
      else
        echo "{url}"
      fi
    fi
    ;;
esac
exit 0
''')


class StateFileTests(unittest.TestCase):
    def test_state_file_is_valid_json_after_a_full_run(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/abc123")
            result = run(env=env)
            self.assertEqual(result.returncode, 0)
            doc = json.loads((directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "ready")
            self.assertEqual(doc["step"], "waiting_for_pairing")
            self.assertIsNone(doc["error"])
            self.assertIn("updated_at", doc)

    def test_err_trap_marks_the_run_failed_with_the_last_log_line(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            curl_stub(stub_bin, fail_on="install.sh")
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/abc123")
            result = run(env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            doc = json.loads((directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "failed")
            self.assertEqual(doc["step"], "hermes")
            self.assertIn("network dropped", doc["error"])

    def test_dry_run_prints_the_steps_in_order_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            result = run("--dry-run", env=env)
            out = result.stdout
            order = [out.index("step: hermes"), out.index("step: alans-way"),
                     out.index("step: tailscale"), out.index("step: ready")]
            self.assertEqual(order, sorted(order))
            self.assertIn("would run", out)
            self.assertFalse((directory / "state" / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
