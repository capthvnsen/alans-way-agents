"""migrate.sh: pack, ship, path rewriting and gateway handover."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "migrate.sh"
BASH = shutil.which("bash") or "/bin/bash"


def run(*args, env=None, check=True):
    result = subprocess.run(
        [BASH, str(SCRIPT)] + list(args), capture_output=True, text=True, env=env,
        input="")
    if check and result.returncode != 0:
        raise AssertionError(f"exit {result.returncode}: {result.stderr}\n{result.stdout}")
    return result


def stub(bin_dir: Path, name: str, body: str):
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


SSH_STUB = '''
echo "ssh $*" >> "$STUB_LOG"
host="$1"; shift
export HOME="$FAKE_REMOTE_HOME"
# Model real ssh: the command arguments are joined with spaces and the
# remote shell re-parses them, so quoting bugs a plain `exec "$@"` would
# hide show up here.
cmd="$*"
if [ -n "$FAKE_SSH_FAIL" ]; then
  case "$cmd" in bash*) exit 3;; esac
fi
case "$cmd" in
  "supervisorctl status"*)
    echo "remote: $cmd" >> "$FAKE_REMOTE_CALLS"
    echo "hermes-gateway ${FAKE_REMOTE_STATE:-RUNNING} pid 4242"
    ;;
  supervisorctl*|systemctl*)
    echo "remote: $cmd" >> "$FAKE_REMOTE_CALLS"
    ;;
  *) eval "$cmd";;
esac
exit 0
'''

SCP_STUB = '''
echo "scp $*" >> "$STUB_LOG"
src="$1"; dst="$2"
dir="${dst#*:}"
# The remote shell re-parses the target — unquote it the same way.
eval "dir=$dir"
mkdir -p "$dir"
cp "$src" "${dir%/}/"
'''

CURL_STUB = '''
echo "curl $*" >> "$STUB_LOG"
printf '{"ok":true,"result":{"username":"fixturebot"}}\\n'
'''


def fixture(directory: Path, hermes_name=".hermes"):
    """A populated Hermes home plus ssh/scp stubs backed by a local 'remote'."""
    home = directory / "srchome"
    hermes = home / hermes_name
    hermes.mkdir(parents=True)
    (hermes / "config.yaml").write_text(
        f"data_dir: {hermes}/data\nhelper: {home}/bin/tool\n", encoding="utf-8")
    (hermes / ".env").write_text(
        'BOT_NAME="Al an Bot"\nTELEGRAM_BOT_TOKEN=999000111:root-token\nPATHLIST="a b:c"\n',
        encoding="utf-8")
    for name in ("SOUL.md", "MEMORY.md", "USER.md", "auth.json", "state.db"):
        (hermes / name).write_text(f"{name} contents\n", encoding="utf-8")
    alpha = hermes / "profiles" / "alpha"
    alpha.mkdir(parents=True)
    (alpha / "config.yaml").write_text(
        f"memory:\n  provider: honcho\nstate_db: {hermes}/profiles/alpha/state.db\n",
        encoding="utf-8")
    (alpha / "profile.yaml").write_text(
        f"path: {home}/.hermes/profiles/alpha\n", encoding="utf-8")
    (alpha / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=111222333:alpha-token\nGREETING='hi there'\n",
        encoding="utf-8")
    beta = hermes / "profiles" / "beta"
    beta.mkdir(parents=True)
    (beta / "config.yaml").write_text("kind: plain\n", encoding="utf-8")
    (beta / ".env").write_text("TELEGRAM_BOT_TOKEN=444555666:beta-token\n", encoding="utf-8")
    ghost = hermes / "profiles" / ".deleted" / "ghost"
    ghost.mkdir(parents=True)
    (ghost / "config.yaml").write_text("dead: true\n", encoding="utf-8")
    (hermes / "cache").mkdir()
    (hermes / "cache" / "junk.bin").write_text("junk\n", encoding="utf-8")
    (hermes / "logs").mkdir()
    (hermes / "logs" / "old.log").write_text("log\n", encoding="utf-8")
    dep = hermes / "plugins" / "p1" / "node_modules" / "dep"
    dep.mkdir(parents=True)
    (dep / "index.js").write_text("module.exports=1\n", encoding="utf-8")
    (hermes / "plugins" / "p1" / "plugin.yaml").write_text("name: p1\n", encoding="utf-8")

    remote_home = directory / "remotehome"
    remote_home.mkdir()
    stub_bin = directory / "stubbin"
    stub_bin.mkdir()
    calls = directory / "calls.log"
    local_calls = directory / "local-calls.log"
    remote_calls = directory / "remote-calls.log"
    stub(stub_bin, "ssh", SSH_STUB)
    stub(stub_bin, "scp", SCP_STUB)
    stub(stub_bin, "curl", CURL_STUB)
    # The remote script also calls supervisorctl; the ssh stub exports the
    # fake remote HOME, so the stub can tell remote calls from local ones.
    stub(stub_bin, "supervisorctl",
         'if [ "$HOME" = "$FAKE_REMOTE_HOME" ]; then '
         'echo "remote: supervisorctl $*" >> "$FAKE_REMOTE_CALLS"; '
         'else echo "local: supervisorctl $*" >> "$FAKE_LOCAL_CALLS"; fi\n'
         'exit "${FAKE_SUPERVISORCTL_RC:-0}"\n')
    stub(stub_bin, "systemctl",
         'echo "local: systemctl $*" >> "$FAKE_LOCAL_CALLS"\nexit "${FAKE_SYSTEMCTL_RC:-0}"\n')
    stub(stub_bin, "hermes",
         'echo "local: hermes $*" >> "$FAKE_LOCAL_CALLS"\nexit "${FAKE_HERMES_RC:-0}"\n')
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "HERMES_HOME": str(hermes),
        "PATH": os.pathsep.join([str(stub_bin), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]),
        "STUB_LOG": str(calls),
        "FAKE_LOCAL_CALLS": str(local_calls),
        "FAKE_REMOTE_CALLS": str(remote_calls),
        "FAKE_REMOTE_HOME": str(remote_home),
    })
    return env, home, hermes, remote_home, local_calls, remote_calls, calls


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


class MigrateTests(unittest.TestCase):
    def test_migrate_rewrites_paths_preserves_env_and_hands_over(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = fixture(directory)
            result = run("--to", "fakehost", "--yes", env=env)
            out = result.stdout

            remote = remote_home / ".hermes"
            # Path rewriting: the old Hermes home AND the old $HOME prefix.
            rconfig = read(remote / "config.yaml")
            self.assertIn(f"data_dir: {remote}/data", rconfig)
            self.assertIn(f"helper: {remote_home}/bin/tool", rconfig)
            self.assertNotIn(str(home), rconfig)
            rprofile = read(remote / "profiles" / "alpha" / "profile.yaml")
            self.assertIn(f"path: {remote}/profiles/alpha", rprofile)
            aconfig = read(remote / "profiles" / "alpha" / "config.yaml")
            self.assertIn(f"state_db: {remote}/profiles/alpha/state.db", aconfig)
            self.assertIn("provider: honcho", aconfig)

            # .env survives byte-for-byte, quotes and spaces included.
            self.assertEqual((hermes / ".env").read_bytes(), (remote / ".env").read_bytes())
            self.assertEqual(
                (hermes / "profiles" / "alpha" / ".env").read_bytes(),
                (remote / "profiles" / "alpha" / ".env").read_bytes())

            # Exclusions are respected.
            self.assertFalse((remote / "profiles" / ".deleted").exists())
            self.assertFalse((remote / "cache").exists())
            self.assertFalse((remote / "logs").exists())
            self.assertFalse((remote / "plugins" / "p1" / "node_modules").exists())
            self.assertTrue((remote / "plugins" / "p1" / "plugin.yaml").exists())
            for name in ("SOUL.md", "MEMORY.md", "USER.md", "auth.json", "state.db"):
                self.assertTrue((remote / name).exists(), name)

            # Manifest: profiles and bot usernames, plus the honcho warning.
            self.assertIn("alpha", out)
            self.assertIn("beta", out)
            self.assertIn("fixturebot", out)
            self.assertIn("honcho", out)

            # Handover: old gateway stopped locally, remote gateway restarted.
            self.assertIn("supervisorctl stop hermes-gateway", read(local_calls))
            self.assertIn("supervisorctl restart hermes-gateway", read(remote_calls))

    def test_remote_home_with_a_space_lands_intact(self):
        """ssh joins the remote command args with spaces and the remote
        shell re-parses them; a spaced path must still arrive as one arg."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = fixture(directory)
            env["FAKE_REMOTE_HOME"] = str(directory / "remote home")
            run("--to", "fakehost", "--yes", env=env)
            remote = directory / "remote home" / ".hermes"
            self.assertIn(f"data_dir: {remote}/data", read(remote / "config.yaml"))
            self.assertIn(f"helper: {directory}/remote home/bin/tool",
                          read(remote / "config.yaml"))

    def test_remote_home_metachars_are_not_command_injection(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = fixture(directory)
            marker = directory / "pwned"
            run("--to", "fakehost", "--yes", "--remote-home",
                f"{directory}/x;touch {marker}", env=env, check=False)
            self.assertFalse(marker.exists())

    def test_dash_leading_to_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = fixture(directory)
            result = run("--to", "-oProxyCommand=echo pwned", "--yes",
                         env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("'-'", result.stderr)

    def test_dot_in_hermes_does_not_rewrite_unrelated_paths(self):
        """'.' in '.hermes' used to be a live regex metachar: ahermes-backup
        got mangled into .hermes-backup. Literal replace leaves it alone."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = fixture(directory)
            cfg = hermes / "config.yaml"
            cfg.write_text(cfg.read_text(encoding="utf-8") +
                           f"backup_dir: {home}/ahermes-backup\n", encoding="utf-8")
            run("--to", "fakehost", "--yes", env=env)
            rconfig = read(remote_home / ".hermes" / "config.yaml")
            self.assertIn(f"backup_dir: {remote_home}/ahermes-backup", rconfig)
            self.assertNotIn(".hermes-backup", rconfig)

    def test_brackets_in_hermes_home_still_rewrite(self):
        """[1] used to parse as a character class, so the literal old path
        never matched and the migrated config kept pointing at the old home."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = fixture(
                directory, hermes_name="x[1]")
            run("--to", "fakehost", "--yes", env=env)
            remote = remote_home / ".hermes"
            self.assertIn(f"data_dir: {remote}/data", read(remote / "config.yaml"))

    def test_remote_home_sharing_the_old_prefix_does_not_double_rewrite(self):
        """Old home /x/srchome -> remote home /x/srchome2: a second pass over
        already-rewritten text must not produce /x/srchome22."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = fixture(directory)
            env["FAKE_REMOTE_HOME"] = str(directory / "srchome2")
            run("--to", "fakehost", "--yes", env=env)
            remote = directory / "srchome2" / ".hermes"
            rconfig = read(remote / "config.yaml")
            self.assertIn(f"data_dir: {remote}/data", rconfig)
            self.assertIn(f"helper: {directory}/srchome2/bin/tool", rconfig)
            self.assertNotIn("srchome22", rconfig)

    def test_yml_files_rewrite_and_other_stragglers_warn(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = fixture(directory)
            (hermes / "extra.yml").write_text(
                f"path: {hermes}/data\n", encoding="utf-8")
            (hermes / "notes.txt").write_text(
                f"see {hermes}/data for details\n", encoding="utf-8")
            result = run("--to", "fakehost", "--yes", env=env)
            remote = remote_home / ".hermes"
            self.assertIn(f"path: {remote}/data", read(remote / "extra.yml"))
            self.assertIn("still references", result.stderr)
            self.assertIn("notes.txt", result.stderr)

    def test_remote_failure_leaves_the_old_gateway_running(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = fixture(directory)
            env["FAKE_SSH_FAIL"] = "1"
            result = run("--to", "fakehost", "--yes", env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("stop", read(local_calls))
            self.assertNotIn("restart", read(remote_calls))
            self.assertFalse((remote_home / ".hermes").exists())

    def test_dry_run_prints_the_plan_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = fixture(directory)
            result = run("--to", "fakehost", "--dry-run", env=env)
            self.assertIn("would", result.stdout)
            self.assertFalse(calls.exists())
            self.assertFalse(local_calls.exists())
            self.assertFalse((remote_home / ".hermes").exists())

    def test_gateway_stop_falls_through_to_systemctl(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = fixture(directory)
            env["FAKE_SUPERVISORCTL_RC"] = "1"
            run("--to", "fakehost", "--yes", env=env)
            calls_text = read(local_calls)
            self.assertIn("supervisorctl stop hermes-gateway", calls_text)
            self.assertIn("systemctl --user stop hermes-gateway", calls_text)

    def test_nonstandard_hermes_home_rewrites_only_the_home_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = fixture(
                directory, hermes_name="hermesdata")
            sibling = home / "other"
            sibling.mkdir()
            (sibling / "keep.txt").write_text("keep\n", encoding="utf-8")
            (hermes / "config.yaml").write_text(
                f"data_dir: {hermes}/data\nother: {home}/other/keep.txt\n",
                encoding="utf-8")
            run("--to", "fakehost", "--yes", env=env)
            remote = remote_home / ".hermes"
            rconfig = read(remote / "config.yaml")
            self.assertIn(f"data_dir: {remote}/data", rconfig)
            # Paths outside the old Hermes home are left alone: the basename
            # isn't .hermes, so the parent dir is not assumed to be $HOME.
            self.assertIn(f"other: {home}/other/keep.txt", rconfig)

    def test_existing_remote_hermes_home_is_backed_up(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = fixture(directory)
            existing = remote_home / ".hermes"
            existing.mkdir()
            (existing / "config.yaml").write_text("old: true\n", encoding="utf-8")
            run("--to", "fakehost", "--yes", env=env)
            backups = list(remote_home.glob(".hermes.pre-migrate-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(read(backups[0] / "config.yaml"), "old: true\n")
            self.assertIn("data_dir:", read(existing / "config.yaml"))


if __name__ == "__main__":
    unittest.main()
