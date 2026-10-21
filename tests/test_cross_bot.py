"""Synthetic fixtures only; public hooks, commands and plugin-owned file contract."""
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor
import asyncio
import time
import sys
import unittest

from test_proactivity import P, FakeCtx

C = importlib.import_module(P.__package__ + ".cross_bot")
NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


# Synthetic X2R2/X2R3 reproductions and the review's ordinary-message corpus.
SECRET_EXAMPLES = [
    "Card: 4111 1111 1111 1111 12-29", "4111 1111 1111 1111 123",
    "Card: 4111111111111111 12 29", "sk_live_" + "A" * 24, "pin is 1234",
    "password: synthetic-sensitive-value", '{"access_token": "synthetic-value"}',
    "DATABASE_PASSWORD=synthetic-value", "AWS_SECRET_ACCESS_KEY=synthetic-value",
    '{"clientSecret": "synthetic-value"}', "Cookie: session=synthetic-value",
    "Your code is 123456", "SERVICE_SECRET=synthetic-value", "SERVICE_TOKEN=synthetic-value",
    "SERVICE_PASSWORD=synthetic-value", "SERVICE_API_KEY=synthetic-value",
    "1 2--3 4 5 6 7 8 9 0 1 2", "123456789012", "12345678901234567890",
    "https://user:synthetic-value@example.invalid/page",
    "postgresql://user:synthetic-value@example.invalid/db",
    "custom+db://user:synthetic-value@example.invalid/db",
    "https://example.invalid/?api_key=synthetic-value",
    "-----BEGIN " + "PRIVATE KEY-----\nsynthetic-key\n-----END " + "PRIVATE KEY-----",
    "A" * 31 + "1", "1" + "z" * 31, "A1_-/+=" * 5,
]
SECRET_KEYWORDS = ("passcode", "cvv", "cvc", "password", "passwd", "secret", "token",
                   "api key", "api_key", "private key", "otp", "verification code", "2fa", "ssn",
                   "routing number", "account number")
SECRET_PREFIXES = ("sk_", "rk_", "pk_live", "ghp_", "gho_", "github_pat_", "xox", "AKIA",
                   "AIza", "sk-ant-", "sk-", "eyJ", "-----BEGIN", "Bearer ")
SECRET_EXAMPLES += ["Before " + word.upper() + " after" for word in SECRET_KEYWORDS]
SECRET_EXAMPLES += [prefix + "synthetic-value" for prefix in SECRET_PREFIXES]
SECRET_EXAMPLES += ["PIN: 9876", "my pin is 1234", "Pin 0000 for the door"]
# X2R4 regressions: compound credential names, Telegram bot tokens, PIN phrasings.
SECRET_EXAMPLES += ["dbPassword=synthetic-value", "refreshToken=synthetic-value", "api-key=synthetic-value",
                    "one-time-code: 123456", "1234567890:" + "A" * 35, "PIN number is 2468",
                    'PIN is "2468"', "PIN:\n2468"]
ORDINARY_MESSAGES = [
    'Call me at 202-555-0123.',
    'Phone +1 (303) 555-0198 is the office.',
    'Use +44 20 7946 0958 for the contact.',
    'Order ID: 4000000000000003',
    'Order 140000000000000026 ships tomorrow.',
    'Track order ORD-20261014-739201.',
    'The meeting is 2026-10-14.',
    'Our trip runs 10/14/2026 to 10/20/2026.',
    'Deadline: October 14, 2026 at 12:30.',
    'The price is $1,234.56.',
    'Lunch costs $12.99 plus a $3.50 tip.',
    'Budget: USD 25000.00 for the project.',
    'Flight UA1234 leaves at 14:05.',
    'AA 114 lands on 10/14.',
    'Flight BA249 is delayed 35 minutes.',
    'Send the parcel to ZIP 80202.',
    'Postal code 10001-1234 is correct.',
    'ZIP codes 90210, 94105, and 60601 are covered.',
    'Meet at 123 Main Street, Denver, CO 80202.',
    'Ship to 456 Elm Ave Apt 7B, Springfield, IL 62701.',
    'The venue is 789 Broadway, New York, NY 10003.',
    'Order ID 4111111111111111 was assigned by the test order system.',
    'Pin the delivery address to the map.',
    'Please pin this order receipt for tomorrow.',
    'Drop a pin at 123 Main Street.',
    'The map pin is at 456 Elm Avenue.',
    'Use the red pushpin for the route.',
    'The invoice is 1234567890123456.',
    'The tracking reference is 9876543210987654321.',
    'Our pickup is at 09:30 on 2026-10-15 and costs $25.',
]


class SanitizerTests(unittest.TestCase):
    def test_secret_signals_drop_entire_text_before_truncation(self):
        for number, text in enumerate(SECRET_EXAMPLES):
            with self.subTest(shape=number):
                self.assertIsNone(C.sanitize("Useful draft\n" + "x" * 680 + " " + text + "\nKeep this",
                                             max_bytes=64))

    def test_utf8_raw_bounds_failure_and_literal_operator_terms(self):
        self.assertEqual(C.sanitize("é" * 100, max_bytes=7), "ééé")
        self.assertEqual(C.sanitize("Ａ draft\n\nKeep\u200b this"), "Ａ draft\n\nKeep\u200b this")
        self.assertIsNone(C.sanitize("bad\ud800"))
        self.assertIsNone(C.sanitize("x" * 8193))
        self.assertIsNone(C.sanitize("é" * 4097))
        self.assertEqual(C.sanitize("é" * 4096, max_bytes=8), "é" * 4)
        self.assertIsNone(C.sanitize({"text": "attachment"}))
        self.assertIsNone(C.sanitize("Private Project: draft", redact_terms=["private project"]))
        self.assertIsNone(C.sanitize("ＰＩＮ: 1234"))
        self.assertIsNone(C.sanitize("pass\u200bword: synthetic-value"))
        for terms in ("bad", [""], ["x" * 129], ["x"] * 33):
            self.assertIsNone(C.sanitize("Draft", redact_terms=terms))

    def test_credential_words_inside_compounds_drop_the_exchange(self):
        # Accepted over-drop: substring matching catches dbPassword/refreshToken/api-key.
        for text in ("secretive tokens", "dbPassword=x", "refreshToken=x", "api-key=x"):
            with self.subTest(text=text):
                self.assertIsNone(C.sanitize(text))

    def test_word_boundaries_and_short_tokens_keep_text(self):
        for text in ("spinning pushpin", "A" * 32, "Ab1" * 10,
                     "Drop a pin at 123 Main Street.", "The map pin is at 456 Elm Avenue.",
                     "https://example.invalid/page?view=draft", "202-555-0123"):
            with self.subTest(text=text):
                self.assertEqual(C.sanitize(text), text)

    def test_direct_signal_scan_is_linear_at_one_mib(self):
        # Production input is capped at EXCHANGE_BYTES (8 KiB) before detection; this
        # guards against super-linear backtracking, not a CI runner's absolute speed.
        size = 1024 * 1024
        probes = (("pin" + " " * (size - 3), False), ("pin is 1234" + " " * (size - 11), True), ("passcode" + " " * (size - 8), True),
                  ("q" * size, False), (" " * size, False), ("4" + "0" * (size - 1), True),
                  ("4 " + "0 " * (size // 2 - 1), True), ("a" * (size - 1) + "1", True), ("1" + "a" * (size - 1), True),
                  (("A" * 31 + " ") * (size // 32), False),
                  (("A" * 30 + "1 ") * (size // 32), False),
                  (("draft. " * (size // 7 + 1))[:size], False))
        for text, expected in probes:
            with self.subTest(prefix=text[:8]):
                timings = []
                half = text[:size // 2]
                half_timings = []
                for _ in range(3):
                    start = time.perf_counter()
                    result = C.secret_signal(text)
                    timings.append(time.perf_counter() - start)
                    self.assertEqual(bool(result), expected)
                    start = time.perf_counter()
                    C.secret_signal(half)
                    half_timings.append(time.perf_counter() - start)
                self.assertLess(min(timings), 0.250, timings)
                # Doubling the input must not more than ~triple the time (quadratic would be 4x).
                self.assertLess(min(timings), 3 * max(min(half_timings), 0.002), (timings, half_timings))

    def test_one_mib_pin_whitespace_is_bounded(self):
        import subprocess
        code = "from test_cross_bot import C; assert C.sanitize('pin' + ' ' * (1024*1024)) is None"
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parent,
                                capture_output=True, text=True, timeout=2)
        self.assertEqual(result.returncode, 0, result.stderr)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "shared"
        self.store = C.SharedStore(self.root, primary="primary", clock=lambda: NOW)

    def test_advancing_clock_keeps_digest_lifetime_valid(self):
        now = [NOW]
        def advancing():
            now[0] += timedelta(microseconds=1)
            return now[0]
        self.store.clock = advancing
        self.store.set_enabled("specialist", True, bound=True)
        self.assertTrue(self.store.append("specialist", "one", "Draft", "Done"))
        self.assertEqual(self.store.status("specialist")["exchanges"], 1)
        self.assertTrue(self.store.append("specialist", "two", "Draft again", "Done"))
        now[0] += timedelta(hours=24)
        self.store.prune()
        self.assertFalse((self.root / "profiles/specialist/digest.json").exists())

    def test_pruning_enumerates_profiles_once_and_keeps_unchanged_files(self):
        for name in ("first", "second"):
            self.store.set_enabled(name, True, bound=True)
            self.store.append(name, name, "Draft", "Done")
        with patch.object(self.store, "names", wraps=self.store.names) as names, \
             patch.object(self.store, "write", wraps=self.store.write) as write:
            self.store.prune()
        self.assertEqual(names.call_count, 1)
        write.assert_not_called()

    def test_enrollment_defaults_off_and_exports_only_after_operator_enable(self):
        self.store.presence("specialist", bound=True)
        self.assertFalse(self.store.status("specialist")["enabled"])
        self.assertFalse(self.store.append("specialist", "turn-one", "Draft a checklist", "First, review."))
        self.store.set_enabled("specialist", True, bound=True)
        self.assertTrue(self.store.append("specialist", "turn-one", "Draft a checklist", "First, review."))
        self.assertEqual(json.loads((self.root / "profiles/specialist/digest.json").read_text())["exchanges"][0]["user"], "Draft a checklist")
        self.assertFalse(self.store.status("specialist")["dispatch_enabled"])
        self.assertEqual((self.root.stat().st_mode & 0o777), 0o700)
        for file in self.root.rglob("*.json"):
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_last_four_dedup_survives_eviction_and_restart_and_ttl_prunes(self):
        now = [NOW]
        self.store.clock = lambda: now[0]
        self.store.set_enabled("specialist", True, bound=True)
        for number in range(6):
            self.assertTrue(self.store.append("specialist", str(number), "Draft " + str(number), "Done."))
        exchanges = json.loads((self.root / "profiles/specialist/digest.json").read_text())["exchanges"]
        self.assertEqual([e["user"] for e in exchanges], ["Draft 2", "Draft 3", "Draft 4", "Draft 5"])
        restarted = C.SharedStore(self.root, primary="primary", clock=lambda: now[0])
        self.assertFalse(restarted.append("specialist", "0", "duplicate", "duplicate"))
        now[0] += timedelta(hours=24)
        restarted.prune()
        self.assertEqual(restarted.status("specialist")["exchanges"], 0)
        self.assertFalse((self.root / "profiles/specialist/digest.json").exists())
        self.assertTrue((self.root / "profiles/specialist/dedup.json").exists())
        now[0] += timedelta(hours=24)
        restarted.prune()
        self.assertFalse((self.root / "profiles/specialist/dedup.json").exists())

    def test_per_exchange_expiry_and_startup_pruning(self):
        now = [NOW]
        self.store.clock = lambda: now[0]
        self.store.set_enabled("specialist", True, bound=True)
        self.store.append("specialist", "old", "Old draft", "Done.")
        now[0] += timedelta(hours=23)
        self.store.presence("specialist", bound=True)
        self.store.append("specialist", "fresh", "Fresh draft", "Done.")
        now[0] += timedelta(hours=1)
        restarted = C.SharedStore(self.root, primary="primary", clock=lambda: now[0])
        self.assertEqual(restarted.status("specialist")["exchanges"], 1)

    def test_serialized_utf8_size_and_concurrent_atomic_appends(self):
        self.store.set_enabled("specialist", True, bound=True)
        stores = [C.SharedStore(self.root, primary="primary", clock=lambda: NOW, lock_timeout=1) for _ in range(8)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda pair: pair[1].append("specialist", str(pair[0]), "é" * 220, "字" * 160), enumerate(stores)))
        self.assertTrue(all(results))
        digest_file = self.root / "profiles/specialist/digest.json"
        self.assertLessEqual(digest_file.stat().st_size, 2048)
        json.loads(digest_file.read_text())
        self.assertEqual(len(json.loads((digest_file.parent / "dedup.json").read_text())["turns"]), 8)
        self.assertEqual(list(self.root.rglob(".tmp-*")), [])

    def test_generation_race_drops_staged_export(self):
        epoch = self.store.set_enabled("specialist", True, bound=True)["generation"]
        self.store.set_enabled("specialist", False, bound=True)
        self.store.set_enabled("specialist", True, bound=True)
        self.assertFalse(self.store.append("specialist", "old-epoch", "Draft", "Done", expected_generation=epoch))

    def test_off_purges_even_a_corrupt_digest(self):
        self.store.set_enabled("specialist", True, bound=True)
        file = self.root / "profiles/specialist/digest.json"
        file.write_text("corrupt synthetic body")
        file.chmod(0o600)
        self.store.set_enabled("specialist", False, bound=True)
        self.assertFalse(file.exists())
        self.assertFalse(self.store.status("specialist")["enabled"])

    def test_startup_removes_orphan_atomic_temp_text(self):
        self.store.presence("specialist")
        file = self.root / "profiles/specialist" / (".tmp-" + "a" * 32)
        file.write_text("orphan synthetic body")
        file.chmod(0o600)
        C.SharedStore(self.root, primary="primary", clock=lambda: NOW)
        self.assertFalse(file.exists())

    def test_profile_cap_and_path_rejection(self):
        for number in range(16):
            self.store.presence("p" + str(number))
        with self.assertRaisesRegex(ValueError, "too many"):
            self.store.presence("extra")
        for name in ("../outside", "a/b", ".", "", "a\\b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.presence(name)
        with self.assertRaises(ValueError):
            C.SharedStore("relative/shared")

    def test_symlink_files_directories_and_permissive_modes_fail_closed(self):
        self.store.set_enabled("specialist", True, bound=True)
        digest = self.root / "profiles/specialist/digest.json"
        target = self.root.parent / "outside"
        target.write_text("untouched")
        digest.symlink_to(target)
        with self.assertRaises(OSError):
            self.store.prune()
        self.assertEqual(target.read_text(), "untouched")
        digest.unlink()
        os.chmod(self.root, 0o755)
        with self.assertRaises(ValueError):
            self.store.prune()
        os.chmod(self.root, 0o700)
        presence = digest.parent / "presence.json"
        os.chmod(presence, 0o644)
        with self.assertRaises(ValueError):
            self.store.prune()
        os.chmod(presence, 0o600)
        directory = self.root / "profiles/linked"
        directory.symlink_to(target.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.store.prune()

    def test_corrupt_schema_is_rejected_without_exporting_body(self):
        self.store.set_enabled("specialist", True, bound=True)
        self.store.append("specialist", "one", "Draft", "Done")
        digest = self.root / "profiles/specialist/digest.json"
        original = digest.read_text()
        bad_values = ["not json", '{"schema":1,"schema":1}',
                      original.replace('"generation":2', '"generation":true'),
                      original.replace('"profile":"specialist"', '"profile":"other"'),
                      original[:-1] + ',"extra":true}']
        for bad in bad_values:
            digest.write_text(bad)
            with self.subTest(bad=bad[:15]), self.assertRaises(ValueError):
                self.store.prune()
        digest.write_text(original)
        control = self.root / "control.json"
        control.write_text('{"schema":1,"primary":"primary","enabled":1,"generation":1}')
        with self.assertRaises(ValueError):
            self.store.append("specialist", "two", "Draft", "Done")

    def test_shared_lock_wait_is_bounded(self):
        import fcntl
        with (self.root / "store.lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            start = time.monotonic()
            with self.assertRaisesRegex(ValueError, "busy"):
                self.store.prune()
            self.assertLess(time.monotonic() - start, 1)

    def test_wrong_owner_hardlinks_and_parent_symlinks_are_rejected(self):
        # fstat is the OS ownership boundary; no chown is needed on a real host.
        real_stat = os.fstat
        def foreign_owner(fd):
            info = real_stat(fd)
            return SimpleNamespace(st_mode=info.st_mode, st_uid=os.geteuid() + 1, st_nlink=info.st_nlink)
        with patch.object(C.os, "fstat", side_effect=foreign_owner), self.assertRaises(ValueError):
            self.store.prune()
        self.store.presence("specialist")
        presence = self.root / "profiles/specialist/presence.json"
        os.link(presence, self.root.parent / "hardlink")
        with self.assertRaises(ValueError):
            self.store.prune()
        link = self.root.parent / "linked-root"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            C.SharedStore(link)

    def test_file_size_and_timestamp_schema_attacks_are_rejected(self):
        self.store.set_enabled("specialist", True, bound=True)
        self.store.append("specialist", "one", "Draft", "Done")
        file = self.root / "profiles/specialist/digest.json"
        original = file.read_text()
        for bad in ("x" * 2049, original.replace("+00:00", ""),
                    original.replace("2026-10-14", "2026-10-15"),
                    original.replace('"assistant":"Done"', '"assistant":[]')):
            file.write_text(bad)
            with self.subTest(bad=bad[:16]), self.assertRaises(ValueError):
                self.store.prune()

    def test_body_free_dedup_budget_is_bounded_and_refuses_overflow(self):
        self.store.set_enabled("specialist", True, bound=True)
        file = self.root / "profiles/specialist/dedup.json"
        turns = [{"id": C.hashlib.sha256(str(n).encode()).hexdigest(), "at": NOW.isoformat()} for n in range(512)]
        file.write_text(json.dumps({"schema": 1, "profile": "specialist", "turns": turns}, separators=(",", ":")))
        file.chmod(0o600)
        self.assertFalse(self.store.append("specialist", "overflow", "Draft", "Done"))
        self.assertNotIn("Draft", file.read_text())
        self.assertLessEqual(file.stat().st_size, 65536)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        routes = patch.object(C, "receiving_routes", return_value=[])
        routes.start()
        self.addCleanup(routes.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "shared"
        self.now = NOW
        self.ctx = FakeCtx()
        self.ctx.profile_name = "specialist"
        config = {"cross_bot.shared_root": str(self.root), "cross_bot.primary": "primary"}
        self.ctx.get_config = lambda key, default=None: config.get(key, default)
        self.ctx.set_config = lambda key, value: config.__setitem__(key, value)
        self.owner = P.Proactivity(self.ctx)
        self.key = "agent:specialist:telegram:dm:42"
        self.owner.bind(self.key)
        self.cross = C.CrossBot(self.ctx, self.owner, clock=lambda: self.now)
        self.addCleanup(self.cross.close)
        self.kw = {"session_id": "session-one", "task_id": "task-one", "turn_id": "turn-one",
                   "platform": "telegram", "model": "synthetic-model"}

    def command(self, text, key=None):
        with patch.object(P, "caller_session_key", return_value=self.key if key is None else key):
            return self.cross.command(text)

    def exchange(self, *, message="Draft a checklist", response="First, review.", key=None, pre=None, outcome=None):
        with patch.object(P, "caller_session_key", return_value=self.key if key is None else key):
            self.assertIsNone(self.cross.on_turn_start(user_message=message, conversation_history=[],
                              **{"is_first_turn": False, "parent_session_id": "", "sender_id": "42", **self.kw, **(pre or {})}))
            self.assertIsNone(self.cross.on_turn_end(user_message=message, assistant_response=response,
                              conversation_history=[{"role": "tool", "content": "not exported"}], **self.kw))
            self.assertIsNone(self.cross.on_session_end(**{**self.kw, "completed": True, "failed": False,
                              "interrupted": False, "turn_exit_reason": "completed", **(outcome or {})}))

    def test_completed_owner_exchange_only_and_off_purges(self):
        self.exchange()
        self.assertEqual(list(self.root.glob("profiles/*/digest.json")), [])
        self.assertIn("on", self.command("cross on"))
        with patch.object(P, "caller_session_key", return_value=self.key):
            self.cross.on_turn_start(user_message="Draft a checklist", parent_session_id="", **self.kw)
            self.cross.on_turn_end(user_message="Draft a checklist", assistant_response="First, review.", **self.kw)
            self.assertEqual(list(self.root.glob("profiles/*/digest.json")), [])
            self.cross.on_session_end(completed=True, failed=False, interrupted=False, **self.kw)
        digest = json.loads((self.root / "profiles/specialist/digest.json").read_text())
        self.assertEqual(digest["exchanges"][0]["assistant"], "First, review.")
        self.assertNotIn(self.key, json.dumps(digest))
        self.assertIn("off", self.command("cross off"))
        self.assertFalse((self.root / "profiles/specialist/digest.json").exists())

    def test_excluded_origins_other_chats_missing_correlation_and_failed_outcomes(self):
        self.command("cross on")
        for message, key, pre, outcome in (
            ("hi", "agent:specialist:telegram:group:42", {}, {}),
            ("hi", "agent:other:telegram:dm:42", {}, {}),
            ("hi", "", {}, {}),
            (P.MARKER + " work", None, {}, {}),
            (P.BRIEF_MARKER + " brief", None, {}, {}),
            ("[Cross-bot ask] draft", None, {}, {}),
            ("hi", None, {"parent_session_id": "parent"}, {}),
            ("hi", None, {"origin": "cron"}, {}),
            ("hi", None, {"imported": True}, {}),
            ("hi", None, {"platform": "cli"}, {}),
            ("hi", None, {"turn_id": None}, {}),
            ("hi", None, {}, {"completed": False}),
            ("hi", None, {}, {"failed": True}),
            ("hi", None, {}, {"interrupted": True}),
            ("hi", None, {}, {"failed": None}),
        ):
            with self.subTest(message=message, key=key, pre=pre, outcome=outcome):
                self.exchange(message=message, key=key, pre=pre, outcome=outcome)
                self.assertEqual(list(self.root.glob("profiles/*/digest.json")), [])
        self.ctx.current_cron_execution = lambda: object()
        self.exchange()
        self.assertEqual(list(self.root.glob("profiles/*/digest.json")), [])

    def test_model_may_only_disable_and_other_chats_cannot_enable(self):
        self.assertIn("bound owner DM", self.command("cross on", key="agent:other:telegram:dm:42"))
        with patch.object(P, "caller_session_key", return_value=self.key):
            result = json.loads(self.cross.tool({"action": "set", "cross_bot_enabled": True}))
            self.assertFalse(result["ok"])
            self.assertEqual(result["ask_user_to_send"], "/proactivity cross on")
            self.assertFalse(self.cross.status()["enabled"])
            self.command("cross on")
            self.exchange()
            result = json.loads(self.cross.tool({"action": "set", "cross_bot_enabled": False}))
            self.assertTrue(result["ok"])
            self.assertFalse(result["enabled"])
        self.assertFalse((self.root / "profiles/specialist/digest.json").exists())

    def test_secret_signals_in_either_field_never_write_exchange(self):
        self.command("cross on")
        for number, text in enumerate(SECRET_EXAMPLES + ["pin" + " " * 65533, "bad\ud800"]):
            for side in ("message", "response", "both"):
                with self.subTest(shape=number, side=side):
                    self.kw["turn_id"] = str(number) + side
                    self.exchange(message=text if side != "response" else "Useful draft",
                                  response=text if side != "message" else "Done")
                    self.assertEqual(self.cross.status()["exchanges"], 0)
                    self.assertEqual(self.cross._pending, {})
                    self.assertFalse((self.root / "profiles/specialist/digest.json").exists())
                    self.assertFalse((self.root / "profiles/specialist/dedup.json").exists())
        self.kw["turn_id"] = "safe-after-drop"
        self.exchange()
        self.assertEqual(self.cross.status()["exchanges"], 1)

    def test_combined_raw_exchange_byte_limit_before_digest_truncation(self):
        self.command("cross on")
        for number, (user, assistant) in enumerate((("x" * 4096, "y" * 4097),
                                                    ("é" * 2048, "字" * 1366))):
            self.kw["turn_id"] = str(number)
            self.exchange(message=user, response=assistant)
            self.assertEqual(self.cross.status()["exchanges"], 0)
            self.assertFalse((self.root / "profiles/specialist/digest.json").exists())
        self.kw["turn_id"] = "at-limit"
        self.exchange(message="x" * 4096, response="y" * 4096)
        self.assertEqual(self.cross.status()["exchanges"], 1)

    def test_x2r3_ordinary_corpus_keeps_most_messages_unchanged(self):
        self.command("cross on")
        kept = 0
        for number, text in enumerate(ORDINARY_MESSAGES):
            self.command("cross off")
            self.command("cross on")
            self.kw["turn_id"] = str(number)
            self.exchange(message=text, response=text)
            file = self.root / "profiles/specialist/digest.json"
            if file.exists():
                entry = json.loads(file.read_text())["exchanges"][-1]
                self.assertEqual((entry["user"], entry["assistant"]), (text, text))
                kept += 1
        self.assertGreater(kept, len(ORDINARY_MESSAGES) // 2)
        self.assertEqual(kept, 23)

    def test_busy_store_off_stops_locally_and_reports_unpurged_digest(self):
        import fcntl
        self.command("cross on")
        self.exchange()
        task = SimpleNamespace(cancel=unittest.mock.Mock())
        self.cross.task = task
        self.cross.on_activation = unittest.mock.Mock()
        self.cross._pending["staged"] = {"user": "synthetic draft"}
        file = self.root / "profiles/specialist/digest.json"
        with (self.root / "store.lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = self.command("cross off")
        self.assertFalse(self.cross.active)
        self.assertFalse(self.ctx.get_config("cross_bot.enabled"))
        task.cancel.assert_called_once_with()
        self.assertIsNone(self.cross.task)
        self.cross.on_activation.assert_called_once_with()
        self.assertEqual(self.cross._pending, {})
        self.assertTrue(file.exists())
        self.assertIn("local export off", result.lower())
        self.assertIn("purge", result.lower())
        self.assertIn("busy", result.lower())
        self.assertIn("cross off", result.lower())
        self.assertIn("export off", self.command("cross off"))
        self.assertFalse(file.exists())

    def test_corrupt_digest_restart_then_off_purges_and_advances_generation(self):
        for body in ("unparseable synthetic body", '{"schema":999}'):
            with self.subTest(body=body):
                self.command("cross on")
                self.exchange()
                old = self.cross.status()["generation"]
                control = json.loads((self.root / "control.json").read_text())["generation"]
                file = self.root / "profiles/specialist/digest.json"
                file.write_text(body)
                file.chmod(0o600)
                self.cross.close()
                self.cross = C.CrossBot(self.ctx, self.owner, clock=lambda: self.now)
                self.addCleanup(self.cross.close)
                self.assertIn("export off", self.command("cross off"))
                self.assertFalse(file.exists())
                presence = json.loads((file.parent / "presence.json").read_text())
                self.assertFalse(presence["enabled"])
                self.assertGreater(presence["generation"], old)
                self.assertGreater(json.loads((self.root / "control.json").read_text())["generation"], control)

    def test_dm_topic_binding_uses_exact_key_and_profile_namespace(self):
        self.key += ":7"
        self.owner.bind(self.key)
        self.assertIn("export on", self.command("cross on"))
        self.exchange(key=self.key.rsplit(":", 1)[0])
        self.assertEqual(self.cross.status()["exchanges"], 0)
        self.exchange(key="agent:other:telegram:dm:42:7")
        self.assertEqual(self.cross.status()["exchanges"], 0)
        self.exchange()
        self.assertEqual(self.cross.status()["exchanges"], 1)

    def test_activation_persists_and_off_restart_is_inert(self):
        self.command("cross on")
        self.assertTrue(self.ctx.get_config("cross_bot.enabled"))
        self.cross.close()
        self.cross = C.CrossBot(self.ctx, self.owner, clock=lambda: self.now)
        self.addCleanup(self.cross.close)
        self.assertTrue(self.cross.active)
        self.exchange()
        self.assertEqual(self.cross.status()["exchanges"], 1)
        self.command("cross off")
        self.assertFalse(self.ctx.get_config("cross_bot.enabled"))
        with patch.object(self.owner, "load", side_effect=AssertionError("off read")), \
             patch.object(C, "SharedStore", side_effect=AssertionError("off store")):
            restarted = C.CrossBot(self.ctx, self.owner, clock=lambda: self.now)
            self.addCleanup(restarted.close)
            self.assertFalse(restarted.active)
            self.assertIsNone(restarted.error)

    def test_off_before_end_and_reconnect_scope_are_captured(self):
        self.command("cross on")
        with patch.object(P, "caller_session_key", return_value=self.key):
            self.cross.on_turn_start(user_message="Draft", **self.kw)
            self.cross.on_turn_end(assistant_response="Done", **self.kw)
            self.command("cross off")
            self.command("cross on")
            self.cross.on_session_end(completed=True, failed=False, interrupted=False, **self.kw)
        self.assertEqual(list(self.root.glob("profiles/*/digest.json")), [])
        # A timer must never re-read ambient profile/config/state from another bot.
        self.ctx.profile_name = "other"
        self.ctx.get_config = lambda *a: self.fail("timer re-read ambient config")
        self.ctx.state = SimpleNamespace(get=lambda *a: self.fail("timer re-read ambient state"))
        self.cross.tick()
        self.assertTrue(self.cross.store.status("specialist")["bound"])
        self.assertFalse((self.root / "profiles/other").exists())

    def test_end_without_pre_legacy_end_and_wrong_ids_never_publish(self):
        self.command("cross on")
        with patch.object(P, "caller_session_key", return_value=self.key):
            self.cross.on_turn_end(user_message="Draft", assistant_response="Done", **self.kw)
            self.cross.on_session_end(completed=True, failed=False, interrupted=False, **self.kw)
            self.cross.on_turn_start(user_message="Draft", **self.kw)
            self.cross.on_turn_end(assistant_response="Done", **self.kw)
            self.cross.on_session_end(session_id="session-one", reason="exit")
            self.cross.on_session_end(**{**self.kw, "turn_id": "different", "completed": True, "failed": False, "interrupted": False})
        self.assertEqual(list(self.root.glob("profiles/*/digest.json")), [])

    def test_rebinding_before_completion_drops_old_owner_dm_exchange(self):
        self.command("cross on")
        with patch.object(P, "caller_session_key", return_value=self.key):
            self.cross.on_turn_start(user_message="Draft", **self.kw)
            self.cross.on_turn_end(assistant_response="Done", **self.kw)
            self.owner.bind("agent:specialist:telegram:dm:43")
            self.cross.on_session_end(completed=True, failed=False, interrupted=False, **self.kw)
        self.assertEqual(list(self.root.glob("profiles/*/digest.json")), [])

    def test_identical_human_ids_are_profile_isolated_and_wrong_scope_cannot_collect(self):
        self.command("cross on")
        other_ctx = FakeCtx()
        other_ctx.profile_name = "other"
        other_ctx.get_config = self.ctx.get_config
        other_owner = P.Proactivity(other_ctx)
        other_key = "agent:other:telegram:dm:42"
        other_owner.bind(other_key)
        other = C.CrossBot(other_ctx, other_owner, clock=lambda: self.now)
        self.addCleanup(other.close)
        with patch.object(P, "caller_session_key", return_value=other_key):
            other.command("cross on")
            self.cross.on_turn_start(user_message="belongs to other", **self.kw)
            self.cross.on_turn_end(assistant_response="Done", **self.kw)
            self.cross.on_session_end(completed=True, failed=False, interrupted=False, **self.kw)
        self.assertEqual(list(self.root.glob("profiles/*/digest.json")), [])
        self.exchange()
        self.assertEqual({f.parent.name for f in self.root.glob("profiles/*/digest.json")}, {"specialist"})


class ScopedTaskTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        routes = patch.object(C, "receiving_routes", return_value=[])
        routes.start()
        self.addCleanup(routes.stop)

    async def test_timer_is_supervised_idempotent_and_unload_cancels(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = FakeCtx()
            ctx.profile_name = "specialist"
            root = Path(tmp).resolve() / "shared"
            ctx.get_config = lambda key, default=None: str(root) if key == "cross_bot.shared_root" else default
            tasks = []
            def spawn(coro, **kwargs):
                task = asyncio.create_task(coro, **kwargs)
                tasks.append(task)
                return task
            ctx.spawn_task = spawn
            cross = C.CrossBot(ctx, P.Proactivity(ctx), clock=lambda: NOW)
            owner = cross.owner
            key = "agent:specialist:telegram:dm:42"
            owner.bind(key)
            with patch.object(P, "caller_session_key", return_value=key):
                cross.command("cross on")
            cross.on_telegram_connect()
            cross.on_telegram_connect()
            await asyncio.sleep(0)
            self.assertEqual(len(tasks), 1)
            with patch.object(P, "caller_session_key", return_value=key):
                self.assertIn("export off", cross.command("cross off"))
            await asyncio.sleep(0)
            self.assertTrue(tasks[0].cancelled())
            self.assertIsNone(cross.task)
            with patch.object(cross.owner, "load", side_effect=AssertionError("off read")):
                cross.on_telegram_connect()
            self.assertEqual(len(tasks), 1)
            cross.close()
            self.assertEqual(ctx.sent, [])

    async def test_sixty_second_tick_prunes_expired_text_using_captured_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [NOW]
            ctx = FakeCtx()
            ctx.profile_name = "specialist"
            root = Path(tmp).resolve() / "shared"
            ctx.get_config = lambda key, default=None: str(root) if key == "cross_bot.shared_root" else default
            ctx.spawn_task = lambda coro, **kw: asyncio.create_task(coro, **kw)
            owner = P.Proactivity(ctx)
            owner.bind("agent:specialist:telegram:dm:42")
            cross = C.CrossBot(ctx, owner, clock=lambda: now[0])
            with patch.object(P, "caller_session_key", return_value="agent:specialist:telegram:dm:42"):
                cross.command("cross on")
            cross.store.append("specialist", "one", "Draft", "Done")
            gate, ticked = asyncio.Event(), asyncio.Event()
            delays = []
            async def sleep(delay):
                delays.append(delay)
                await gate.wait()
                gate.clear()
            async def thread(fn):
                fn()
                ticked.set()
            real_sleep = asyncio.sleep
            with patch("asyncio.sleep", side_effect=sleep), patch("asyncio.to_thread", side_effect=thread):
                cross.on_telegram_connect()
                await real_sleep(0)
                now[0] += timedelta(hours=24)
                ctx.profile_name = "other"
                ctx.get_config = lambda *a: self.fail("background config access")
                ctx.state = SimpleNamespace(get=lambda *a: self.fail("background state access"))
                gate.set()
                await asyncio.wait_for(ticked.wait(), 1)
                self.assertEqual(delays[0], 60)
                self.assertFalse((root / "profiles/specialist/digest.json").exists())
                cross.close()
                await real_sleep(0)


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        routes = patch.object(C, "receiving_routes", return_value=[])
        routes.start()
        self.addCleanup(routes.stop)

    def test_off_primary_and_secondary_match_base_without_cross_state_or_store_io(self):
        # Cross-bot off preserves the base schema and shared voice, including
        # the task-completion wording; only explicit voice changes update these hashes.
        schema_sha = "94a082ce76756e20d76a4f9701c1a9cf3ed3eadf007efc1094d17da351f2d622"
        for profile in ("default", "primary", "specialist"):
            for configured in (False, True):
                with self.subTest(profile=profile, configured=configured), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp).resolve() / "shared"
                    ctx = FakeCtx()
                    ctx.profile_name = profile
                    config = {"cross_bot.primary": "primary", "cross_bot.enabled": False}
                    if configured:
                        config["cross_bot.shared_root"] = str(root)
                    ctx.get_config = lambda key, default=None: config.get(key, default)
                    hooks, tools, unloads = {}, {}, []
                    ctx.register_hook = lambda name, fn: hooks.setdefault(name, []).append(fn)
                    ctx.register_tool = lambda **kw: tools.__setitem__(kw["name"], kw)
                    ctx.register_command = ctx.register_cli_command = ctx.register_skill = lambda *a, **kw: None
                    ctx.register_platform_handler = lambda *a: None
                    ctx.on_unload = unloads.append
                    with patch.object(ctx.state, "get", side_effect=AssertionError("off state read")), \
                         patch.object(ctx.state, "set", side_effect=AssertionError("off state write")), \
                         patch.object(C, "SharedStore", side_effect=AssertionError("off store access")):
                        runtime = sys.modules[P.__package__].register(ctx, legacy_home=tmp)
                        cross = next(fn.__self__ for fn in unloads if isinstance(fn.__self__, C.CrossBot))
                        for fn in (cross.on_turn_start, cross.on_turn_end, cross.on_session_end, cross.on_telegram_connect, cross.tick):
                            fn()
                        self.assertIsNone(cross.error)
                        self.assertIsNone(cross.task)
                        self.assertFalse(root.exists())
                    self.assertEqual(runtime is not None, profile == "default")
                    self.assertEqual(any(isinstance(getattr(fn, "__self__", None), P.Proactivity)
                                         for fn in hooks["pre_llm_call"]),
                                     profile == "default")
                    if profile == "default":
                        self.assertEqual(C.hashlib.sha256(json.dumps(tools["proactivity"]["schema"], sort_keys=True).encode()).hexdigest(), schema_sha)
                        s = P.Settings(timezone="UTC")
                        for text, expected in ((runtime.prompt(s, timedelta(hours=2), NOW), "3a15e2cd26f14046e92be647bd86d3acd9a34ba69e7225ba712447dcfd7c5cc8"),
                                               (runtime.brief_prompt(s, NOW), "4a4a614ed8d439f6f0c6bcbaf21e0a817ced6eba03963deb1b377610fd813c07")):
                            self.assertEqual(C.hashlib.sha256(text.encode()).hexdigest(), expected)
                    else:
                        self.assertEqual(tools, {})
                    for fn in unloads:
                        fn()

    def test_every_profile_registers_collector_controls_and_local_binding_cli_without_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "custom-shared"
            for profile in ("default", "specialist"):
                hooks, commands, tools, clis, unloads = {}, {}, {}, {}, []
                ctx = FakeCtx()
                ctx.profile_name = profile
                ctx.get_config = lambda key, default=None: str(root) if key == "cross_bot.shared_root" else default
                ctx.register_hook = lambda name, fn: hooks.setdefault(name, []).append(fn)
                ctx.register_command = lambda name, fn, **kw: commands.__setitem__(name, fn)
                def register_tool(**kw):
                    tools[kw["name"]] = kw
                    return SimpleNamespace(dispose=lambda: tools.pop(kw["name"], None))
                ctx.register_tool = register_tool
                ctx.register_cli_command = lambda name, desc, setup, run: clis.__setitem__(name, run)
                ctx.register_skill = lambda *a: None
                ctx.on_unload = unloads.append
                runtime = sys.modules[P.__package__].register(ctx, background=False, legacy_home=tmp)
                self.addCleanup(lambda callbacks=unloads: [fn() for fn in callbacks])
                for name in ("pre_llm_call", "post_llm_call", "on_session_end"):
                    self.assertTrue(any(isinstance(getattr(fn, "__self__", None), C.CrossBot)
                                        for fn in hooks[name]))
                self.assertEqual(set(tools), {"proactivity"} if profile == "default" else set())
                key = f"agent:{'main' if profile == 'default' else profile}:telegram:dm:42"
                args = SimpleNamespace(action="bind", session_key=key, settings=None, timezone=None)
                with patch("builtins.print"):
                    self.assertEqual(clis["proactivity"](args), 0)
                with patch.object(P, "caller_session_key", return_value=key):
                    self.assertIn("on", commands["proactivity"]("cross on"))
                    blocked = json.loads(tools["proactivity"]["handler"]({"action": "set", "cross_bot_enabled": True}))
                    self.assertEqual(blocked["ask_user_to_send"], "/proactivity cross on")
                    cross = next(fn.__self__ for fn in unloads if isinstance(fn.__self__, C.CrossBot))
                    with patch.object(cross.store, "set_enabled", side_effect=ValueError("shared store is busy")):
                        self.assertIn("purge", commands["proactivity"]("cross off"))
                    self.assertEqual(set(tools), {"proactivity"} if profile == "default" else set())
                    if profile == "default":
                        self.assertEqual(tools["proactivity"]["schema"], P.SCHEMA)
                    self.assertIn("export off", commands["proactivity"]("cross off"))
                self.assertEqual(set(tools), {"proactivity"} if profile == "default" else set())
                if profile == "default":
                    self.assertEqual(tools["proactivity"]["schema"], P.SCHEMA)
                cross = next(fn.__self__ for fn in unloads if isinstance(fn.__self__, C.CrossBot))
                with patch.object(cross.owner, "load", side_effect=AssertionError("off state read")), \
                     patch.object(cross.store, "status", side_effect=AssertionError("off store read")):
                    cross.on_turn_start()
                    cross.on_turn_end()
                    cross.on_session_end()
                    cross.tick()
                self.assertIsNone(cross.error)
                if profile != "default":
                    self.assertIsNone(runtime)
                    self.assertEqual(ctx.sent, [])
            self.assertEqual(C.SharedStore(root).status("specialist")["bound"], True)


if __name__ == "__main__":
    unittest.main()
