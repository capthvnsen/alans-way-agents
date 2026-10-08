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


def run(*args, env=None, check=True, input_text=None):
    result = subprocess.run(
        [BASH, str(SCRIPT)] + list(args), capture_output=True, text=True,
        env=env, input=input_text)
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
        "TAILSCALE_STATE_DIR": str(directory / "tailscale-state"),
        "TAILSCALE_SOCKET": str(directory / "tailscale-run" / "tailscaled.sock"),
        # Orgo: no systemd running, no /dev/net/tun, whatever the CI host has.
        "ALAN_SYSTEMD_RUN_DIR": str(directory / "no-systemd"),
        "ALAN_TUN_DEVICE": str(directory / "no-tun"),
        "SSHD_BIN": str(directory / "ssh" / "sshd"),
        # System dirs only: the real hermes/curl/tailscale on this machine
        # must not leak into the script's view of the world.
        "PATH": os.pathsep.join([str(stub_bin), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]),
        "STUB_LOG": str(log),
    })
    stub(stub_bin, "supervisorctl", '''echo "supervisorctl $*" >> "$STUB_LOG"
# Status reads must see a RUNNING gateway — the relay step only restarts a
# gateway that supervisord reports as up.
case "$1" in status) echo "hermes-gateway RUNNING pid 1, uptime 0:01:00";; esac
''')
    stub(stub_bin, "tailscaled", 'echo "tailscaled $*" >> "$STUB_LOG"\n')
    # Nothing on :22 by default — 8022 is a decoy for sloppy `22$` matching.
    stub(stub_bin, "ss",
         'printf "LISTEN 0 128 *:8022 *:*\\n"\n')
    # Installing openssh-server lands the sshd binary.
    stub(stub_bin, "apt-get", '''
echo "apt-get $*" >> "$STUB_LOG"
mkdir -p "$(dirname "$SSHD_BIN")"
printf '#!/bin/sh\\n' > "$SSHD_BIN"
chmod 755 "$SSHD_BIN"
''')
    return env, log, stub_bin


def curl_stub(stub_bin: Path, fail_on=""):
    """A curl that plays both installers: it prints a no-op script for the
    `| bash` pipe and lands the side effects a real install would."""
    fail_case = f'*{fail_on}*) echo "stub: network dropped mid-install" >&2; exit 1;;' if fail_on else ""
    stub(stub_bin, "curl", f'''
echo "curl $*" >> "$STUB_LOG"
# Bodies posted via --data @- are captured so tests can check them while
# argv (what ps would show) stays secret-free.
case "$*" in
  *" -d @-"*|*"--data @-"*) cat > "$STUB_LOG.body";;
esac
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
    # The piped script records the flags bash -s hands it.
    printf 'echo "setup.sh: $*" >> "$STUB_LOG"\\n'
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


class InstallStepTests(unittest.TestCase):
    def test_login_url_on_stderr_is_captured_and_posted_to_the_callback(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            curl_stub(stub_bin)
            tailscale_stub(
                stub_bin, url="https://login.tailscale.com/a/abc123", url_stream="stderr")
            result = run(
                "--callback", "https://example.test/api/computer/tailscale-url",
                "--secret", "s3cret", "--id", "c-42",
                env=env,
            )
            self.assertEqual(result.returncode, 0)
            calls = log.read_text(encoding="utf-8")
            self.assertIn("https://example.test/api/computer/tailscale-url", calls)
            self.assertIn("tailscale up --hostname alan-c-42", calls)
            # The secret rides on stdin, never argv — so neither the calls
            # log nor bootstrap.log may contain it.
            self.assertNotIn("s3cret", calls)
            body = Path(str(log) + ".body").read_text(encoding="utf-8")
            self.assertIn("s3cret", body)
            self.assertIn("c-42", body)
            self.assertIn("https://login.tailscale.com/a/abc123", body)
            bootlog = (directory / "state" / "bootstrap.log").read_text(encoding="utf-8")
            self.assertNotIn("s3cret", bootlog)

    def test_login_url_printed_after_a_delay_on_stdout(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            curl_stub(stub_bin)
            tailscale_stub(
                stub_bin, url="https://login.tailscale.com/a/zz99",
                url_stream="stdout", up_extra="sleep 2")
            result = run(env=env)
            self.assertEqual(result.returncode, 0)
            self.assertIn("https://login.tailscale.com/a/zz99", result.stdout)

    def test_no_login_url_within_the_timeout_marks_the_run_failed(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            env["ALAN_TAILSCALE_URL_TIMEOUT"] = "2"
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="", up_extra="sleep 30")
            result = run(env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            doc = json.loads((directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "failed")
            self.assertEqual(doc["step"], "tailscale")
            self.assertIn("login URL", doc["error"])

    def test_tailscale_up_exiting_without_a_url_fails_fast(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            env["ALAN_TAILSCALE_URL_TIMEOUT"] = "60"
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="")
            result = run(env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            doc = json.loads((directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "failed")
            self.assertEqual(doc["step"], "tailscale")

    def test_rerun_does_not_reinstall_or_duplicate_supervisord_entries(self):
        """A re-run after a tailscale-step failure resumes: hermes and
        alans-way are not reinstalled and no conf file is written twice."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            env["ALAN_TAILSCALE_URL_TIMEOUT"] = "2"
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="", up_extra="sleep 30")
            first = run(env=env, check=False)
            self.assertNotEqual(first.returncode, 0)
            del env["ALAN_TAILSCALE_URL_TIMEOUT"]
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/re2")
            second = run(env=env)
            self.assertEqual(second.returncode, 0)
            calls = log.read_text(encoding="utf-8")
            self.assertEqual(calls.count("hermes-agent.nousresearch.com/install.sh"), 1)
            setup_calls = [l for l in calls.splitlines()
                           if l.startswith("curl ") and "setup.sh" in l]
            self.assertEqual(len(setup_calls), 1)
            confs = list((directory / "svconf").glob("*.conf"))
            programs = "".join(c.read_text(encoding="utf-8") for c in confs)
            self.assertEqual(programs.count("[program:hermes-gateway]"), 1)
            self.assertEqual(programs.count("[program:tailscaled]"), 1)
            self.assertEqual(programs.count("[program:alans-way-browser]"), 1)
            self.assertIn("--skip-services", calls)
            doc = json.loads((directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "ready")

    def test_orgos_own_gateway_program_is_reused_not_duplicated(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            bin_dest = directory / "sbin"
            (directory / "svconf" / "orgo.conf").write_text(
                "; orgo-generated — do not edit\n"
                "[program:hermes-gateway]\n"
                f"command={bin_dest}/orgo-hermes-gateway\n",
                encoding="utf-8",
            )
            (bin_dest / "orgo-hermes-gateway").write_text("#!/bin/sh\n", encoding="utf-8")
            (bin_dest / "orgo-hermes-gateway").chmod(0o755)
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/x1")
            result = run(env=env)
            self.assertEqual(result.returncode, 0)
            self.assertFalse((directory / "svconf" / "hermes-gateway.conf").exists())
            self.assertFalse((bin_dest / "alan-hermes-gateway").exists())
            programs = "".join(
                c.read_text(encoding="utf-8")
                for c in (directory / "svconf").glob("*.conf"))
            self.assertEqual(programs.count("[program:hermes-gateway]"), 1)

    def test_the_generated_gateway_conf_waits_for_the_drain(self):
        """Issue #65: with no stopwaitsecs supervisord escalates SIGTERM to
        SIGKILL after 10s, and a kill mid-checkpoint corrupts state.db, so the
        generated program must give Hermes' drain its full bound."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/x9")
            result = run(env=env)
            self.assertEqual(result.returncode, 0)
            conf = (directory / "svconf" / "hermes-gateway.conf").read_text(
                encoding="utf-8")
            self.assertIn("stopwaitsecs=180", conf)

    def test_tailscaled_uses_userspace_networking_without_dev_net_tun(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/x2")
            run(env=env)
            conf = (directory / "svconf" / "tailscaled.conf").read_text(encoding="utf-8")
            self.assertIn("--tun=userspace-networking", conf)
            self.assertIn("--state=", conf)
            # Userspace networking can only reach tailnet peers through the
            # SOCKS5 server, and the CLI needs a fixed socket path.
            self.assertIn("--socks5-server=localhost:1055", conf)
            self.assertIn(f"--socket={env['TAILSCALE_SOCKET']}", conf)

    def test_sshd_is_installed_and_supervised_when_absent(self):
        """Inbound tailnet ssh lands on localhost:22, so sshd must run —
        the Orgo template supervises it; we add a program when none exists."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            self.assertFalse(Path(env["SSHD_BIN"]).exists())
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/s1")
            run(env=env)
            calls = log.read_text(encoding="utf-8")
            self.assertIn("apt-get", calls)  # openssh-server install
            self.assertTrue(Path(env["SSHD_BIN"]).exists())
            conf = (directory / "svconf" / "sshd.conf").read_text(encoding="utf-8")
            self.assertIn("[program:sshd]", conf)

    def test_an_existing_sshd_program_is_reused(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            (directory / "svconf" / "sshd.conf").write_text(
                "; orgo template\n[program:sshd]\ncommand=/usr/sbin/sshd -D\n",
                encoding="utf-8")
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/s2")
            run(env=env)
            confs = [c.read_text(encoding="utf-8")
                     for c in (directory / "svconf").glob("*.conf")]
            self.assertEqual(sum("program:sshd" in c for c in confs), 1)
            self.assertNotIn("apt-get", log.read_text(encoding="utf-8"))

    def test_a_command_mentioning_sshd_is_not_a_running_sshd(self):
        """'sshd-healthcheck' satisfies '^command=.*sshd' but is no sshd —
        only a command whose binary basename is sshd (and exists) counts,
        or inbound tailnet ssh stays dead silently."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            (directory / "svconf" / "monit.conf").write_text(
                "[program:monit]\ncommand=/usr/bin/sshd-healthcheck\n",
                encoding="utf-8")
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/s8")
            run(env=env)
            calls = log.read_text(encoding="utf-8")
            self.assertIn("apt-get", calls)
            conf = (directory / "svconf" / "sshd.conf").read_text(encoding="utf-8")
            self.assertIn("[program:sshd]", conf)

    def test_a_port_22_listener_skips_the_supervised_sshd(self):
        """A non-supervised sshd already bound to :22 (systemd on a DIY
        host) works — adding our own program would just crash-loop on
        bind."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            stub(stub_bin, "ss",
                 'printf "LISTEN 0 128 *:22 *:*\\n"\n')
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/s9")
            result = run(env=env)
            self.assertIn("port 22", result.stdout)
            self.assertFalse((directory / "svconf" / "sshd.conf").exists())
            self.assertNotIn("apt-get", log.read_text(encoding="utf-8"))

    def test_ssh_config_gets_the_tailnet_proxycommand_block_once(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/s3")
            run(env=env)
            conf = (directory / "home" / ".ssh" / "config").read_text(encoding="utf-8")
            self.assertIn("Host 100.*", conf)
            self.assertIn("ProxyCommand tailscale nc %h %p", conf)
            # A second run does not duplicate the managed block.
            run(env=env)
            conf = (directory / "home" / ".ssh" / "config").read_text(encoding="utf-8")
            self.assertEqual(conf.count("Host 100.*"), 1)

    def test_hostname_is_alan_id_lowercased_and_sanitized(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/s4")
            run("--id", "C_42.X", env=env)
            self.assertIn("tailscale up --hostname alan-c42x",
                          log.read_text(encoding="utf-8"))

    def test_tailscale_up_log_is_removed_after_the_url_is_captured(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/s5")
            run(env=env)
            self.assertFalse(list((directory / "state").glob(".tailscale-up.*")))

    def test_conf_backup_file_does_not_count_as_a_defined_program(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            (directory / "svconf" / "hermes-gateway.conf.bak").write_text(
                "[program:hermes-gateway]\ncommand=/gone\n", encoding="utf-8")
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/s6")
            run(env=env)
            self.assertTrue((directory / "svconf" / "hermes-gateway.conf").exists())

    def test_a_program_conf_whose_command_is_missing_fails_the_step(self):
        """A stale platform conf that points at a missing binary would
        crash-loop forever — fail loudly and name the conf; never write a
        second [program:...] elsewhere, which breaks supervisorctl reread."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            bin_dest = directory / "sbin"
            (directory / "svconf" / "orgo.conf").write_text(
                "[program:hermes-gateway]\n"
                f"command={bin_dest}/orgo-hermes-gateway\n",
                encoding="utf-8")
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/s7")
            result = run(env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((bin_dest / "orgo-hermes-gateway").exists())
            self.assertFalse((directory / "svconf" / "hermes-gateway.conf").exists())
            doc = json.loads((directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "failed")
            self.assertEqual(doc["step"], "hermes")
            self.assertIn("fix or remove", doc["error"])
            self.assertIn("orgo.conf", doc["error"])

    def test_a_defined_gateway_without_a_command_fails_not_duplicated(self):
        """A [program:hermes-gateway] with no parseable command= fails the
        step naming the conf — repairing it in place risks folding indented
        junk into the new option, and a second [program:...] elsewhere makes
        `supervisorctl reread` fail on the duplicate."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            orgo_conf = directory / "svconf" / "orgo.conf"
            before = "; platform file\n[program:hermes-gateway]\nuser=root\n"
            orgo_conf.write_text(before, encoding="utf-8")
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/s10")
            result = run(env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((directory / "svconf" / "hermes-gateway.conf").exists())
            # The foreign conf is left exactly as it was.
            self.assertEqual(orgo_conf.read_text(encoding="utf-8"), before)
            doc = json.loads((directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "failed")
            self.assertEqual(doc["step"], "hermes")
            self.assertIn("fix or remove", doc["error"])
            self.assertIn("orgo.conf", doc["error"])

    def test_a_defined_tailscaled_whose_command_binary_is_missing_fails(self):
        """The indented command= under a section header is a real option to
        ConfigParser, so /gone is the command — missing binary means fail,
        naming the conf."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            conf = directory / "svconf" / "orgo-tailscale.conf"
            before = "[program:tailscaled]\n command=/gone\n"
            conf.write_text(before, encoding="utf-8")
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/s11")
            result = run(env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((directory / "svconf" / "tailscaled.conf").exists())
            self.assertEqual(conf.read_text(encoding="utf-8"), before)
            doc = json.loads((directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "failed")
            self.assertEqual(doc["step"], "tailscale")
            self.assertIn("fix or remove", doc["error"])
            self.assertIn("orgo-tailscale.conf", doc["error"])

    def test_an_indented_command_under_the_header_counts_as_a_command(self):
        """ConfigParser reads an indented command= directly under a section
        header as a real option. When its binary exists the conf is reused
        as-is — treating it as command-less would fail a working conf."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            conf = directory / "svconf" / "orgo-tailscale.conf"
            before = ("[program:tailscaled]\n"
                      " command=tailscaled --tun=userspace-networking\n")
            conf.write_text(before, encoding="utf-8")
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/s12")
            result = run(env=env)
            self.assertEqual(result.returncode, 0)
            self.assertFalse((directory / "svconf" / "tailscaled.conf").exists())
            self.assertEqual(conf.read_text(encoding="utf-8"), before)
            self.assertIn("tailscaled already defined", result.stdout)

    def test_a_defined_program_header_tolerates_trailing_junk(self):
        """'[program:x] ; comment', trailing whitespace and CRLF endings are
        still that section to ConfigParser — a broken command under them
        must fail by name, never silently write a duplicate conf."""
        cases = [
            "[program:hermes-gateway] ; platform file\ncommand=/gone\n",
            "[program:hermes-gateway] \ncommand=/gone\n",
            "[program:hermes-gateway]\r\ncommand=/gone\r\n",
        ]
        for text in cases:
            with self.subTest(text=text.splitlines()[0]):
                with tempfile.TemporaryDirectory() as d:
                    directory = Path(d)
                    env, log, stub_bin = fixture(directory)
                    (directory / "svconf" / "orgo.conf").write_text(
                        text, encoding="utf-8")
                    curl_stub(stub_bin)
                    tailscale_stub(
                        stub_bin, url="https://login.tailscale.com/a/s13")
                    result = run(env=env, check=False)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(
                        (directory / "svconf" / "hermes-gateway.conf").exists())
                    doc = json.loads(
                        (directory / "state" / "state.json").read_text(
                            encoding="utf-8"))
                    self.assertEqual(doc["state"], "failed")
                    self.assertIn("fix or remove", doc["error"])
                    self.assertIn("orgo.conf", doc["error"])

    def test_repo_ref_is_never_interpreted_as_shell(self):
        """--repo-ref comes from the provisioning backend; a quote or $(...)
        in it must not break out of a composed command string."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            marker = directory / "pwned"
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/i1")
            run("--repo-ref", f"x';touch {marker};'", env=env)
            self.assertFalse(marker.exists())

    def test_alans_way_conf_runs_as_the_invoking_user(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            curl_stub(stub_bin)
            tailscale_stub(stub_bin, url="https://login.tailscale.com/a/u1")
            run(env=env)
            conf = (directory / "svconf" / "alans-way.conf").read_text(encoding="utf-8")
            self.assertEqual(conf.count("user="), 2)

    def test_wait_paired_fails_fast_when_tailscale_is_missing(self):
        """No tailscale stub on PATH — a poller hitting --wait-paired before
        bootstrap ran must fail, not spin forever."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            result = run("--wait-paired", env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            doc = json.loads((directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "failed")
            self.assertEqual(doc["step"], "wait_paired")

    def test_wait_paired_times_out(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            env["ALAN_WAIT_PAIRED_TIMEOUT"] = "1"
            env["ALAN_WAIT_PAIRED_INTERVAL"] = "1"
            tailscale_stub(stub_bin, backend="NeedsLogin")
            result = run("--wait-paired", env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            doc = json.loads((directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "failed")

    def test_wait_paired_writes_ready_paired(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            tailscale_stub(stub_bin, backend="Running")
            result = run("--wait-paired", env=env)
            self.assertEqual(result.returncode, 0)
            doc = json.loads((directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "ready")
            self.assertEqual(doc["step"], "paired")


def jev_repo(directory: Path, install_py: str = None) -> str:
    """A local stand-in for github.com/kerpopule/hermes-jev-skills: a real git
    checkout whose install.py records its argv, so no network or GitHub is
    involved. Returns the commit the bootstrap should pin."""
    repo = directory / "jev-repo"
    repo.mkdir()
    (repo / "install.py").write_text(
        install_py or
        "import os, sys\n"
        "open(os.environ['STUB_LOG'], 'a').write("
        "'install.py ' + ' '.join(sys.argv[1:]) + '\\n')\n",
        encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "install.py"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "pin me"], check=True)
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True).stdout.strip()
    return sha


def relay_fixture(directory: Path, env: dict, commit: str = None):
    """Point the bootstrap's relay hooks at local fakes: the watcher script
    ships in this repo, and the jev checkout is a local repo on the pin."""
    env["ALAN_VOICE_WATCH"] = str(ROOT / "scripts" / "alan-relay-voice-watch")
    env["ALAN_JEV_DIR"] = str(directory / "jev-repo")
    env["ALAN_JEV_COMMIT"] = commit or jev_repo(directory)


class RelayStepTests(unittest.TestCase):
    TOKEN = "rly-test-token-9f8e7d6c"

    def full_run(self, directory: Path, env: dict, *args, input_text=None, check=True):
        curl_stub(directory / "stubbin")
        tailscale_stub(directory / "stubbin", url="https://login.tailscale.com/a/r1")
        return run(*args, env=env, check=check, input_text=input_text)

    def test_no_token_runs_no_relay_wiring(self):
        """DIY: nothing relay-shaped may happen — no credential files, no
        config writes, no watcher program, no jev checkout."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            result = self.full_run(directory, env)
            self.assertEqual(result.returncode, 0)
            self.assertIn("skipping hosted relay wiring", result.stdout)
            self.assertFalse((directory / "state" / "relay-token").exists())
            env_file = directory / "home" / ".hermes" / ".env"
            if env_file.exists():
                self.assertNotIn("ALAN_RELAY", env_file.read_text(encoding="utf-8"))
            calls = log.read_text(encoding="utf-8")
            self.assertNotIn("config set", calls)
            self.assertNotIn("install.py", calls)
            self.assertFalse(
                (directory / "svconf" / "alan-relay-voice-watch.conf").exists())
            self.assertFalse((directory / "home" / ".hermes" / "jev").exists())

    def test_relay_token_wires_voice_jev_and_the_watcher(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            result = self.full_run(directory, env, "--relay-token", self.TOKEN)
            self.assertEqual(result.returncode, 0)

            # The token is persisted for the backend, root-only.
            token_file = directory / "state" / "relay-token"
            self.assertEqual(token_file.read_text(encoding="utf-8"), self.TOKEN)
            self.assertEqual(token_file.stat().st_mode & 0o777, 0o600)

            env_text = (directory / "home" / ".hermes" / ".env").read_text(
                encoding="utf-8")
            self.assertIn(f"ALAN_RELAY_BASE=https://openalan.com/api/relay", env_text)
            self.assertIn(f"ALAN_RELAY_TOKEN={self.TOKEN}", env_text)
            self.assertIn(f"VOICE_TOOLS_OPENAI_KEY={self.TOKEN}", env_text)
            self.assertIn(
                "TYPESAFE_BASE_URL=https://openalan.com/api/relay/jev", env_text)
            self.assertIn(f"JEV_PROXY_API_KEY={self.TOKEN}", env_text)
            self.assertIn(f"TYPESAFE_API_KEY={self.TOKEN}", env_text)
            self.assertEqual(
                (directory / "home" / ".hermes" / ".env").stat().st_mode & 0o777,
                0o600)

            calls = log.read_text(encoding="utf-8")
            for want in (
                "hermes config set tts.provider openai",
                "hermes config set tts.openai.model gpt-4o-mini-tts",
                "hermes config set tts.openai.base_url "
                    "https://openalan.com/api/relay/openai/v1",
                "hermes config set tts.openai.api_key ${VOICE_TOOLS_OPENAI_KEY}",
                "hermes config set stt.enabled true",
                "hermes config set stt.provider openai",
                "hermes config set stt.openai.model whisper-1",
                "hermes config set stt.openai.base_url "
                    "https://openalan.com/api/relay/openai/v1",
                "hermes config set stt.openai.api_key ${VOICE_TOOLS_OPENAI_KEY}",
            ):
                self.assertIn(want, calls)
            self.assertIn("install.py --hermes-home", calls)
            self.assertIn("--enable all", calls)

            switches = json.loads(
                (directory / "home" / ".hermes" / "jev" / "state.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(switches["routing"], "shadow")
            self.assertEqual(switches["screen"], "on")
            self.assertEqual(switches["skills"], "on")

            conf = (directory / "svconf" / "alan-relay-voice-watch.conf").read_text(
                encoding="utf-8")
            self.assertIn("[program:alan-relay-voice-watch]", conf)
            self.assertIn(str(directory / "sbin" / "alan-relay-voice-watch"), conf)
            self.assertNotIn(self.TOKEN, conf)
            self.assertTrue(
                (directory / "sbin" / "alan-relay-voice-watch").exists())
            self.assertIn("supervisorctl restart hermes-gateway", calls)

    def test_the_token_never_reaches_argv_or_logs(self):
        """Every stubbed command echoes its argv to STUB_LOG, and every `run`
        echoes '+ cmd' to bootstrap.log — the token may appear in neither,
        nor in stdout."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            result = self.full_run(directory, env, "--relay-token", self.TOKEN)
            self.assertNotIn(self.TOKEN, log.read_text(encoding="utf-8"))
            self.assertNotIn(
                self.TOKEN,
                (directory / "state" / "bootstrap.log").read_text(encoding="utf-8"))
            self.assertNotIn(self.TOKEN, result.stdout)

    def test_token_via_stdin_and_env_both_work(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            result = self.full_run(
                directory, env, "--relay-token", "-", input_text=self.TOKEN + "\n")
            self.assertEqual(result.returncode, 0)
            self.assertEqual(
                (directory / "state" / "relay-token").read_text(encoding="utf-8"),
                self.TOKEN)
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            env["ALAN_RELAY_TOKEN"] = self.TOKEN
            result = self.full_run(directory, env)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(
                (directory / "state" / "relay-token").read_text(encoding="utf-8"),
                self.TOKEN)
            # env-supplied tokens must not echo into argv either
            self.assertNotIn(self.TOKEN, log.read_text(encoding="utf-8"))

    def test_relay_base_override_reaches_voice_and_jev_urls(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            self.full_run(directory, env, "--relay-token", self.TOKEN,
                          "--relay-base", "http://relay.test:8080/api/relay/")
            calls = log.read_text(encoding="utf-8")
            self.assertIn(
                "tts.openai.base_url http://relay.test:8080/api/relay/openai/v1",
                calls)
            env_text = (directory / "home" / ".hermes" / ".env").read_text(
                encoding="utf-8")
            self.assertIn(
                "TYPESAFE_BASE_URL=http://relay.test:8080/api/relay/jev",
                env_text)

    def test_rerun_is_idempotent_and_preserves_operator_jev_switches(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            self.full_run(directory, env, "--relay-token", self.TOKEN)
            # The operator flipped routing on; a re-run must not reset it.
            state_path = directory / "home" / ".hermes" / "jev" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["routing"] = "on"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            self.full_run(directory, env, "--relay-token", "rotated-token-2")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["routing"], "on")
            self.assertEqual(state["screen"], "on")
            # rotated token propagates to both stores
            self.assertEqual(
                (directory / "state" / "relay-token").read_text(encoding="utf-8"),
                "rotated-token-2")
            env_text = (directory / "home" / ".hermes" / ".env").read_text(
                encoding="utf-8")
            self.assertEqual(env_text.count("ALAN_RELAY_TOKEN="), 1)
            self.assertIn("ALAN_RELAY_TOKEN=rotated-token-2", env_text)
            confs = "".join(
                c.read_text(encoding="utf-8")
                for c in (directory / "svconf").glob("*.conf"))
            self.assertEqual(confs.count("[program:alan-relay-voice-watch]"), 1)

    def test_a_non_git_jev_dir_degrades_to_a_warning_not_a_delete(self):
        """The jev plugin is a third-party GitHub install: a blocked checkout
        must not fail a computer whose pairing and voice work. It degrades
        to a warnings marker — and the foreign dir is still never touched."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            env["ALAN_VOICE_WATCH"] = str(
                ROOT / "scripts" / "alan-relay-voice-watch")
            env["ALAN_JEV_DIR"] = str(directory / "precious")
            (directory / "precious").mkdir()
            (directory / "precious" / "keep.txt").write_text("mine")
            result = self.full_run(directory, env, "--relay-token", self.TOKEN)
            self.assertEqual(result.returncode, 0)
            self.assertTrue((directory / "precious" / "keep.txt").exists())
            doc = json.loads(
                (directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "ready")
            self.assertEqual(doc["step"], "waiting_for_pairing")
            self.assertEqual(doc["warnings"], ["jev"])
            # the required wiring still landed
            self.assertTrue(
                (directory / "svconf" / "alan-relay-voice-watch.conf").exists())

    def test_a_failed_jev_clone_degrades_to_a_warning(self):
        """github.com/kerpopule/hermes-jev-skills is third-party — an outage
        mid-bootstrap is a warning, not a failed computer."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            env["ALAN_VOICE_WATCH"] = str(
                ROOT / "scripts" / "alan-relay-voice-watch")
            env["ALAN_JEV_REPO_URL"] = str(directory / "no-such-repo")
            env["ALAN_JEV_DIR"] = str(directory / "jev-dest")
            result = self.full_run(directory, env, "--relay-token", self.TOKEN)
            self.assertEqual(result.returncode, 0)
            self.assertFalse((directory / "jev-dest" / ".git").exists())
            doc = json.loads(
                (directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "ready")
            self.assertEqual(doc["warnings"], ["jev"])
            self.assertTrue(
                (directory / "svconf" / "alan-relay-voice-watch.conf").exists())

    def test_a_failing_jev_installer_degrades_to_a_warning(self):
        """The checkout is pinned but upstream install.py dies — same
        degrade, and the /jev switches file is not written half-way."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            env["ALAN_VOICE_WATCH"] = str(
                ROOT / "scripts" / "alan-relay-voice-watch")
            env["ALAN_JEV_DIR"] = str(directory / "jev-repo")
            env["ALAN_JEV_COMMIT"] = jev_repo(
                directory, install_py="import sys\nsys.exit(3)\n")
            result = self.full_run(directory, env, "--relay-token", self.TOKEN)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(
                (directory / "home" / ".hermes" / "jev" / "state.json").exists())
            doc = json.loads(
                (directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "ready")
            self.assertEqual(doc["warnings"], ["jev"])

    def test_a_missing_voice_watch_source_still_fails_the_run(self):
        """The degrade is for the third-party plugin only: the voice watcher
        is our own wiring — if it cannot be installed the computer fails."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            env["ALAN_VOICE_WATCH"] = str(directory / "no-such-script")
            result = self.full_run(
                directory, env, "--relay-token", self.TOKEN, check=False)
            self.assertNotEqual(result.returncode, 0)
            doc = json.loads(
                (directory / "state" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["state"], "failed")
            self.assertEqual(doc["step"], "relay")

    def test_the_watcher_comes_from_a_local_setup_checkout(self):
        """ALAN_SETUP_SH means 'nothing comes from GitHub': when it points
        into a mounted checkout the watcher must install from
        <checkout>/scripts/ rather than curling raw.githubusercontent.com."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            repo = directory / "repo"
            (repo / "scripts").mkdir(parents=True)
            (repo / "setup.sh").write_text(
                '#!/bin/sh\nmkdir -p "$HERMES_HOME/plugins/alans-way"\n',
                encoding="utf-8")
            (repo / "scripts" / "alan-relay-voice-watch").write_text(
                "#!/bin/sh\n# the mounted checkout's watcher\n",
                encoding="utf-8")
            env["ALAN_SETUP_SH"] = str(repo / "setup.sh")
            env["ALAN_JEV_DIR"] = str(directory / "jev-repo")
            env["ALAN_JEV_COMMIT"] = jev_repo(directory)
            curl_stub(stub_bin, fail_on="raw.githubusercontent.com")
            tailscale_stub(
                stub_bin, url="https://login.tailscale.com/a/lw1")
            result = run("--relay-token", self.TOKEN, env=env)
            self.assertEqual(result.returncode, 0)
            installed = (directory / "sbin" / "alan-relay-voice-watch")
            self.assertIn("mounted checkout", installed.read_text(
                encoding="utf-8"))
            self.assertNotIn(
                "raw.githubusercontent.com",
                log.read_text(encoding="utf-8"))

    def test_stdin_token_is_refused_when_the_script_is_on_stdin(self):
        """`curl ... | bash -s -- --relay-token -` would read the script's
        own bytes as the token — refuse and say to use ALAN_RELAY_TOKEN."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            with open(SCRIPT, "rb") as f:
                result = subprocess.run(
                    [BASH, "-s", "--", "--relay-token", "-"],
                    stdin=f, capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 2)
            self.assertIn("stdin", result.stderr)
            self.assertFalse((directory / "state").exists())

    def test_an_empty_stdin_token_fails_loudly(self):
        """EOF on the token read used to degrade silently to a DIY install;
        a billed hosted computer must fail instead."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            result = self.full_run(
                directory, env, "--relay-token", "-", input_text="",
                check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("empty", result.stderr)
            self.assertFalse(
                (directory / "state" / "state.json").exists())

    def test_a_value_flag_without_a_value_is_a_usage_error(self):
        """--relay-token as the last argv word used to die on unbound $2
        under set -u instead of printing a usage error."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            for flag in ("--relay-token", "--callback", "--id",
                         "--relay-base"):
                with self.subTest(flag=flag):
                    result = run(flag, env=env, check=False)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("requires a value", result.stderr)

    def test_wait_paired_preserves_recorded_warnings(self):
        """A jev degrade writes warnings:[jev]; a later --wait-paired
        invocation rewrites state.json and must not erase it — warnings are
        the only observability the backend has."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            env["ALAN_VOICE_WATCH"] = str(
                ROOT / "scripts" / "alan-relay-voice-watch")
            env["ALAN_JEV_DIR"] = str(directory / "precious")
            (directory / "precious").mkdir()
            (directory / "precious" / "keep.txt").write_text("mine")
            self.full_run(directory, env, "--relay-token", self.TOKEN)
            doc = json.loads(
                (directory / "state" / "state.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(doc["warnings"], ["jev"])
            tailscale_stub(stub_bin, backend="Running")
            result = run("--wait-paired", env=env)
            self.assertEqual(result.returncode, 0)
            doc = json.loads(
                (directory / "state" / "state.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(doc["state"], "ready")
            self.assertEqual(doc["step"], "paired")
            self.assertEqual(doc["warnings"], ["jev"])

    def test_an_unrecognized_gateway_status_is_logged_not_silent(self):
        """'hermes-gateway: no such process' matches no case arm — the old
        code fell through with no bounce and no log, leaving the new audio
        config unloaded while state said ready."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            stub(stub_bin, "supervisorctl", '''
echo "supervisorctl $*" >> "$STUB_LOG"
case "$1" in
  status) echo "hermes-gateway: ERROR (no such process)" >&2; exit 1;;
esac
''')
            relay_fixture(directory, env)
            result = self.full_run(directory, env, "--relay-token",
                                   self.TOKEN)
            self.assertEqual(result.returncode, 0)
            bootlog = (directory / "state" / "bootstrap.log").read_text(
                encoding="utf-8")
            self.assertIn("unrecognized", bootlog)
            doc = json.loads(
                (directory / "state" / "state.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(doc["state"], "ready")

    def test_a_failed_gateway_restart_does_not_fail_the_step(self):
        """'Never let the bounce fail the step' — a nonzero supervisorctl
        restart under errexit used to mark the whole relay step failed."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            stub(stub_bin, "supervisorctl", '''
echo "supervisorctl $*" >> "$STUB_LOG"
case "$1" in
  status) echo "hermes-gateway RUNNING pid 1, uptime 0:01:00";;
  restart) exit 1;;
esac
''')
            relay_fixture(directory, env)
            result = self.full_run(directory, env, "--relay-token",
                                   self.TOKEN)
            self.assertEqual(result.returncode, 0)
            doc = json.loads(
                (directory / "state" / "state.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(doc["state"], "ready")

    def test_operator_audio_config_survives_a_rerun(self):
        """The marker file records what bootstrap set; a re-run only writes
        keys that are still unset or still hold the recorded value, so a
        customer-set tts.provider is not clobbered."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            self.full_run(directory, env, "--relay-token", self.TOKEN)
            marker = directory / "home" / ".hermes" / ".alan-relay-managed"
            self.assertTrue(marker.exists())
            managed = json.loads(marker.read_text(encoding="utf-8"))[
                "managed"]
            self.assertEqual(managed["tts.provider"], "openai")
            # The customer switches to their own provider; a provisioning
            # retry must not reset it (the stub records calls cumulatively,
            # so the count must stay at one).
            cfg = directory / "home" / ".hermes" / "config.yaml"
            cfg.write_text("tts:\n  provider: elevenlabs\n",
                           encoding="utf-8")
            self.full_run(directory, env, "--relay-token",
                          "rotated-token-3")
            calls = log.read_text(encoding="utf-8")
            self.assertEqual(
                calls.count("hermes config set tts.provider openai"), 1)
            # Keys the customer did not touch are still refreshed.
            self.assertEqual(
                calls.count("hermes config set tts.openai.model "
                            "gpt-4o-mini-tts"), 2)

    def test_jev_checkout_is_reset_before_install(self):
        """A dirty managed checkout must not fail the pin or run a locally
        modified install.py — the dir is ours, so reset it hard."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            self.full_run(directory, env, "--relay-token", self.TOKEN)
            install_py = directory / "jev-repo" / "install.py"
            original = install_py.read_text(encoding="utf-8")
            # A locally poisoned install.py plus an untracked stray file:
            # the next run must restore the pin, not execute or trip on it.
            install_py.write_text("import sys\nsys.exit(9)\n",
                                  encoding="utf-8")
            (directory / "jev-repo" / "stray.txt").write_text("x")
            self.full_run(directory, env, "--relay-token",
                          "rotated-token-4")
            self.assertEqual(install_py.read_text(encoding="utf-8"),
                             original)
            self.assertFalse(
                (directory / "jev-repo" / "stray.txt").exists())
            doc = json.loads(
                (directory / "state" / "state.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(doc["state"], "ready")

    def test_the_watcher_conf_bakes_the_absolute_hermes_path(self):
        """supervisord's environment has no PATH guarantee; a bare `hermes`
        lookup inside the watcher used to die as a swallowed poll error."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            self.full_run(directory, env, "--relay-token", self.TOKEN)
            conf = (directory / "svconf" /
                    "alan-relay-voice-watch.conf").read_text(
                        encoding="utf-8")
            self.assertIn(f"--hermes {stub_bin}/hermes", conf)

    def test_a_foreign_watcher_conf_is_reused_not_duplicated(self):
        """A pre-existing [program:alan-relay-voice-watch] elsewhere must be
        reused like every other program here — a second section makes
        `supervisorctl reread` fail the whole step."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            foreign = directory / "svconf" / "platform.conf"
            bin_path = directory / "sbin" / "alan-relay-voice-watch"
            foreign.write_text(
                "[program:alan-relay-voice-watch]\n"
                f"command={bin_path}\n", encoding="utf-8")
            # The foreign conf names the bin we install — place it so the
            # command resolves and the conf is reused.
            bin_path.write_text("#!/bin/sh\n", encoding="utf-8")
            bin_path.chmod(0o755)
            self.full_run(directory, env, "--relay-token", self.TOKEN)
            self.assertFalse(
                (directory / "svconf" /
                 "alan-relay-voice-watch.conf").exists())
            programs = "".join(
                c.read_text(encoding="utf-8")
                for c in (directory / "svconf").glob("*.conf"))
            self.assertEqual(
                programs.count("[program:alan-relay-voice-watch]"), 1)
            bootlog = (directory / "state" / "bootstrap.log").read_text(
                encoding="utf-8")
            self.assertIn("already defined", bootlog)

    def test_the_watcher_binary_installs_via_a_tmp_file(self):
        """A truncated curl -o used to land a half-written watcher as the
        live binary; the install must be tmp+rename like every other
        writer here."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            self.full_run(directory, env, "--relay-token", self.TOKEN)
            self.assertFalse(
                list((directory / "sbin").glob(
                    "alan-relay-voice-watch.tmp*")))
            # The fetch is routed through `run` so its stderr reaches
            # bootstrap.log.
            self.assertFalse(
                list((directory / "home" / ".hermes").glob(".env.tmp*")))

    def test_relay_base_without_a_token_warns_instead_of_ignoring(self):
        """--relay-base without a token used to silently mean DIY."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            relay_fixture(directory, env)
            result = self.full_run(
                directory, env,
                "--relay-base", "http://relay.test:8080/api/relay")
            self.assertEqual(result.returncode, 0)
            self.assertIn("relay token", result.stdout)
            self.assertIn("relay-base", result.stdout)


if __name__ == "__main__":
    unittest.main()
