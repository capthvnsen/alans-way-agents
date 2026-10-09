"""setup.sh CLI: verify strictness, bot-id derivation, timezone, and doc flags."""
from pathlib import Path
import json
import os
import re
import shutil
import stat
import subprocess
import signal
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "setup.sh"
SH = shutil.which("sh") or "/bin/sh"


def run(*args, env=None, check=True, script=SCRIPT):
    cmd = [SH, str(script)] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if check and result.returncode != 0:
        raise AssertionError(f"exit {result.returncode}: {result.stderr}\n{result.stdout}")
    return result


def fake_hermes_bin(directory: Path, *, plugins="", tools="", proactivity_status="{}", config_get=""):
    bin_dir = directory / "bin"
    bin_dir.mkdir()
    hermes = bin_dir / "hermes"
    hermes.write_text(f"""#!/bin/sh
[ "$1" = -p ] && shift 2
case "$1" in
  --version) echo "hermes 0.21.5"; exit 0;;
  plugins)
    shift
    [ "$1" = list ] && {{ echo "{plugins}"; exit 0; }}
    ;;
  tools)
    shift
    [ "$1" = list ] && {{ echo "{tools}"; exit 0; }}
    ;;
  proactivity)
    shift
    [ "$1" = status ] && {{ echo '{proactivity_status}'; exit 0; }}
    ;;
  config)
    shift
    [ "$1" = get ] && {{ echo "{config_get}"; exit 0; }}
    ;;
esac
exit 0
""")
    hermes.chmod(0o755)
    return bin_dir


class SetupVerifyTests(unittest.TestCase):
    def test_verify_fails_when_workspace_browser_block_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            home.mkdir()
            bin_dir = fake_hermes_bin(
                Path(directory),
                plugins="alans-way",
                tools="enabled proactivity",
            )
            env = dict(os.environ)
            env["HERMES_HOME"] = str(home)
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
            result = run("--verify", "--hermes-home", str(home), env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no workspace_browser block", result.stdout)
            self.assertIn("check(s) failed", result.stdout)

    def test_verify_fails_when_proactivity_toolset_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            home.mkdir()
            config = home / "config.yaml"
            config.write_text(
                "mcp_servers:\n"
                "# >>> alans-way workspace_browser managed block >>>\n"
                "  workspace_browser:\n    command: node\n"
                "# <<< alans-way workspace_browser managed block <<<\n",
                encoding="utf-8",
            )
            bin_dir = fake_hermes_bin(Path(directory), plugins="alans-way", tools="")
            env = dict(os.environ)
            env["HERMES_HOME"] = str(home)
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
            result = run("--verify", "--hermes-home", str(home), env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("proactivity toolset not enabled", result.stdout)

    def test_verify_skips_workspace_block_with_skip_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            home.mkdir()
            bin_dir = fake_hermes_bin(
                Path(directory),
                plugins="alans-way",
                tools="enabled proactivity",
            )
            env = dict(os.environ)
            env["HERMES_HOME"] = str(home)
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
            result = run(
                "--verify", "--skip-browser", "--hermes-home", str(home), env=env, check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("skip workspace_browser block", result.stdout)
            self.assertIn("all required checks passed", result.stdout)


class StaleHookTests(unittest.TestCase):
    def test_a_stale_gateway_hook_is_removed_and_other_hooks_are_left_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            stale = home / "hooks" / "alans-way"
            stale.mkdir(parents=True)
            (stale / "HOOK.yaml").write_text("name: alans-way-gateway\n", encoding="utf-8")
            (stale / "handler.py").write_text("# 0.6 hook\n", encoding="utf-8")
            other = home / "hooks" / "other"
            other.mkdir(parents=True)
            (other / "HOOK.yaml").write_text("name: other\n", encoding="utf-8")
            bin_dir = fake_hermes_bin(
                Path(directory),
                plugins="alans-way",
                tools="enabled proactivity",
            )
            env = dict(os.environ)
            env["HERMES_HOME"] = str(home)
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
            result = run(
                "--skip-browser", "--skip-services", "--non-interactive",
                "--hermes-home", str(home), env=env, check=False,
            )
            self.assertIn("removed the old proactivity hook", result.stdout)
            self.assertFalse(stale.exists())
            self.assertTrue((other / "HOOK.yaml").exists())

    def test_a_stale_hook_that_cannot_be_removed_warns(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            hooks = home / "hooks"
            stale = hooks / "alans-way"
            stale.mkdir(parents=True)
            (stale / "HOOK.yaml").write_text("name: alans-way-gateway\n", encoding="utf-8")
            (stale / "handler.py").write_text("# 0.6 hook\n", encoding="utf-8")
            hooks.chmod(0o555)
            bin_dir = fake_hermes_bin(
                Path(directory),
                plugins="alans-way",
                tools="enabled proactivity",
            )
            env = dict(os.environ)
            env["HERMES_HOME"] = str(home)
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
            try:
                result = run(
                    "--skip-browser", "--skip-services", "--non-interactive",
                    "--hermes-home", str(home), env=env, check=False,
                )
            finally:
                hooks.chmod(0o755)
            self.assertIn("could not remove the old proactivity hook", result.stdout)
            self.assertTrue(stale.exists())


class BotIdDerivationTests(unittest.TestCase):
    def test_derives_bot_id_from_profile_env_without_printing_token(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            profile_dir = home / "profiles" / "alan-local"
            profile_dir.mkdir(parents=True)
            (profile_dir / ".env").write_text(
                "TELEGRAM_BOT_TOKEN=987654321:AAFakeTokenForTests\n", encoding="utf-8",
            )
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            hermes = bin_dir / "hermes"
            hermes.write_text("""#!/bin/sh
[ "$1" = -p ] && shift 2
case "$1" in
  --version) echo "hermes 0.21.5"; exit 0;;
  plugins)
    shift
    case "$1" in
      list) echo "alans-way"; exit 0;;
      install) exit 0;;
      enable) exit 0;;
    esac;;
  tools)
    shift
    [ "$1" = enable ] || [ "$1" = disable ] && exit 0;;
  gateway)
    shift
    [ "$1" = restart ] && exit 0;;
esac
exit 0
""", encoding="utf-8")
            hermes.chmod(0o755)
            env = dict(os.environ)
            env["HERMES_HOME"] = str(home)
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
            result = run(
                "--profile", "alan-local",
                "--skip-browser", "--skip-services", "--non-interactive",
                "--hermes-home", str(home),
                env=env,
            )
            self.assertIn("using bot id 987654321", result.stdout)
            self.assertNotIn("AAFakeTokenForTests", result.stdout)
            config = profile_dir / "config.yaml"
            self.assertTrue(config.exists())
            self.assertIn("987654321", config.read_text(encoding="utf-8"))


class TimezoneFallbackTests(unittest.TestCase):
    def test_the_vps_timezone_is_never_used_for_quiet_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            home.mkdir()
            (home / ".env").write_text("TELEGRAM_BOT_TOKEN=111222333:token\n", encoding="utf-8")
            bin_dir = fake_hermes_bin(
                Path(directory),
                plugins="alans-way",
                tools="enabled proactivity",
            )
            timedatectl = bin_dir / "timedatectl"
            timedatectl.write_text("#!/bin/sh\necho America/Denver\n", encoding="utf-8")
            timedatectl.chmod(0o755)
            env = dict(os.environ)
            env["HERMES_HOME"] = str(home)
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
            result = run(
                "--bot-id", "111222333",
                "--non-interactive",
                "--skip-browser", "--skip-services",
                "--hermes-home", str(home),
                env=env,
            )
            self.assertNotIn("VPS timezone", result.stdout)
            self.assertNotIn("America/Denver", result.stdout)


def logging_hermes_bin(directory: Path, log: Path, version="0.21.5", proactivity_status=""):
    bin_dir = directory / "bin"
    bin_dir.mkdir(exist_ok=True)
    hermes = bin_dir / "hermes"
    hermes.write_text(f"""#!/bin/sh
echo "$*" >> "{log}"
[ "$1" = -p ] && shift 2
case "$1" in
  --version) echo "hermes {version}";;
  plugins) [ "$2" = list ] && echo "alans-way";;
  proactivity) [ "$2" = status ] && echo '{proactivity_status}';;
esac
exit 0
""", encoding="utf-8")
    hermes.chmod(0o755)
    return bin_dir


def fake(bin_dir: Path, name: str, body: str):
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def tailnet_ip(*tail):
    return ".".join(["100"] + [str(part) for part in tail])


TAILSCALE_UP = """case "$1" in
  status) cat <<'JSON'
{"BackendState":"Running","Self":{"HostName":"vps","TailscaleIPs":["%s"]},
 "Peer":{"nodekey:abc":{"HostName":"mymac","DNSName":"mymac.tail1234.ts.net.","TailscaleIPs":["%s"]}}}
JSON
  ;;
esac
exit 0
""" % (tailnet_ip(64, 0, 2), tailnet_ip(64, 0, 9))


def tooling(directory: Path, log: Path, **kwargs):
    """A bin dir with a profile-aware hermes, a running tailscale and node >= 22."""
    bin_dir = logging_hermes_bin(directory, log, **kwargs)
    fake(bin_dir, "tailscale", TAILSCALE_UP)
    fake(bin_dir, "systemd-run", "exit 1\n")
    return bin_dir


def env_for(directory, bin_dir, home, **extra):
    return dict(os.environ, HOME=str(directory), HERMES_HOME=str(home), TMPDIR=str(directory),
                PATH=str(bin_dir) + os.pathsep + os.environ["PATH"], ALANS_WAY_BROWSER_PATH=str(bin_dir), **extra)


class SkipPluginTests(unittest.TestCase):
    def test_skip_plugin_does_not_reinstall_an_existing_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            (home / "plugins" / "alans-way").mkdir(parents=True)
            log = Path(directory) / "log"
            bin_dir = logging_hermes_bin(Path(directory), log)
            env = dict(os.environ, HERMES_HOME=str(home), PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            result = run(
                "--skip-plugin", "--skip-browser", "--skip-services", "--non-interactive",
                "--hermes-home", str(home),
                env=env, check=False,
            )
            calls = log.read_text(encoding="utf-8")
            self.assertIn("not replacing it", result.stdout)
            self.assertNotIn("plugins install", calls)

    def test_catalog_install_is_never_force_replaced_without_skip_plugin(self):
        """A catalog-installed plugin is provenance in .install-metadata.json;
        setup must stop short of install --force and point at the catalog's
        own update path instead."""
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            plugin_dir = home / "plugins" / "alans-way"
            plugin_dir.mkdir(parents=True)
            # The recorded sha pins the clone too: record this checkout's HEAD.
            head = subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True).stdout.strip()
            (home / "plugins" / ".install-metadata.json").write_text(
                '{"alans-way": {"source": "catalog", "catalog": {"name": "alans-way", '
                '"sha": "%s"}, "pinned": true}}' % head,
                encoding="utf-8",
            )
            log = Path(directory) / "log"
            bin_dir = logging_hermes_bin(Path(directory), log)
            env = dict(os.environ, HERMES_HOME=str(home), PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            result = run(
                "--skip-browser", "--skip-services", "--non-interactive",
                "--hermes-home", str(home),
                env=env, check=False,
            )
            calls = log.read_text(encoding="utf-8")
            self.assertIn("leaving its pin in place", result.stdout)
            self.assertIn("hermes plugins update", result.stdout)
            self.assertNotIn("plugins install", calls)

    def test_catalog_sidecar_alone_also_marks_a_catalog_install(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            plugin_dir = home / "plugins" / "alans-way"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / ".hermes-catalog.json").write_text(
                '{"catalog_name": "alans-way", "sha": "3a74614aa6ef43353500553526325c2fc33da9e5"}',
                encoding="utf-8",
            )
            log = Path(directory) / "log"
            bin_dir = logging_hermes_bin(Path(directory), log)
            env = dict(os.environ, HERMES_HOME=str(home), PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            result = run(
                "--skip-browser", "--skip-services", "--non-interactive",
                "--hermes-home", str(home),
                env=env, check=False,
            )
            self.assertNotIn("plugins install", log.read_text(encoding="utf-8"))

    def test_ref_flags_reject_non_ref_values(self):
        result = run("--repo-ref", "HEAD:hook.py", "--verify", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid ref", result.stderr)


class AgentShellTests(unittest.TestCase):
    def test_runs_to_completion_without_a_controlling_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            home.mkdir()
            bin_dir = logging_hermes_bin(Path(directory), Path(directory) / "log")
            env = dict(os.environ, HERMES_HOME=str(home), PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            result = subprocess.run(
                [SH, str(SCRIPT), "--bot-id", "111222333", "--skip-browser", "--skip-services",
                 "--hermes-home", str(home)],
                capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, start_new_session=True,
            )
            self.assertNotIn("Device not configured", result.stderr)
            self.assertIn("== Done", result.stdout)

    def test_non_interactive_bind_picks_the_profile_route_from_a_multiplexed_index(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            (home / "profiles" / "delta").mkdir(parents=True)
            (home / "sessions").mkdir()
            (home / "sessions" / "sessions.json").write_text(
                '{"agent:main:telegram:dm:1": {"platform": "telegram", "chat_type": "dm"},'
                ' "agent:delta:telegram:dm:1": {"platform": "telegram", "chat_type": "dm"}}',
                encoding="utf-8",
            )
            log = Path(directory) / "log"
            bin_dir = logging_hermes_bin(Path(directory), log)
            env = dict(os.environ, HERMES_HOME=str(home), PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            result = run(
                "--profile", "delta", "--bind", "--proactive", "yes", "--timezone", "Europe/Berlin",
                "--non-interactive", "--skip-browser", "--skip-services", "--hermes-home", str(home),
                env=env, check=False,
            )
            calls = log.read_text(encoding="utf-8")
            self.assertIn("bound primary route: delta", result.stdout)
            self.assertIn("-p delta proactivity bind --session-key agent:delta:telegram:dm:1", calls)
            self.assertIn("-p delta config set plugins.entries.alans-way.allow_gateway_injection true", calls)
            self.assertNotIn("proactivity probe", calls)
            self.assertIn("proactivity on by default", result.stdout)

    def test_proactive_no_binds_paused(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            (home / "sessions").mkdir(parents=True)
            (home / "sessions" / "sessions.json").write_text(
                '{"agent:main:telegram:dm:1": {"platform": "telegram", "chat_type": "dm"}}', encoding="utf-8")
            log = Path(directory) / "log"
            bin_dir = logging_hermes_bin(Path(directory), log)
            env = dict(os.environ, HERMES_HOME=str(home), PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            run("--bind", "--proactive", "no", "--non-interactive", "--skip-browser", "--skip-services",
                "--hermes-home", str(home), env=env, check=False)
            calls = log.read_text(encoding="utf-8")
            self.assertIn('proactivity set --settings {"paused_until": "off"}', calls)
            self.assertNotIn("proactivity probe", calls)

    def test_proactive_must_be_yes_or_no(self):
        result = run("--proactive", "maybe", "--verify", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--proactive", result.stderr)

    def test_non_interactive_bind_discovers_a_state_db_only_route(self):
        """No sessions.json mirror: --bind must find Telegram DM routes in the
        profile's state.db gateway_routing table — the same store the runtime
        bind path treats as authoritative."""
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            prof = home / "profiles" / "delta"
            prof.mkdir(parents=True)
            route = "agent:delta:telegram:dm:42"
            entry = {"session_key": route, "session_id": "abc",
                     "platform": "telegram", "chat_type": "dm", "suspended": False}
            db = sqlite3.connect(prof / "state.db")
            db.execute("""CREATE TABLE gateway_routing (
                scope TEXT NOT NULL DEFAULT '', session_key TEXT NOT NULL,
                entry_json TEXT NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY (scope, session_key))""")
            db.execute("INSERT INTO gateway_routing VALUES ('', ?, ?, 0)",
                       (route, json.dumps(entry)))
            db.commit(); db.close()
            log = Path(directory) / "log"
            bin_dir = logging_hermes_bin(Path(directory), log)
            env = dict(os.environ, HERMES_HOME=str(home), PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            result = run(
                "--profile", "delta", "--bind", "--proactive", "yes",
                "--non-interactive", "--skip-browser", "--skip-services",
                "--hermes-home", str(home),
                env=env, check=False,
            )
            calls = log.read_text(encoding="utf-8")
            self.assertIn("bound primary route: delta", result.stdout)
            self.assertIn("-p delta proactivity bind --session-key agent:delta:telegram:dm:42", calls)

    def test_an_already_bound_profile_keeps_its_binding(self):
        """A re-run where the target profile is already bound must say so and
        skip the route list, not claim check-ins stay silent until a bind."""
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            (home / "sessions").mkdir(parents=True)
            (home / "sessions" / "sessions.json").write_text(
                '{"agent:main:telegram:dm:1": {"platform": "telegram", "chat_type": "dm"}}', encoding="utf-8")
            log = Path(directory) / "log"
            bin_dir = logging_hermes_bin(Path(directory), log, proactivity_status='{"bound": true}')
            env = dict(os.environ, HERMES_HOME=str(home), PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            result = run("--non-interactive", "--skip-browser", "--skip-services",
                         "--hermes-home", str(home), env=env, check=False)
            self.assertIn("already bound", result.stdout)
            self.assertNotIn("stays silent", result.stdout)
            self.assertNotIn("pick which bot", result.stdout)
            self.assertNotIn("proactivity bind", log.read_text(encoding="utf-8"))

    def test_bind_still_rebinds_an_already_bound_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            (home / "sessions").mkdir(parents=True)
            (home / "sessions" / "sessions.json").write_text(
                '{"agent:main:telegram:dm:1": {"platform": "telegram", "chat_type": "dm"}}', encoding="utf-8")
            log = Path(directory) / "log"
            bin_dir = logging_hermes_bin(Path(directory), log, proactivity_status='{"bound": true}')
            env = dict(os.environ, HERMES_HOME=str(home), PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            result = run("--bind", "--non-interactive", "--skip-browser", "--skip-services",
                         "--hermes-home", str(home), env=env, check=False)
            self.assertIn("bound primary route", result.stdout)
            self.assertIn("proactivity bind --session-key agent:main:telegram:dm:1",
                          log.read_text(encoding="utf-8"))


class PinAndListTests(unittest.TestCase):
    def setup_env(self, plugins_list="alans-way"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.log = self.root / "log"
        bin_dir = tooling(self.root, self.log)
        fake(bin_dir, "hermes", 'echo "$*" >> "%s"\n[ "$1" = -p ] && shift 2\ncase "$*" in\n'
             '  "--version") echo "hermes 0.21.5";;\n  "plugins list") printf "%s\\n";;\nesac\nexit 0\n' % (self.log, plugins_list))
        return env_for(self.root, bin_dir, self.home)

    def test_a_longer_plugin_name_does_not_satisfy_the_check(self):
        env = self.setup_env("alans-way-computer")
        result = run("--verify", "--skip-browser", env=env, check=False)
        self.assertIn("not in hermes plugins list", result.stdout)
        env = self.setup_env("alans-way\\nalans-way-computer")
        result = run("--verify", "--skip-browser", env=env, check=False)
        self.assertNotIn("not in hermes plugins list", result.stdout)

    def test_desktop_ref_on_a_non_git_checkout_stops(self):
        env = self.setup_env()
        app = desktop_tree(self.root / "app")
        result = run("--skip-plugin", "--desktop-dir", str(app), "--desktop-ref", "abc1234", "--non-interactive",
                     "--hermes-home", str(self.home), env=env, check=False)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("not a git checkout", result.stdout)

    def test_repo_ref_from_a_clone_must_match_the_checkout(self):
        env = self.setup_env()
        repo = self.root / "repo"
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "tests", "__pycache__"))
        script = repo / "setup.sh"
        flags = ("--repo-ref", "abc1234", "--skip-browser", "--skip-services", "--non-interactive", "--hermes-home", str(self.home))
        result = run(*flags, env=env, check=False, script=script)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "x"], check=True)
        result = run(*flags, env=env, check=False, script=script)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        flags = ("--repo-ref", head, *flags[2:])
        result = run(*flags, env=env, check=False, script=script)
        self.assertIn("is at %s" % head, result.stdout)

    def test_repo_ref_tag_must_resolve_to_the_checkout_commit(self):
        env = self.setup_env()
        repo = self.root / "repo"
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "tests", "__pycache__"))
        script = repo / "setup.sh"
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "x"], check=True)
        subprocess.run([*git, "tag", "v9.9.9"], check=True)
        subprocess.run([*git, "commit", "-qm", "unreviewed change", "--allow-empty"], check=True)
        flags = ("--repo-ref", "v9.9.9", "--skip-browser", "--skip-services", "--non-interactive",
                 "--hermes-home", str(self.home))
        # A clone that drifted past the tag's commit hard-stops.
        result = run(*flags, env=env, check=False, script=script)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("is not at --repo-ref v9.9.9", result.stdout)
        # Back at the tag, the pin holds.
        subprocess.run([*git, "checkout", "-q", "v9.9.9"], check=True)
        result = run(*flags, env=env, check=False, script=script)
        self.assertIn("is at v9.9.9", result.stdout)
        self.assertNotIn("is not at --repo-ref", result.stdout)

    def make_git_repo(self):
        repo = self.root / "repo"
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "tests", "__pycache__"))
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "x"], check=True)
        return repo / "setup.sh", git

    def write_catalog_record(self, sha):
        plugins = self.home / "plugins"
        plugins.mkdir(parents=True, exist_ok=True)
        (plugins / "alans-way").mkdir(exist_ok=True)
        (plugins / ".install-metadata.json").write_text(
            json.dumps({"alans-way": {"pinned": True, "revision": sha, "source": "catalog",
                                      "catalog": {"name": "alans-way", "sha": sha}}}),
            encoding="utf-8")

    def test_a_catalog_record_pins_the_clone_to_the_reviewed_sha(self):
        env = self.setup_env()
        script, git = self.make_git_repo()
        head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        self.write_catalog_record(head)
        flags = ("--skip-browser", "--skip-services", "--non-interactive", "--hermes-home", str(self.home))
        result = run(*flags, env=env, check=False, script=script)
        self.assertIn("is at %s" % head, result.stdout)
        # Once the clone drifts off the recorded commit, setup hard-stops.
        subprocess.run([*git, "commit", "-qm", "unreviewed change", "--allow-empty"], check=True)
        result = run(*flags, env=env, check=False, script=script)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("is not at --repo-ref %s" % head, result.stdout)

    def test_a_moved_tag_cannot_override_the_recorded_sha(self):
        env = self.setup_env()
        script, git = self.make_git_repo()
        head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run([*git, "commit", "-qm", "moved", "--allow-empty"], check=True)
        subprocess.run([*git, "tag", "v9.9.9"], check=True)  # the tag now sits past the pin
        subprocess.run([*git, "checkout", "-q", head], check=True)
        self.write_catalog_record(head)
        # Passing the moved tag still resolves to the recorded sha, not the tag.
        result = run("--repo-ref", "v9.9.9", "--skip-browser", "--skip-services", "--non-interactive",
                     "--hermes-home", str(self.home), env=env, check=False, script=script)
        self.assertIn("--repo-ref v9.9.9 ignored", result.stdout)
        self.assertIn("is at %s" % head, result.stdout)
        self.assertNotIn("is not at --repo-ref", result.stdout)

    def test_without_a_catalog_record_the_release_tag_is_the_pin(self):
        env = self.setup_env()
        script, git = self.make_git_repo()
        subprocess.run([*git, "tag", "v9.9.9"], check=True)
        subprocess.run([*git, "commit", "-qm", "unreviewed change", "--allow-empty"], check=True)
        result = run("--repo-ref", "v9.9.9", "--skip-browser", "--skip-services", "--non-interactive",
                     "--hermes-home", str(self.home), env=env, check=False, script=script)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("is not at --repo-ref v9.9.9", result.stdout)
        self.assertNotIn("ignored", result.stdout)

    def test_a_ref_that_cannot_be_resolved_stops_with_a_clear_error(self):
        env = self.setup_env()
        script, git = self.make_git_repo()
        result = run("--repo-ref", "v9.9.9", "--skip-browser", "--skip-services", "--non-interactive",
                     "--hermes-home", str(self.home), env=env, check=False, script=script)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("cannot resolve --repo-ref v9.9.9", result.stdout)


class DocFlagTests(unittest.TestCase):
    def test_setup_prompt_flags_exist_in_setup_sh(self):
        prompt = (ROOT / "docs" / "setup-prompt.md").read_text(encoding="utf-8")
        setup_help = run("-h").stdout
        declared = set(re.findall(r"--[a-z-]+", setup_help))
        for flag in re.findall(r"--[a-z-]+", prompt):
            self.assertIn(flag, declared, f"{flag} in setup-prompt.md is not in setup.sh --help")

    def test_readme_bootstrap_flags_exist_in_setup_sh(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        setup_help = run("-h").stdout
        declared = set(re.findall(r"--[a-z-]+", setup_help))
        section = readme.split("curl -fsSL")[1].split("```")[0] if "curl -fsSL" in readme else ""
        for flag in re.findall(r"--[a-z-]+", section):
            self.assertIn(flag, declared, f"{flag} in README bootstrap is not in setup.sh --help")


class NodePreflightTests(unittest.TestCase):
    def test_preflight_fails_when_node_major_is_too_old(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            node = bin_dir / "node"
            node.write_text('#!/bin/sh\nif [ "$1" = "-p" ]; then echo 16; else echo v16.20.0; fi\n', encoding="utf-8")
            node.chmod(0o755)
            (bin_dir / "hermes").write_text('#!/bin/sh\necho hermes 0.21.5\n', encoding="utf-8")
            (bin_dir / "hermes").chmod(0o755)
            env = dict(os.environ)
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
            result = run("--verify", env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("below 22", result.stdout)


def desktop_tree(root: Path) -> Path:
    desktop = root / "desktop"
    (desktop / "scripts").mkdir(parents=True)
    (desktop / "src").mkdir()
    (desktop / "node_modules" / "@modelcontextprotocol").mkdir(parents=True)
    for name in ("scripts/browser-mcp.cjs", "scripts/mac-computer.swift", "scripts/vps-chromium-host.cjs",
                 "scripts/vps-browser-host.cjs", "src/computer.cjs", "package.json", "package-lock.json"):
        (desktop / name).write_text("//\n", encoding="utf-8")
    return root


def read_log(log: Path) -> str:
    return log.read_text(encoding="utf-8") if log.exists() else ""


class HermesHomeTests(unittest.TestCase):
    def test_exported_hermes_home_is_respected_and_the_flag_overrides_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exported, flagged = root / "exported", root / "flagged"
            exported.mkdir(); flagged.mkdir()
            bin_dir = tooling(root, root / "log")
            env = env_for(root, bin_dir, exported)
            result = run("--verify", env=env, check=False)
            self.assertIn(f"HERMES_HOME: {exported}", result.stdout)
            result = run("--verify", "--hermes-home", str(flagged), env=env, check=False)
            self.assertIn(f"HERMES_HOME: {flagged}", result.stdout)

    def test_hermes_commands_run_against_the_resolved_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flagged = root / "flagged"
            flagged.mkdir()
            bin_dir = tooling(root, root / "log")
            fake(bin_dir, "hermes", 'case "$1" in --version) echo "hermes 0.21.5";; *) echo "$HERMES_HOME" >> "%s";; esac\n' % (root / "homes"))
            env = env_for(root, bin_dir, root / "ignored")
            del env["HERMES_HOME"]
            run("--skip-browser", "--skip-services", "--non-interactive", "--hermes-home", str(flagged), env=env, check=False)
            self.assertEqual(set((root / "homes").read_text().split()), {str(flagged)})


class HermesVersionTests(unittest.TestCase):
    def run_with_version(self, version):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        home.mkdir()
        bin_dir = tooling(root, root / "log", version=version)
        return run("--verify", env=env_for(root, bin_dir, home), check=False)

    def test_stops_when_hermes_is_older_than_the_plugin_requires(self):
        for version in ("0.21", "0.21.4", "0.20.9"):
            result = self.run_with_version(version)
            self.assertNotEqual(result.returncode, 0, version)
            self.assertIn("older than 0.21.5", result.stdout, version)

    def test_accepts_the_minimum_and_compares_numerically(self):
        for version in ("0.21.5", "0.21.10", "0.22.0", "1.0"):
            self.assertNotIn("older than", self.run_with_version(version).stdout, version)

    def test_minimum_matches_plugin_manifest(self):
        manifest = (ROOT / "alans-way" / "plugin.yaml").read_text(encoding="utf-8")
        required = re.search(r'requires_hermes: ">=([0-9.]+)"', manifest).group(1)
        self.assertRegex((ROOT / "setup.sh").read_text(encoding="utf-8"), rf'MIN_HERMES="{re.escape(required)}"')


class ProfileScopeTests(unittest.TestCase):
    def test_every_hermes_call_is_scoped_to_the_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            (home / "profiles" / "delta").mkdir(parents=True)
            log = root / "log"
            bin_dir = tooling(root, log)
            run("--profile", "delta", "--bot-id", "111222333", "--skip-browser", "--skip-services",
                "--non-interactive", "--restart", "--hermes-home", str(home),
                env=env_for(root, bin_dir, home, ALANS_WAY_RESTART_DELAY="0"))
            time.sleep(1)
            calls = [line for line in read_log(log).splitlines() if not line.startswith("--version")]
            self.assertTrue(any("plugins install" in line for line in calls))
            self.assertTrue(any("tools enable proactivity" in line for line in calls))
            self.assertTrue(any("gateway restart" in line for line in calls))
            for line in calls:
                self.assertTrue(line.startswith("-p delta "), line)

    def test_without_a_profile_every_call_pins_the_default_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            log = root / "log"
            bin_dir = tooling(root, log)
            run("--bot-id", "111222333", "--skip-browser", "--skip-services", "--non-interactive",
                "--hermes-home", str(home), env=env_for(root, bin_dir, home))
            calls = [line for line in read_log(log).splitlines() if not line.startswith("--version")]
            self.assertTrue(calls)
            for line in calls:
                self.assertTrue(line.startswith("-p default "), line)

    def test_catalog_provenance_is_read_from_the_profile_plugins_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            plugins = home / "profiles" / "delta" / "plugins"
            (plugins / "alans-way").mkdir(parents=True)
            (plugins / ".install-metadata.json").write_text(
                '{"alans-way": {"source": "catalog", "catalog": {"name": "alans-way", "sha": "3a74614"}}}',
                encoding="utf-8")
            log = root / "log"
            bin_dir = tooling(root, log)
            result = run("--profile", "delta", "--skip-browser", "--skip-services", "--non-interactive",
                         env=env_for(root, bin_dir, home), check=False)
            self.assertIn("leaving its pin in place", result.stdout)
            self.assertNotIn("plugins install", read_log(log))


class RestartOrderTests(unittest.TestCase):
    def test_restart_is_last_and_detached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            (home / "profiles" / "delta").mkdir(parents=True)
            (home / "sessions").mkdir()
            (home / "sessions" / "sessions.json").write_text(
                '{"agent:delta:telegram:dm:1": {"platform": "telegram", "chat_type": "dm"}}', encoding="utf-8")
            log = root / "log"
            bin_dir = tooling(root, log)
            result = run("--profile", "delta", "--bind", "--timezone", "Europe/Berlin", "--restart",
                          "--non-interactive", "--skip-browser", "--skip-services", "--hermes-home", str(home),
                          env=env_for(root, bin_dir, home, ALANS_WAY_RESTART_DELAY="3"))
            self.assertNotIn("gateway restart", read_log(log), "restart must not run before setup.sh returns")
            deadline = time.time() + 15
            while "gateway restart" not in read_log(log) and time.time() < deadline:
                time.sleep(0.2)
            calls = read_log(log).splitlines()
            self.assertIn("gateway restart", calls[-1])
            for needed in ("proactivity bind", "plugins list"):
                self.assertTrue(any(needed in line for line in calls[:-1]), needed)
            self.assertTrue(any("proactivity bind --session-key agent:delta:telegram:dm:1 --timezone Europe/Berlin" in line
                                for line in calls), calls)
            self.assertLess(result.stdout.index("== Done"), result.stdout.index("Restarting the gateway"))
            self.assertTrue(result.stdout.rstrip().splitlines()[-1].lstrip().startswith("Restarting"))

    def test_no_restart_without_the_flag_or_a_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            log = root / "log"
            bin_dir = tooling(root, log)
            run("--skip-browser", "--skip-services", "--non-interactive", env=env_for(root, bin_dir, home, ALANS_WAY_RESTART_DELAY="0"))
            time.sleep(1)
            self.assertNotIn("gateway restart", read_log(log))


class StockBrowserTests(unittest.TestCase):
    def setup_run(self, *flags):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        home.mkdir()
        log = root / "log"
        bin_dir = tooling(root, log)
        result = run("--bot-id", "111222333", "--skip-browser", "--skip-services", "--non-interactive",
                     *flags, env=env_for(root, bin_dir, home), check=False)
        return result, read_log(log)

    def test_disables_the_stock_browser_and_says_so(self):
        result, calls = self.setup_run()
        self.assertIn("tools disable browser --platform telegram", calls)
        self.assertIn("tools disable browser --platform cron", calls)
        self.assertIn("built-in browser toolset disabled for telegram", result.stdout)
        self.assertIn("built-in browser toolset disabled for cron", result.stdout)
        self.assertIn("--keep-browser", result.stdout)

    def test_keep_browser_opts_out(self):
        result, calls = self.setup_run("--keep-browser")
        self.assertNotIn("tools disable browser", calls)
        self.assertIn("keeping the built-in browser toolset", result.stdout)

    def test_not_disabled_when_the_workspace_browser_was_not_configured(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        home.mkdir()
        log = root / "log"
        bin_dir = tooling(root, log)
        run("--skip-browser", "--skip-services", "--non-interactive", env=env_for(root, bin_dir, home), check=False)
        self.assertNotIn("tools disable browser", read_log(log))

    def test_verify_does_not_warn_under_keep_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            bin_dir = tooling(root, root / "log")
            fake(bin_dir, "hermes", '[ "$1" = -p ] && shift 2\ncase "$1" in --version) echo "hermes 0.21.5";; tools) echo "enabled browser"; echo "enabled proactivity";; esac\n')
            kept = run("--verify", "--keep-browser", env=env_for(root, bin_dir, home), check=False)
            self.assertNotIn("built-in 'browser' toolset still enabled", kept.stdout)
            plain = run("--verify", env=env_for(root, bin_dir, home), check=False)
            self.assertIn("built-in 'browser' toolset still enabled", plain.stdout)

    def test_verify_checks_cron_for_the_stock_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            (home / "hooks" / "alans-way").mkdir(parents=True)
            (home / "hooks" / "alans-way" / "handler.py").write_text("# stub\n", encoding="utf-8")
            bin_dir = tooling(root, root / "log")
            fake(bin_dir, "hermes", '[ "$1" = -p ] && shift 2\ncase "$1" in\n'
                 '  --version) echo "hermes 0.21.5";;\n'
                 '  plugins) [ "$2" = list ] && echo alans-way;;\n'
                 '  tools) [ "$2" = list ] && case "$4" in\n'
                 '    cron) echo "enabled browser"; echo "enabled proactivity";;\n'
                 '    *) echo "enabled proactivity";;\n'
                 '  esac;;\n'
                 'esac\n')
            result = run("--verify", "--skip-browser", env=env_for(root, bin_dir, home), check=False)
            self.assertIn("browser' toolset still enabled for cron", result.stdout)
            self.assertIn("browser toolset disabled for telegram", result.stdout)


class HostAddressTests(unittest.TestCase):
    def attempt(self, address, *flags, tailscale=TAILSCALE_UP):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        home.mkdir()
        bin_dir = tooling(root, root / "log")
        fake(bin_dir, "tailscale", tailscale)
        fake(bin_dir, "ssh", 'printf "%%s\\n" "ssh $*" >> "%s"; cat >/dev/null 2>&1 </dev/null; exit 0\n' % (root / "ssh.log"))
        fake(bin_dir, "scp", 'printf "%%s\\n" "scp $*" >> "%s"; exit 0\n' % (root / "ssh.log"))
        result = run("--bot-id", "111222333", "--mac-ssh", address, "--skip-browser", "--skip-services",
                     "--non-interactive", *flags, env=env_for(root, bin_dir, home), check=False)
        return result

    def test_malformed_addresses_are_rejected_before_any_work(self):
        for address in ("-oProxyCommand=touch /tmp/x", "-me@mac.ts.net", "me@mac host.ts.net", "me@mac;ls.ts.net",
                        "@mac.ts.net", "me@", "me@@mac.ts.net", "me@mac$(id).ts.net"):
            result = self.attempt(address)
            self.assertEqual(result.returncode, 2, address)
            self.assertIn("invalid --mac-ssh", result.stderr, address)
            self.assertNotIn("== Plugin", result.stdout, address)

    def test_tailnet_addresses_are_accepted(self):
        for address in ("me@" + tailnet_ip(101, 102, 103), tailnet_ip(64, 0, 1), "me@" + tailnet_ip(127, 255, 254),
                        "me@mac.tail1234.ts.net",
                        "me@fd7a:115c:a1e0::5", "me@FD7A:115C:A1E0:ab12::1", "me@mymac", "me@MyMac"):
            result = self.attempt(address)
            self.assertNotIn("not a Tailscale address", result.stdout + result.stderr, address)
            self.assertIn("Tailscale", result.stdout, address)

    def test_public_and_lan_addresses_are_refused_in_plain_english(self):
        for address in ("me@203.0.113.7", "me@" + tailnet_ip(63, 0, 1), "me@" + tailnet_ip(128, 0, 1), "me@example.com",
                        "me@" + ".".join(["192", "168", "1", "20"]), "me@someothername", "me@fd7b:115c:a1e0::1"):
            result = self.attempt(address)
            self.assertNotEqual(result.returncode, 0, address)
            text = result.stdout + result.stderr
            self.assertIn("not a Tailscale address", text, address)
            self.assertIn("https://tailscale.com/download", text, address)
            self.assertNotIn("== Plugin", result.stdout, address)

    def test_refuses_when_tailscale_is_not_running_on_this_machine(self):
        stopped = 'case "$1" in status) echo \'{"BackendState":"Stopped"}\';; esac\nexit 0\n'
        result = self.attempt("me@mac.tail1234.ts.net", tailscale=stopped)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Tailscale is not running", result.stdout + result.stderr)


class HostCopyTests(unittest.TestCase):
    def setup_run(self, host_os, host="me@mac.tail1234.ts.net"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        home.mkdir()
        app = desktop_tree(root / "app")
        log = root / "log"
        ssh_log = root / "ssh.log"
        bin_dir = tooling(root, log)
        fake(bin_dir, "ssh", 'printf "%%s\\n" "ssh $*" >> "%s"\ncase "$*" in *"tar -xf -"*) cat > "%s/$$.tar";; *) cat >/dev/null 2>&1;; esac\nexit 0\n' % (ssh_log, root))
        fake(bin_dir, "scp", 'printf "%%s\\n" "scp $*" >> "%s"; exit 0\n' % ssh_log)
        run("--bot-id", "111222333", "--mac-ssh", host, "--host-os", host_os, "--desktop-dir", str(app),
            "--skip-services", "--non-interactive", "--hermes-home", str(home),
            env=env_for(root, bin_dir, home), check=False)
        self.root = root
        return read_log(ssh_log)

    def archives(self):
        names = []
        for archive in self.root.glob("*.tar"):
            names += subprocess.run(["tar", "-tf", str(archive)], capture_output=True, text=True).stdout.split()
        return names

    def test_every_ssh_and_scp_call_ends_options_before_the_host(self):
        for host_os in ("mac", "linux", "windows"):
            calls = self.setup_run(host_os)
            self.assertTrue(calls, host_os)
            for line in calls.splitlines():
                self.assertIn(" -- ", line, line)
                self.assertLess(line.index(" -- "), line.index("me@mac.tail1234.ts.net"), line)

    def test_scp_never_receives_a_remote_path_with_a_space(self):
        for host_os in ("mac", "linux", "windows"):
            calls = self.setup_run(host_os)
            for line in calls.splitlines():
                if line.startswith("scp "):
                    remote = [word for word in line.split() if word.startswith("me@")]
                    self.assertTrue(all(" " not in word for word in remote), line)
                    self.assertNotIn("Application Support", line)
                    self.assertNotIn("Hermes Workspace", line)

    def test_mac_connector_is_shipped_as_one_tar_stream(self):
        calls = self.setup_run("mac")
        self.assertNotIn("scp ", calls)
        self.assertIn("Library/Application Support/Hermes Workspace", calls)
        self.assertIn("connector/scripts/browser-mcp.cjs", " ".join(self.archives()))
        self.assertIn("connector/src/computer.cjs", " ".join(self.archives()))
        self.assertIn("npm ci --omit=dev --ignore-scripts", calls)

    def test_linux_host_gets_the_connector_and_its_dependencies(self):
        calls = self.setup_run("linux")
        archive = " ".join(self.archives())
        self.assertIn("connector/scripts/browser-mcp.cjs", archive)
        self.assertIn("connector/package-lock.json", archive)
        self.assertNotIn("mac-computer.swift", archive)
        self.assertIn("Hermes Workspace/connector", calls)
        self.assertIn("npm ci --omit=dev --ignore-scripts", calls)
        self.assertNotIn("swiftc", calls)

    def test_windows_connector_is_staged_without_spaces_then_moved_remotely(self):
        calls = self.setup_run("windows")
        self.assertIn("scp ", calls)
        self.assertIn("Copy-Item", calls)
        self.assertIn("Hermes Workspace", calls)
        self.assertNotIn("tar -xf", calls)


class HostKeyTests(unittest.TestCase):
    KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGWj8Wb1mYxlC0oS1U3cOQ0f1qVv7xH3m5T1kZ4r0w2L me@mac"
    HOST_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOoO8Wb1mYxlC0oS1U3cOQ0f1qVv7xH3m5T1kZ4r0w2M"

    def attempt(self, *flags):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        home = self.root / "home"
        home.mkdir()
        bin_dir = tooling(self.root, self.root / "log")
        fake(bin_dir, "ssh", "cat >/dev/null 2>&1 </dev/null; exit 0\n")
        result = run("--bot-id", "111222333", "--mac-ssh", "me@mac.tail1234.ts.net", "--skip-browser",
                     "--skip-services", "--non-interactive", "--hermes-home", str(home), *flags,
                     env=env_for(self.root, bin_dir, home), check=False)
        return result

    def test_valid_keys_are_appended_once(self):
        for _ in range(2):
            result = self.attempt("--mac-key", self.KEY, "--mac-host-key", self.HOST_KEY)
        ssh = self.root / ".ssh"
        self.assertEqual((ssh / "authorized_keys").read_text().splitlines(), [self.KEY])
        self.assertEqual((ssh / "known_hosts").read_text().splitlines(), ["mac.tail1234.ts.net " + self.HOST_KEY])
        self.assertEqual(oct((ssh / "authorized_keys").stat().st_mode & 0o777), oct(0o600))

    def test_anything_but_a_public_key_line_is_rejected_untouched(self):
        for bad in ('command="touch /tmp/x" ' + self.KEY, self.KEY + "\nssh-rsa AAAA", "not a key",
                    "ssh-ed25519", "ssh-ed25519 !!!notbase64", "ssh-dss AAAAB3NzaC1kc3MAAACB"):
            result = self.attempt("--mac-key", bad)
            self.assertEqual(result.returncode, 2, repr(bad))
            self.assertIn("invalid --mac-key", result.stderr)
            self.assertFalse((self.root / ".ssh" / "authorized_keys").exists())
        result = self.attempt("--mac-host-key", "mac.tail1234.ts.net " + self.HOST_KEY)
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid --mac-host-key", result.stderr)


class BrowserHostServiceTests(unittest.TestCase):
    """Linux guest: simulated on any machine by faking uname, systemctl, id and stat."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.data = self.root / "data"
        self.units = self.root / "units"
        self.units.mkdir()
        self.app = desktop_tree(self.root / "app")
        self.bin_dir = tooling(self.root, self.root / "log")
        self.systemctl_log = self.root / "systemctl.log"
        fake(self.bin_dir, "uname", "echo Linux\n")
        linux_with_systemd(self.bin_dir, self.systemctl_log)
        self.path = [str(self.bin_dir)]

    def run_setup(self, *, root_user=False, owner="alice", browsers=(), snap_browsers=()):
        if root_user:
            fake(self.bin_dir, "id", 'case "$1" in -u) echo 0;; -un) echo root;; *) exec /usr/bin/id "$@";; esac\n')
            fake(self.bin_dir, "stat", "echo %s\n" % owner)
            fake(self.bin_dir, "chown", "exit 0\n")
        for name in browsers:
            fake(self.bin_dir, name, "exit 0\n")
        for name in snap_browsers:
            fake(self.root / "snap" / "bin", name, "exit 0\n")
            self.path.insert(0, str(self.root / "snap" / "bin"))
        env = env_for(self.root, self.bin_dir, self.home, HERMES_VPS_BROWSER_DATA=str(self.data),
                      ALANS_WAY_UNIT_DIR=str(self.units))
        env["PATH"] = os.pathsep.join(self.path + [os.environ["PATH"]])
        env["ALANS_WAY_BROWSER_PATH"] = os.pathsep.join(self.path)
        return run("--skip-plugin", "--desktop-dir", str(self.app), "--non-interactive",
                   "--hermes-home", str(self.home), env=env, check=False)

    def config(self):
        return json.loads((self.data / "config.json").read_text(encoding="utf-8"))

    def test_a_standalone_workspace_skill_that_shadows_the_plugin_is_warned_about(self):
        for skills in (self.home / "skills", self.home / "profiles" / "work" / "skills"):
            (skills / "workspace-operations").mkdir(parents=True)
            (skills / "workspace-operations" / "SKILL.md").write_text("---\nname: workspace-operations\n---\n")
        out = self.run_setup(browsers=("google-chrome",)).stdout
        self.assertIn("warn %s/skills/workspace-operations shadows" % self.home, out)
        self.assertIn("warn %s/profiles/work/skills/workspace-operations shadows" % self.home, out)
        self.assertTrue((self.home / "skills" / "workspace-operations" / "SKILL.md").exists(), "setup only warns; it never deletes")

    def test_non_root_run_needs_no_sandbox_flag_and_no_user_line(self):
        result = self.run_setup(browsers=("google-chrome",))
        self.assertNotIn("--no-sandbox", self.config()["browserArgs"])
        unit = (self.units / "hermes-alans-way-chromium.service").read_text()
        self.assertNotIn("User=root", unit)

    def test_root_owned_hermes_runs_chromium_as_root_with_no_sandbox_and_says_so(self):
        result = self.run_setup(root_user=True, owner="root", browsers=("google-chrome",))
        self.assertIn("--no-sandbox", self.config()["browserArgs"])
        self.assertIn("User=root", (self.units / "hermes-alans-way-chromium.service").read_text())
        self.assertIn("as root", result.stdout)

    def test_root_run_drops_to_the_hermes_home_owner(self):
        self.run_setup(root_user=True, owner="alice", browsers=("google-chrome",))
        self.assertNotIn("--no-sandbox", self.config()["browserArgs"])
        for name in ("hermes-alans-way-chromium.service", "hermes-alans-way-browser.service"):
            self.assertIn("User=alice", (self.units / name).read_text())

    def test_snap_chromium_gets_a_snap_safe_profile_dir(self):
        self.run_setup(snap_browsers=("chromium",))
        args = " ".join(self.config()["browserArgs"])
        self.assertIn("--user-data-dir=%s/snap/chromium/common/" % (self.root), args)

    def test_a_real_chrome_wins_over_snap_chromium(self):
        self.run_setup(browsers=("google-chrome",), snap_browsers=("chromium",))
        config = self.config()
        self.assertTrue(config["browserCommand"].endswith("google-chrome"), config["browserCommand"])
        self.assertIn("--user-data-dir=%s/chromium" % self.data, config["browserArgs"])

    def test_the_packaged_chrome_wins_over_a_bare_google_chrome_wrapper(self):
        # A host image (Orgo) puts a google-chrome wrapper on PATH that adds its
        # own debugging port and profile ahead of ours.
        self.run_setup(browsers=("google-chrome", "google-chrome-stable"))
        config = self.config()
        self.assertTrue(config["browserCommand"].endswith("google-chrome-stable"), config["browserCommand"])

    def test_args_match_the_exec_deploy_example(self):
        self.run_setup(browsers=("google-chrome",))
        example = json.loads((ROOT / "deploy" / "browser-exec-config.json").read_text())
        for flag in ("--no-first-run", "--disable-dev-shm-usage", "--ozone-platform=x11"):
            self.assertIn(flag, example["browserArgs"])
            self.assertIn(flag, self.config()["browserArgs"])

    def test_upgrade_rewrites_a_stale_unit_and_config_and_reloads_systemd(self):
        self.run_setup(browsers=("google-chrome",))
        stale = "[Service]\nExecStart=/usr/bin/node /old/path/vps-chromium-host.cjs\n"
        for name in ("hermes-alans-way-chromium.service", "hermes-alans-way-browser.service"):
            (self.units / name).write_text(stale, encoding="utf-8")
        (self.data / "config.json").write_text('{"browserCommand": "/old/chromium"}', encoding="utf-8")
        self.systemctl_log.write_text("")
        self.run_setup()
        unit = (self.units / "hermes-alans-way-chromium.service").read_text()
        self.assertNotIn("/old/path", unit)
        self.assertIn(str(self.app), unit)
        self.assertNotEqual(self.config().get("browserCommand"), "/old/chromium")
        self.assertTrue((self.data / "config.json.bak").exists())
        self.assertIn("daemon-reload", self.systemctl_log.read_text())

    def test_unchanged_files_are_not_rewritten_or_restarted(self):
        self.run_setup(browsers=("google-chrome",))
        self.systemctl_log.write_text("")
        before = (self.units / "hermes-alans-way-chromium.service").stat().st_mtime_ns
        self.run_setup()
        self.assertEqual((self.units / "hermes-alans-way-chromium.service").stat().st_mtime_ns, before)
        self.assertNotIn("restart", self.systemctl_log.read_text())


class DeployExampleTests(unittest.TestCase):
    def test_watcher_example_runs_the_router_directly(self):
        unit = (ROOT / "deploy" / "mac-watch.service").read_text(encoding="utf-8")
        self.assertRegex(unit, r"ExecStart=/usr/bin/node \S+/workspace-router\.cjs --watch --interval 10")

    def test_exec_example_avoids_root_and_snap(self):
        config = json.loads((ROOT / "deploy" / "browser-exec-config.json").read_text(encoding="utf-8"))
        self.assertNotIn("/snap/", config["browserCommand"])
        self.assertFalse(any("/root/" in arg for arg in config["browserArgs"]))
        self.assertNotIn("--no-sandbox", config["browserArgs"])
        unit = (ROOT / "deploy" / "browser-exec-chromium.service").read_text(encoding="utf-8")
        self.assertNotIn("User=root", unit)
        self.assertNotIn("/root/", unit)


class ReadmeTests(unittest.TestCase):
    def test_readme_states_the_real_requirements_and_layout(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("Node 18", readme)
        self.assertIn("Node 22", readme)
        self.assertIn("0.21.5", readme)


class HostTimezoneTests(unittest.TestCase):
    """The proactivity timezone comes from the user's computer, read over ssh."""

    def attempt(self, host_os, replies, *flags):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        (home / "sessions").mkdir(parents=True)
        (home / "sessions" / "sessions.json").write_text(
            '{"agent:main:telegram:dm:1": {"platform": "telegram", "chat_type": "dm"}}', encoding="utf-8")
        log = root / "log"
        self.ssh_log = root / "ssh.log"
        bin_dir = tooling(root, log)
        arms = "".join('  *"%s"*) echo "%s";;\n' % (needle, reply) for needle, reply in replies.items())
        fake(bin_dir, "ssh", 'printf "%%s\\n" "ssh $*" >> "%s"\ncat >/dev/null 2>&1 </dev/null\ncase "$*" in\n%s  *) ;;\nesac\nexit 0\n' % (self.ssh_log, arms))
        fake(bin_dir, "scp", "exit 0\n")
        result = run("--bind", "--mac-ssh", "me@mac.tail1234.ts.net", "--host-os", host_os, "--skip-browser",
                     "--skip-services", "--non-interactive", "--hermes-home", str(home), *flags,
                     env=env_for(root, bin_dir, home), check=False)
        self.calls = read_log(log)
        return result

    def test_every_host_os_asks_node_for_its_zone(self):
        for host_os in ("mac", "linux", "windows"):
            result = self.attempt(host_os, {"Intl.DateTimeFormat": "Europe/Berlin"})
            self.assertIn("from your computer", result.stdout, host_os)
            self.assertIn("--timezone Europe/Berlin", self.calls, host_os)
        self.assertIn("ELECTRON_RUN_AS_NODE", read_log(self.ssh_log))

    def test_explicit_flag_wins_and_skips_the_ssh_lookup(self):
        self.attempt("mac", {"Intl.DateTimeFormat": "Europe/Berlin"}, "--timezone", "Asia/Tokyo")
        self.assertIn('--timezone Asia/Tokyo', self.calls)
        self.assertNotIn("Intl.DateTimeFormat", read_log(self.ssh_log))

    def test_unusable_answers_are_skipped_with_a_warning(self):
        for reply in ("not a zone!", "../../etc/passwd", "n/a", "Local", ""):
            result = self.attempt("mac", {"Intl.DateTimeFormat": reply})
            self.assertNotIn("from your computer", result.stdout, reply)
            self.assertIn("could not read your computer's timezone", result.stdout, reply)
            self.assertNotIn("--timezone", self.calls)


class WatcherServiceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.app = desktop_tree(self.root / "app")
        self.bin_dir = tooling(self.root, self.root / "log")
        fake(self.bin_dir, "ssh", "cat >/dev/null 2>&1 </dev/null; exit 0\n")
        fake(self.bin_dir, "scp", "exit 0\n")

    def run_setup(self, guest, **env_extra):
        fake(self.bin_dir, "uname", "echo %s\n" % guest)
        env = env_for(self.root, self.bin_dir, self.home, **env_extra)
        return run("--skip-plugin", "--mac-ssh", "me@mac.tail1234.ts.net", "--host-os", "linux",
                   "--desktop-dir", str(self.app), "--non-interactive", "--hermes-home", str(self.home),
                   env=env, check=False)

    def linux_root(self):
        linux_with_systemd(self.bin_dir, self.root / "systemctl.log")
        fake(self.bin_dir, "id", 'case "$1" in -u) echo 0;; -un) echo root;; *) exec /usr/bin/id "$@";; esac\n')
        fake(self.bin_dir, "stat", "echo alice\n")
        fake(self.bin_dir, "chown", "exit 0\n")
        fake(self.bin_dir, "chromium-browser", "exit 0\n")
        self.units, self.etc = self.root / "units", self.root / "etc"
        return dict(ALANS_WAY_UNIT_DIR=str(self.units), ALANS_WAY_ENV_DIR=str(self.etc),
                    HERMES_VPS_BROWSER_DATA=str(self.root / "data"))

    def test_systemd_units_for_the_watcher_and_the_broker(self):
        self.run_setup("Linux", **self.linux_root())
        watch = (self.units / "mac-watch.service").read_text()
        self.assertIn("--interval 10", watch)
        self.assertNotIn("--interval 30", watch)
        self.assertIn("RestartPreventExitStatus=2", watch)
        self.assertRegex(watch, r"ExecStart=\S*node \S+/alans-way/scripts/workspace-router\.cjs --watch --interval 10")
        self.assertNotIn("mac-watch.sh", watch)
        self.assertRegex(watch, r"Environment=PATH=\S*:/usr/bin")
        env = (self.etc / "mac-watch.env").read_text()
        self.assertIn("HERMES_WORKSPACE_MAC_SSH=me@mac.tail1234.ts.net", env)
        self.assertIn("HERMES_WORKSPACE_HOST_OS=linux", env)
        self.assertIn("RestartPreventExitStatus=78", (self.units / "hermes-alans-way-browser.service").read_text())
        self.assertNotIn("RestartPreventExitStatus", (self.units / "hermes-alans-way-chromium.service").read_text())

    def test_a_stale_watcher_unit_and_env_are_regenerated(self):
        env = self.linux_root()
        self.run_setup("Linux", **env)
        (self.units / "mac-watch.service").write_text("[Service]\nExecStart=/bin/sh /old/mac-watch.sh --interval 30\n")
        (self.etc / "mac-watch.env").write_text("HERMES_WORKSPACE_MAC_SSH=old@host\n")
        self.run_setup("Linux", **env)
        self.assertIn("--interval 10", (self.units / "mac-watch.service").read_text())
        self.assertIn("HOST_OS=linux", (self.etc / "mac-watch.env").read_text())

    def test_launch_agent_carries_host_os_path_and_the_fast_interval(self):
        fake(self.bin_dir, "launchctl", "exit 0\n")
        self.run_setup("Darwin")
        plist = (self.root / "Library" / "LaunchAgents" / "com.alans-way.mac-watch.plist").read_text()
        self.assertIn("<string>10</string>", plist)
        self.assertNotIn("<string>30</string>", plist)
        self.assertRegex(plist, r"<string>[^<]*/alans-way/scripts/workspace-router\.cjs</string>\s*<string>--watch</string>")
        self.assertNotIn("mac-watch.sh", plist)
        self.assertRegex(plist, r"<key>HERMES_WORKSPACE_HOST_OS</key>\s*<string>linux</string>")
        self.assertRegex(plist, r"<key>PATH</key>\s*<string>[^<]*%s[^<]*</string>" % re.escape(str(Path(shutil.which("node")).parent)))

    def test_overseer_bot_ids_survive_a_rerun_without_the_env(self):
        # The systemd path must preserve HERMES_OVERSEER_BOT_IDS the way the
        # supervisord conf does: a re-run without the variable keeps the
        # value the first run wrote, instead of silently dropping it.
        env = self.linux_root()
        self.run_setup("Linux", HERMES_OVERSEER_BOT_IDS="4242", **env)
        unit = self.units / "hermes-alans-way-browser.service"
        self.assertIn('Environment=HERMES_OVERSEER_BOT_IDS="4242"', unit.read_text())
        self.run_setup("Linux", **env)
        self.assertIn('Environment=HERMES_OVERSEER_BOT_IDS="4242"', unit.read_text())

    def test_an_unquoted_overseer_value_in_an_existing_unit_is_kept_and_quoted(self):
        # Units written before the value was quoted carry a bare
        # `Environment=HERMES_OVERSEER_BOT_IDS=...`; the read-back keeps the
        # value and the rewrite quotes it (a space-separated list would
        # otherwise parse as stray tokens).
        env = self.linux_root()
        self.units.mkdir(parents=True)
        (self.units / "hermes-alans-way-browser.service").write_text(
            "[Service]\nEnvironment=HERMES_OVERSEER_BOT_IDS=777\n", encoding="utf-8")
        self.run_setup("Linux", **env)
        self.assertIn('Environment=HERMES_OVERSEER_BOT_IDS="777"',
                      (self.units / "hermes-alans-way-browser.service").read_text())

    def test_the_watcher_and_the_managed_block_run_the_installed_plugin_copy(self):
        # With a catalog install the router Hermes loaded lives in the
        # profile's plugins dir, not in this clone: services and the managed
        # block must point there so the reviewed pin stays the only code that
        # runs. The same holds under --skip-plugin.
        plugins = self.home / "plugins"
        catalog = plugins / "alans-way" / "scripts"
        catalog.mkdir(parents=True)
        router = catalog / "workspace-router.cjs"
        router.write_text("// catalog copy\n", encoding="utf-8")
        (plugins / ".install-metadata.json").write_text(
            '{"alans-way": {"catalog": {"name": "alans-way", "sha": "3a74614"}}}', encoding="utf-8")
        clone_router = ROOT / "alans-way" / "scripts" / "workspace-router.cjs"
        fake(self.bin_dir, "uname", "echo Linux\n")
        env = env_for(self.root, self.bin_dir, self.home, **self.linux_root())
        self.assertEqual(
            run("--bot-id", "111222333", "--mac-ssh", "me@mac.tail1234.ts.net",
                "--host-os", "linux", "--desktop-dir", str(self.app), "--non-interactive",
                "--hermes-home", str(self.home), env=env, check=False).returncode, 0)
        self.assertIn(str(router), (self.units / "mac-watch.service").read_text())
        block = (self.home / "config.yaml").read_text()
        self.assertIn(str(router), block)
        self.assertNotIn(str(clone_router), block)

    def test_the_watcher_falls_back_to_the_clone_when_no_catalog_copy_exists(self):
        self.run_setup("Linux", **self.linux_root())
        watch = (self.units / "mac-watch.service").read_text()
        self.assertIn(str(ROOT / "alans-way" / "scripts" / "workspace-router.cjs"), watch)

    def test_a_non_catalog_install_still_prefers_the_installed_router(self):
        # A plugin installed from a checkout (file://, no catalog metadata)
        # still lands its own workspace-router.cjs in the profile's plugins
        # dir. That installed copy wins: the checkout may be a temp directory
        # (issue #63).
        plugins = self.home / "plugins"
        router = plugins / "alans-way" / "scripts" / "workspace-router.cjs"
        router.parent.mkdir(parents=True)
        router.write_text("// installed copy\n", encoding="utf-8")
        fake(self.bin_dir, "uname", "echo Linux\n")
        env = env_for(self.root, self.bin_dir, self.home, **self.linux_root())
        self.assertEqual(
            run("--bot-id", "111222333", "--mac-ssh", "me@mac.tail1234.ts.net",
                "--host-os", "linux", "--desktop-dir", str(self.app), "--non-interactive",
                "--hermes-home", str(self.home), env=env, check=False).returncode, 0)
        watch = (self.units / "mac-watch.service").read_text()
        self.assertIn(str(router), watch)
        block = (self.home / "config.yaml").read_text()
        self.assertIn(str(router), block)
        self.assertNotIn(str(ROOT / "alans-way" / "scripts" / "workspace-router.cjs"), block)


FAKE_POWERSHELL = r"""script="$(cat)"
printf '%s\n----\n' "$script" >> "$PS_LOG"
case "$script" in
  *Get-Service*) echo "${FAKE_SSHD:-running user shell-ps}";;
  *) if [ -n "${AW_TASK:-}" ]; then
       reg="$PS_STATE/$AW_TASK"; new="$AW_EXE|$AW_ARGS"
       mkdir -p "$PS_STATE"
       if [ -f "$reg" ] && [ "$(cat "$reg")" = "$new" ]; then echo unchanged
       elif [ -f "$reg" ]; then printf '%s' "$new" > "$reg"; echo updated
       else printf '%s' "$new" > "$reg"; echo registered; fi
     fi;;
esac
exit 0
"""


class WindowsGuestSetupTests(unittest.TestCase):
    """Git Bash on a native-Windows Hermes box, simulated with a fake uname, cygpath, powershell and exes."""

    HOST = "me@mac.tail1234.ts.net"

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home"
        self.local = self.root / "Local"
        self.programs = self.root / "Program Files"
        self.system_root = self.root / "Windows"
        self.program_data = self.root / "ProgramData"
        for path in (self.home, self.local):
            path.mkdir()
        self.app = desktop_tree(self.root / "app")
        self.log = self.root / "hermes.log"
        self.ps_log = self.root / "powershell.log"
        self.ps_state = self.root / "tasks"
        self.bin_dir = logging_hermes_bin(self.root, self.log)
        fake(self.bin_dir, "uname", "echo MINGW64_NT-10.0-26100\n")
        fake(self.bin_dir, "cygpath", 'echo "$*" >> "%s"\ncase "$1" in\n'
             '  -m) case "$2" in "$FAKE_PREFIXED"*) printf "C:%%s" "$2";; */tmp.*) [ -d "$2" ] && printf "C:%%s" "$2" || printf "%%s" "$2";; *) printf "%%s" "$2";; esac;;\n'
             '  -w) printf "W:%%s" "$2" | tr / "\\\\";;\n  *) printf "%%s" "$2";;\nesac\n' % (self.root / "cygpath.log"))
        fake(self.bin_dir, "powershell", FAKE_POWERSHELL)
        fake(self.bin_dir, "ssh", 'echo path-ssh >> "%s"\nexit 0\n' % (self.root / "ssh.log"))
        fake(self.bin_dir, "runuser", 'echo "$*" >> "%s"\nexit 1\n' % (self.root / "runuser.log"))
        fake(self.bin_dir, "icacls", 'echo "$*" >> "%s"\n' % (self.root / "icacls.log"))
        self.native = self.system_root / "System32" / "OpenSSH"
        self.exe(self.native / "ssh.exe", 'echo "ssh $*" >> "%s"\ncat >/dev/null 2>&1 </dev/null\nexit 0\n' % (self.root / "native.log"))
        self.exe(self.native / "scp.exe", 'echo "scp $*" >> "%s"\nexit 0\n' % (self.root / "native.log"))
        self.exe(self.programs / "Tailscale" / "tailscale.exe", TAILSCALE_UP)
        self.chrome = self.programs / "Google" / "Chrome" / "Application" / "chrome.exe"
        self.exe(self.chrome, "exit 0\n")
        self.data = self.home / ".local" / "share" / "hermes-alans-way" / "browser"

    def exe(self, path: Path, body: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def env(self, **extra):
        node = Path(shutil.which("node")).parent
        env = {k: v for k, v in os.environ.items() if k not in ("HERMES_HOME", "WSL_DISTRO_NAME")}
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), USERNAME="winuser", LOCALAPPDATA=str(self.local),
                   PROGRAMFILES=str(self.programs), PROGRAMDATA=str(self.program_data), SYSTEMROOT=str(self.system_root),
                   PS_LOG=str(self.ps_log), PS_STATE=str(self.ps_state),
                   FAKE_PREFIXED=str(ROOT), ALANS_WAY_RESTART_DELAY="3",
                   PATH=os.pathsep.join([str(self.bin_dir), str(node), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]))
        env.update(extra)
        return env

    def setup(self, *flags, env=None, host=True, host_os="mac"):
        args = ["--skip-plugin", "--desktop-dir", str(self.app), "--bot-id", "111222333", "--non-interactive", *flags]
        if host:
            args += ["--mac-ssh", self.HOST, "--host-os", host_os]
        return run(*args, env=env or self.env(), check=False)

    def tasks(self):
        return {path.name: path.read_text() for path in self.ps_state.glob("*")}

    def test_native_paths_and_no_untested_guest_warning(self):
        result = self.setup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("untested", result.stdout)
        config = (self.local / "hermes" / "config.yaml").read_text()
        self.assertIn('"C:%s/alans-way/scripts/workspace-router.cjs"' % ROOT, config)
        self.assertIn("HERMES_WORKSPACE_HOST_OS", config)
        self.assertNotIn("systemd", result.stdout)

    def test_chrome_is_configured_without_the_linux_only_flags(self):
        self.setup()
        config = json.loads((self.data / "config.json").read_text())
        self.assertEqual(config["browserCommand"], str(self.chrome))
        args = config["browserArgs"]
        self.assertIn("--user-data-dir=%s" % (self.data / "chromium"), args)
        self.assertIn("--remote-debugging-port=9223", args)
        self.assertIn("--no-first-run", args)
        for flag in ("--ozone-platform=x11", "--disable-dev-shm-usage", "--no-sandbox"):
            self.assertNotIn(flag, args)
        self.assertEqual(args[-1], "about:blank")

    def test_edge_is_used_when_no_chrome_is_installed(self):
        self.chrome.unlink()
        edge = Path(str(self.programs) + " (x86)") / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        self.exe(edge, "exit 0\n")
        self.setup()
        self.assertEqual(json.loads((self.data / "config.json").read_text())["browserCommand"], str(edge))

    def test_no_browser_at_all_warns_how_to_install_one(self):
        self.chrome.unlink()
        result = self.setup()
        self.assertIn("winget install Google.Chrome", result.stdout)

    def test_services_are_logon_tasks_that_restart_on_failure(self):
        self.setup()
        tasks = self.tasks()
        self.assertEqual(set(tasks), {"AlansWay_Chromium", "AlansWay_Browser", "AlansWay_MacWatch"})
        scripts = self.ps_log.read_text()
        for needle in ("New-ScheduledTaskTrigger -AtLogOn", "-RestartCount", "-RunLevel Limited", "Register-ScheduledTask",
                       "-ExecutionTimeLimit"):
            self.assertIn(needle, scripts)
        host = tasks["AlansWay_Browser"]
        scripts_dir = r"W:%s\desktop\scripts" % str(self.app).replace("/", "\\")
        self.assertIn("powershell.exe|-NoProfile -WindowStyle Hidden -Command", host)
        self.assertIn("'%s\\vps-browser-host.cjs' serve" % scripts_dir, host)
        self.assertIn("HERMES_VPS_BROWSER_DATA='%s'" % self.data, host)
        self.assertIn("exit $LASTEXITCODE", host)
        self.assertIn("Start-Sleep -Seconds 5; $env:HERMES_VPS_BROWSER_DATA", host)
        self.assertNotIn("Start-Sleep", tasks["AlansWay_Chromium"] + tasks["AlansWay_MacWatch"])
        self.assertIn("'%s\\vps-chromium-host.cjs'" % scripts_dir, tasks["AlansWay_Chromium"])
        watch = tasks["AlansWay_MacWatch"]
        self.assertIn("workspace-router.cjs' --watch --interval 10 --mac-ssh '%s' --host-os 'mac'" % self.HOST, watch)

    def test_no_watcher_task_without_a_host(self):
        self.setup(host=False)
        self.assertEqual(set(self.tasks()), {"AlansWay_Chromium", "AlansWay_Browser"})

    def test_skip_services_registers_nothing(self):
        self.setup("--skip-services")
        self.assertEqual(self.tasks(), {})

    def test_a_second_run_changes_nothing_and_a_moved_checkout_reports_an_update(self):
        self.setup()
        second = self.setup()
        self.assertEqual(second.stdout.count("already current"), 4, second.stdout)
        self.assertNotIn("restarted", second.stdout)
        moved = desktop_tree(self.root / "moved")
        third = run("--skip-plugin", "--desktop-dir", str(moved), "--bot-id", "111222333", "--non-interactive",
                    "--mac-ssh", self.HOST, "--host-os", "mac", env=self.env(), check=False)
        self.assertIn("AlansWay_Browser updated", third.stdout)
        self.assertIn(str(moved).replace("/", "\\"), self.tasks()["AlansWay_Browser"])

    def test_tailscale_is_found_under_program_files_when_it_is_not_on_path(self):
        result = self.setup()
        self.assertIn("is on your tailnet", result.stdout)

    def test_every_host_call_uses_the_native_openssh(self):
        self.setup(host_os="windows")
        self.assertFalse((self.root / "ssh.log").exists(), "an ssh from PATH was used")
        self.assertFalse((self.root / "runuser.log").exists(), "a Windows guest switched users with runuser")
        calls = (self.root / "native.log").read_text()
        self.assertIn("StrictHostKeyChecking=yes", calls)
        self.assertIn("scp -q", calls)

    def test_the_connector_is_staged_with_a_windows_path_for_scp(self):
        self.setup(host_os="windows")
        scp = [line for line in (self.root / "native.log").read_text().splitlines() if line.startswith("scp")]
        self.assertRegex(scp[0], r" -- C:/\S+/tmp\.\w+/connector ")

    def test_the_plugin_installs_from_a_file_url_with_a_drive_path(self):
        run("--desktop-dir", str(self.app), "--bot-id", "111222333", "--non-interactive", "--skip-browser",
            env=self.env(), check=False)
        self.assertIn("file:///C:%s#alans-way" % ROOT, read_log(self.log))

    def test_the_restart_is_a_one_shot_scheduled_task_that_outlives_the_gateway(self):
        result = self.setup("--restart", "--skip-browser")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        task = self.tasks()["AlansWay_GatewayRestart"]
        self.assertIn("Start-Sleep -Seconds 3", task)
        self.assertIn("gateway restart", task)
        self.assertIn("-p 'default'", task)
        self.assertIn("HERMES_HOME='%s'" % (self.local / "hermes"), task)
        self.assertIn("Unregister-ScheduledTask -TaskName 'AlansWay_GatewayRestart'", task)
        self.assertIn("Start-ScheduledTask", self.ps_log.read_text())
        self.assertIn("Restarting the gateway in 3s", result.stdout)

    def test_no_restart_task_without_the_flag(self):
        self.setup("--skip-browser")
        self.assertNotIn("AlansWay_GatewayRestart", self.tasks())

    def test_the_computer_provider_needs_hermes_python_which_is_not_on_path(self):
        result = self.setup("--skip-browser")
        self.assertIn("HERMES_PYTHON", result.stdout)

    def test_a_missing_sshd_says_how_to_install_it(self):
        result = self.setup(env=self.env(FAKE_SSHD="missing"))
        self.assertIn("Add-WindowsCapability", result.stdout)

    def test_a_non_powershell_default_shell_is_flagged(self):
        result = self.setup(env=self.env(FAKE_SSHD="running user shell-other"))
        self.assertIn("DefaultShell", result.stdout)

    def test_an_admin_account_gets_its_key_in_the_administrators_file(self):
        key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHxX8Wb1mYxlC0oS1U3cOQ0f1qVv7xH3m5T1kZ4r0w2P me@mac"
        (self.program_data / "ssh").mkdir(parents=True)
        self.setup("--mac-key", key, env=self.env(FAKE_SSHD="running admin shell-ps"))
        self.assertIn(key, (self.program_data / "ssh" / "administrators_authorized_keys").read_text())
        self.assertIn(key, (self.home / ".ssh" / "authorized_keys").read_text())
        self.assertIn("S-1-5-32-544", (self.root / "icacls.log").read_text())

    def test_a_blocked_task_registration_is_a_warning_not_a_crash(self):
        fake(self.bin_dir, "powershell", 'cat >/dev/null\necho "Register-ScheduledTask : Access is denied."\nexit 1\n')
        result = self.setup()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("could not schedule AlansWay_Browser (group policy may block logon tasks): Register-ScheduledTask : Access is denied.", result.stdout)

    def test_a_store_stub_python3_gives_way_to_a_real_python(self):
        fake(self.bin_dir, "python3", 'echo "Python was not found; run without arguments to install from the Microsoft Store" >&2\nexit 49\n')
        fake(self.bin_dir, "python", 'exec %s "$@"\n' % shutil.which("python3"))
        result = self.setup("--skip-browser")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("FAIL", result.stdout)
        self.assertIn("workspace_browser configured", result.stdout)

    def test_wsl_is_linux_not_native_windows(self):
        fake(self.bin_dir, "uname", "echo Linux\n")
        linux_with_systemd(self.bin_dir, self.root / "systemctl.log")
        fake(self.bin_dir, "tailscale", TAILSCALE_UP)
        result = self.setup(env=self.env(WSL_DISTRO_NAME="Ubuntu", ALANS_WAY_UNIT_DIR=str(self.root / "units")))
        self.assertEqual(self.tasks(), {})
        self.assertFalse(self.ps_log.exists())
        self.assertTrue((self.root / "units" / "hermes-alans-way-browser.service").exists(), result.stdout)


class ProfileLayoutTests(unittest.TestCase):
    """An agent inside a profile gateway sees HERMES_HOME=<root>/profiles/<name>."""

    def layout(self, root: Path, name="work"):
        home = root / "hermes" / "profiles" / name
        plugins = home / "plugins"
        (plugins / "alans-way").mkdir(parents=True)
        (plugins / ".install-metadata.json").write_text(
            '{"alans-way": {"source": "catalog", "catalog": {"name": "alans-way", "sha": "3a74614"}}}',
            encoding="utf-8")
        return home

    def test_a_profile_shaped_home_is_the_profile_not_a_nested_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = self.layout(root)
            log = root / "log"
            bin_dir = tooling(root, log)
            result = run("--skip-browser", "--skip-services", "--non-interactive",
                         env=env_for(root, bin_dir, home), check=False)
            self.assertIn("leaving its pin in place", result.stdout)
            self.assertIn("HERMES_HOME: %s" % (root / "hermes"), result.stdout)
            calls = [line for line in read_log(log).splitlines() if not line.startswith("--version")]
            self.assertFalse(any("plugins install" in line for line in calls), calls)
            for line in calls:
                self.assertTrue(line.startswith("-p work "), line)
            self.assertFalse((home / "profiles").exists())

    def test_an_explicit_profile_wins_over_a_profile_shaped_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = self.layout(root)
            (root / "hermes" / "profiles" / "other").mkdir()
            log = root / "log"
            bin_dir = tooling(root, log)
            run("--profile", "other", "--skip-browser", "--skip-services", "--non-interactive",
                env=env_for(root, bin_dir, home), check=False)
            calls = [line for line in read_log(log).splitlines() if not line.startswith("--version")]
            self.assertTrue(calls)
            for line in calls:
                self.assertTrue(line.startswith("-p other "), line)

    def test_a_bad_profile_name_is_rejected_up_front(self):
        for name in ("../x", "a b", "x;y", "-p"):
            result = run("--profile", name, "--verify", check=False)
            self.assertEqual(result.returncode, 2, name)
            self.assertIn("invalid --profile", result.stderr)


class RestartSurvivalTests(unittest.TestCase):
    def setup_run(self, extra_bins=()):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.log = self.root / "log"
        self.bin_dir = tooling(self.root, self.log)
        return env_for(self.root, self.bin_dir, self.home, ALANS_WAY_RESTART_DELAY="2")

    def wait_for_restart(self, seconds=15):
        deadline = time.time() + seconds
        while "gateway restart" not in read_log(self.log) and time.time() < deadline:
            time.sleep(0.2)
        return "gateway restart" in read_log(self.log)

    def test_the_restarter_outlives_the_session_that_ran_setup(self):
        env = self.setup_run()
        proc = subprocess.Popen(
            [SH, str(SCRIPT), "--restart", "--skip-browser", "--skip-services", "--non-interactive",
             "--hermes-home", str(self.home)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True)
        proc.communicate()
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                pass
        self.assertTrue(self.wait_for_restart(), "the restart died with the session")

    def test_on_a_systemd_guest_the_restart_is_a_transient_unit_outside_the_gateway_cgroup(self):
        env = self.setup_run()
        run_log = self.root / "systemd-run.log"
        fake(self.bin_dir, "uname", "echo Linux\n")
        fake(self.bin_dir, "systemctl", "exit 0\n")
        fake(self.bin_dir, "systemd-run", 'printf "%%s\\n" "$*" >> "%s"\nexit 0\n' % run_log)
        run("--restart", "--skip-browser", "--skip-services", "--non-interactive", "--hermes-home", str(self.home),
            env=env)
        text = run_log.read_text()
        self.assertIn("--collect", text)
        self.assertIn("--on-active=2s", text)
        self.assertIn("--user", text)
        self.assertIn("HERMES_HOME=%s" % self.home, text)
        time.sleep(1)
        self.assertNotIn("gateway restart", read_log(self.log), "must not also restart through the fallback")

    def test_the_restart_log_name_is_not_predictable(self):
        env = self.setup_run()
        env["TMPDIR"] = str(self.root)
        run("--restart", "--skip-browser", "--skip-services", "--non-interactive", "--hermes-home", str(self.home),
            env=env)
        logs = list(self.root.glob("alans-way-gateway-restart.*"))
        self.assertEqual(len(logs), 1)
        self.assertNotEqual(logs[0].name, "alans-way-gateway-restart.log")


class UserSystemdTests(unittest.TestCase):
    def setup_run(self, user_systemd):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        home = self.root / "home"
        home.mkdir()
        app = desktop_tree(self.root / "app")
        bin_dir = tooling(self.root, self.root / "log")
        self.loginctl = self.root / "loginctl.log"
        fake(bin_dir, "uname", "echo Linux\n")
        fake(bin_dir, "google-chrome", "exit 0\n")
        fake(bin_dir, "loginctl", 'printf "%%s\\n" "$*" >> "%s"\nexit 0\n' % self.loginctl)
        fake(bin_dir, "systemctl",
             'case "$*" in\n  is-system-running) echo running;;\n  *--user*) exit %d;;\nesac\nexit 0\n'
             % (0 if user_systemd else 1))
        env = env_for(self.root, bin_dir, home, HERMES_VPS_BROWSER_DATA=str(self.root / "data"))
        return run("--skip-plugin", "--desktop-dir", str(app), "--non-interactive", "--hermes-home", str(home),
                   env=env, check=False)

    def test_no_user_session_warns_and_finishes_instead_of_dying_silently(self):
        result = self.setup_run(user_systemd=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("== Done", result.stdout)
        self.assertRegex(result.stdout, r"warn .*systemd")
        self.assertTrue((self.root / "data" / "config.json").exists())

    def test_user_units_get_lingering_so_they_survive_logout(self):
        self.setup_run(user_systemd=True)
        self.assertIn("enable-linger", self.loginctl.read_text())


class RootOwnedSshFilesTests(unittest.TestCase):
    KEY = HostKeyTests.KEY

    def test_ssh_trust_lands_in_the_hermes_owners_home_and_is_chowned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "root-home"
            owner_home = root / "alice-home"
            home.mkdir(); owner_home.mkdir()
            hermes_home = root / "hermes"
            hermes_home.mkdir()
            chown_log = root / "chown.log"
            bin_dir = tooling(root, root / "log")
            fake(bin_dir, "id", 'case "$1" in -u) echo 0;; -un) echo root;; *) exec /usr/bin/id "$@";; esac\n')
            fake(bin_dir, "stat", "echo alice\n")
            fake(bin_dir, "getent", 'echo "alice:x:1000:1000::%s:/bin/sh"\n' % owner_home)
            fake(bin_dir, "chown", 'printf "%%s\\n" "$*" >> "%s"\n' % chown_log)
            fake(bin_dir, "ssh", "exit 0\n")
            env = dict(env_for(root, bin_dir, hermes_home), HOME=str(home))
            run("--mac-ssh", "me@mac.tail1234.ts.net", "--mac-key", HostKeyTests.KEY, "--mac-host-key",
                HostKeyTests.HOST_KEY, "--skip-browser", "--skip-services", "--non-interactive",
                "--hermes-home", str(hermes_home), env=env, check=False)
            self.assertEqual((owner_home / ".ssh" / "authorized_keys").read_text().strip(), HostKeyTests.KEY)
            self.assertTrue((owner_home / ".ssh" / "known_hosts").exists())
            self.assertFalse((home / ".ssh").exists())
            chowned = chown_log.read_text()
            self.assertIn("alice", chowned)
            self.assertIn(".ssh", chowned)


class KeyTypeTests(unittest.TestCase):
    def test_security_key_types_are_accepted(self):
        blob = "AAAAGnNrLXNzaC1lZDI1NTE5QG9wZW5zc2guY29tAAAAIGWj8Wb1mYxlC0oS1U3cOQ0f1qVv7xH3m5T1kZ4r0w2L"
        for kind in ("sk-ssh-ed25519@openssh.com", "sk-ecdsa-sha2-nistp256@openssh.com"):
            directory = tempfile.TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            root = Path(directory.name)
            home = root / "home"
            home.mkdir()
            bin_dir = tooling(root, root / "log")
            result = run("--mac-key", f"{kind} {blob} me@mac", "--mac-ssh", "me@mac.tail1234.ts.net",
                         "--skip-browser", "--skip-services", "--non-interactive", "--hermes-home", str(home),
                         env=env_for(root, bin_dir, home), check=False)
            self.assertNotEqual(result.returncode, 2, result.stderr)
            self.assertTrue((root / ".ssh" / "authorized_keys").exists(), kind)


def repo_with_computer_plugin(root: Path) -> Path:
    """A throwaway checkout that also carries the (separately developed) provider plugin dir."""
    repo = root / "repo"
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "tests", "__pycache__"))
    (repo / "alans-way-computer").mkdir(exist_ok=True)
    return repo / "setup.sh"


class IntegrationBase:
    def run_setup(self, *flags, tools_fake=None, python_ok=True, config_get="", tools_list=""):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        home = self.root / "home"
        home.mkdir()
        self.home = home
        self.log = self.root / "log"
        bin_dir = tooling(self.root, self.log)
        # `config` is a stateful key store: setup reads back what it wrote, so a
        # `set` must be visible to a later `get` (an unset key returns the
        # test-supplied default, same as before).
        fake(bin_dir, "hermes", 'echo "$*" >> "%s"\n[ "$1" = -p ] && shift 2\ncase "$1" in\n'
             '  --version) echo "hermes 0.21.5";;\n  plugins) [ "$2" = list ] && echo "alans-way";;\n'
             '  tools) [ "$2" = list ] && { echo \'%s\'; };;\n'
             '  config) case "$2" in\n'
             '      set) printf \'%%s=%%s\\n\' "$3" "$4" >> "%s.config";;\n'
             '      get) _v="$(awk -v k="$3" \'index($0, k "=") == 1 { v = substr($0, length(k) + 2) }'
             ' END { printf "%%s", v }\' "%s.config" 2>/dev/null)"; [ -n "$_v" ] && echo "$_v" || echo \'%s\';;\n'
             '    esac;;\nesac\nexit 0\n' % (self.log, tools_list, self.log, self.log, config_get))
        fake(bin_dir, "hermes-python", "exit %d\n" % (0 if python_ok else 1))
        self.env = env_for(self.root, bin_dir, home, HERMES_PYTHON=str(bin_dir / "hermes-python"))
        return run("--bot-id", "111222333", "--skip-browser", "--skip-services", "--non-interactive",
                   "--hermes-home", str(home), *flags, env=self.env, check=False,
                   script=repo_with_computer_plugin(self.root))


class ProactivityIntegrationTests(IntegrationBase, unittest.TestCase):
    def test_the_proactivity_toolset_is_enabled_for_telegram_only(self):
        self.run_setup()
        calls = read_log(self.log)
        self.assertIn("tools enable proactivity --platform telegram", calls)
        self.assertNotIn("tools enable proactivity --platform cron", calls)

    def test_bind_falls_back_to_set_when_bind_rejects_the_timezone_flag(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        (home / "sessions").mkdir(parents=True)
        (home / "sessions" / "sessions.json").write_text(
            '{"agent:main:telegram:dm:1": {"platform": "telegram", "chat_type": "dm"}}', encoding="utf-8")
        log = root / "log"
        bin_dir = tooling(root, log)
        fake(bin_dir, "hermes", 'echo "$*" >> "%s"\n[ "$1" = -p ] && shift 2\ncase "$*" in\n'
             '  "--version") echo "hermes 0.21.5";;\n  "plugins list") echo alans-way;;\n'
             '  "proactivity bind"*"--timezone"*) exit 2;;\nesac\nexit 0\n' % log)
        run("--bind", "--timezone", "Europe/Berlin", "--skip-browser", "--skip-services", "--non-interactive",
            "--hermes-home", str(home), env=env_for(root, bin_dir, home), check=False)
        calls = read_log(log)
        self.assertIn("proactivity bind --session-key agent:main:telegram:dm:1\n", calls)
        self.assertIn("proactivity set --timezone Europe/Berlin", calls)


class ComputerProbeShimTests(unittest.TestCase):
    """Hermes 0.21.5 installs `hermes` as a bash shim around its venv, and ImageMagick's `import` hangs."""

    def run_shim(self, shim_dir_exists=True, probe_timeout=None, venv_ok=True):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        home.mkdir()
        self.log, self.probes = root / "log", root / "probes"
        bin_dir = tooling(root, self.log)
        (bin_dir / "hermes").rename(bin_dir / "hermes-real")
        agent = root / "elsewhere" / "hermes-agent"
        shim = "#!/bin/bash\n"
        if shim_dir_exists:
            (agent / "venv" / "bin").mkdir(parents=True)
            (agent / "venv" / "bin" / "activate").write_text('export PATH="%s:$PATH"\n' % (agent / "venv" / "bin"), encoding="utf-8")
            fake(agent / "venv" / "bin", "python",
                 'case "$1" in\n  -c) echo "$0" >> "%s"; %s;;\n  hermes) shift; exec "%s" "$@";;\nesac\n'
                 % (self.probes, "exit 0" if venv_ok else "sleep 1000", bin_dir / "hermes-real"))
            shim += 'cd %s && source venv/bin/activate && python hermes "$@"\n' % agent
        else:
            shim += 'exec "%s" "$@"\n' % (bin_dir / "hermes-real")
        (bin_dir / "hermes").write_text(shim, encoding="utf-8")
        (bin_dir / "hermes").chmod(0o755)
        fake(bin_dir, "import", 'echo "$0 $*" >> "%s"\nsleep 1000\n' % self.probes)
        extra = {"ALANS_WAY_PROBE_TIMEOUT": probe_timeout} if probe_timeout else {}
        started = time.monotonic()
        result = subprocess.run(
            [SH, str(repo_with_computer_plugin(root)), "--bot-id", "111222333", "--skip-browser", "--skip-services",
             "--non-interactive", "--hermes-home", str(home)],
            capture_output=True, text=True, timeout=60, env=env_for(root, bin_dir, home, **extra))
        self.elapsed = time.monotonic() - started
        self.probe_log = read_log(self.probes)
        return result, agent

    def test_a_bash_shim_is_resolved_to_its_venv_python_and_never_run_as_one(self):
        result, agent = self.run_shim()
        self.assertIn(str(agent / "venv" / "bin" / "python"), self.probe_log)
        self.assertNotIn("import", self.probe_log)
        calls = read_log(self.log)
        self.assertRegex(calls, r"plugins install alans-way-computer\n")
        self.assertNotRegex(calls, r"plugins install[^\n]*file://[^\n]*alans-way-computer")
        self.assertNotRegex(calls, r"plugins install[^\n]*--force[^\n]*alans-way-computer")

    def test_no_python_to_be_found_skips_the_provider_without_running_the_shell(self):
        result, _ = self.run_shim(shim_dir_exists=False)
        self.assertEqual(self.probe_log, "")
        self.assertIn("skip computer-use provider", result.stdout)

    def test_a_hung_probe_is_killed_and_the_provider_skipped_with_a_warning(self):
        result, _ = self.run_shim(probe_timeout="2", venv_ok=False)
        self.assertLess(self.elapsed, 30)
        self.assertIn("timed out", result.stdout + result.stderr)
        self.assertNotIn("alans-way-computer", read_log(self.log))


class ComputerProviderTests(IntegrationBase, unittest.TestCase):
    def test_installed_per_profile_and_selected_when_hermes_has_the_provider_api(self):
        self.run_setup("--profile", "work", python_ok=True)
        calls = read_log(self.log)
        self.assertIn("-p work plugins install alans-way-computer\n", calls)
        self.assertNotRegex(calls, r"plugins install[^\n]*alans-way-computer[^\n]*--force")
        self.assertNotRegex(calls, r"plugins install[^\n]*file://[^\n]*alans-way-computer")
        self.assertIn("-p work plugins enable alans-way-computer", calls)
        self.assertIn("-p work config set computer_use.backend alans-way-computer", calls)
        self.assertLess(calls.index("plugins install alans-way-computer"), calls.index("computer_use.backend"))

    def test_the_dev_flag_installs_the_provider_from_the_clone(self):
        result = self.run_setup("--dev-plugin-install", python_ok=True)
        calls = read_log(self.log)
        self.assertRegex(calls, r"-p default plugins install --force file://\S+#alans-way-computer\n")
        self.assertIn("computer-use provider installed from", result.stdout)

    def test_skip_plugin_skips_the_provider_install_entirely(self):
        result = self.run_setup("--skip-plugin", python_ok=True)
        calls = read_log(self.log)
        self.assertNotIn("alans-way-computer", calls)
        self.assertIn("computer-use provider (--skip-plugin", result.stdout)
        self.assertNotIn("config set computer_use.backend", calls)

    def test_without_the_provider_api_the_stock_computer_use_toolset_is_left_on(self):
        result = self.run_setup(python_ok=False)
        calls = read_log(self.log)
        self.assertNotIn("tools disable computer_use", calls)
        # The managed block keeps the ungated desktop-input tool out.
        config = (self.home / "config.yaml").read_text()
        self.assertIn("- workspace_computer_action", config)
        self.assertNotIn("HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS", config)

    def test_allow_desktop_actions_opts_in_the_raw_tool_only_without_the_provider_api(self):
        result = self.run_setup("--allow-desktop-actions", python_ok=False)
        config = (self.home / "config.yaml").read_text()
        self.assertNotIn("exclude:\n        - workspace_computer_action", config)
        self.assertIn('HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS: "1"', config)
        self.assertIn("command_allowlist", read_log(self.log))
        # With the provider API the flag only seeds the allowlist: the
        # ungated tool stays excluded.
        result = self.run_setup("--allow-desktop-actions", python_ok=True)
        config = (self.home / "config.yaml").read_text()
        self.assertIn("- workspace_computer_action", config)
        self.assertNotIn("HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS", config)

    def test_with_the_provider_api_the_toolset_is_left_to_the_provider(self):
        self.run_setup(python_ok=True)
        calls = read_log(self.log)
        self.assertNotIn("tools disable computer_use", calls)
        # An older setup that disabled the gated toolset is repaired so the
        # provider's desktop input path is live.
        self.assertIn("-p default tools enable computer_use --platform telegram\n", calls)
        self.assertIn("-p default tools enable computer_use --platform cron\n", calls)

    def test_keep_computer_use_is_a_deprecated_noop(self):
        result = self.run_setup("--keep-computer-use", python_ok=False)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("tools disable computer_use", read_log(self.log))

    def test_an_older_setups_disabled_computer_use_is_reenabled_without_the_provider_api(self):
        result = self.run_setup(python_ok=False, tools_list="disabled computer_use")
        calls = read_log(self.log)
        self.assertIn("tools enable computer_use --platform telegram\n", calls)
        self.assertIn("tools enable computer_use --platform cron\n", calls)
        self.assertIn("re-enabled computer_use for telegram (turn it off with:"
                      " hermes tools disable computer_use --platform telegram)", result.stdout)
        self.assertIn("re-enabled computer_use for cron", result.stdout)

    def test_an_enabled_computer_use_is_left_alone_without_the_provider_api(self):
        self.run_setup(python_ok=False, tools_list="enabled computer_use")
        self.assertNotIn("tools enable computer_use", read_log(self.log))
        self.assertFalse((self.home / ".alans-way-computer-use-restored").exists())

    def test_the_reenable_runs_once_so_a_users_later_disable_sticks(self):
        # Nothing records whose `tools disable` it was, so the repair fires once
        # per platform and is journaled: a disable that is still there on rerun
        # is the user's choice after seeing the re-enabled line.
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        home.mkdir()
        log = root / "log"
        bin_dir = tooling(root, log)
        fake(bin_dir, "hermes", 'echo "$*" >> "%s"\n[ "$1" = -p ] && shift 2\ncase "$1" in\n'
             '  --version) echo "hermes 0.21.5";;\n  plugins) [ "$2" = list ] && echo "alans-way";;\n'
             '  tools) [ "$2" = list ] && echo "disabled computer_use";;\nesac\nexit 0\n' % log)
        fake(bin_dir, "hermes-python", "exit 1\n")
        env = env_for(root, bin_dir, home, HERMES_PYTHON=str(bin_dir / "hermes-python"))
        script = repo_with_computer_plugin(root)
        args = ["--bot-id", "111222333", "--skip-browser", "--skip-services", "--non-interactive",
                "--hermes-home", str(home)]
        run(*args, env=env, check=False, script=script)
        run(*args, env=env, check=False, script=script)
        calls = read_log(log)
        self.assertEqual(calls.count("tools enable computer_use --platform telegram"), 1)
        self.assertEqual(calls.count("tools enable computer_use --platform cron"), 1)

    def test_skipped_without_the_provider_api(self):
        result = self.run_setup(python_ok=False)
        calls = read_log(self.log)
        self.assertNotIn("alans-way-computer", calls)
        self.assertNotIn("config set computer_use.backend", calls)

    def test_an_installed_provider_is_never_force_reinstalled(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        home.mkdir()
        log = root / "log"
        bin_dir = tooling(root, log)
        fake(bin_dir, "hermes", 'echo "$*" >> "%s"\n[ "$1" = -p ] && shift 2\ncase "$*" in\n'
             '  "--version") echo "hermes 0.21.5";;\n  "plugins list") printf "alans-way\\nalans-way-computer\\n";;\nesac\nexit 0\n' % log)
        fake(bin_dir, "hermes-python", "exit 0\n")
        run("--bot-id", "111222333", "--skip-browser", "--skip-services", "--non-interactive",
            "--hermes-home", str(home), env=env_for(root, bin_dir, home, HERMES_PYTHON=str(bin_dir / "hermes-python")),
            check=False, script=repo_with_computer_plugin(root))
        calls = read_log(log)
        self.assertNotIn("install --force file://%s" % ROOT, calls.replace("alans-way\n", ""))
        self.assertNotRegex(calls, r"plugins install[^\n]*alans-way-computer")

    def test_verify_runs_the_provider_doctor_when_selected(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        home.mkdir()
        log = root / "log"
        bin_dir = tooling(root, log)
        fake(bin_dir, "hermes", 'echo "$*" >> "%s"\n[ "$1" = -p ] && shift 2\ncase "$*" in\n'
             '  "--version") echo "hermes 0.21.5";;\n  "config get computer_use.backend") echo alans-way-computer;;\n'
             '  "computer-use doctor") exit 1;;\nesac\nexit 0\n' % log)
        result = run("--verify", "--skip-browser", env=env_for(root, bin_dir, home), check=False)
        self.assertIn("computer-use doctor", read_log(log))
        self.assertRegex(result.stdout, r"FAIL .*computer")

    def test_verify_audits_the_block_exclusion_even_when_the_provider_is_selected(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        home.mkdir()
        log = root / "log"
        bin_dir = tooling(root, log)
        fake(bin_dir, "hermes", 'echo "$*" >> "%s"\n[ "$1" = -p ] && shift 2\ncase "$*" in\n'
             '  "--version") echo "hermes 0.21.5";;\n  "config get computer_use.backend") echo alans-way-computer;;\n'
             '  "computer-use doctor") exit 0;;\nesac\nexit 0\n' % log)
        # A managed block that predates the exclusion must be flagged even with
        # the provider backend selected; only a block-scoped exclusion counts.
        (home / "config.yaml").write_text(
            "# >>> alans-way workspace_browser managed block >>>\n"
            "  workspace_browser:\n    command: node\n"
            "    # workspace_computer_action mentioned in a comment\n"
            "# <<< alans-way workspace_browser managed block <<<\n", encoding="utf-8")
        result = run("--verify", "--skip-browser", env=env_for(root, bin_dir, home), check=False)
        self.assertIn("does not exclude workspace_computer_action", result.stdout)
        self.assertIn("computer-use doctor", read_log(log))
        (home / "config.yaml").write_text(
            "# >>> alans-way workspace_browser managed block >>>\n"
            "  workspace_browser:\n    command: node\n"
            "    tools:\n      exclude:\n        - workspace_computer_action\n"
            "# <<< alans-way workspace_browser managed block <<<\n", encoding="utf-8")
        result = run("--verify", "--skip-browser", env=env_for(root, bin_dir, home), check=False)
        self.assertIn("ungated desktop input excluded from workspace_browser", result.stdout)

    def test_the_approval_allowlist_is_only_seeded_on_request(self):
        result = self.run_setup()
        self.assertNotIn("command_allowlist", read_log(self.log))
        self.assertIn("--allow-desktop-actions", result.stdout)
        self.run_setup("--allow-desktop-actions", config_get="Config key not set: command_allowlist")
        calls = read_log(self.log)
        match = re.search(r"config set command_allowlist (\[.*\])", calls)
        self.assertIsNotNone(match, calls)
        entries = json.loads(match.group(1))
        for action in ("click", "double_click", "right_click", "middle_click", "drag", "scroll", "type", "key",
                       "set_value", "focus_app"):
            self.assertIn("cua:%s:background" % action, entries)
        self.assertFalse(any(entry.endswith(":foreground") for entry in entries))


class AllProfilesHarness(IntegrationBase):
    TOKEN = "AAFakeSecretTokenForTests"

    def layout(self, home: Path):
        (home / ".env").write_text("TELEGRAM_BOT_TOKEN=111:%s\n" % self.TOKEN, encoding="utf-8")
        profiles = home / "profiles"
        for name in ("alpha", "beta", "botless", "gamma", "quoted"):
            (profiles / name).mkdir(parents=True)
        (profiles / "alpha" / "config.yaml").write_text(
            "model:\n  default: x\nplatforms:\n  telegram:\n    enabled: true\n    token: \"222:%s\"\n" % self.TOKEN, encoding="utf-8")
        (profiles / "quoted" / "config.yaml").write_text(
            "platforms:\n  telegram:\n    botToken: '555:%s'  # mine\n" % self.TOKEN, encoding="utf-8")
        (profiles / "beta" / ".env").write_text("OTHER=1\nTELEGRAM_BOT_TOKEN=333:%s\n" % self.TOKEN, encoding="utf-8")
        (profiles / "gamma" / ".env").write_text("TELEGRAM_BOT_TOKEN=444:%s\n" % self.TOKEN, encoding="utf-8")
        (profiles / "gamma" / "config.yaml").write_text(
            "mcp_servers:\n  cua_alans_way:\n    command: node\n    args:\n      - /x/workspace-router.cjs\n"
            "  cua_alans_way_vps:\n    command: node\n    args:\n      - /x/browser-mcp.cjs\n", encoding="utf-8")
        (profiles / "botless" / "config.yaml").write_text("model:\n  default: x\n", encoding="utf-8")

    def ids(self, home, name=None):
        config = (home / "profiles" / name / "config.yaml") if name else home / "config.yaml"
        return re.findall(r'- --bot-id\n\s+- "(\d+)"', config.read_text(encoding="utf-8"))

    def run_all(self, *flags, layout=None, listed='echo alans-way', hermes_extra="", python_ok=True):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        home.mkdir()
        (layout or self.layout)(home)
        log = root / "log"
        bin_dir = tooling(root, log)
        fake(bin_dir, "hermes", 'echo "$*" >> "%s"\nP=default; [ "$1" = -p ] && { P="$2"; shift 2; }\ncase "$1" in\n'
             '  --version) echo "hermes 0.21.5";;\n  plugins) [ "$2" = list ] && { %s; };\n'
             '    [ "$2" = install ] && [ "$P" != default ] && case "$*" in *file://*) case "$*" in *--force*) ;; *) echo BLOCKED community source >&2; exit 1;; esac;; esac;;\n%s\nesac\nexit 0\n' % (log, listed, hermes_extra))
        fake(bin_dir, "hermes-python", "exit %d\n" % (0 if python_ok else 1))
        env = env_for(root, bin_dir, home, HERMES_PYTHON=str(bin_dir / "hermes-python"))
        self.env, self.root = env, root
        self.script = repo_with_computer_plugin(root)
        result = run("--skip-browser", "--skip-services", "--non-interactive", "--hermes-home", str(home), *flags,
                     env=env, check=False, script=self.script)
        return result, home, read_log(log)


class AllProfilesTests(AllProfilesHarness, unittest.TestCase):
    def test_every_profile_with_a_telegram_bot_gets_its_own_bot_id(self):
        result, home, calls = self.run_all()
        self.assertEqual(self.ids(home), ["111"])
        for name, bot in (("alpha", "222"), ("beta", "333"), ("gamma", "444"), ("quoted", "555")):
            self.assertEqual(self.ids(home, name), [bot], name)
        self.assertFalse((home / "profiles" / "botless" / "config.yaml").read_text().count("workspace_browser"))
        self.assertNotIn(self.TOKEN, result.stdout + result.stderr)

    def test_legacy_router_entries_are_removed_and_reported(self):
        result, home, calls = self.run_all()
        config = (home / "profiles" / "gamma" / "config.yaml").read_text()
        self.assertNotIn("cua_alans_way", config)
        self.assertEqual(config.count("workspace_browser:"), 1)
        self.assertIn("removed unmanaged mcp_servers entry cua_alans_way_vps", result.stdout)
        self.assertEqual(len(list((home / "profiles" / "gamma").glob("config.yaml.bak-*"))), 1)

    def test_each_profile_gets_the_per_profile_work_but_only_the_primary_is_bound(self):
        result, home, calls = self.run_all()
        for name in ("default", "alpha", "beta", "gamma", "quoted"):
            for needed in ("tools disable browser --platform telegram", "tools disable browser --platform cron",
                           "config set computer_use.backend alans-way-computer"):
                self.assertIn("-p %s %s" % (name, needed), calls, (name, needed))
        self.assertIn("-p default tools enable proactivity --platform telegram", calls)
        self.assertNotIn("proactivity --platform", calls.replace("-p default tools enable proactivity", ""))
        self.assertNotIn("-p botless tools disable browser", calls)
        self.assertNotIn("proactivity bind", calls)

    def test_the_plugin_is_force_installed_into_bot_profiles_that_have_no_catalog_install(self):
        result, home, calls = self.run_all(listed='[ "$P" = default ] && echo alans-way')
        for name in ("alpha", "beta", "gamma", "quoted"):
            self.assertRegex(calls, r"-p %s plugins install --force file://\S+#alans-way\n" % name)
            self.assertIn("-p %s plugins enable alans-way\n" % name, calls)
            self.assertIn("plugin installed in profile %s" % name, result.stdout)
        self.assertNotRegex(calls, r"-p botless plugins install \S+#alans-way\n")
        self.assertNotIn("allow_gateway_injection", calls.split("-p alpha", 1)[1].split("\n")[0])

    def test_an_installed_plugin_in_a_bot_profile_is_left_alone_with_the_update_command(self):
        result, home, calls = self.run_all(listed='[ "$P" = default ] || [ "$P" = beta ] && echo alans-way')
        self.assertNotRegex(calls, r"-p beta plugins install \S+#alans-way\n")
        self.assertIn("hermes -p beta plugins update alans-way", result.stdout)
        self.assertNotRegex(calls, r"-p beta plugins install --force \S+#alans-way\n")

    def test_a_catalog_install_in_a_bot_profile_is_never_replaced(self):
        def layout(home):
            self.layout(home)
            plugins = home / "profiles" / "beta" / "plugins"
            (plugins / "alans-way").mkdir(parents=True)
            (plugins / ".install-metadata.json").write_text(
                '{"alans-way": {"catalog": {"name": "alans-way", "sha": "3a74614"}}}', encoding="utf-8")
        result, home, calls = self.run_all(layout=layout, listed='[ "$P" = default ] || [ "$P" = beta ] && echo alans-way')
        self.assertNotRegex(calls, r"-p beta plugins install \S+#alans-way\n")
        self.assertNotRegex(calls, r"-p beta plugins install --force \S+#alans-way\n")

    def test_the_provider_installs_by_catalog_name_and_respects_catalog_installs(self):
        def layout(home):
            self.layout(home)
            plugins = home / "profiles" / "beta" / "plugins"
            plugins.mkdir(parents=True)
            (plugins / ".install-metadata.json").write_text(
                '{"alans-way-computer": {"catalog": {"name": "alans-way-computer", "sha": "3a74614"}}}', encoding="utf-8")
        result, home, calls = self.run_all(layout=layout)
        self.assertIn("-p alpha plugins install alans-way-computer\n", calls)
        self.assertNotRegex(calls, r"plugins install[^\n]*alans-way-computer[^\n]*--force")
        self.assertNotRegex(calls, r"plugins install[^\n]*file://[^\n]*alans-way-computer")
        self.assertIn("-p alpha config set computer_use.backend alans-way-computer", calls)
        # beta's provider is a catalog install: never installed over, still selected.
        self.assertNotRegex(calls, r"-p beta plugins install[^\n]*alans-way-computer")
        self.assertIn("-p beta config set computer_use.backend alans-way-computer", calls)

    def test_without_the_provider_api_computer_use_stays_on_and_input_stays_gated(self):
        result, home, calls = self.run_all(python_ok=False)
        self.assertNotIn("tools disable computer_use", calls)
        self.assertNotIn("config set computer_use.backend", calls)
        for name in (None, "alpha", "beta", "gamma", "quoted"):
            config = home / "config.yaml" if name is None else home / "profiles" / name / "config.yaml"
            text = config.read_text(encoding="utf-8")
            self.assertIn("- workspace_computer_action", text, name)
            self.assertNotIn("HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS", text, name)
        _, _, kept = self.run_all("--keep-computer-use", python_ok=False)
        self.assertNotIn("tools disable computer_use", kept)

    def test_an_older_setups_disabled_computer_use_is_reenabled_per_profile(self):
        extra = ('  tools) [ "$2" = list ] && case "$P" in default|alpha) echo "disabled computer_use";; esac;;\n')
        result, home, calls = self.run_all(python_ok=False, hermes_extra=extra)
        for name in ("default", "alpha"):
            for platform in ("telegram", "cron"):
                self.assertIn("-p %s tools enable computer_use --platform %s\n" % (name, platform), calls)
        self.assertNotIn("-p beta tools enable computer_use", calls)
        self.assertIn("re-enabled computer_use for telegram (turn it off with:"
                      " hermes -p alpha tools disable computer_use --platform telegram)", result.stdout)

    def test_allow_desktop_actions_opts_every_profile_in_only_without_the_provider_api(self):
        result, home, calls = self.run_all("--allow-desktop-actions", python_ok=False)
        for name in ("alpha", "beta", "gamma", "quoted"):
            text = (home / "profiles" / name / "config.yaml").read_text(encoding="utf-8")
            self.assertIn('HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS: "1"', text, name)
        self.assertNotIn("tools disable computer_use", calls)
        # With the provider API the flag only seeds the allowlist.
        result, home, calls = self.run_all("--allow-desktop-actions")
        text = (home / "config.yaml").read_text(encoding="utf-8")
        self.assertIn("- workspace_computer_action", text)
        self.assertNotIn("HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS", text)
        self.assertIn("command_allowlist", calls)

    def test_a_users_cua_driver_server_is_kept_and_warned_about_once_per_profile(self):
        def layout(home):
            self.layout(home)
            beta = home / "profiles" / "beta" / "config.yaml"
            beta.write_text("mcp_servers:\n  cua-driver:\n    command: cua-driver\n    args: [mcp]\n", encoding="utf-8")
            quoted = home / "profiles" / "quoted" / "config.yaml"
            quoted.write_text(quoted.read_text() + "mcp_servers:\n  desk:\n    command: npx\n    args: [-y, cua-driver, mcp]\n", encoding="utf-8")
        result, home, calls = self.run_all(layout=layout)
        self.assertEqual(result.stdout.count("hermes -p beta mcp remove cua-driver"), 1)
        self.assertEqual(result.stdout.count("hermes -p quoted mcp remove desk"), 1)
        self.assertNotIn("mcp remove cua-driver", result.stdout.replace("hermes -p beta mcp remove cua-driver", ""))
        self.assertIn("two computer-use paths", result.stdout)
        self.assertIn("cua-driver:", (home / "profiles" / "beta" / "config.yaml").read_text())
        self.assertNotIn("mcp remove", calls)

    def test_keep_browser_applies_to_every_profile(self):
        _, _, calls = self.run_all("--keep-browser")
        self.assertNotIn("tools disable browser", calls)

    def test_a_named_profile_limits_the_run_to_that_profile(self):
        _, home, calls = self.run_all("--profile", "beta")
        self.assertEqual(self.ids(home, "beta"), ["333"])
        self.assertFalse((home / "config.yaml").exists())
        self.assertNotIn("workspace_browser", (home / "profiles" / "alpha" / "config.yaml").read_text())
        self.assertNotIn("-p alpha", calls)

    def test_an_explicit_bot_id_is_the_primary_s_only(self):
        _, home, _ = self.run_all("--bot-id", "999")
        self.assertEqual(self.ids(home), ["999"])
        self.assertEqual(self.ids(home, "alpha"), ["222"])


class BotTokenSourceTests(AllProfilesHarness, unittest.TestCase):
    """The reviewer's token fixtures: every shape of config.yaml and .env Hermes accepts."""
    CASES = {
        "plain": ({"config.yaml": "platforms:\n  telegram:\n    token: 111:AAA\n"}, "111"),
        "dq": ({"config.yaml": 'platforms:\n  telegram:\n    token: "222:BBB"  # c\n'}, "222"),
        "sq": ({"config.yaml": "platforms:\n  telegram:\n    botToken: '333:CCC'\n"}, "333"),
        "crlf": ({"config.yaml": "platforms:\r\n  telegram:\r\n    token: 444:DDD\r\n"}, "444"),
        "envonly": ({".env": 'TELEGRAM_BOT_TOKEN="888:HHH"\n'}, "888"),
        "envcrlf": ({".env": "TELEGRAM_BOT_TOKEN=1111:KKK\r\n"}, "1111"),
        "export": ({".env": "export TELEGRAM_BOT_TOKEN=999:III\n"}, "999"),
        "spaced": ({".env": "TELEGRAM_BOT_TOKEN = 1010:JJJ\n"}, "1010"),
        "sp_in_val": ({"config.yaml": 'platforms:\n  telegram:\n    token:   "2222:VVV"\n'}, "2222"),
        "ind4": ({"config.yaml": "platforms:\n    telegram:\n        token: 1717:QQQ\n"}, "1717"),
        "listbetween": ({"config.yaml": "platforms:\n  telegram:\n    allowed:\n      - 1\n    token: 2121:UUU\n"}, "2121"),
        "flow": ({"config.yaml": 'platforms:\n  telegram: {token: "1212:LLL"}\n'}, "1212"),
        "bom": ({"config.yaml": "\ufeffplatforms:\n  telegram:\n    token: 1818:RRR\n"}, "1818"),
        "envlate": ({"config.yaml": "platforms:\n  telegram:\n    token: 1919:SSS\n"}, "1919"),
        "envref": ({"config.yaml": "platforms:\n  telegram:\n    token: ${TELEGRAM_BOT_TOKEN}\n",
                    ".env": "TELEGRAM_BOT_TOKEN=777:GGG\n"}, "777"),
        "cfgbad_envgood": ({"config.yaml": "platforms:\n  telegram:\n    token: junk\n",
                            ".env": "TELEGRAM_BOT_TOKEN=1313:MMM\n"}, "1313"),
        "both": ({"config.yaml": "platforms:\n  telegram:\n    token: 1414:NNN\n",
                  ".env": "TELEGRAM_BOT_TOKEN=1515:OOO\n"}, "1515"),
        "empty": ({"config.yaml": 'platforms:\n  telegram:\n    token: ""\n', ".env": "TELEGRAM_BOT_TOKEN=\n"}, None),
        "invalid": ({"config.yaml": "platforms:\n  telegram:\n    token: notatoken\n"}, None),
        "none": ({"config.yaml": "model:\n  x: 1\n"}, None),
        "nested": ({"config.yaml": "platforms:\n  telegram:\n    extra:\n      token: 555:EEE\n"}, None),
        "otherplat": ({"config.yaml": "platforms:\n  discord:\n    token: 666:FFF\n  telegram:\n    enabled: true\n"}, None),
        "commentline": ({"config.yaml": "platforms:\n  telegram:\n    # token: 2020:TTT\n    enabled: true\n"}, None),
        "telegram_top": ({"config.yaml": "telegram:\n  token: 1616:PPP\n"}, None),
    }

    def layout(self, home: Path):
        (home / ".env").write_text("TELEGRAM_BOT_TOKEN=100:AAHprimary\n", encoding="utf-8")
        for name, (files, _) in self.CASES.items():
            (home / "profiles" / name).mkdir(parents=True)
            for file, text in files.items():
                (home / "profiles" / name / file).write_bytes(text.encode("utf-8"))
        bad = home / "profiles" / "aaa-bad"
        bad.mkdir()
        (bad / ".env").write_text("TELEGRAM_BOT_TOKEN=999:ZZZ\n", encoding="utf-8")
        (bad / "config.yaml").write_bytes(b"model: \xff\xfe\n")

    def test_each_shape_gives_the_bot_hermes_would_run_and_none_leaks_a_token(self):
        result, home, calls = self.run_all()
        for name, (_, expected) in self.CASES.items():
            config = home / "profiles" / name / "config.yaml"
            found = re.findall(r'- --bot-id\n\s+- "(\d+)"', config.read_text(encoding="utf-8")) if config.exists() else []
            self.assertEqual(found, [expected] if expected else [], name)
        out = result.stdout + result.stderr + calls
        for secret in ("AAA", "BBB", "KKK", "OOO", "NNN", "GGG", "AAHprimary", "ZZZ"):
            self.assertNotIn(":" + secret, out)
            self.assertNotIn("=" + secret, out)

    def test_env_wins_over_config_and_the_disagreement_is_reported_by_id(self):
        result, _, _ = self.run_all()
        self.assertIn("bot id 1515 in .env, 1414 in config.yaml", result.stdout)

    def test_a_profile_with_an_undecodable_file_is_skipped_and_the_rest_continue(self):
        result, home, _ = self.run_all()
        self.assertIn("config.yaml is not valid UTF-8 text, so this profile was skipped", result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((home / "profiles" / "aaa-bad" / "config.yaml").read_bytes(), b"model: \xff\xfe\n")
        self.assertEqual(self.ids(home, "plain"), ["111"])


class VerifyAllProfilesTests(AllProfilesHarness, unittest.TestCase):
    EXTRA = ('  tools) [ "$2" = list ] && { [ "$P" = beta ] && echo "enabled browser"; echo "enabled proactivity"; };;\n'
             '  config) [ "$2" = get ] && echo alans-way-computer;;\n'
             '  computer-use) [ "$P" = alpha ] && exit 1;;')

    def test_verify_covers_the_other_profiles_and_lists_the_skipped(self):
        def layout(home):
            self.layout(home)
            bad = home / "profiles" / "aaa-bad"
            bad.mkdir()
            (bad / "config.yaml").write_bytes(b"\xff\xfe")
        self.run_all(layout=layout, hermes_extra=self.EXTRA)
        result = run("--verify", "--hermes-home", str(self.root / "home"), env=self.env, check=False, script=self.script)
        out = result.stdout
        for name in ("alpha", "beta", "gamma", "quoted"):
            self.assertRegex(out, r"ok   workspace_browser block in \S*profiles/%s/config.yaml" % name)
        self.assertIn("profile botless has no Telegram bot of its own", out)
        self.assertIn("profile aaa-bad was not checked: config.yaml is not valid UTF-8 text", out)
        self.assertIn("browser' toolset still enabled for telegram in profile beta", out)
        self.assertIn("browser' toolset still enabled for cron in profile beta", out)
        self.assertRegex(out, r"FAIL .*hermes -p alpha computer-use doctor")
        self.assertNotRegex(out, r"FAIL .*-p beta computer-use")
        keep = run("--verify", "--keep-browser", "--hermes-home", str(self.root / "home"), env=self.env, check=False, script=self.script)
        self.assertNotIn("still enabled for telegram in profile", keep.stdout)

    def test_verify_flags_a_workspace_block_that_still_exposes_desktop_input(self):
        # The provider backend is not selected, so verify inspects each
        # profile's managed block for the desktop-input exclusion instead.
        extra = '  config) [ "$2" = get ] && echo "";;'
        self.run_all(python_ok=False, hermes_extra=extra)
        verify = lambda *flags: run("--verify", *flags, "--hermes-home", str(self.root / "home"),
                                   env=self.env, check=False, script=self.script).stdout
        out = verify()
        # run_all wrote the managed block with the exclusion everywhere.
        for name in ("alpha", "beta", "gamma", "quoted"):
            self.assertIn("ungated desktop input excluded from workspace_browser in profile %s" % name, out)
        self.assertNotIn("does not exclude workspace_computer_action", out)
        # Strip the exclusion from one profile and verify flags it.
        beta = self.root / "home" / "profiles" / "beta" / "config.yaml"
        beta.write_text(beta.read_text().replace(
            "    tools:\n      exclude:\n        - workspace_computer_action\n", ""), encoding="utf-8")
        self.assertIn("does not exclude workspace_computer_action", verify())
        # The explicit opt-in marker is reported as deliberate, not an error.
        gamma = self.root / "home" / "profiles" / "gamma" / "config.yaml"
        gamma.write_text(gamma.read_text().replace(
            "# <<< alans-way workspace_browser managed block <<<",
            '      HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS: "1"\n'
            "# <<< alans-way workspace_browser managed block <<<"), encoding="utf-8")
        self.assertIn("workspace_computer_action exposed by explicit opt-in (--allow-desktop-actions) in profile gamma",
                      verify())


class AgentSshReuseTests(unittest.TestCase):
    HOST = "mac.tail1234.ts.net"
    BLOCK = ("# >>> alans-way >>>\nHost %s\n  ControlMaster auto\n  ControlPath ~/.ssh/cm-%%C\n"
             "  ControlPersist 10m\n  ServerAliveInterval 15\n  ServerAliveCountMax 3\n# <<< alans-way <<<\n" % HOST)

    def setup_run(self, existing=None, host=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.config = self.root / ".ssh" / "config"
        if existing is not None:
            self.config.parent.mkdir(mode=0o700)
            self.config.write_text(existing, encoding="utf-8")
        bin_dir = tooling(self.root, self.root / "log")
        fake(bin_dir, "ssh", 'cat >/dev/null 2>&1 </dev/null; exit 0\n')
        fake(bin_dir, "scp", "exit 0\n")
        self.env = env_for(self.root, bin_dir, self.home)
        return self.again(host)

    def again(self, host=None):
        return run("--mac-ssh", "me@" + (host or self.HOST), "--skip-browser", "--skip-services", "--non-interactive",
                   "--hermes-home", str(self.home), env=self.env, check=False)

    def test_writes_one_managed_block_with_connection_reuse_and_is_idempotent(self):
        self.setup_run()
        self.assertEqual(self.config.read_text(), self.BLOCK)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.again()
        self.assertEqual(self.config.read_text(), self.BLOCK)

    def test_other_content_is_kept_and_a_stale_block_is_refreshed(self):
        stale = "# >>> alans-way >>>\nHost old.ts.net\n  ControlMaster no\n# <<< alans-way <<<\n"
        self.setup_run(existing="Host work\n  User bob\n\n" + stale + "Host tail\n  Port 2222\n")
        self.assertEqual(self.config.read_text(), "Host work\n  User bob\n\n" + self.BLOCK + "Host tail\n  Port 2222\n")

    def test_the_users_own_host_entry_is_left_alone_with_a_warning(self):
        mine = "Host other %s\n  User me\n" % self.HOST
        result = self.setup_run(existing=mine)
        self.assertEqual(self.config.read_text(), mine)
        self.assertRegex(result.stdout, r"warn .*already has a Host entry for %s" % re.escape(self.HOST))

    def test_no_host_means_no_ssh_config(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        home = root / "home"
        home.mkdir()
        run("--skip-browser", "--skip-services", "--non-interactive", "--hermes-home", str(home),
            env=env_for(root, tooling(root, root / "log"), home), check=False)
        self.assertFalse((root / ".ssh" / "config").exists())


def linux_without_systemd(bin_dir, log):
    """A VM image or container: the systemctl binary exists but PID 1 is not systemd."""
    fake(bin_dir, "uname", "echo Linux\n")
    fake(bin_dir, "systemctl",
         'echo "$*" >> "%s"\ncase "$1" in is-system-running) echo offline;; esac\nexit 0\n' % log)


def linux_with_systemd(bin_dir, log):
    fake(bin_dir, "uname", "echo Linux\n")
    fake(bin_dir, "systemctl",
         'echo "$*" >> "%s"\ncase "$1" in is-system-running) echo running;; esac\nexit 0\n' % log)


def sup_line(name, state, desc=""):
    """One `supervisorctl status` line as the real tool prints it: the name
    column padded to 33, the state column padded to 10."""
    return "%-33s%-10s%s\n" % (name, state, desc)


def fake_supervisord(bin_dir, root, state=""):
    """A working supervisorctl; program states live in a state file the test
    owns, in the real padded status format. Exit codes mirror the real tool:
    status is nonzero when a queried program is not RUNNING (a bare `status`
    exits 3 if any is down), and `pid` prints the daemon's own pid when no
    program is named. `signal USR1` plays Hermes's drain-and-respawn: the
    program keeps reporting its old pid for the next two queries (the drain),
    then the supervisor relaunches it under a new pid. Plant <root>/no-respawn
    to leave it STOPPED instead, <root>/no-signal for a daemon old enough to
    lack the signal verb, or <root>/need-sudo for a socket only root can use
    (a fake sudo must remove the flag and exec the verb)."""
    state_file = Path(root) / "supervisor.state"
    state_file.write_text(state, encoding="utf-8")
    log = Path(root) / "supervisorctl.log"
    fake(bin_dir, "supervisorctl", '''echo "$*" >> "%s"
state="%s"
nosignal="%s"
norespawn="%s"
needsudo="%s"
[ ! -f "$needsudo" ] || exit 1
_fmtline() { printf '%%-33s%%-10s%%s\\n' "$1" "$2" "${3:-}"; }
_respawn() {
  [ -f "$state.respawn-$1" ] || return 0
  _n="$(cat "$state.respawn-$1" 2>/dev/null)"; _n="${_n:-1}"
  if [ "$_n" -gt 0 ]; then echo $((_n - 1)) > "$state.respawn-$1"; return 0; fi
  rm -f "$state.respawn-$1"
  grep -v "^$1 " "$state" > "$state.tmp" 2>/dev/null || true
  _fmtline "$1" RUNNING "pid 888, uptime 0:00:01" >> "$state.tmp"
  mv "$state.tmp" "$state"
}
case "$1" in
  status)
    if [ -n "${2:-}" ]; then
      _line="$(grep "^$2 " "$state" 2>/dev/null)"; [ -n "$_line" ] || _line="$(_fmtline "$2" STOPPED)"
      echo "$_line"
      _respawn "$2"
      case "$_line" in *" RUNNING "*) exit 0;; *) exit 3;; esac
    fi
    cat "$state" 2>/dev/null || true
    grep -v " RUNNING " "$state" >/dev/null 2>&1 && exit 3
    exit 0;;
  pid)
    if [ -z "${2:-}" ]; then echo 4321; exit 0; fi
    _p="$(awk -v n="$2" '$1 == n { gsub(",", "", $4); print $4 }' "$state" 2>/dev/null)"
    echo "${_p:-0}"
    _respawn "$2"
    [ -n "$_p" ] || exit 7;;
  start)
    rm -f "$state.respawn-$2"
    grep -v "^$2 " "$state" > "$state.tmp" 2>/dev/null || true
    _fmtline "$2" RUNNING "pid 777, uptime 0:00:01" >> "$state.tmp"
    mv "$state.tmp" "$state";;
  signal)
    [ ! -f "$nosignal" ] || exit 1
    [ "$2" = USR1 ] || exit 1
    grep "^$3 " "$state" 2>/dev/null | grep -q " RUNNING " || exit 1
    rm -f "$state.respawn-$3"
    if [ -f "$norespawn" ]; then
      grep -v "^$3 " "$state" > "$state.tmp" 2>/dev/null || true
      _fmtline "$3" STOPPED >> "$state.tmp"
      mv "$state.tmp" "$state"
    else
      echo 1 > "$state.respawn-$3"
    fi;;
  stop)
    _line="$(grep "^$2 " "$state" 2>/dev/null || true)"
    case "$_line" in
      *" RUNNING "*)
        grep -v "^$2 " "$state" > "$state.tmp" 2>/dev/null || true
        _fmtline "$2" STOPPED >> "$state.tmp"
        mv "$state.tmp" "$state"
        echo "$2: stopped";;
      *) echo "$2: ERROR (not running)" >&2; exit 1;;
    esac;;
esac
exit 0
''' % (log, state_file, root / "no-signal", root / "no-respawn", root / "need-sudo"))
    return log


class SupervisordServiceTests(unittest.TestCase):
    """A Linux guest with no live systemd but a working supervisord gets the
    services as supervisor programs in a conf.d drop-in, not dead units."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.data = self.root / "data"
        self.units = self.root / "units"
        self.units.mkdir()
        self.confd = self.root / "conf.d"
        self.confd.mkdir()
        self.app = desktop_tree(self.root / "app")
        self.bin_dir = tooling(self.root, self.root / "log")
        linux_without_systemd(self.bin_dir, self.root / "systemctl.log")
        self.supervisor_log = fake_supervisord(self.bin_dir, self.root)
        fake(self.bin_dir, "google-chrome", "exit 0\n")
        fake(self.bin_dir, "ssh", "cat >/dev/null 2>&1 </dev/null; exit 0\n")
        fake(self.bin_dir, "scp", "exit 0\n")

    def env(self, **extra):
        return env_for(self.root, self.bin_dir, self.home,
                       HERMES_VPS_BROWSER_DATA=str(self.data),
                       ALANS_WAY_UNIT_DIR=str(self.units),
                       ALANS_WAY_SUPERVISOR_CONF_DIR=str(self.confd), **extra)

    def run_setup(self, *flags, **env):
        if "--restart" in flags:
            # The detached restarter outlives setup.sh; wait for it before
            # the temp dir is torn down (see wait_for_restarter).
            self.addCleanup(self.wait_for_restarter)
        return run("--skip-plugin", "--desktop-dir", str(self.app), "--non-interactive",
                   "--hermes-home", str(self.home), *flags, env=self.env(**env), check=False)

    def conf(self):
        return (self.confd / "alans-way.conf").read_text(encoding="utf-8")

    def test_writes_supervisor_programs_instead_of_dead_systemd_units(self):
        result = self.run_setup("--mac-ssh", "me@mac.tail1234.ts.net")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(list(self.units.glob("*.service")), [])
        conf = self.conf()
        for prog in ("alans-way-chromium", "alans-way-browser", "alans-way-mac-watch"):
            self.assertIn("[program:%s]" % prog, conf)
        self.assertIn("vps-chromium-host.cjs", conf)
        self.assertIn("vps-browser-host.cjs serve", conf)
        self.assertIn("workspace-router.cjs --watch --interval 10", conf)
        self.assertIn("autorestart=unexpected", conf)
        # exitcodes mirrors the units' RestartPreventExitStatus: 0 is a clean
        # exit under on-failure, so it must be "expected" too.
        self.assertIn("exitcodes=0,78", conf)
        self.assertIn("exitcodes=2", conf)
        self.assertIn('HERMES_VPS_BROWSER_DATA="%s"' % self.data, conf)
        self.assertIn('DISPLAY=', conf)
        self.assertIn('HERMES_WORKSPACE_MAC_SSH="me@mac.tail1234.ts.net"', conf)
        self.assertIn('HERMES_WORKSPACE_HOST_OS="mac"', conf)

    def test_a_rerun_without_mac_ssh_keeps_the_computer_and_the_watcher(self):
        # Issue #62: omitting --mac-ssh on a re-run must keep the configured
        # computer, not write the empty flag default over it.
        self.assertEqual(self.run_setup("--bot-id", "111222333", "--mac-ssh", "me@mac.tail1234.ts.net").returncode, 0)
        self.assertEqual(self.run_setup("--bot-id", "111222333").returncode, 0)
        conf = self.conf()
        self.assertIn("[program:alans-way-mac-watch]", conf)
        self.assertIn('HERMES_WORKSPACE_MAC_SSH="me@mac.tail1234.ts.net"', conf)
        block = (self.home / "config.yaml").read_text()
        self.assertIn('HERMES_WORKSPACE_MAC_SSH: "me@mac.tail1234.ts.net"', block)

    def test_mac_ssh_none_clears_the_computer_and_the_watcher(self):
        self.assertEqual(self.run_setup("--bot-id", "111222333", "--mac-ssh", "me@mac.tail1234.ts.net").returncode, 0)
        self.assertEqual(self.run_setup("--bot-id", "111222333", "--mac-ssh", "none").returncode, 0)
        self.assertNotIn("alans-way-mac-watch", self.conf())
        block = (self.home / "config.yaml").read_text()
        self.assertIn('HERMES_WORKSPACE_MAC_SSH: ""', block)

    def test_a_computer_configured_only_in_a_profile_keeps_the_watcher(self):
        # The #62 residual: `--profile alt --mac-ssh` writes the computer
        # into alt's managed block only. A bare re-run must still keep the
        # watcher, the shared state-file env and the managed ssh block —
        # the computer is configured even though the main block has none.
        prof = self.home / "profiles" / "alt"
        prof.mkdir(parents=True)
        (prof / ".env").write_text("TELEGRAM_BOT_TOKEN=111222333:alt-token\n", encoding="utf-8")
        self.assertEqual(
            self.run_setup("--profile", "alt", "--mac-ssh", "me@mac.tail1234.ts.net",
                           "--bot-id", "111222333").returncode, 0)
        self.assertIn("[program:alans-way-mac-watch]", self.conf())
        self.assertEqual(self.run_setup().returncode, 0)
        conf = self.conf()
        self.assertIn("[program:alans-way-mac-watch]", conf)
        self.assertIn('HERMES_WORKSPACE_MAC_SSH="me@mac.tail1234.ts.net"', conf)
        block = (prof / "config.yaml").read_text()
        self.assertIn('HERMES_WORKSPACE_MAC_SSH: "me@mac.tail1234.ts.net"', block)
        self.assertIn("HERMES_MAC_STATE_FILE:", block)
        self.assertIn("Host mac.tail1234.ts.net",
                      (self.root / ".ssh" / "config").read_text())

    def test_a_rerun_without_a_prior_block_stays_vps_only(self):
        self.assertEqual(self.run_setup("--bot-id", "111222333").returncode, 0)
        self.assertEqual(self.run_setup("--bot-id", "111222333").returncode, 0)
        self.assertNotIn("alans-way-mac-watch", self.conf())
        block = (self.home / "config.yaml").read_text()
        self.assertIn('HERMES_WORKSPACE_MAC_SSH: ""', block)
        calls = self.supervisor_log.read_text()
        self.assertIn("reread", calls)
        self.assertIn("update", calls)

    def test_no_watcher_program_without_a_host(self):
        self.run_setup()
        conf = self.conf()
        self.assertIn("alans-way-browser", conf)
        self.assertNotIn("alans-way-mac-watch", conf)

    def test_overseer_bot_ids_ride_along_when_configured(self):
        self.run_setup(HERMES_OVERSEER_BOT_IDS="4242")
        self.assertIn('HERMES_OVERSEER_BOT_IDS="4242"', self.conf())

    def test_an_overseer_value_in_an_existing_conf_is_kept(self):
        (self.confd / "alans-way.conf").write_text(
            '[program:alans-way-browser]\nenvironment=HERMES_OVERSEER_BOT_IDS="777"\n', encoding="utf-8")
        self.run_setup()
        self.assertIn('HERMES_OVERSEER_BOT_IDS="777"', self.conf())

    def test_a_commented_out_overseer_value_stays_disabled(self):
        # An operator who commented the pair out disabled it on purpose; the
        # read-back must not resurrect the value on the next run.
        (self.confd / "alans-way.conf").write_text(
            '[program:alans-way-browser]\n'
            ';environment=HERMES_OVERSEER_BOT_IDS="777"\n'
            '#environment=HERMES_OVERSEER_BOT_IDS="888"\n', encoding="utf-8")
        self.run_setup()
        self.assertNotIn("HERMES_OVERSEER_BOT_IDS", self.conf())

    def test_a_re_run_is_idempotent_and_starts_stopped_programs(self):
        self.run_setup()
        conf = self.confd / "alans-way.conf"
        before = conf.read_bytes()
        self.supervisor_log.write_text("")
        (self.root / "supervisor.state").write_text("")
        self.run_setup()
        self.assertEqual(conf.read_bytes(), before)
        calls = self.supervisor_log.read_text()
        self.assertNotIn("reread", calls)
        self.assertNotIn("update", calls)
        self.assertIn("start alans-way-chromium", calls)
        self.assertIn("start alans-way-browser", calls)

    def test_running_programs_are_not_restarted(self):
        self.run_setup()
        (self.root / "supervisor.state").write_text(
            sup_line("alans-way-chromium", "RUNNING", "pid 11, uptime 1:00:00") +
            sup_line("alans-way-browser", "RUNNING", "pid 12, uptime 1:00:00"), encoding="utf-8")
        self.supervisor_log.write_text("")
        self.run_setup()
        calls = self.supervisor_log.read_text()
        self.assertNotIn("start alans-way", calls)
        self.assertNotIn("restart", calls)

    def test_skip_services_writes_no_conf(self):
        result = self.run_setup("--skip-services")
        self.assertFalse((self.confd / "alans-way.conf").exists())
        self.assertNotIn("reread", read_log(self.supervisor_log))

    def test_neither_manager_warns_instead_of_half_installing(self):
        (self.bin_dir / "supervisorctl").unlink()
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"warn .*(systemd|supervisor)")
        self.assertFalse((self.confd / "alans-way.conf").exists())
        self.assertEqual(list(self.units.glob("*.service")), [])

    def test_the_browser_display_matches_the_live_desktop(self):
        fake(self.bin_dir, "pgrep", 'case "$*" in\n'
             '  *websockify*) exit 1;;\n'
             '  *) echo "548 /usr/bin/Xtigervnc :98 -rfbport 5998 -localhost";;\nesac\n')
        self.run_setup(ALANS_WAY_X11_DIR=str(self.root / "no-x11"))
        self.assertIn('DISPLAY=":98"', self.conf())

    def test_a_live_display_stack_prints_the_viewer_url(self):
        fake(self.bin_dir, "pgrep", 'case "$*" in\n'
             '  *websockify*) echo "581 /usr/bin/python3 /usr/bin/websockify --web /usr/share/novnc 127.0.0.1:6080 localhost:5999";;\n'
             '  *) echo "548 /usr/bin/Xtigervnc :99 -rfbport 5999 -localhost";;\nesac\n')
        ip = tailnet_ip(64, 0, 2)
        fake(self.bin_dir, "tailscale",
             'case "$1" in\n  ip) echo "%s";;\nesac\n%s' % (ip, TAILSCALE_UP))
        result = self.run_setup()
        self.assertIn("6080", result.stdout)
        self.assertIn("vnc.html", result.stdout)
        self.assertIn(ip, result.stdout)
        self.assertNotIn("apt-get install xvfb", result.stdout)

    def test_a_running_vnc_display_beats_a_lower_numbered_socket(self):
        import socket as socket_mod
        sockdir = self.root / "x11"
        sockdir.mkdir()
        sock = socket_mod.socket(socket_mod.AF_UNIX)
        try:
            sock.bind(str(sockdir / "X0"))
        except OSError:
            self.skipTest("cannot bind a unix socket here")
        self.addCleanup(sock.close)
        fake(self.bin_dir, "pgrep", 'case "$*" in\n'
             '  *websockify*) exit 1;;\n'
             '  *) echo "548 /usr/bin/Xtigervnc :98 -rfbport 5998 -localhost";;\nesac\n')
        self.run_setup(ALANS_WAY_X11_DIR=str(sockdir))
        self.assertIn('DISPLAY=":98"', self.conf())

    def test_a_skip_services_rerun_keeps_the_watcher_state_file_in_the_router_env(self):
        args = ("--mac-ssh", "me@mac.tail1234.ts.net", "--bot-id", "111222333")
        self.run_setup(*args)
        self.run_setup(*args, "--skip-services")
        config = (self.home / "config.yaml").read_text()
        state = str(self.root / ".local/share/hermes-alans-way/mac-state.json")
        self.assertIn('HERMES_MAC_STATE_FILE: "%s"' % state, config)

    def test_gateway_restart_uses_the_supervisor_program_that_owns_it(self):
        (self.root / "supervisor.state").write_text(
            sup_line("custom-gateway", "RUNNING", "pid 777, uptime 1:00:00"), encoding="utf-8")
        fake(self.bin_dir, "ps",
             'case "$*" in *777*) echo "/opt/venv/bin/python /usr/lib/hermes gateway run --no-supervise";; esac\n')
        self.run_setup("--restart", ALANS_WAY_RESTART_DELAY="1")
        deadline = time.time() + 15
        while "signal USR1 custom-gateway" not in read_log(self.supervisor_log) and time.time() < deadline:
            time.sleep(0.2)
        self.assertIn("signal USR1 custom-gateway", read_log(self.supervisor_log))
        self.assertNotIn("gateway restart", read_log(self.root / "log"))

    def test_gateway_restart_prefers_the_program_running_the_selected_profile(self):
        (self.root / "supervisor.state").write_text(
            sup_line("main-gateway", "RUNNING", "pid 771, uptime 1:00:00") +
            sup_line("alt-gateway", "RUNNING", "pid 772, uptime 1:00:00"), encoding="utf-8")
        fake(self.bin_dir, "ps",
             'case "$*" in\n'
             '  *771*) echo "hermes gateway run --no-supervise";;\n'
             '  *772*) echo "hermes -p alt gateway run --no-supervise";;\n'
             'esac\n')
        self.run_setup("--restart", "--profile", "alt", ALANS_WAY_RESTART_DELAY="1")
        deadline = time.time() + 15
        while "signal USR1 alt-gateway" not in read_log(self.supervisor_log) and time.time() < deadline:
            time.sleep(0.2)
        self.assertIn("signal USR1 alt-gateway", read_log(self.supervisor_log))
        self.assertNotIn("USR1 main-gateway", read_log(self.supervisor_log))

    def test_gateway_restart_without_a_profile_prefers_the_unprofiled_program(self):
        (self.root / "supervisor.state").write_text(
            sup_line("alt-gateway", "RUNNING", "pid 771, uptime 1:00:00") +
            sup_line("main-gateway", "RUNNING", "pid 772, uptime 1:00:00"), encoding="utf-8")
        fake(self.bin_dir, "ps",
             'case "$*" in\n'
             '  *771*) echo "hermes -p alt gateway run --no-supervise";;\n'
             '  *772*) echo "hermes gateway run --no-supervise";;\n'
             'esac\n')
        self.run_setup("--restart", ALANS_WAY_RESTART_DELAY="1")
        deadline = time.time() + 15
        while "signal USR1 main-gateway" not in read_log(self.supervisor_log) and time.time() < deadline:
            time.sleep(0.2)
        self.assertIn("signal USR1 main-gateway", read_log(self.supervisor_log))
        self.assertNotIn("USR1 alt-gateway", read_log(self.supervisor_log))

    def test_gateway_restart_matches_every_profile_flag_form(self):
        # `hermes --profile alt gateway run`, `--profile=alt`, `-p=alt` and
        # `-palt` name the same profile `-p alt` does — each must pick the
        # alt program, not the unprofiled candidate.
        for form in ("-p alt", "-p=alt", "-palt", "--profile alt", "--profile=alt"):
            with self.subTest(form=form):
                (self.root / "supervisor.state").write_text(
                    sup_line("main-gateway", "RUNNING", "pid 771, uptime 1:00:00") +
                    sup_line("alt-gateway", "RUNNING", "pid 772, uptime 1:00:00"), encoding="utf-8")
                for stale in self.root.glob("supervisor.state.respawn-*"):
                    stale.unlink()
                fake(self.bin_dir, "ps",
                     'case "$*" in\n'
                     '  *771*) echo "hermes gateway run --no-supervise";;\n'
                     '  *772*) echo "hermes %s gateway run --no-supervise";;\n'
                     'esac\n' % form)
                self.supervisor_log.write_text("")
                self.run_setup("--restart", "--profile", "alt", ALANS_WAY_RESTART_DELAY="1")
                deadline = time.time() + 15
                while "signal USR1 alt-gateway" not in read_log(self.supervisor_log) and time.time() < deadline:
                    time.sleep(0.2)
                self.assertIn("signal USR1 alt-gateway", read_log(self.supervisor_log))
                self.assertNotIn("USR1 main-gateway", read_log(self.supervisor_log))
                # Wait out each restarter before the next subTest rewrites
                # supervisor.state and unlinks respawn-* — otherwise the
                # previous form's restarter loses its respawn marker
                # mid-drain and polls the full drain bound.
                self.wait_for_restarter()

    def test_a_glued_profile_flag_is_not_the_unprofiled_gateway(self):
        # "-palt" used to fall through to the unprofiled candidate, so a
        # default --restart could signal the wrong profile's gateway.
        (self.root / "supervisor.state").write_text(
            sup_line("alt-gateway", "RUNNING", "pid 771, uptime 1:00:00") +
            sup_line("main-gateway", "RUNNING", "pid 772, uptime 1:00:00"), encoding="utf-8")
        fake(self.bin_dir, "ps",
             'case "$*" in\n'
             '  *771*) echo "hermes -palt gateway run";;\n'
             '  *772*) echo "hermes gateway run";;\n'
             'esac\n')
        self.run_setup("--restart", ALANS_WAY_RESTART_DELAY="1")
        deadline = time.time() + 15
        while "signal USR1 main-gateway" not in read_log(self.supervisor_log) and time.time() < deadline:
            time.sleep(0.2)
        self.assertIn("signal USR1 main-gateway", read_log(self.supervisor_log))
        self.assertNotIn("USR1 alt-gateway", read_log(self.supervisor_log))

    def test_a_profiled_restart_never_signals_the_unprofiled_gateway(self):
        # The unprofiled candidate only serves a default target, same strict
        # rule as the conf scan: `--profile alt --restart` on a host whose
        # only RUNNING gateway is the default one must not drain it — the
        # restart falls through to `hermes -p alt gateway restart`.
        (self.root / "supervisor.state").write_text(
            sup_line("main-gateway", "RUNNING", "pid 771, uptime 1:00:00"), encoding="utf-8")
        fake(self.bin_dir, "ps",
             'case "$*" in *771*) echo "hermes gateway run --no-supervise";; esac\n')
        self.run_setup("--restart", "--profile", "alt", ALANS_WAY_RESTART_DELAY="1")
        deadline = time.time() + 15
        while "gateway restart" not in read_log(self.root / "log") and time.time() < deadline:
            time.sleep(0.2)
        self.assertNotIn("signal USR1", read_log(self.supervisor_log))
        self.assertIn("-p alt gateway restart", read_log(self.root / "log"))

    def test_gateway_restart_ignores_a_non_hermes_gateway_program(self):
        (self.root / "supervisor.state").write_text(
            sup_line("api-gateway", "RUNNING", "pid 780, uptime 1:00:00"), encoding="utf-8")
        fake(self.bin_dir, "ps", 'case "$*" in *780*) echo "kong gateway run";; esac\n')
        self.run_setup("--restart", ALANS_WAY_RESTART_DELAY="1")
        deadline = time.time() + 15
        while "gateway restart" not in read_log(self.root / "log") and time.time() < deadline:
            time.sleep(0.2)
        self.assertIn("gateway restart", read_log(self.root / "log"))
        self.assertNotIn("restart api-gateway", read_log(self.supervisor_log))

    def restart_log(self):
        """The detached restarter's own log (its mktemp file lands in TMPDIR)."""
        return "\n".join(p.read_text(encoding="utf-8")
                         for p in self.root.glob("alans-way-gateway-restart.*"))

    def wait_for_restarter(self, seconds=30):
        """Teardown barrier for the detached restarter. It sleeps
        ALANS_WAY_RESTART_DELAY, then polls supervisorctl — writing its log,
        supervisorctl.log and the respawn/state tmp files, all inside this
        test's temp dir — for up to the drain bound after setup.sh returns.
        Without the wait, cleanup's rmtree races those writes on CI
        (OSError: Directory not empty). Done when every restart log ends in
        a final "restarted:"/"failed"/"by hand" line or no restarter is
        left running."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            if not self._restarter_running():
                return
            logs = list(self.root.glob("alans-way-gateway-restart.*"))
            if logs and all(any(m in p.read_text(encoding="utf-8", errors="replace")
                                for m in ("restarted:", "failed", "by hand"))
                            for p in logs):
                return
            time.sleep(0.2)

    def _restarter_running(self):
        # The restarter's argv carries this test's bin dir (the fake hermes
        # and supervisorctl paths it was launched with), so a real pgrep -f
        # on the temp dir names it — the test's own PATH is untouched by the
        # fixture's.
        try:
            return subprocess.run(["pgrep", "-f", str(self.root)],
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0
        except OSError:
            return True  # no pgrep: keep waiting on the log markers alone

    def test_gateway_restart_signals_usr1_and_waits_for_a_new_pid(self):
        """A Hermes gateway drains its turns on SIGUSR1 and supervisord relaunches
        it; `supervisorctl restart` would escalate SIGTERM to SIGKILL after
        stopwaitsecs, which corrupts state.db mid-checkpoint."""
        (self.root / "supervisor.state").write_text(
            sup_line("main-gateway", "RUNNING", "pid 771, uptime 1:00:00"), encoding="utf-8")
        fake(self.bin_dir, "ps",
             'case "$*" in *771*) echo "hermes gateway run --no-supervise";; esac\n')
        self.run_setup("--restart", ALANS_WAY_RESTART_DELAY="1")
        deadline = time.time() + 15
        while "signal USR1" not in self.restart_log() and time.time() < deadline:
            time.sleep(0.2)
        self.assertIn("signal USR1 main-gateway", read_log(self.supervisor_log))
        self.assertIn("signal USR1 main-gateway (new pid 888)", self.restart_log())
        self.assertNotIn("restart main-gateway", read_log(self.supervisor_log))

    def test_gateway_restart_starts_a_program_that_did_not_come_back(self):
        (self.root / "supervisor.state").write_text(
            sup_line("main-gateway", "RUNNING", "pid 771, uptime 1:00:00"), encoding="utf-8")
        (self.root / "no-respawn").write_text("", encoding="utf-8")
        fake(self.bin_dir, "ps",
             'case "$*" in *771*) echo "hermes gateway run --no-supervise";; esac\n')
        self.run_setup("--restart", ALANS_WAY_RESTART_DELAY="1")
        deadline = time.time() + 15
        while "start main-gateway" not in read_log(self.supervisor_log) and time.time() < deadline:
            time.sleep(0.2)
        self.assertIn("signal USR1 main-gateway", read_log(self.supervisor_log))
        self.assertIn("start main-gateway", read_log(self.supervisor_log))
        self.assertNotIn("restart main-gateway", read_log(self.supervisor_log))

    def test_gateway_restart_falls_back_to_restart_when_signal_is_unsupported(self):
        (self.root / "supervisor.state").write_text(
            sup_line("main-gateway", "RUNNING", "pid 771, uptime 1:00:00"), encoding="utf-8")
        (self.root / "no-signal").write_text("", encoding="utf-8")
        fake(self.bin_dir, "ps",
             'case "$*" in *771*) echo "hermes gateway run --no-supervise";; esac\n')
        self.run_setup("--restart", ALANS_WAY_RESTART_DELAY="1")
        deadline = time.time() + 15
        while "restart main-gateway" not in read_log(self.supervisor_log) and time.time() < deadline:
            time.sleep(0.2)
        self.assertIn("signal USR1 main-gateway", read_log(self.supervisor_log))
        self.assertIn("restart main-gateway", read_log(self.supervisor_log))

    def test_gateway_restart_finds_a_stopped_program_by_its_conf_command(self):
        """A STOPPED gateway has no argv to match, so its [program:] conf
        command stands in; the restart then goes through supervisord, not
        `hermes gateway restart`."""
        (self.root / "supervisor.state").write_text(
            sup_line("main-gateway", "STOPPED"), encoding="utf-8")
        (self.confd / "gw.conf").write_text(
            "[program:main-gateway]\ncommand=/usr/local/bin/hermes gateway run --no-supervise\n",
            encoding="utf-8")
        fake(self.bin_dir, "ps", "exit 0\n")
        self.run_setup("--restart", ALANS_WAY_RESTART_DELAY="1")
        deadline = time.time() + 15
        while "restart main-gateway" not in read_log(self.supervisor_log) and time.time() < deadline:
            time.sleep(0.2)
        self.assertIn("signal USR1 main-gateway", read_log(self.supervisor_log))
        self.assertIn("restart main-gateway", read_log(self.supervisor_log))
        self.assertNotIn("gateway restart", read_log(self.root / "log"))

    def test_gateway_restart_retries_supervisorctl_under_sudo_n(self):
        """A supervisor socket that needs root must not strand the gateway
        restart on `hermes gateway restart`; the sudo retry is non-interactive."""
        (self.root / "supervisor.state").write_text(
            sup_line("main-gateway", "RUNNING", "pid 771, uptime 1:00:00"), encoding="utf-8")
        (self.root / "need-sudo").write_text("", encoding="utf-8")
        fake(self.bin_dir, "sudo",
             'shift; rm -f "%s"\nexec "$@"\n' % (self.root / "need-sudo"))
        fake(self.bin_dir, "ps",
             'case "$*" in *771*) echo "hermes gateway run --no-supervise";; esac\n')
        self.run_setup("--restart", ALANS_WAY_RESTART_DELAY="1")
        deadline = time.time() + 15
        while "signal USR1 main-gateway" not in read_log(self.supervisor_log) and time.time() < deadline:
            time.sleep(0.2)
        self.assertIn("signal USR1 main-gateway", read_log(self.supervisor_log))

    def test_install_retries_mutating_supervisorctl_calls_under_sudo_n(self):
        """A socket that answers reads but needs root for reread/update/
        start must not strand the install on a warn: supervisorctl_call's
        `sudo -n` retry applies to the install verbs too."""
        # Detection stays open; mutating verbs are gated until sudo unlocks
        # them, like the fixture's need-sudo flag but per-verb.
        real = self.bin_dir / "supervisorctl"
        real.rename(self.bin_dir / "supervisorctl-real")
        fake(self.bin_dir, "supervisorctl",
             'case "$1" in\n'
             '  reread|update|add|start|restart|signal) [ ! -f "%s" ] || exit 1;;\n'
             'esac\n'
             'exec "%s" "$@"\n' % (self.root / "verb-sudo", self.bin_dir / "supervisorctl-real"))
        (self.root / "verb-sudo").write_text("", encoding="utf-8")
        fake(self.bin_dir, "sudo",
             'shift; rm -f "%s"\nexec "$@"\n' % (self.root / "verb-sudo"))
        result = self.run_setup("--mac-ssh", "me@mac.tail1234.ts.net")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("reread or update failed", result.stdout)
        calls = read_log(self.supervisor_log)
        self.assertIn("reread", calls)
        self.assertIn("start alans-way-chromium", calls)

    def test_a_root_only_socket_still_counts_as_usable(self):
        """The detection probe must use supervisorctl_call's sudo -n retry
        like every other call — otherwise a socket that needs root reads as
        no daemon and the install skips with a misleading warn."""
        (self.root / "need-sudo").write_text("", encoding="utf-8")
        fake(self.bin_dir, "sudo",
             'shift; rm -f "%s"\nexec "$@"\n' % (self.root / "need-sudo"))
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("no live systemd or supervisord", result.stdout)
        self.assertIn("[program:alans-way-browser]", self.conf())

    def test_supervisord_counts_as_usable_while_another_program_is_down(self):
        # A real `supervisorctl status` exits 3 when any program is not RUNNING
        # (a host with an EXITED one-shot program): detection must not rely on its
        # exit code, only on the daemon answering.
        (self.root / "supervisor.state").write_text(
            sup_line("other-thing", "EXITED", "Oct 07 10:38 PM"), encoding="utf-8")
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[program:alans-way-browser]", self.conf())

    def test_the_drop_in_dir_comes_from_the_live_daemons_conf_include(self):
        custom = self.root / "sup"
        (custom / "conf.d").mkdir(parents=True)
        (custom / "supervisord.conf").write_text(
            "[include]\nfiles = conf.d/*.conf\n", encoding="utf-8")
        fake(self.bin_dir, "pgrep",
             'case "$*" in\n'
             '  *supervisord*) echo "499 python3 /usr/bin/supervisord -n -c %s/supervisord.conf";;\n'
             '  *) exit 1;;\n'
             'esac\n' % custom)
        env = self.env()
        del env["ALANS_WAY_SUPERVISOR_CONF_DIR"]
        result = run("--skip-plugin", "--desktop-dir", str(self.app), "--non-interactive",
                     "--hermes-home", str(self.home), env=env, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[program:alans-way-browser]",
                      (custom / "conf.d" / "alans-way.conf").read_text(encoding="utf-8"))

    def test_an_unwritable_drop_in_dir_warns_instead_of_claiming_a_write(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores the permission bits")
        self.confd.chmod(0o555)
        self.addCleanup(self.confd.chmod, 0o755)
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("could not write", result.stdout)
        self.assertNotIn("wrote %s" % (self.confd / "alans-way.conf"), result.stdout)
        self.assertNotIn("reread", read_log(self.supervisor_log))


class LiveGatewayRefusalTests(unittest.TestCase):
    """Recent Hermes refuses `plugins install --force` (a reinstall),
    `plugins update` and `plugins remove` while that profile's gateway runs
    (Hermes #70473). The refused call is queued, the gateway is drain-stopped
    once (supervisord USR1 + wait + stop, a service stop, else `hermes gateway
    stop`), the calls are replayed, and the gateway is started again either
    way. A run with nothing refused must not stop it."""

    REFUSAL = ("Cannot reinstall plugin files while the messaging gateway is"
               " running. Run hermes gateway stop, apply the change, then"
               " hermes gateway start.")

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        # A stale installed copy, so the update path reaches install --force.
        plugin = self.home / "plugins" / "alans-way"
        plugin.mkdir(parents=True)
        (plugin / "STALE").write_text("old\n", encoding="utf-8")
        self.log = self.root / "log"
        self.bin_dir = tooling(self.root, self.log)
        linux_without_systemd(self.bin_dir, self.root / "systemctl.log")
        fake(self.bin_dir, "hermes-python", "exit 1\n")

    def live_gate(self, gate, retry_fails=False, extra_log=None):
        """A hermes that plays the live-gateway guard: mutating plugins calls
        fail with Hermes's own refusal while `gate` (a shell test) holds, and
        with a plain error afterwards when retry_fails is set."""
        lines = ['echo "$*" >> "%s"' % self.log]
        if extra_log is not None:
            lines.append('echo "hermes $*" >> "%s"' % extra_log)
        lines += [
            '[ "$1" = -p ] && shift 2',
            'case "$1" in',
            '  --version) echo "hermes 0.21.5";;',
            '  plugins) case "$2" in',
            '      list) echo "alans-way";;',
            '      install|update|remove) if %s; then' % gate,
            '          echo "%s" >&2' % self.REFUSAL,
            '          exit 1',
            '        fi%s;;' % ("; echo broken >&2; exit 1" if retry_fails else ""),
            '    esac;;',
            'esac',
            'exit 0',
        ]
        fake(self.bin_dir, "hermes", "\n".join(lines) + "\n")

    def run_setup(self, **env):
        return run("--skip-browser", "--skip-services", "--non-interactive",
                   "--hermes-home", str(self.home),
                   env=env_for(self.root, self.bin_dir, self.home, **env),
                   check=False)

    def supervised_gateway(self):
        self.supervisor_log = fake_supervisord(
            self.bin_dir, self.root,
            state=sup_line("main-gateway", "RUNNING", "pid 771, uptime 1:00:00"))
        fake(self.bin_dir, "ps",
             'case "$*" in *771*) echo "hermes gateway run --no-supervise";; esac\n')

    def test_a_refusal_drain_stops_retries_and_starts_the_gateway(self):
        self.supervised_gateway()
        self.live_gate('grep "^main-gateway " "%s" | grep -q " RUNNING "'
                       % (self.root / "supervisor.state"),
                       extra_log=self.supervisor_log)
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = read_log(self.supervisor_log)
        self.assertEqual(calls.count("plugins install --force file://"), 2, calls)
        self.assertLess(calls.index("signal USR1 main-gateway"),
                        calls.index("stop main-gateway"))
        retry = calls.rindex("hermes -p default plugins install --force")
        self.assertLess(calls.index("stop main-gateway"), retry)
        self.assertLess(retry, calls.index("start main-gateway"))
        self.assertNotIn("restart main-gateway", calls)
        self.assertIn(" RUNNING ", (self.root / "supervisor.state").read_text())
        self.assertIn("started again", result.stdout)

    def test_a_run_with_nothing_refused_never_stops_the_gateway(self):
        self.supervised_gateway()
        # tooling()'s logging hermes never refuses: install --force goes through.
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("plugin updated", result.stdout)
        sup = read_log(self.supervisor_log)
        self.assertNotIn("stop", sup)
        self.assertNotIn("signal", sup)
        self.assertNotIn("start", sup)

    def test_a_failed_retry_still_starts_the_gateway(self):
        self.supervised_gateway()
        self.live_gate('grep "^main-gateway " "%s" | grep -q " RUNNING "'
                       % (self.root / "supervisor.state"),
                       retry_fails=True, extra_log=self.supervisor_log)
        result = self.run_setup()
        calls = read_log(self.supervisor_log)
        self.assertIn("stop main-gateway", calls)
        self.assertIn("start main-gateway", calls)
        self.assertLess(calls.index("stop main-gateway"),
                        calls.index("start main-gateway"))
        self.assertIn(" RUNNING ", (self.root / "supervisor.state").read_text())
        self.assertIn("still failed", result.stdout)

    def test_the_systemd_branch_stops_the_unit_and_starts_it_again(self):
        state = self.root / "unit.state"
        state.write_text("running\n", encoding="utf-8")
        fake(self.bin_dir, "systemctl",
             'echo "systemctl $*" >> "%s"\n'
             '[ "$1" = --user ] && shift\n'
             'case "$1" in\n'
             '  is-system-running) echo offline;;\n'
             '  stop) [ "$(cat "%s" 2>/dev/null)" = running ] || exit 1\n'
             '        echo stopped > "%s";;\n'
             '  start) echo running > "%s";;\n'
             'esac\nexit 0\n' % (self.log, state, state, state))
        self.live_gate('[ "$(cat "%s" 2>/dev/null)" = running ]' % state)
        result = self.run_setup(ALANS_WAY_MISSING="supervisorctl")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = read_log(self.log)
        retry = calls.rindex("plugins install --force file://")
        self.assertLess(calls.index("systemctl --user stop hermes-gateway"), retry)
        self.assertLess(retry, calls.index("systemctl --user start hermes-gateway"))
        self.assertEqual(state.read_text().strip(), "running")

    def test_without_a_service_manager_the_hermes_stop_start_pair_is_used(self):
        gwstate = self.root / "gw.state"
        gwstate.write_text("running\n", encoding="utf-8")
        fake(self.bin_dir, "hermes", 'echo "$*" >> "%s"\n'
             '[ "$1" = -p ] && shift 2\n'
             'case "$1" in\n'
             '  --version) echo "hermes 0.21.5";;\n'
             '  gateway)\n'
             '    [ "$2" = stop ] && echo stopped > "%s"\n'
             '    [ "$2" = start ] && echo running > "%s";;\n'
             '  plugins) case "$2" in\n'
             '      list) echo "alans-way";;\n'
             '      install|update|remove)\n'
             '        [ "$(cat "%s")" = running ] || exit 0\n'
             '        echo "%s" >&2; exit 1;;\n'
             '    esac;;\n'
             'esac\nexit 0\n' % (self.log, gwstate, gwstate, gwstate, self.REFUSAL))
        result = self.run_setup(ALANS_WAY_MISSING="systemctl supervisorctl")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = read_log(self.log)
        retry = calls.rindex("plugins install --force file://")
        self.assertLess(calls.index("-p default gateway stop"), retry)
        self.assertLess(retry, calls.index("-p default gateway start"))

    def test_a_failed_systemctl_stop_falls_back_to_hermes_gateway_stop(self):
        """On a systemd host whose unit stop fails (a unit that is not really
        there, while a manual `hermes gateway run` holds the profile), the
        drain-stop still has `hermes gateway stop` to try."""
        gwstate = self.root / "gw.state"
        gwstate.write_text("running\n", encoding="utf-8")
        fake(self.bin_dir, "systemctl",
             'echo "systemctl $*" >> "%s"\n'
             '[ "$1" = --user ] && shift\n'
             'case "$1" in\n'
             '  is-system-running) echo running; exit 0;;\n'
             '  stop) exit 1;;\n'
             'esac\nexit 0\n' % self.log)
        fake(self.bin_dir, "hermes", 'echo "$*" >> "%s"\n'
             '[ "$1" = -p ] && shift 2\n'
             'case "$1" in\n'
             '  --version) echo "hermes 0.21.5";;\n'
             '  gateway)\n'
             '    [ "$2" = stop ] && echo stopped > "%s"\n'
             '    [ "$2" = start ] && echo running > "%s";;\n'
             '  plugins) case "$2" in\n'
             '      list) echo "alans-way";;\n'
             '      install|update|remove)\n'
             '        [ "$(cat "%s")" = running ] || exit 0\n'
             '        echo "%s" >&2; exit 1;;\n'
             '    esac;;\n'
             'esac\nexit 0\n' % (self.log, gwstate, gwstate, gwstate, self.REFUSAL))
        result = self.run_setup(ALANS_WAY_MISSING="supervisorctl")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = read_log(self.log)
        retry = calls.rindex("plugins install --force file://")
        self.assertLess(calls.index("systemctl --user stop hermes-gateway"),
                        calls.index("-p default gateway stop"))
        self.assertLess(calls.index("-p default gateway stop"), retry)
        self.assertLess(retry, calls.index("-p default gateway start"))
        self.assertEqual(gwstate.read_text().strip(), "running")

    def test_a_registered_but_stopped_program_is_not_claimed_as_the_gateway(self):
        """The supervisor program is STOPPED yet the install was refused: the
        live gateway runs outside supervisord. Claiming the program anyway
        would skip every real stop, retry under the still-live gateway, and
        `supervisorctl start` a second poller beside it. Fall through to the
        real stops instead."""
        confd = self.root / "conf.d"
        confd.mkdir()
        (confd / "gw.conf").write_text(
            "[program:main-gateway]\ncommand=/usr/local/bin/hermes gateway run --no-supervise\n",
            encoding="utf-8")
        self.supervisor_log = fake_supervisord(
            self.bin_dir, self.root,
            state=sup_line("main-gateway", "STOPPED"))
        gwstate = self.root / "gw.state"
        gwstate.write_text("running\n", encoding="utf-8")
        fake(self.bin_dir, "systemctl",
             'echo "systemctl $*" >> "%s"\n'
             'case "$1" in is-system-running) echo offline;; esac\nexit 1\n' % self.log)
        fake(self.bin_dir, "hermes", 'echo "$*" >> "%s"\n'
             '[ "$1" = -p ] && shift 2\n'
             'case "$1" in\n'
             '  --version) echo "hermes 0.21.5";;\n'
             '  gateway)\n'
             '    [ "$2" = stop ] && echo stopped > "%s"\n'
             '    [ "$2" = start ] && echo running > "%s";;\n'
             '  plugins) case "$2" in\n'
             '      list) echo "alans-way";;\n'
             '      install|update|remove)\n'
             '        [ "$(cat "%s")" = running ] || exit 0\n'
             '        echo "%s" >&2; exit 1;;\n'
             '    esac;;\n'
             'esac\nexit 0\n' % (self.log, gwstate, gwstate, gwstate, self.REFUSAL))
        result = self.run_setup(ALANS_WAY_SUPERVISOR_CONF_DIR=str(confd))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = read_log(self.log)
        retry = calls.rindex("plugins install --force file://")
        self.assertLess(calls.index("-p default gateway stop"), retry)
        self.assertLess(retry, calls.index("-p default gateway start"))
        self.assertNotIn("still failed", result.stdout)
        sup = read_log(self.supervisor_log)
        self.assertNotIn("stop main-gateway", sup)
        self.assertNotIn("start main-gateway", sup)

    def test_a_drain_that_outlives_the_wait_is_left_running_and_refused(self):
        """USR1 was delivered but the old pid is still there when the wait
        ends: a stop now is the mid-checkpoint kill USR1 exists to avoid, so
        no stop runs at all and the op reports as still refused."""
        state_file = self.root / "supervisor.state"
        state_file.write_text(
            sup_line("main-gateway", "RUNNING", "pid 771, uptime 1:00:00"), encoding="utf-8")
        supervisor_log = self.root / "supervisorctl.log"
        fake(self.bin_dir, "supervisorctl", '''echo "$*" >> "%s"
state="%s"
case "$1" in
  status) cat "$state" 2>/dev/null || true;;
  pid) [ -n "${2:-}" ] || { echo 4321; exit 0; }
    awk -v n="$2" '$1 == n { gsub(",", "", $4); print $4 }' "$state";;
  signal) [ "$2" = USR1 ] || exit 1;;
esac
exit 0
''' % (supervisor_log, state_file))
        fake(self.bin_dir, "ps",
             'case "$*" in *771*) echo "hermes gateway run --no-supervise";; esac\n')
        self.live_gate('grep "^main-gateway " "%s" | grep -q " RUNNING "' % state_file)
        result = self.run_setup(ALANS_WAY_DRAIN_WAIT="2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        sup = read_log(supervisor_log)
        self.assertIn("signal USR1 main-gateway", sup)
        self.assertNotIn("stop main-gateway", sup)
        calls = read_log(self.log)
        self.assertEqual(calls.count("plugins install --force file://"), 1, calls)
        self.assertNotIn("gateway stop", calls)
        self.assertIn("could not stop profile default's gateway", result.stdout)
        self.assertNotIn("systemctl", read_log(self.root / "systemctl.log"))

    def test_a_replayed_computer_provider_install_selects_the_backend(self):
        """The COMPUTER_READY-gated select runs before the replay, so a
        provider whose catalog install was only applied under the drain-stop
        would stay installed but unselected. The replay selects it."""
        self.supervised_gateway()
        cfg = self.root / "cfg.state"
        fake(self.bin_dir, "hermes", 'echo "$*" >> "%s"\n'
             'echo "hermes $*" >> "%s"\n'
             '[ "$1" = -p ] && shift 2\n'
             'case "$1" in\n'
             '  --version) echo "hermes 0.21.5";;\n'
             '  plugins) case "$2" in\n'
             '      list) echo "alans-way";;\n'
             '      install|update|remove)\n'
             '        if grep "^main-gateway " "%s" | grep -q " RUNNING "; then\n'
             '          echo "%s" >&2; exit 1\n'
             '        fi;;\n'
             '    esac;;\n'
             '  config) case "$2" in\n'
             '      set) [ "$3" = computer_use.backend ] && echo "$4" > "%s";;\n'
             '      get) cat "%s" 2>/dev/null;;\n'
             '    esac;;\n'
             'esac\nexit 0\n'
             % (self.log, self.supervisor_log, self.root / "supervisor.state",
                self.REFUSAL, cfg, cfg))
        fake(self.bin_dir, "fake-python", "exit 0\n")
        result = self.run_setup(HERMES_PYTHON=str(self.bin_dir / "fake-python"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = read_log(self.supervisor_log)
        retry = calls.rindex("hermes -p default plugins install alans-way-computer")
        self.assertLess(calls.index("stop main-gateway"), retry)
        select = calls.index("hermes -p default config set computer_use.backend alans-way-computer")
        self.assertLess(calls.index("start main-gateway"), select)
        self.assertIn("computer use runs through alans-way-computer", result.stdout)
        self.assertEqual(cfg.read_text().strip(), "alans-way-computer")


class CdpPortTests(unittest.TestCase):
    """The managed browser's CDP port is configurable, preserved on re-run,
    and moves off the default when another process already owns it."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.data = self.root / "data"
        self.app = desktop_tree(self.root / "app")
        self.bin_dir = tooling(self.root, self.root / "log")
        fake(self.bin_dir, "uname", "echo Linux\n")
        fake(self.bin_dir, "google-chrome", "exit 0\n")

    def run_setup(self, *flags, **env):
        return run("--skip-plugin", "--skip-services", "--desktop-dir", str(self.app),
                   "--non-interactive", "--hermes-home", str(self.home), *flags,
                   env=env_for(self.root, self.bin_dir, self.home,
                               HERMES_VPS_BROWSER_DATA=str(self.data), **env),
                   check=False)

    def config(self):
        return json.loads((self.data / "config.json").read_text(encoding="utf-8"))

    def config_port(self):
        config = self.config()
        port = int(config["cdpUrl"].rsplit(":", 1)[1])
        self.assertIn("--remote-debugging-port=%d" % port, config["browserArgs"])
        return port

    def test_the_default_port_is_9223(self):
        self.run_setup()
        self.assertEqual(self.config_port(), 9223)

    def test_an_existing_port_is_preserved_on_rerun(self):
        self.data.mkdir(parents=True)
        (self.data / "config.json").write_text(json.dumps({
            "port": 9465, "cdpUrl": "http://127.0.0.1:9224",
            "browserCommand": "/usr/bin/google-chrome",
            "browserArgs": ["--remote-debugging-port=9224"]}), encoding="utf-8")
        self.run_setup()
        self.assertEqual(self.config_port(), 9224)
        # And a second re-run keeps it stable.
        self.run_setup()
        self.assertEqual(self.config_port(), 9224)

    def test_a_cdpurl_with_a_trailing_slash_is_still_preserved(self):
        self.data.mkdir(parents=True)
        (self.data / "config.json").write_text(json.dumps({
            "port": 9465, "cdpUrl": "http://127.0.0.1:9224/",
            "browserCommand": "/usr/bin/google-chrome",
            "browserArgs": ["--remote-debugging-port=9224"]}), encoding="utf-8")
        self.run_setup()
        self.assertEqual(self.config_port(), 9224)

    def test_cdp_port_flag_overrides_an_existing_config(self):
        self.data.mkdir(parents=True)
        (self.data / "config.json").write_text(json.dumps({
            "port": 9465, "cdpUrl": "http://127.0.0.1:9224",
            "browserCommand": "/usr/bin/google-chrome",
            "browserArgs": ["--remote-debugging-port=9224"]}), encoding="utf-8")
        self.run_setup("--cdp-port", "9330")
        self.assertEqual(self.config_port(), 9330)

    def test_cdp_port_env_overrides_the_default(self):
        self.run_setup(ALANS_WAY_CDP_PORT="9331")
        self.assertEqual(self.config_port(), 9331)

    def test_a_busy_default_port_moves_to_the_next_free_one(self):
        import socket
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", 9223))
        except OSError:
            self.skipTest("port 9223 is already bound on this machine")
        sock.listen()
        try:
            result = self.run_setup()
        finally:
            sock.close()
        self.assertNotEqual(self.config_port(), 9223)
        self.assertIn("9223 is already in use", result.stdout)

    def test_an_invalid_port_is_rejected(self):
        result = self.run_setup("--cdp-port", "abc")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--cdp-port", result.stderr)


class AgentSshProxyTests(unittest.TestCase):
    """On a userspace-networking Tailscale host (no tailscale0 interface) the
    managed ssh block reaches tailnet addresses through `tailscale nc`."""

    HOST = "mac.tail1234.ts.net"

    def setup_run(self, tun):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        bin_dir = tooling(self.root, self.root / "log")
        fake(bin_dir, "uname", "echo Linux\n")
        ts = TAILSCALE_UP
        if tun is not None:
            ts = ts.replace('"BackendState":"Running"',
                            '"BackendState":"Running","TUN":%s' % tun)
        fake(bin_dir, "tailscale", ts)
        self.config = self.root / ".ssh" / "config"
        sysnet = self.root / "sysnet"
        sysnet.mkdir()
        if tun == "true":
            (sysnet / "tailscale0").touch()
        env = env_for(self.root, bin_dir, self.home,
                      ALANS_WAY_SYS_CLASS_NET=str(sysnet))
        return run("--mac-ssh", "me@" + self.HOST, "--skip-browser", "--skip-services",
                   "--non-interactive", "--hermes-home", str(self.home), env=env, check=False)

    def test_userspace_tailscale_gets_a_proxycommand(self):
        result = self.setup_run(tun="false")
        text = self.config.read_text()
        # The ProxyCommand must be its own line ending after %p: a literal "\n"
        # would merge it with the ControlMaster line and break ssh outright.
        self.assertIn("  ProxyCommand tailscale nc %h %p\n", text)
        self.assertIn("nc %h %p\n  ControlMaster auto", text)

    def test_kernel_tailscale_gets_no_proxycommand(self):
        for tun in ("true", None):
            self.setup_run(tun=tun)
            self.assertNotIn("ProxyCommand", self.config.read_text(), tun)


class ProviderVerifyTests(unittest.TestCase):
    """--verify reports a provider that is installed but not selected, and the
    Linux desktop pieces its VM-side path needs."""

    def setup_env(self, directory, *, linux=False, provider_dir=False, backend="",
                  tools="enabled proactivity"):
        root = Path(directory)
        home = root / "home"
        home.mkdir()
        if provider_dir:
            (home / "plugins" / "alans-way-computer").mkdir(parents=True)
        (home / "config.yaml").write_text(
            "mcp_servers:\n"
            "# >>> alans-way workspace_browser managed block >>>\n"
            "  workspace_browser:\n    command: node\n"
            "    tools:\n      exclude:\n        - workspace_computer_action\n"
            "# <<< alans-way workspace_browser managed block <<<\n", encoding="utf-8")
        bin_dir = Path(directory) / "bin"
        bin_dir.mkdir()
        hermes = bin_dir / "hermes"
        plugin_list = "alans-way\\n" + ("alans-way-computer\\n" if provider_dir else "")
        hermes.write_text("""#!/bin/sh
[ "$1" = -p ] && shift 2
case "$1" in
  --version) echo "hermes 0.21.5";;
  plugins) [ "$2" = list ] && printf '%%b' '%s';;
  tools) [ "$2" = list ] && echo "%s";;
  config) [ "$2" = get ] && [ "$3" = computer_use.backend ] && echo "%s";;
  proactivity) [ "$2" = status ] && echo '{"bound":true,"paused":false,"timezone_known":true}';;
esac
exit 0
""" % (plugin_list, tools, backend), encoding="utf-8")
        hermes.chmod(0o755)
        if linux:
            fake(bin_dir, "uname", "echo Linux\n")
        return env_for(root, bin_dir, home)

    def test_installed_but_unselected_provider_is_flagged(self):
        with tempfile.TemporaryDirectory() as directory:
            env = self.setup_env(directory, provider_dir=True, backend="")
            result = run("--verify", env=env, check=False)
            self.assertIn("installed but", result.stdout)
            self.assertIn("config set computer_use.backend alans-way-computer", result.stdout)

    def test_a_selected_provider_runs_the_doctor_not_the_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            env = self.setup_env(directory, provider_dir=True, backend="alans-way-computer")
            result = run("--verify", env=env, check=False)
            self.assertNotIn("installed but", result.stdout)

    def test_linux_desktop_deps_are_checked_when_the_provider_is_present(self):
        with tempfile.TemporaryDirectory() as directory:
            env = self.setup_env(directory, linux=True, provider_dir=True, backend="alans-way-computer")
            # A real at-spi bus running on the dev host would mask the warning.
            fake(Path(directory) / "bin", "pgrep", "exit 1\n")
            env["ALANS_WAY_MISSING"] = "at-spi-bus-launcher xdotool scrot import maim"
            result = run("--verify", env=env, check=False)
            self.assertIn("at-spi", result.stdout)
            self.assertIn("xdotool", result.stdout)

    def test_no_desktop_dep_warnings_without_the_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            env = self.setup_env(directory, linux=True, provider_dir=False, backend="")
            result = run("--verify", env=env, check=False)
            self.assertNotIn("at-spi", result.stdout)


class VerifyExtrasTests(unittest.TestCase):
    """--verify surfaces a missing proactivity timezone and a stale watcher."""

    def setup_env(self, directory, proactivity_status):
        root = Path(directory)
        home = root / "home"
        home.mkdir()
        bin_dir = fake_hermes_bin(root, plugins="alans-way", tools="enabled proactivity",
                                  proactivity_status=proactivity_status)
        return env_for(root, bin_dir, home), home

    def test_verify_warns_when_the_timezone_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            env, _ = self.setup_env(directory, '{"bound":true,"paused":false,"timezone_known":false}')
            result = run("--verify", "--skip-browser", env=env, check=False)
            self.assertIn("timezone", result.stdout)
            self.assertRegex(result.stdout, r"warn .*timezone")

    def test_no_timezone_warning_when_known_or_unreported(self):
        for status in ('{"bound":true,"paused":false,"timezone_known":true}',
                       '{"bound":true,"paused":false}'):
            with tempfile.TemporaryDirectory() as directory:
                env, _ = self.setup_env(directory, status)
                result = run("--verify", "--skip-browser", env=env, check=False)
                self.assertNotRegex(result.stdout, r"warn .*timezone", status)

    def test_verify_warns_on_a_stale_watcher_state_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env, home = self.setup_env(directory, '{"bound":true,"paused":false,"timezone_known":true}')
            state = Path(directory) / "mac-state.json"
            state.write_text('{"state":"online"}', encoding="utf-8")
            old = time.time() - 3600
            os.utime(state, (old, old))
            env["HERMES_MAC_STATE_FILE"] = str(state)
            result = run("--verify", "--skip-browser", "--mac-ssh", "me@mac.tail1234.ts.net",
                         env=env, check=False)
            self.assertIn("stale", result.stdout)

    def test_verify_is_quiet_about_a_fresh_watcher_state_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env, home = self.setup_env(directory, '{"bound":true,"paused":false,"timezone_known":true}')
            state = Path(directory) / "mac-state.json"
            state.write_text('{"state":"online"}', encoding="utf-8")
            env["HERMES_MAC_STATE_FILE"] = str(state)
            result = run("--verify", "--skip-browser", "--mac-ssh", "me@mac.tail1234.ts.net",
                         env=env, check=False)
            self.assertNotIn("stale", result.stdout)


class GitAttributesTests(unittest.TestCase):
    def test_scripts_setup_runs_are_lf_in_every_checkout(self):
        files = ["setup.sh", "setup-workspace.sh", "alans-way/scripts/mac-watch.sh", "alans-way/scripts/workspace-router.cjs",
                 "scripts/check_publication.py", "alans-way/__init__.py", "deploy/mac-watch.service",
                 "deploy/browser-exec-chromium.service"]
        out = subprocess.run(["git", "check-attr", "eol", "--", *files], cwd=ROOT, capture_output=True, text=True).stdout
        for f in files:
            self.assertIn(f"{f}: eol: lf", out)


if __name__ == "__main__":
    unittest.main()
