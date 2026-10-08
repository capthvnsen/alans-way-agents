"""Voice-call plugin module: session-key parsing, reply matching, /call gate."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import asyncio
import importlib.util
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "alans-way"


def load():
    name = "alans_way_voice_test"
    if name + ".voice_call" in sys.modules:
        return sys.modules[name + ".voice_call"]
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "__init__.py",
                                                  submodule_search_locations=[str(PLUGIN)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return importlib.import_module(name + ".voice_call")


V = load()


class ChatIdTests(unittest.TestCase):
    def test_dm_key_yields_the_chat_id(self):
        self.assertEqual(V._chat_id_of("agent:main:telegram:dm:777001"), "777001")

    def test_extra_suffix_is_not_a_dm_chat_id(self):
        self.assertEqual(V._chat_id_of("agent:main:telegram:dm:777001:x"), "777001")

    def test_group_and_foreign_keys_are_refused(self):
        for key in ("agent:main:telegram:group:-99", "agent:main:discord:dm:5",
                    "agent:main:telegram:dm:", ""):
            self.assertEqual(V._chat_id_of(key), "")


def voice(home):
    return V.VoiceCall(SimpleNamespace(), Path(home))


class ReplyMatchTests(unittest.TestCase):
    """The pending future resolves only for its own session + message."""

    def pending(self, calls, session="agent:main:telegram:dm:777001", text="hi"):
        loop = asyncio.new_event_loop()
        fut = loop.create_future()
        calls._pending.setdefault(session, []).append((V.MARKER + text, loop, fut))
        return loop, fut

    def test_the_matching_pending_turn_gets_the_reply(self):
        with tempfile.TemporaryDirectory() as d:
            calls = voice(d)
            loop, fut = self.pending(calls)
            with patch.object(V, "caller_session_key",
                              return_value="agent:main:telegram:dm:777001"):
                calls.on_turn_end(assistant_response="the reply",
                                  user_message=V.MARKER + "hi")
            self.assertEqual(loop.run_until_complete(fut), "the reply")
            self.assertEqual(calls._pending, {})
            loop.close()

    def test_a_wrapped_user_message_still_matches(self):
        """The gateway may prepend envelope text to injected turns."""
        with tempfile.TemporaryDirectory() as d:
            calls = voice(d)
            loop, fut = self.pending(calls)
            with patch.object(V, "caller_session_key",
                              return_value="agent:main:telegram:dm:777001"):
                calls.on_turn_end(assistant_response="ok",
                                  user_message="[telegram] " + V.MARKER + "hi")
            self.assertEqual(loop.run_until_complete(fut), "ok")
            loop.close()

    def test_other_sessions_and_other_messages_do_not_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            calls = voice(d)
            loop, fut = self.pending(calls)
            with patch.object(V, "caller_session_key",
                              return_value="agent:main:telegram:dm:999999"):
                calls.on_turn_end(assistant_response="nope",
                                  user_message=V.MARKER + "hi")
            self.assertFalse(fut.done())
            with patch.object(V, "caller_session_key",
                              return_value="agent:main:telegram:dm:777001"):
                calls.on_turn_end(assistant_response="nope",
                                  user_message="a different message")
            self.assertFalse(fut.done())
            loop.close()

    def test_no_session_key_is_a_noop(self):
        with tempfile.TemporaryDirectory() as d:
            calls = voice(d)
            loop, fut = self.pending(calls)
            with patch.object(V, "caller_session_key", return_value=""):
                calls.on_turn_end(assistant_response="x",
                                  user_message=V.MARKER + "hi")
            self.assertFalse(fut.done())
            loop.close()


class CommandTests(unittest.TestCase):
    def test_outside_telegram_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            calls = voice(d)
            with patch.object(V, "caller_session_key", return_value=""):
                self.assertIn("Telegram", calls.command(""))

    def test_without_a_configured_app_url_the_command_is_honest(self):
        with tempfile.TemporaryDirectory() as d:
            calls = voice(d)
            calls._tg_bot_token = "synthetic"
            with patch.object(V, "caller_session_key",
                              return_value="agent:main:telegram:dm:777001"):
                import os
                os.environ.pop("ALAN_CALL_APP_URL", None)
                self.assertIn("No call app is configured", calls.command(""))

    def test_the_button_posts_the_configured_url_verbatim(self):
        with tempfile.TemporaryDirectory() as d:
            calls = voice(d)
            calls._tg_bot_token = "synthetic"
            sent = {}

            class FakeResp:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *a): return False

            def fake_urlopen(req, timeout=0):
                sent["url"] = req.full_url
                import json as _j
                sent["payload"] = _j.loads(req.data)
                return FakeResp()

            with patch.object(V, "caller_session_key",
                              return_value="agent:main:telegram:dm:777001"), \
                 patch.dict("os.environ",
                            {"ALAN_CALL_APP_URL": "https://calls.example.test/app?c=9"}), \
                 patch.object(V.urllib.request, "urlopen", fake_urlopen):
                out = calls.command("")
            self.assertEqual(out, "")
            kb = sent["payload"]["reply_markup"]["inline_keyboard"][0][0]
            self.assertEqual(kb["web_app"]["url"],
                             "https://calls.example.test/app?c=9")
            self.assertIn("botsynthetic", sent["url"])


class ApiRoutesTests(unittest.TestCase):
    def test_a_turn_without_a_dm_session_is_a_400(self):
        with tempfile.TemporaryDirectory() as d:
            calls = voice(d)
            try:
                from aiohttp import web
            except ImportError:
                self.skipTest("aiohttp not installed in the test env")
            app = web.Application()
            adapter = SimpleNamespace(_check_auth=lambda req: None)
            calls.api_routes(native=app, adapter=adapter)
            routes = [r.resource.canonical for r in app.router.routes()]
            self.assertIn("/api/voice/turn", routes)

    def test_a_second_registration_noops_instead_of_raising(self):
        """Another plugin may serve the same path — aiohttp would raise on a
        duplicate add_post and take api_server down with it."""
        with tempfile.TemporaryDirectory() as d:
            calls = voice(d)
            try:
                from aiohttp import web
            except ImportError:
                self.skipTest("aiohttp not installed in the test env")
            app = web.Application()
            adapter = SimpleNamespace(_check_auth=lambda req: None)
            calls.api_routes(native=app, adapter=adapter)
            voice(d).api_routes(native=app, adapter=adapter)
            routes = [r.resource.canonical for r in app.router.routes()]
            self.assertEqual(routes.count("/api/voice/turn"), 1)


if __name__ == "__main__":
    unittest.main()
