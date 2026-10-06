"""setup.sh CLI: verify strictness, bot-id derivation, timezone, and doc flags."""
from pathlib import Path
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "setup.sh"
SH = shutil.which("sh") or "/bin/sh"


def run(*args, env=None, check=True):
    cmd = [SH, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if check and result.returncode != 0:
        raise AssertionError(f"exit {result.returncode}: {result.stderr}\n{result.stdout}")
    return result


def fake_hermes_bin(directory: Path, *, plugins="", tools="", proactivity_status="{}", config_get=""):
    bin_dir = directory / "bin"
    bin_dir.mkdir()
    hermes = bin_dir / "hermes"
    hermes.write_text(f"""#!/bin/sh
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


def logging_hermes_bin(directory: Path, log: Path):
    bin_dir = directory / "bin"
    bin_dir.mkdir()
    hermes = bin_dir / "hermes"
    hermes.write_text(f"""#!/bin/sh
echo "$*" >> "{log}"
case "$1" in
  --version) echo "hermes 0.21.5";;
  plugins) [ "$2" = list ] && echo "alans-way";;
esac
exit 0
""", encoding="utf-8")
    hermes.chmod(0o755)
    return bin_dir


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
            self.assertIn("-p sprk1 proactivity resume", calls)
            self.assertIn("proactivity on", result.stdout)


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
            self.assertIn("below 18", result.stdout)


if __name__ == "__main__":
    unittest.main()
