"""scripts/alan-relay-voice-watch: one poll of /usage drives tts.provider."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
WATCHER = ROOT / "scripts" / "alan-relay-voice-watch"


class UsageServer:
    """Minimal relay stub: records GET /usage (auth included), answers with
    a programmable document or error."""

    def __init__(self):
        self.requests = []
        self.document = {"jev_tasks_left_est": 10,
                         "voice_minutes_left_est": 0,
                         "resets_at": "2026-11-01T00:00:00Z"}
        self.status = 200

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append(
                    {"path": self.path,
                     "auth": self.headers.get("Authorization")})
                if outer.status != 200:
                    self.send_error(outer.status)
                    return
                body = json.dumps(outer.document).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}/api/relay"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def run_watch(directory: Path, *, base="", token="relay-secret-1",
              config=None, env_extra=None, interval_env=None, managed=None):
    """One --once pass against a stub hermes that records `config set` argv."""
    bin_dir = directory / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = directory / "hermes-calls.log"
    hermes = bin_dir / "hermes"
    hermes.write_text(
        "#!/bin/sh\necho \"hermes $*\" >> \"$CALLS_LOG\"\n", encoding="utf-8")
    hermes.chmod(0o755)
    env_file = directory / ".env"
    lines = []
    if base:
        lines.append(f"ALAN_RELAY_BASE={base}")
    if token is not None:
        lines.append(f"ALAN_RELAY_TOKEN={token}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    config_path = directory / "config.yaml"
    if config is not None:
        config_path.write_text(config, encoding="utf-8")
    managed_path = directory / ".alan-relay-managed"
    if managed is not None:
        managed_path.write_text(json.dumps(managed), encoding="utf-8")
    env = dict(os.environ)
    env.update({"CALLS_LOG": str(calls), "HERMES_HOME": str(directory)})
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, str(WATCHER), "--once",
         "--env-file", str(env_file), "--config", str(config_path),
         "--hermes", str(hermes),
         "--managed-file", str(managed_path)],
        capture_output=True, text=True, env=env, timeout=60)
    calls_text = calls.read_text(encoding="utf-8") if calls.exists() else ""
    marker = (json.loads(managed_path.read_text(encoding="utf-8"))
              if managed_path.exists() else None)
    return result, calls_text, marker


def relay_config(base: str, provider: str = "openai") -> str:
    """The tts block bootstrap writes: provider + the relay openai wiring."""
    return (f"tts:\n  provider: {provider}\n  openai:\n"
            f"    model: gpt-4o-mini-tts\n"
            f"    base_url: {base}/openai/v1\n"
            "    api_key: ${VOICE_TOOLS_OPENAI_KEY}\n")


class WatcherTests(unittest.TestCase):
    def test_no_credentials_polls_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            result, calls, _ = run_watch(Path(d), base="", token=None)
            self.assertEqual(result.returncode, 0)
            self.assertIn("nothing to watch", result.stdout)
            self.assertEqual(calls, "")

    def test_zero_voice_minutes_flips_to_edge(self):
        server = UsageServer()
        try:
            with tempfile.TemporaryDirectory() as d:
                result, calls, marker = run_watch(Path(d), base=server.base)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(server.requests[0]["path"], "/api/relay/usage")
                self.assertEqual(
                    server.requests[0]["auth"], "Bearer relay-secret-1")
                self.assertIn("hermes config set tts.provider edge", calls)
                # The flip records provenance so a later positive balance may
                # restore openai — and only if the watcher set edge itself.
                self.assertEqual(marker["watcher_provider"], "edge")
        finally:
            server.close()

    def test_positive_minutes_restores_openai(self):
        """After resets_at the relay's counter is positive again; the next
        poll flips the fallback off — but only because the marker says this
        watcher set edge, and only while the relay wiring is intact."""
        server = UsageServer()
        server.document["voice_minutes_left_est"] = 42.5
        try:
            with tempfile.TemporaryDirectory() as d:
                result, calls, marker = run_watch(
                    Path(d), base=server.base,
                    config=relay_config(server.base, provider="edge"),
                    managed={"watcher_provider": "edge"})
                self.assertEqual(result.returncode, 0)
                self.assertIn("hermes config set tts.provider openai", calls)
                self.assertEqual(marker["watcher_provider"], "openai")
        finally:
            server.close()

    def test_customer_chosen_edge_is_never_flipped_back(self):
        """provider=edge the customer set themselves is indistinguishable by
        value — only the marker proves the watcher did not set it, so a
        positive balance must leave it alone."""
        server = UsageServer()
        server.document["voice_minutes_left_est"] = 42.5
        try:
            with tempfile.TemporaryDirectory() as d:
                for managed in (None, {"watcher_provider": "openai"},
                                {"managed": {"tts.provider": "openai"}}):
                    with self.subTest(managed=managed):
                        result, calls, _ = run_watch(
                            Path(d), base=server.base,
                            config=relay_config(server.base, provider="edge"),
                            managed=managed)
                        self.assertEqual(calls, "")
        finally:
            server.close()

    def test_customer_openai_is_never_flipped_to_edge(self):
        """A customer running their own OpenAI TTS has tts.provider=openai
        but a base_url that is not the relay (or an api_key that is not the
        env-ref template): an exhausted relay balance must not flip it —
        they never consume the relay's voice minutes."""
        server = UsageServer()  # voice_minutes_left_est: 0
        try:
            configs = [
                # entirely their own OpenAI account
                "tts:\n  provider: openai\n  openai:\n"
                "    base_url: https://api.openai.com/v1\n"
                "    api_key: sk-customer\n",
                # relay base_url but a literal key — not our template
                "tts:\n  provider: openai\n  openai:\n"
                f"    base_url: {server.base}/openai/v1\n"
                "    api_key: sk-theirs\n",
            ]
            for config in configs:
                with self.subTest(config=config):
                    with tempfile.TemporaryDirectory() as d:
                        result, calls, _ = run_watch(
                            Path(d), base=server.base, config=config)
                        self.assertEqual(calls, "")
        finally:
            server.close()

    def test_watcher_set_edge_flips_back_only_while_relay_wired(self):
        """If the operator re-points tts.openai while the provider sits on
        watcher-set edge, restoring openai would send the relay bearer to a
        third party — hands off instead."""
        server = UsageServer()
        server.document["voice_minutes_left_est"] = 42.5
        try:
            with tempfile.TemporaryDirectory() as d:
                result, calls, _ = run_watch(
                    Path(d), base=server.base,
                    config="tts:\n  provider: edge\n  openai:\n"
                           "    base_url: https://api.openai.com/v1\n"
                           "    api_key: sk-customer\n",
                    managed={"watcher_provider": "edge"})
                self.assertEqual(calls, "")
        finally:
            server.close()

    def test_non_finite_minutes_leaves_the_provider_alone(self):
        """json.loads accepts bare NaN/Infinity; nan <= 0 is False which
        used to read as 'credit restored' — fail closed instead."""
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                server = UsageServer()
                server.document["voice_minutes_left_est"] = value
                try:
                    with tempfile.TemporaryDirectory() as d:
                        result, calls, _ = run_watch(Path(d), base=server.base)
                        self.assertEqual(result.returncode, 0)
                        self.assertEqual(calls, "")
                finally:
                    server.close()

    def test_flow_style_tts_block_is_read(self):
        """`tts: {provider: edge}` is the same selection as a block —
        missing it used to read as unset, which the watcher then owned."""
        server = UsageServer()
        server.document["voice_minutes_left_est"] = 7
        try:
            with tempfile.TemporaryDirectory() as d:
                result, calls, _ = run_watch(
                    Path(d), base=server.base,
                    config="tts: {provider: elevenlabs}\n")
                self.assertEqual(calls, "")
                self.assertIn("operator-owned", result.stdout)
        finally:
            server.close()

    def test_matching_provider_is_a_no_op(self):
        server = UsageServer()
        try:
            with tempfile.TemporaryDirectory() as d:
                result, calls, _ = run_watch(
                    Path(d), base=server.base,
                    config="tts:\n  provider: edge\n")
                self.assertEqual(calls, "")
        finally:
            server.close()

    def test_missing_config_flips_from_unset(self):
        server = UsageServer()
        try:
            with tempfile.TemporaryDirectory() as d:
                result, calls, _ = run_watch(Path(d), base=server.base)
                self.assertIn("hermes config set tts.provider edge", calls)
        finally:
            server.close()

    def test_operator_owned_provider_is_never_touched(self):
        """A customer who set tts.provider to elevenlabs (or anything that is
        not ours) keeps it — even when the relay is out of credit."""
        server = UsageServer()
        try:
            with tempfile.TemporaryDirectory() as d:
                result, calls, _ = run_watch(
                    Path(d), base=server.base,
                    config="tts:\n  provider: elevenlabs\n")
                self.assertEqual(result.returncode, 0)
                self.assertEqual(calls, "")
                self.assertIn("operator-owned", result.stdout)
        finally:
            server.close()

    def test_use_gateway_selection_is_never_touched(self):
        server = UsageServer()
        try:
            with tempfile.TemporaryDirectory() as d:
                result, calls, _ = run_watch(
                    Path(d), base=server.base,
                    config="tts:\n  use_gateway: true\n  provider: openai\n")
                self.assertEqual(calls, "")
        finally:
            server.close()

    def test_nested_provider_key_is_not_misread_as_the_selection(self):
        """tts.openai.provider-style nesting must not be read as
        tts.provider — only the direct key under tts: counts."""
        server = UsageServer()
        server.document["voice_minutes_left_est"] = 5
        try:
            with tempfile.TemporaryDirectory() as d:
                result, calls, _ = run_watch(
                    Path(d), base=server.base,
                    config=relay_config(server.base, provider="edge")
                           + "    provider: nested\n",
                    managed={"watcher_provider": "edge"})
                self.assertIn("hermes config set tts.provider openai", calls)
        finally:
            server.close()

    def test_relay_errors_leave_the_provider_alone(self):
        for status in (500, 401, 429):
            with self.subTest(status=status):
                server = UsageServer()
                server.status = status
                try:
                    with tempfile.TemporaryDirectory() as d:
                        result, calls, _ = run_watch(Path(d), base=server.base)
                        self.assertEqual(result.returncode, 0)
                        self.assertEqual(calls, "")
                finally:
                    server.close()

    def test_non_json_usage_leaves_the_provider_alone(self):
        server = UsageServer()
        try:
            with tempfile.TemporaryDirectory() as d:
                # Malformed payload: the field is absent.
                server.document = {"resets_at": "2026-11-01T00:00:00Z"}
                result, calls, _ = run_watch(Path(d), base=server.base)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(calls, "")
        finally:
            server.close()

    def test_unreachable_relay_leaves_the_provider_alone(self):
        server = UsageServer()
        base = server.base
        server.close()  # port now refuses connections
        with tempfile.TemporaryDirectory() as d:
            result, calls, _ = run_watch(Path(d), base=base)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(calls, "")

    def test_env_vars_win_over_the_env_file(self):
        server = UsageServer()
        try:
            with tempfile.TemporaryDirectory() as d:
                result, calls, _ = run_watch(
                    Path(d), base="http://ignored.invalid/rel",
                    token="file-token",
                    env_extra={"ALAN_RELAY_BASE": server.base,
                               "ALAN_RELAY_TOKEN": "env-token"})
                self.assertEqual(result.returncode, 0)
                self.assertEqual(server.requests[0]["auth"], "Bearer env-token")
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
