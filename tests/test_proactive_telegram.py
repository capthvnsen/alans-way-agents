"""Approve, snooze and dismiss buttons: the bound human's tap is the approval."""
from pathlib import Path
from unittest.mock import patch
import asyncio
import importlib.util
import json
import sys
import tempfile
import threading
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "alans-way"
ROUTE = "agent:main:telegram:dm:123456789"


def load_plugin():
    name = "companion_proactive_telegram_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "__init__.py",
                                                submodule_search_locations=[str(PLUGIN)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def telegram_stubs():
    telegram = types.ModuleType("telegram")
    telegram.InlineKeyboardButton = lambda text, callback_data: {"text": text, "callback_data": callback_data}
    telegram.InlineKeyboardMarkup = lambda rows: {"rows": rows}
    ext = types.ModuleType("telegram.ext")
    ext.CallbackQueryHandler = lambda callback, pattern: {"callback": callback, "pattern": pattern}
    return {"telegram": telegram, "telegram.ext": ext}


class App:
    def __init__(self):
        self.handlers, self.sent = [], []
        self.bot = self

    def add_handler(self, handler):
        self.handlers.append(handler)

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)


class Query:
    def __init__(self, data, user_id, chat_id):
        self.data, self.from_user = data, types.SimpleNamespace(id=user_id)
        self.message = types.SimpleNamespace(chat_id=chat_id)
        self.answered, self.edited = [], []

    async def answer(self, text=None):
        self.answered.append(text)

    async def edit_message_text(self, text):
        self.edited.append(text)


PROPOSAL = {"id": "rent", "title": "Rent", "scope": "Check rent posts", "next_action": "Check the feed",
            "owner": "primary", "status": "active", "cadence_seconds": 3600}


class TelegramButtonTests(unittest.TestCase):
    def setUp(self):
        self.module = load_plugin()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.runtime = self.module.Runtime(None, Path(self.directory.name))
        self.runtime.store.update_policy({"session_key": ROUTE})
        self.addCleanup(self.runtime.close)
        env = patch.dict("os.environ", {"HERMES_SESSION_KEY": ROUTE})
        env.start()
        self.addCleanup(env.stop)

    def propose(self, **changes):
        return json.loads(self.runtime.tool_control({"action": "record_task", "task": {**PROPOSAL, **changes}}))

    def code(self, watch_id="rent"):
        task = next(t for t in self.runtime.ledger.snapshot()["tasks"] if t["id"] == watch_id)
        return self.runtime.ledger.proposal_hash(task)

    def tap(self, data, user=123456789, chat=123456789):
        tg = importlib.import_module(self.module.__name__ + ".proactive_telegram")
        return tg.handle_callback(self.runtime, data, user, chat)

    def status(self, watch_id="rent"):
        return next(t for t in self.runtime.ledger.snapshot()["tasks"] if t["id"] == watch_id)["status"]

    def test_only_the_bound_user_in_the_bound_chat_can_decide(self):
        self.propose()
        data = f"aw:a:rent:{self.code()}"
        for user, chat in ((999, 123456789), (123456789, 999), (None, None)):
            answer, text = self.tap(data, user, chat)
            self.assertIsNone(text)
            self.assertEqual(self.status(), "proposed")
        answer, text = self.tap(data)
        self.assertEqual(self.status(), "active")
        self.assertIn("Check rent posts", text)
        self.assertIn("Check the feed", text)

    def test_stale_hash_dismiss_and_garbage(self):
        self.propose()
        stale = f"aw:a:rent:{self.code()}"
        self.propose(next_action="Something else")
        answer, text = self.tap(stale)
        self.assertIn("changed since you read it", text)
        self.assertIn("changed", answer)
        self.assertEqual(self.status(), "proposed")
        self.assertEqual(self.runtime.ledger.recent_log()[-1]["outcome"], "stale")
        answer, text = self.tap(f"aw:d:rent:{self.code()}")
        self.assertIn("Dismissed", text)
        self.assertEqual(self.runtime.ledger.recent_log()[-1]["outcome"], "dismissed")
        self.assertEqual(self.status(), "cancelled")
        for junk in ("aw:s:rent:abcd1234", "aw:x:rent:abcd1234", "aw:a", "aw:a:ghost:abcd1234", "other:a:rent:x"):
            answer, text = self.tap(junk)
            self.assertIsNone(text, junk)
            self.assertIn("no longer valid", answer)

    def test_slash_fallbacks_match_the_buttons(self):
        self.propose()
        self.assertIn("Dismissed", self.runtime.watch_command("dismiss rent"))
        self.assertIn("failed", self.runtime.watch_command("dismiss rent"))
        self.assertIn("Use /watch", self.runtime.watch_command("snooze rent"))

    def test_three_dismissals_suppress_a_kind_until_an_approval(self):
        for name in "abcd":
            self.assertTrue(self.propose(id=name, kind="loop")["ok"])
        for name in "abc":
            self.runtime.watch_command(f"dismiss {name}")
        refused = self.propose(id="e", kind="loop")
        self.assertFalse(refused["ok"])
        self.assertIn("dismissed", refused["error"])
        self.assertTrue(self.propose(id="e", kind="sweep")["ok"])
        self.runtime.watch_command("approve d")
        self.assertTrue(self.propose(id="f", kind="loop")["ok"])

    def test_dismissals_older_than_two_weeks_do_not_count(self):
        from datetime import datetime, timedelta, timezone
        for name in "abc":
            self.propose(id=name)
            self.runtime.watch_command(f"dismiss {name}")
        with self.runtime.ledger.transaction() as data:
            old = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
            data["dismissals"]["watch"][0] = old
        self.assertTrue(self.propose(id="d")["ok"])

    def test_registration_degrades_without_a_telegram_hook(self):
        ctx = types.SimpleNamespace(register_tool=lambda **k: None, register_command=lambda *a, **k: None,
                                    register_skill=lambda *a, **k: None, on_unload=lambda *a: None)
        runtime = self.module.register(ctx, home=Path(self.directory.name) / "h", background=False)
        self.assertIsNone(runtime.telegram)
        runtime.close()

    def test_factory_wires_a_pattern_scoped_handler_and_proposals_send_buttons(self):
        registered = []
        ctx = types.SimpleNamespace(register_tool=lambda **k: None, register_command=lambda *a, **k: None,
                                    register_skill=lambda *a, **k: None, on_unload=lambda *a: None,
                                    register_telegram_handler=registered.append)
        runtime = self.module.register(ctx, home=Path(self.directory.name) / "h2", background=False)
        runtime.store.update_policy({"session_key": ROUTE})
        self.assertEqual(len(registered), 1)
        app, loop = App(), asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (loop.call_soon_threadsafe(loop.stop), thread.join(2), loop.close()))
        with patch.dict(sys.modules, telegram_stubs()):
            async def wire():
                registered[0](app, types.SimpleNamespace())
            asyncio.run_coroutine_threadsafe(wire(), loop).result(5)
            self.assertEqual([h["pattern"] for h in app.handlers], [r"^aw:"])
            reply = json.loads(runtime.tool_control({"action": "record_task", "task": PROPOSAL}))
            self.assertTrue(reply["ok"])
            deadline = 50
            while not app.sent and deadline:
                threading.Event().wait(0.1)
                deadline -= 1
        message, = app.sent
        self.assertEqual(message["chat_id"], 123456789)
        self.assertIn("Check rent posts", message["text"])
        buttons = [b for row in message["reply_markup"]["rows"] for b in row]
        self.assertEqual([b["text"] for b in buttons], ["Approve", "Dismiss"])
        self.assertTrue(all(len(b["callback_data"].encode()) <= 64 for b in buttons))
        self.assertEqual([b["callback_data"].split(":")[1] for b in buttons], ["a", "d"])
        # An over-long id falls back to the text command.
        json.loads(runtime.tool_control({"action": "record_task", "task": {**PROPOSAL, "id": "x" * 60}}))
        threading.Event().wait(0.3)
        self.assertEqual(len(app.sent), 1)
        runtime.close()

    def expired(self, runtime, **changes):
        from datetime import datetime, timedelta, timezone
        runtime.store.update_policy({"session_key": ROUTE})
        runtime.ledger.record_task({**PROPOSAL, **changes, "approved": True})
        with runtime.ledger.transaction() as data:
            data["tasks"][changes.get("id", "rent")]["approved_at"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()

    def register(self, name, handler, injected):
        ctx = types.SimpleNamespace(register_tool=lambda **k: None, register_command=lambda *a, **k: None,
                                    register_skill=lambda *a, **k: None, on_unload=lambda *a: None,
                                    inject_message=lambda message, **k: injected.append(message) or True)
        if handler is not None:
            ctx.register_telegram_handler = handler.append
        return self.module.register(ctx, home=Path(self.directory.name) / name, background=False)

    def test_reapproval_waits_for_telegram_then_sends_buttons_once(self):
        registered, injected = [], []
        runtime = self.register("h3", registered, injected)
        self.addCleanup(runtime.close)
        self.expired(runtime)
        runtime._ask_reapproval()
        self.assertEqual(injected, [])
        app, loop = App(), asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (loop.call_soon_threadsafe(loop.stop), thread.join(2), loop.close()))
        with patch.dict(sys.modules, telegram_stubs()):
            async def wire():
                registered[0](app, types.SimpleNamespace())
            asyncio.run_coroutine_threadsafe(wire(), loop).result(5)
            runtime._ask_reapproval()
            runtime._ask_reapproval()
            threading.Event().wait(0.3)
        message, = app.sent
        self.assertIn("approving again", message["text"])
        self.assertEqual(injected, [])

    def test_reapproval_without_buttons_sends_the_text_command_once(self):
        injected = []
        runtime = self.register("h4", None, injected)
        self.addCleanup(runtime.close)
        self.expired(runtime)
        runtime._ask_reapproval()
        runtime._ask_reapproval()
        message, = injected
        self.assertIn(f"/watch approve rent {self.code_for(runtime)}", message)

    def test_reapproval_with_an_over_long_id_uses_text_even_when_connected(self):
        registered, injected = [], []
        runtime = self.register("h5", registered, injected)
        self.addCleanup(runtime.close)
        runtime.telegram = {"application": App(), "loop": object()}
        self.expired(runtime, id="x" * 60)
        runtime._ask_reapproval()
        message, = injected
        self.assertIn("/watch approve " + "x" * 60, message)

    def code_for(self, runtime, watch_id="rent"):
        task = next(t for t in runtime.ledger.snapshot()["tasks"] if t["id"] == watch_id)
        return runtime.ledger.proposal_hash(task)

    def test_button_handler_answers_and_edits_the_message(self):
        self.propose()
        tg = importlib.import_module(self.module.__name__ + ".proactive_telegram")
        query = Query(f"aw:a:rent:{self.code()}", 123456789, 123456789)
        asyncio.run(tg.on_button(self.runtime, types.SimpleNamespace(callback_query=query), None))
        self.assertIn("approved", query.edited[0])
        self.assertEqual(self.status(), "active")
        denied = Query("aw:a:rent:00000000", 5, 123456789)
        asyncio.run(tg.on_button(self.runtime, types.SimpleNamespace(callback_query=denied), None))
        self.assertEqual(denied.edited, [])
        self.assertEqual(denied.answered, ["Not authorized"])


if __name__ == "__main__":
    unittest.main()
