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
    def test_non_interactive_uses_vps_timezone_when_not_utc(self):
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
            self.assertIn("using VPS timezone America/Denver", result.stdout)


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

    def test_mac_reads_the_localtime_link(self):
        result = self.attempt("mac", {"readlink /etc/localtime": "/var/db/timezone/zoneinfo/Europe/Berlin"})
        self.assertIn("from your computer", result.stdout)
        self.assertIn("--timezone Europe/Berlin", self.calls)

    def test_linux_asks_timedatectl(self):
        self.attempt("linux", {"timedatectl show -p Timezone --value": "America/Chicago"})
        self.assertIn('--timezone America/Chicago', self.calls)

    def test_windows_zone_ids_are_mapped_to_iana(self):
        self.attempt("windows", {"tzutil /g": "W. Europe Standard Time"})
        self.assertIn("--timezone Europe/Berlin", self.calls)
        self.attempt("windows", {"tzutil /g": "Pacific Standard Time"})
        self.assertIn('--timezone America/Los_Angeles', self.calls)

    def test_explicit_flag_wins_and_skips_the_ssh_lookup(self):
        self.attempt("mac", {"readlink": "Europe/Berlin"}, "--timezone", "Asia/Tokyo")
        self.assertIn('--timezone Asia/Tokyo', self.calls)
        self.assertNotIn("readlink", read_log(self.ssh_log))

    def test_timedatectl_n_a_and_other_shapeless_answers_are_rejected(self):
        for reply in ("n/a", "Local", "garbage"):
            result = self.attempt("linux", {"timedatectl show -p Timezone --value": reply})
            self.assertNotIn("from your computer", result.stdout, reply)
        result = self.attempt("linux", {"timedatectl show -p Timezone --value": "UTC"})
        self.assertIn("from your computer", result.stdout)

    def test_unusable_answers_are_ignored(self):
        for reply in ("not a zone!", "../../etc/passwd", "Mars Standard Time"):
            host_os = "windows" if "Mars" in reply else "mac"
            needle = "tzutil /g" if host_os == "windows" else "readlink /etc/localtime"
            result = self.attempt(host_os, {needle: reply})
            self.assertNotIn("from your computer", result.stdout, reply)
            self.assertNotIn(reply, self.calls)


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
        self.assertRegex(plist, r"<key>HERMES_WORKSPACE_HOST_OS</key>\s*<string>linux</string>")
        self.assertRegex(plist, r"<key>PATH</key>\s*<string>[^<]*%s[^<]*</string>" % re.escape(str(Path(shutil.which("node")).parent)))


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


class ComputerProviderTests(IntegrationBase, unittest.TestCase):
    def test_installed_per_profile_and_selected_when_hermes_has_the_provider_api(self):
        self.run_setup("--profile", "work", python_ok=True)
        calls = read_log(self.log)
        self.assertRegex(calls, r"-p work plugins install file://\S+#alans-way-computer")
        self.assertIn("-p work plugins enable alans-way-computer", calls)
        self.assertIn("-p work config set computer_use.backend alans-way-computer", calls)
        self.assertLess(calls.index("plugins install"), calls.index("computer_use.backend"))

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


if __name__ == "__main__":
    unittest.main()
