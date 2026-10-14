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


class SanitizerTests(unittest.TestCase):
    def test_redaction_precedes_truncation_and_synthetic_secret_fixtures(self):
        secret = "synthetic-sensitive-value"
        private = "-----BEGIN " + "PRIVATE KEY-----\nsynthetic-key\n-----END " + "PRIVATE KEY-----"
        cases = ["password: " + secret, '{"access_token": "' + secret + '"}',
                 "DATABASE_PASSWORD=" + secret, "AWS_SECRET_ACCESS_KEY=" + secret,
                 '{"clientSecret": "' + secret + '"}',
                 "Authorization: Bearer " + secret, "OTP is 123456", "Cookie: session=" + secret,
                 "https://user:" + secret + "@example.invalid/page",
                 "https://example.invalid/?api_key=" + secret,
                 private, "token=" + "A" * 6000,
                 "ghp_" + "x" * 30, "sk-" + "x" * 40]
        for text in cases:
            with self.subTest(text=text[:16]):
                result = C.sanitize("Useful draft\n" + text + "\nKeep this", max_bytes=64)
                self.assertIn("Useful draft", result)
                self.assertNotIn(secret, result)
                self.assertNotIn("synthetic-key", result)
                self.assertNotIn("123456", result)
                self.assertNotIn("A" * 20, result)
                self.assertNotIn("x" * 20, result)

    def test_utf8_and_failure_drop_and_configurable_over_redaction(self):
        self.assertEqual(C.sanitize("é" * 100, max_bytes=7), "ééé")
        self.assertIsNone(C.sanitize("bad\ud800"))
        self.assertIsNone(C.sanitize("x" * 65537))
        self.assertIsNone(C.sanitize({"text": "attachment"}))
        self.assertNotIn("private project", C.sanitize("Private Project: draft", redact_terms=["private project"]))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "shared"
        self.store = C.SharedStore(self.root, primary="primary", clock=lambda: NOW)

    def test_enrollment_defaults_off_and_exports_only_after_operator_enable(self):
        self.store.presence("specialist", bound=True)
        self.assertFalse(self.store.status("specialist")["enabled"])
        self.assertFalse(self.store.append("specialist", "turn-one", "Draft a checklist", "First, review."))
        self.store.set_enabled("specialist", True, bound=True)
        self.assertTrue(self.store.append("specialist", "turn-one", "Draft a checklist", "First, review."))
        self.assertEqual(self.store.snapshot()["profiles"]["specialist"]["exchanges"][0]["user"], "Draft a checklist")
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
        exchanges = self.store.snapshot()["profiles"]["specialist"]["exchanges"]
        self.assertEqual([e["user"] for e in exchanges], ["Draft 2", "Draft 3", "Draft 4", "Draft 5"])
        restarted = C.SharedStore(self.root, primary="primary", clock=lambda: now[0])
        self.assertFalse(restarted.append("specialist", "0", "duplicate", "duplicate"))
        now[0] += timedelta(hours=24)
        restarted.prune()
        self.assertEqual(restarted.snapshot()["profiles"], {})
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
        # Offline presence is not eligible, even when its digest has fresh text.
        self.assertEqual(restarted.snapshot()["profiles"], {})

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

    def test_oversized_snapshot_is_refused_without_rotating_profiles(self):
        for number in range(16):
            name = "p" + str(number)
            self.store.set_enabled(name, True, bound=True)
            self.assertTrue(self.store.append(name, str(number), "x" * 1748, "y"))
        with self.assertRaisesRegex(ValueError, "snapshot too large"):
            self.store.snapshot()
        self.assertEqual(len(list((self.root / "profiles").iterdir())), 16)

    def test_symlink_files_directories_and_permissive_modes_fail_closed(self):
        self.store.set_enabled("specialist", True, bound=True)
        digest = self.root / "profiles/specialist/digest.json"
        target = self.root.parent / "outside"
        target.write_text("untouched")
        digest.symlink_to(target)
        with self.assertRaises(OSError):
            self.store.snapshot()
        self.assertEqual(target.read_text(), "untouched")
        digest.unlink()
        os.chmod(self.root, 0o755)
        with self.assertRaises(ValueError):
            self.store.snapshot()
        os.chmod(self.root, 0o700)
        presence = digest.parent / "presence.json"
        os.chmod(presence, 0o644)
        with self.assertRaises(ValueError):
            self.store.snapshot()
        os.chmod(presence, 0o600)
        directory = self.root / "profiles/linked"
        directory.symlink_to(target.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.store.snapshot()

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
                self.store.snapshot()
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
                self.store.snapshot()

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
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "shared"
        self.now = NOW
        self.ctx = FakeCtx()
        self.ctx.profile_name = "specialist"
        config = {"cross_bot.shared_root": str(self.root), "cross_bot.primary": "primary"}
        self.ctx.get_config = lambda key, default=None: config.get(key, default)
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
        self.assertEqual(self.cross.store.snapshot()["profiles"], {})
        self.assertIn("on", self.command("cross on"))
        with patch.object(P, "caller_session_key", return_value=self.key):
            self.cross.on_turn_start(user_message="Draft a checklist", parent_session_id="", **self.kw)
            self.cross.on_turn_end(user_message="Draft a checklist", assistant_response="First, review.", **self.kw)
            self.assertEqual(self.cross.store.snapshot()["profiles"], {})
            self.cross.on_session_end(completed=True, failed=False, interrupted=False, **self.kw)
        digest = self.cross.store.snapshot()["profiles"]["specialist"]
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
                self.assertEqual(self.cross.store.snapshot()["profiles"], {})
        self.ctx.current_cron_execution = lambda: object()
        self.exchange()
        self.assertEqual(self.cross.store.snapshot()["profiles"], {})

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

    def test_secret_sanitization_and_failed_sanitizer_never_write_raw_exchange(self):
        self.command("cross on")
        self.exchange(message="Draft\npassword: synthetic-private-value", response="Plan\nOTP: 123456")
        text = (self.root / "profiles/specialist/digest.json").read_text()
        self.assertNotIn("synthetic-private-value", text)
        self.assertNotIn("123456", text)
        self.assertNotIn("not exported", text)
        self.kw["turn_id"] = "turn-two"
        self.exchange(response="bad\ud800")
        self.assertEqual(self.cross.status()["exchanges"], 1)

    def test_off_before_end_and_reconnect_scope_are_captured(self):
        self.command("cross on")
        with patch.object(P, "caller_session_key", return_value=self.key):
            self.cross.on_turn_start(user_message="Draft", **self.kw)
            self.cross.on_turn_end(assistant_response="Done", **self.kw)
            self.command("cross off")
            self.command("cross on")
            self.cross.on_session_end(completed=True, failed=False, interrupted=False, **self.kw)
        self.assertEqual(self.cross.store.snapshot()["profiles"], {})
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
        self.assertEqual(self.cross.store.snapshot()["profiles"], {})

    def test_rebinding_before_completion_drops_old_owner_dm_exchange(self):
        self.command("cross on")
        with patch.object(P, "caller_session_key", return_value=self.key):
            self.cross.on_turn_start(user_message="Draft", **self.kw)
            self.cross.on_turn_end(assistant_response="Done", **self.kw)
            self.owner.bind("agent:specialist:telegram:dm:43")
            self.cross.on_session_end(completed=True, failed=False, interrupted=False, **self.kw)
        self.assertEqual(self.cross.store.snapshot()["profiles"], {})

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
        self.assertEqual(self.cross.store.snapshot()["profiles"], {})
        self.exchange()
        self.assertEqual(set(self.cross.store.snapshot()["profiles"]), {"specialist"})


class ScopedTaskTests(unittest.IsolatedAsyncioTestCase):
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
            cross.on_telegram_connect()
            cross.on_telegram_connect()
            await asyncio.sleep(0)
            self.assertEqual(len(tasks), 1)
            cross.close()
            await asyncio.sleep(0)
            self.assertTrue(tasks[0].cancelled())
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
            cross.store.set_enabled("specialist", True, bound=True)
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
                ctx.register_tool = lambda **kw: tools.__setitem__(kw["name"], kw)
                ctx.register_cli_command = lambda name, desc, setup, run: clis.__setitem__(name, run)
                ctx.register_skill = lambda *a: None
                ctx.on_unload = unloads.append
                runtime = sys.modules[P.__package__].register(ctx, background=False, legacy_home=tmp)
                self.addCleanup(lambda callbacks=unloads: [fn() for fn in callbacks])
                for name in ("pre_llm_call", "post_llm_call", "on_session_end"):
                    self.assertTrue(any(isinstance(fn.__self__, C.CrossBot) for fn in hooks[name]))
                self.assertEqual(set(tools), {"proactivity"})
                key = f"agent:{'main' if profile == 'default' else profile}:telegram:dm:42"
                args = SimpleNamespace(action="bind", session_key=key, settings=None, timezone=None)
                with patch("builtins.print"):
                    self.assertEqual(clis["proactivity"](args), 0)
                with patch.object(P, "caller_session_key", return_value=key):
                    self.assertIn("on", commands["proactivity"]("cross on"))
                    blocked = json.loads(tools["proactivity"]["handler"]({"action": "set", "cross_bot_enabled": True}))
                    self.assertEqual(blocked["ask_user_to_send"], "/proactivity cross on")
                if profile != "default":
                    self.assertIsNone(runtime)
                    self.assertEqual(ctx.sent, [])
            self.assertEqual(C.SharedStore(root).status("specialist")["bound"], True)


if __name__ == "__main__":
    unittest.main()
