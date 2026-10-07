"""setup.sh CLI: verify strictness, bot-id derivation, timezone, and doc flags."""
from pathlib import Path
import json
import os
import re
import shutil
import stat
import subprocess
import signal
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import importlib.util

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
            (home / "hooks" / "alans-way").mkdir(parents=True)
            (home / "hooks" / "alans-way" / "handler.py").write_text("# stub\n", encoding="utf-8")
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
            (home / "hooks" / "alans-way").mkdir(parents=True)
            (home / "hooks" / "alans-way" / "handler.py").write_text("# stub\n", encoding="utf-8")
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
            (home / "hooks" / "alans-way").mkdir(parents=True)
            (home / "hooks" / "alans-way" / "handler.py").write_text("# stub\n", encoding="utf-8")
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


def logging_hermes_bin(directory: Path, log: Path, version="0.21.5"):
    bin_dir = directory / "bin"
    bin_dir.mkdir(exist_ok=True)
    hermes = bin_dir / "hermes"
    hermes.write_text(f"""#!/bin/sh
echo "$*" >> "{log}"
[ "$1" = -p ] && shift 2
case "$1" in
  --version) echo "hermes {version}";;
  plugins) [ "$2" = list ] && echo "alans-way";;
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
                PATH=str(bin_dir) + os.pathsep + os.environ["PATH"], **extra)


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
            (home / "plugins" / ".install-metadata.json").write_text(
                '{"alans-way": {"source": "catalog", "catalog": {"name": "alans-way", '
                '"sha": "3a74614aa6ef43353500553526325c2fc33da9e5"}, "pinned": true}}',
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
            (home / "profiles" / "sprk1").mkdir(parents=True)
            (home / "sessions").mkdir()
            (home / "sessions" / "sessions.json").write_text(
                '{"agent:main:telegram:dm:1": {"platform": "telegram", "chat_type": "dm"},'
                ' "agent:sprk1:telegram:dm:1": {"platform": "telegram", "chat_type": "dm"}}',
                encoding="utf-8",
            )
            log = Path(directory) / "log"
            bin_dir = logging_hermes_bin(Path(directory), log)
            env = dict(os.environ, HERMES_HOME=str(home), PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            result = run(
                "--profile", "sprk1", "--bind", "--proactive", "yes", "--timezone", "Europe/Berlin",
                "--non-interactive", "--skip-browser", "--skip-services", "--hermes-home", str(home),
                env=env, check=False,
            )
            calls = log.read_text(encoding="utf-8")
            self.assertIn("bound primary route: sprk1", result.stdout)
            self.assertIn("-p sprk1 proactivity bind --session-key agent:sprk1:telegram:dm:1", calls)
            self.assertIn("-p sprk1 config set plugins.entries.alans-way.allow_gateway_injection true", calls)
            self.assertIn("-p sprk1 proactivity probe", calls)
            self.assertIn("proactivity on by default", result.stdout)

    def test_proactive_no_pauses_before_the_probe(self):
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
            self.assertIn("proactivity pause", calls)
            self.assertLess(calls.index("proactivity pause"), calls.index("proactivity probe"))

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
            prof = home / "profiles" / "sprk1"
            prof.mkdir(parents=True)
            route = "agent:sprk1:telegram:dm:42"
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
                "--profile", "sprk1", "--bind", "--proactive", "yes",
                "--non-interactive", "--skip-browser", "--skip-services",
                "--hermes-home", str(home),
                env=env, check=False,
            )
            calls = log.read_text(encoding="utf-8")
            self.assertIn("bound primary route: sprk1", result.stdout)
            self.assertIn("-p sprk1 proactivity bind --session-key agent:sprk1:telegram:dm:42", calls)


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
            (home / "profiles" / "sprk1").mkdir(parents=True)
            log = root / "log"
            bin_dir = tooling(root, log)
            run("--profile", "sprk1", "--bot-id", "111222333", "--skip-browser", "--skip-services",
                "--non-interactive", "--restart", "--hermes-home", str(home),
                env=env_for(root, bin_dir, home, ALANS_WAY_RESTART_DELAY="0"))
            time.sleep(1)
            calls = [line for line in read_log(log).splitlines() if not line.startswith("--version")]
            self.assertTrue(any("plugins install" in line for line in calls))
            self.assertTrue(any("tools enable proactivity" in line for line in calls))
            self.assertTrue(any("gateway restart" in line for line in calls))
            for line in calls:
                self.assertTrue(line.startswith("-p sprk1 "), line)

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
            plugins = home / "profiles" / "sprk1" / "plugins"
            (plugins / "alans-way").mkdir(parents=True)
            (plugins / ".install-metadata.json").write_text(
                '{"alans-way": {"source": "catalog", "catalog": {"name": "alans-way", "sha": "3a74614"}}}',
                encoding="utf-8")
            log = root / "log"
            bin_dir = tooling(root, log)
            result = run("--profile", "sprk1", "--skip-browser", "--skip-services", "--non-interactive",
                         env=env_for(root, bin_dir, home), check=False)
            self.assertIn("leaving its pin in place", result.stdout)
            self.assertNotIn("plugins install", read_log(log))


class RestartOrderTests(unittest.TestCase):
    def test_restart_is_last_and_detached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            (home / "profiles" / "sprk1").mkdir(parents=True)
            (home / "sessions").mkdir()
            (home / "sessions" / "sessions.json").write_text(
                '{"agent:sprk1:telegram:dm:1": {"platform": "telegram", "chat_type": "dm"}}', encoding="utf-8")
            log = root / "log"
            bin_dir = tooling(root, log)
            result = run("--profile", "sprk1", "--bind", "--timezone", "Europe/Berlin", "--restart",
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
            self.assertTrue(any("proactivity bind --session-key agent:sprk1:telegram:dm:1 --timezone Europe/Berlin" in line
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
        self.assertIn("built-in browser toolset disabled", result.stdout)
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
        fake(self.bin_dir, "systemctl", 'echo "$*" >> "%s"\nexit 0\n' % self.systemctl_log)
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
        return run("--skip-plugin", "--desktop-dir", str(self.app), "--non-interactive",
                   "--hermes-home", str(self.home), env=env, check=False)

    def config(self):
        return json.loads((self.data / "config.json").read_text(encoding="utf-8"))

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
        self.assertNotRegex(readme, r"(?m)^hooks/")
        self.assertTrue((ROOT / "alans-way" / "gateway-hook").is_dir())


class GatewayGuardPortabilityTests(unittest.TestCase):
    def test_private_state_writes_where_os_fchmod_is_missing(self):
        spec = importlib.util.spec_from_file_location("guard_without_fchmod", ROOT / "alans-way" / "gateway_guard.py")
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        saved = os.fchmod
        del os.fchmod
        try:
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "state" / "value.json"
                guard.write_private_json(target, {"ok": True})
                self.assertEqual(json.loads(target.read_text()), {"ok": True})
        finally:
            os.fchmod = saved


class WindowsGuestPluginTests(unittest.TestCase):
    """Native Windows has no fcntl, O_NOFOLLOW, fchmod, /proc or ps, and its default home is %LOCALAPPDATA%\\hermes."""

    def load(self, name):
        path = ROOT / "alans-way"
        spec = importlib.util.spec_from_file_location(name, path / "__init__.py", submodule_search_locations=[str(path)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(lambda: [sys.modules.pop(k) for k in [k for k in sys.modules if k == name or k.startswith(name + ".")]])
        spec.loader.exec_module(module)
        return module

    def test_state_and_observation_work_without_the_posix_only_apis(self):
        calls = []
        fake_msvcrt = types.SimpleNamespace(LK_LOCK=1, LK_UNLCK=0, locking=lambda fd, mode, size: calls.append(mode))
        saved = {name: getattr(os, name) for name in ("fchmod", "O_NOFOLLOW")}
        for name in saved:
            delattr(os, name)
        try:
            with patch.dict(sys.modules, {"fcntl": None, "msvcrt": fake_msvcrt}):
                plugin = self.load("windows_guest_plugin_test")
                context, core, observe = (importlib.import_module(plugin.__name__ + "." + name)
                                          for name in ("proactive_context", "proactive_core", "proactive_observe"))
                with tempfile.TemporaryDirectory() as directory:
                    home = Path(directory)
                    with context.Ledger(home / "ledger").transaction() as data:
                        data["tasks"]["a"] = {"id": "a"}
                    core.Store(home / "store")
                    (home / "SOUL.md").write_text("be kind\r\n", encoding="utf-8")
                    seen = observe.read_source(home, "SOUL.md")
                    self.assertEqual(seen["text"], "be kind\r\n")
        finally:
            for name, value in saved.items():
                setattr(os, name, value)
        self.assertEqual(calls, [1, 0])

    def test_sqlite_is_opened_by_file_uri_not_a_pasted_path(self):
        for name in ("proactive_operator.py", "proactive_board.py"):
            source = (ROOT / "alans-way" / name).read_text(encoding="utf-8")
            self.assertNotIn('f"file:{', source, name)
            self.assertIn(".as_uri()", source, name)

    def test_the_default_home_is_localappdata_on_native_windows(self):
        spec = importlib.util.spec_from_file_location("guard_on_windows", ROOT / "alans-way" / "gateway_guard.py")
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        with tempfile.TemporaryDirectory() as directory:
            env = {k: v for k, v in os.environ.items() if k != "HERMES_HOME"}
            env["LOCALAPPDATA"] = directory
            with patch.dict(os.environ, env, clear=True), patch.object(guard.sys, "platform", "win32"):
                self.assertEqual(guard.hermes_home(), (Path(directory) / "hermes").absolute())
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(guard.hermes_home(), (Path.home() / ".hermes").absolute())

    def test_the_startup_hook_arms_the_windows_default_home(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory).resolve()
            home = local / "hermes"
            hook = home / "hooks" / "alans-way"
            hook.mkdir(parents=True)
            shutil.copy(ROOT / "alans-way" / "gateway-hook" / "handler.py", hook / "handler.py")
            (home / "plugins" / "alans-way").mkdir(parents=True)
            shutil.copy(ROOT / "alans-way" / "gateway_guard.py", home / "plugins" / "alans-way" / "gateway_guard.py")
            spec = importlib.util.spec_from_file_location("hook_on_windows", hook / "handler.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            env = {k: v for k, v in os.environ.items() if k != "HERMES_HOME"}
            env["LOCALAPPDATA"] = str(local)
            with patch.dict(os.environ, env, clear=True), patch.object(module.sys, "platform", "win32"):
                module.handle("gateway:startup", {})
            self.assertTrue((home / "companion" / "proactivity" / "gateway-owner.json").exists())

    def test_process_start_comes_from_psutil_where_there_is_no_proc_or_ps(self):
        spec = importlib.util.spec_from_file_location("guard_psutil", ROOT / "alans-way" / "gateway_guard.py")
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        begun = time.time() - 300
        fake_psutil = types.SimpleNamespace(Process=lambda pid=None: types.SimpleNamespace(create_time=lambda: begun))
        with patch.dict(sys.modules, {"psutil": fake_psutil}):
            started = guard._process_started_at()
        self.assertAlmostEqual(started.timestamp(), begun, delta=1)

    def test_a_host_with_no_psutil_and_no_ps_degrades_to_the_registration_window(self):
        spec = importlib.util.spec_from_file_location("guard_blind", ROOT / "alans-way" / "gateway_guard.py")
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        with patch.dict(sys.modules, {"psutil": None}), patch("subprocess.check_output", side_effect=FileNotFoundError("ps")):
            started = guard._process_started_at()
        self.assertTrue(started is None or started.tzinfo is not None)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            guard.mark_gateway_ready(home)
            with patch.object(guard, "_process_started_at", return_value=None):
                self.assertTrue(guard.gateway_ready(home, guard.datetime.now(guard.timezone.utc)))


class GatewayHookProfileTests(unittest.TestCase):
    """The handler copy under <home>/profiles/<name>/hooks must still arm the launch home."""

    def install(self, plugin_home: Path, where: Path):
        hook = where / "hooks" / "alans-way"
        hook.mkdir(parents=True)
        shutil.copy(ROOT / "alans-way" / "gateway-hook" / "handler.py", hook / "handler.py")
        plugin = plugin_home / "plugins" / "alans-way"
        if not plugin.exists():
            plugin.mkdir(parents=True)
            shutil.copy(ROOT / "alans-way" / "gateway_guard.py", plugin / "gateway_guard.py")
        spec = importlib.util.spec_from_file_location("hook_under_test_%d" % id(hook), hook / "handler.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def marker(self, home: Path) -> Path:
        return home / "companion" / "proactivity" / "gateway-owner.json"

    def test_profile_copy_arms_the_profile_and_the_launch_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            profile = root / "profiles" / "sprk1"
            profile.mkdir(parents=True)
            module = self.install(root, profile)
            with patch.dict(os.environ, {"HERMES_HOME": str(root)}):
                module.handle("gateway:startup", {})
            self.assertTrue(self.marker(profile).exists())
            self.assertTrue(self.marker(root).exists())

    def test_profile_copy_for_a_profile_gateway_does_not_touch_the_root_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            profile = root / "profiles" / "sprk1"
            profile.mkdir(parents=True)
            module = self.install(profile, profile)
            with patch.dict(os.environ, {"HERMES_HOME": str(profile)}):
                module.handle("gateway:startup", {})
            self.assertTrue(self.marker(profile).exists())
            self.assertFalse(self.marker(root).exists())

    def test_a_copy_under_an_unrelated_home_stays_inert(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            other = root / "elsewhere"
            profile = root / "profiles" / "sprk1"
            profile.mkdir(parents=True)
            other.mkdir()
            module = self.install(root, profile)
            with patch.dict(os.environ, {"HERMES_HOME": str(other)}):
                module.handle("gateway:startup", {})
            self.assertFalse(self.marker(profile).exists())
            self.assertFalse(self.marker(other).exists())


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
        fake(self.bin_dir, "systemctl", "exit 0\n")
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
        key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl me@mac"
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
        fake(self.bin_dir, "systemctl", "exit 0\n")
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
            self.assertTrue((root / "hermes" / "hooks" / "alans-way" / "handler.py").exists())
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
        fake(bin_dir, "systemctl", 'case "$*" in *--user*) exit %d;; esac\nexit 0\n' % (0 if user_systemd else 1))
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
    def run_setup(self, *flags, tools_fake=None, python_ok=True, config_get=""):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        home = self.root / "home"
        home.mkdir()
        self.home = home
        self.log = self.root / "log"
        bin_dir = tooling(self.root, self.log)
        fake(bin_dir, "hermes", 'echo "$*" >> "%s"\n[ "$1" = -p ] && shift 2\ncase "$1" in\n'
             '  --version) echo "hermes 0.21.5";;\n  plugins) [ "$2" = list ] && echo "alans-way";;\n'
             '  config) [ "$2" = get ] && { echo \'%s\'; };;\nesac\nexit 0\n' % (self.log, config_get))
        fake(bin_dir, "hermes-python", "exit %d\n" % (0 if python_ok else 1))
        self.env = env_for(self.root, bin_dir, home, HERMES_PYTHON=str(bin_dir / "hermes-python"))
        return run("--bot-id", "111222333", "--skip-browser", "--skip-services", "--non-interactive",
                   "--hermes-home", str(home), *flags, env=self.env, check=False,
                   script=repo_with_computer_plugin(self.root))


class ProactivityIntegrationTests(IntegrationBase, unittest.TestCase):
    def test_the_proactivity_toolset_is_enabled_for_cron_wakes_too(self):
        self.run_setup()
        calls = read_log(self.log)
        self.assertIn("tools enable proactivity --platform telegram", calls)
        self.assertIn("tools enable proactivity --platform cron", calls)

    def test_summary_names_the_two_ways_to_approve_a_watch(self):
        result = self.run_setup()
        self.assertIn("/watch approve", result.stdout)
        self.assertIn("button", result.stdout)

    def test_bind_falls_back_to_configure_when_bind_rejects_the_timezone_flag(self):
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
        self.assertIn("proactivity configure", calls)


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
        self.assertRegex(read_log(self.log), r"plugins install --force file://\S+#alans-way-computer")

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
        self.assertRegex(calls, r"-p work plugins install --force file://\S+#alans-way-computer")
        self.assertIn("-p work plugins enable alans-way-computer", calls)
        self.assertIn("-p work config set computer_use.backend alans-way-computer", calls)
        self.assertLess(calls.index("plugins install"), calls.index("computer_use.backend"))

    def test_without_the_provider_api_the_stock_computer_use_toolset_is_turned_off(self):
        result = self.run_setup(python_ok=False)
        calls = read_log(self.log)
        self.assertIn("-p default tools disable computer_use --platform telegram\n", calls)
        self.assertIn("--keep-computer-use", result.stdout)
        self.assertIn("tools enable computer_use --platform telegram", result.stdout)

    def test_with_the_provider_api_the_toolset_is_left_to_the_provider(self):
        self.run_setup(python_ok=True)
        self.assertNotIn("tools disable computer_use", read_log(self.log))

    def test_keep_computer_use_leaves_the_stock_toolset_on(self):
        result = self.run_setup("--keep-computer-use", python_ok=False)
        self.assertNotIn("tools disable computer_use", read_log(self.log))
        self.assertIn("--keep-computer-use", result.stdout)

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
        for name in ("familydental", "manda", "botless", "f4f", "quoted"):
            (profiles / name).mkdir(parents=True)
        (profiles / "familydental" / "config.yaml").write_text(
            "model:\n  default: x\nplatforms:\n  telegram:\n    enabled: true\n    token: \"222:%s\"\n" % self.TOKEN, encoding="utf-8")
        (profiles / "quoted" / "config.yaml").write_text(
            "platforms:\n  telegram:\n    botToken: '555:%s'  # mine\n" % self.TOKEN, encoding="utf-8")
        (profiles / "manda" / ".env").write_text("OTHER=1\nTELEGRAM_BOT_TOKEN=333:%s\n" % self.TOKEN, encoding="utf-8")
        (profiles / "f4f" / ".env").write_text("TELEGRAM_BOT_TOKEN=444:%s\n" % self.TOKEN, encoding="utf-8")
        (profiles / "f4f" / "config.yaml").write_text(
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
             '    [ "$2" = install ] && [ "$P" != default ] && case "$*" in *--force*) ;; *) echo BLOCKED community source >&2; exit 1;; esac;;\n%s\nesac\nexit 0\n' % (log, listed, hermes_extra))
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
        for name, bot in (("familydental", "222"), ("manda", "333"), ("f4f", "444"), ("quoted", "555")):
            self.assertEqual(self.ids(home, name), [bot], name)
        self.assertFalse((home / "profiles" / "botless" / "config.yaml").read_text().count("workspace_browser"))
        self.assertNotIn(self.TOKEN, result.stdout + result.stderr)

    def test_legacy_router_entries_are_removed_and_reported(self):
        result, home, calls = self.run_all()
        config = (home / "profiles" / "f4f" / "config.yaml").read_text()
        self.assertNotIn("cua_alans_way", config)
        self.assertEqual(config.count("workspace_browser:"), 1)
        self.assertIn("removed unmanaged mcp_servers entry cua_alans_way_vps", result.stdout)
        self.assertEqual(len(list((home / "profiles" / "f4f").glob("config.yaml.bak-*"))), 1)

    def test_each_profile_gets_the_per_profile_work_but_only_the_primary_is_bound(self):
        result, home, calls = self.run_all()
        for name in ("default", "familydental", "manda", "f4f", "quoted"):
            for needed in ("tools disable browser --platform telegram", "config set computer_use.backend alans-way-computer"):
                self.assertIn("-p %s %s" % (name, needed), calls, (name, needed))
        self.assertIn("-p default tools enable proactivity --platform cron", calls)
        self.assertNotIn("proactivity --platform", calls.replace("-p default tools enable proactivity", ""))
        self.assertNotIn("-p botless tools disable browser", calls)
        self.assertNotIn("proactivity bind", calls)

    def test_the_plugin_is_force_installed_into_bot_profiles_that_have_no_catalog_install(self):
        result, home, calls = self.run_all(listed='[ "$P" = default ] && echo alans-way')
        for name in ("familydental", "manda", "f4f", "quoted"):
            self.assertRegex(calls, r"-p %s plugins install --force file://\S+#alans-way\n" % name)
            self.assertIn("-p %s plugins enable alans-way\n" % name, calls)
            self.assertIn("plugin installed in profile %s" % name, result.stdout)
        self.assertNotRegex(calls, r"-p botless plugins install \S+#alans-way\n")
        self.assertNotIn("allow_gateway_injection", calls.split("-p familydental", 1)[1].split("\n")[0])

    def test_an_installed_plugin_in_a_bot_profile_is_left_alone_with_the_update_command(self):
        result, home, calls = self.run_all(listed='[ "$P" = default ] || [ "$P" = manda ] && echo alans-way')
        self.assertNotRegex(calls, r"-p manda plugins install \S+#alans-way\n")
        self.assertIn("hermes -p manda plugins update alans-way", result.stdout)
        self.assertNotRegex(calls, r"-p manda plugins install --force \S+#alans-way\n")

    def test_a_catalog_install_in_a_bot_profile_is_never_replaced(self):
        def layout(home):
            self.layout(home)
            plugins = home / "profiles" / "manda" / "plugins"
            (plugins / "alans-way").mkdir(parents=True)
            (plugins / ".install-metadata.json").write_text(
                '{"alans-way": {"catalog": {"name": "alans-way", "sha": "3a74614"}}}', encoding="utf-8")
        result, home, calls = self.run_all(layout=layout, listed='[ "$P" = default ] || [ "$P" = manda ] && echo alans-way')
        self.assertNotRegex(calls, r"-p manda plugins install \S+#alans-way\n")
        self.assertNotRegex(calls, r"-p manda plugins install --force \S+#alans-way\n")

    def test_a_provider_install_is_forced_unless_the_profile_has_a_catalog_install(self):
        def layout(home):
            self.layout(home)
            plugins = home / "profiles" / "manda" / "plugins"
            plugins.mkdir(parents=True)
            (plugins / ".install-metadata.json").write_text(
                '{"alans-way-computer": {"catalog": {"name": "alans-way-computer", "sha": "3a74614"}}}', encoding="utf-8")
        result, home, calls = self.run_all(layout=layout)
        self.assertRegex(calls, r"-p familydental plugins install --force file://\S+#alans-way-computer\n")
        self.assertIn("-p familydental config set computer_use.backend alans-way-computer", calls)
        self.assertNotRegex(calls, r"-p manda plugins install [^\n]*alans-way-computer")

    def test_without_the_provider_api_every_profile_loses_the_stock_computer_use_toolset(self):
        result, home, calls = self.run_all(python_ok=False)
        for name in ("default", "familydental", "manda", "f4f", "quoted"):
            self.assertIn("-p %s tools disable computer_use --platform telegram\n" % name, calls, name)
        self.assertNotIn("-p botless tools disable computer_use", calls)
        self.assertNotIn("config set computer_use.backend", calls)
        _, _, kept = self.run_all("--keep-computer-use", python_ok=False)
        self.assertNotIn("tools disable computer_use", kept)

    def test_a_users_cua_driver_server_is_kept_and_warned_about_once_per_profile(self):
        def layout(home):
            self.layout(home)
            manda = home / "profiles" / "manda" / "config.yaml"
            manda.write_text("mcp_servers:\n  cua-driver:\n    command: cua-driver\n    args: [mcp]\n", encoding="utf-8")
            quoted = home / "profiles" / "quoted" / "config.yaml"
            quoted.write_text(quoted.read_text() + "mcp_servers:\n  desk:\n    command: npx\n    args: [-y, cua-driver, mcp]\n", encoding="utf-8")
        result, home, calls = self.run_all(layout=layout)
        self.assertEqual(result.stdout.count("hermes -p manda mcp remove cua-driver"), 1)
        self.assertEqual(result.stdout.count("hermes -p quoted mcp remove desk"), 1)
        self.assertNotIn("mcp remove cua-driver", result.stdout.replace("hermes -p manda mcp remove cua-driver", ""))
        self.assertIn("two computer-use paths", result.stdout)
        self.assertIn("cua-driver:", (home / "profiles" / "manda" / "config.yaml").read_text())
        self.assertNotIn("mcp remove", calls)

    def test_keep_browser_applies_to_every_profile(self):
        _, _, calls = self.run_all("--keep-browser")
        self.assertNotIn("tools disable browser", calls)

    def test_a_named_profile_limits_the_run_to_that_profile(self):
        _, home, calls = self.run_all("--profile", "manda")
        self.assertEqual(self.ids(home, "manda"), ["333"])
        self.assertFalse((home / "config.yaml").exists())
        self.assertNotIn("workspace_browser", (home / "profiles" / "familydental" / "config.yaml").read_text())
        self.assertNotIn("-p familydental", calls)

    def test_an_explicit_bot_id_is_the_primary_s_only(self):
        _, home, _ = self.run_all("--bot-id", "999")
        self.assertEqual(self.ids(home), ["999"])
        self.assertEqual(self.ids(home, "familydental"), ["222"])


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
    EXTRA = ('  tools) [ "$2" = list ] && { [ "$P" = manda ] && echo "enabled browser"; echo "enabled proactivity"; };;\n'
             '  config) [ "$2" = get ] && echo alans-way-computer;;\n'
             '  computer-use) [ "$P" = familydental ] && exit 1;;')

    def test_verify_covers_the_other_profiles_and_lists_the_skipped(self):
        def layout(home):
            self.layout(home)
            bad = home / "profiles" / "aaa-bad"
            bad.mkdir()
            (bad / "config.yaml").write_bytes(b"\xff\xfe")
        self.run_all(layout=layout, hermes_extra=self.EXTRA)
        result = run("--verify", "--hermes-home", str(self.root / "home"), env=self.env, check=False, script=self.script)
        out = result.stdout
        for name in ("familydental", "manda", "f4f", "quoted"):
            self.assertRegex(out, r"ok   workspace_browser block in \S*profiles/%s/config.yaml" % name)
        self.assertIn("profile botless has no Telegram bot of its own", out)
        self.assertIn("profile aaa-bad was not checked: config.yaml is not valid UTF-8 text", out)
        self.assertIn("browser' toolset still enabled for telegram in profile manda", out)
        self.assertRegex(out, r"FAIL .*hermes -p familydental computer-use doctor")
        self.assertNotRegex(out, r"FAIL .*-p manda computer-use")
        keep = run("--verify", "--keep-browser", "--hermes-home", str(self.root / "home"), env=self.env, check=False, script=self.script)
        self.assertNotIn("still enabled for telegram in profile", keep.stdout)

    def test_verify_checks_the_stock_computer_use_toolset_when_the_provider_is_not_selected(self):
        extra = ('  tools) [ "$2" = list ] && { [ "$P" = manda ] && echo "enabled computer_use"; echo "enabled proactivity"; };;\n'
                 '  config) [ "$2" = get ] && echo "";;')
        self.run_all(hermes_extra=extra)
        verify = lambda *flags: run("--verify", *flags, "--hermes-home", str(self.root / "home"),
                                   env=self.env, check=False, script=self.script).stdout
        out = verify()
        self.assertIn("computer_use' toolset still enabled for telegram in profile manda", out)
        self.assertRegex(out, r"ok   .*computer_use toolset disabled for telegram in profile familydental")
        self.assertNotIn("computer_use' toolset still enabled", verify("--keep-computer-use"))


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
