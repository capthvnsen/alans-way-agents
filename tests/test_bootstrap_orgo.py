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
    stub(stub_bin, "supervisorctl", 'echo "supervisorctl $*" >> "$STUB_LOG"\n')
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

    def test_a_value_flag_without_a_value_is_a_usage_error(self):
        """A value flag as the last argv word must print a usage error
        rather than dying on unbound $2 under set -u."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = fixture(directory)
            for flag in ("--callback", "--secret", "--id",
                         "--hermes-home", "--repo-ref"):
                with self.subTest(flag=flag):
                    result = run(flag, env=env, check=False)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("requires a value", result.stderr)


if __name__ == "__main__":
    unittest.main()
