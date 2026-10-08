"""Generic voice-turn hook: an api_server route that injects a spoken turn.

``POST /api/voice/turn`` (same Bearer auth as every api_server route) takes
``{chat_id, text}`` — or a full ``session_key`` — and injects the text as a
user turn on that Telegram DM session via ``ctx.inject_message``. The reply
is captured when the turn's ``post_llm_call`` hook fires and returned in the
HTTP response, so a caller-side speech layer can both log and speak it.

The ``/call`` chat command posts a call-button (an inline ``web_app``
keyboard) into the DM when ``ALAN_CALL_APP_URL`` is set in the environment or
~/.hermes/.env — the plugin ships no default URL; whatever serves that URL
decides how a call actually works.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import urllib.request
from pathlib import Path

from .proactivity import caller_session_key

# Voice turns are tagged in the transcript so spoken and typed messages stay
# distinguishable; any transport matching replies against user_message should
# use the same prefix.
MARKER = "🎙 "
TURN_TIMEOUT_S = float(os.environ.get("ALAN_CALL_TURN_TIMEOUT", "150"))


def _env(home: Path, key: str) -> str:
    v = os.environ.get(key, "").strip()
    if v:
        return v
    try:
        for line in (home / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip("'").strip('"')
    except OSError:
        pass
    return ""


def _chat_id_of(session_key: str) -> str:
    tag = ":telegram:dm:"
    if tag in session_key and not session_key.endswith(tag):
        return session_key.rsplit(tag, 1)[1].split(":", 1)[0]
    return ""


class VoiceCall:
    def __init__(self, ctx, home: Path):
        self.ctx = ctx
        self.home = home
        self._lock = threading.Lock()
        # session_key -> [(expected_user_message, loop, asyncio.Future)]
        self._pending: dict[str, list] = {}
        self._tg_bot_token = ""

    # -- api_server native route -------------------------------------------------

    def api_routes(self, native=None, adapter=None, **kwargs):
        """register_platform_handler("api_server") factory — `native` is the
        aiohttp web.Application; routes must be added before AppRunner.setup."""
        try:
            from aiohttp import web
        except Exception:
            return
        # Another plugin may already serve the same route — whichever loads
        # first wins; a duplicate add_post would raise and kill api_server.
        for resource in native.router.resources():
            if getattr(resource, "canonical", None) == "/api/voice/turn":
                return

        async def turn(request):
            denied = adapter._check_auth(request)
            if denied is not None:
                return denied
            try:
                body = await request.json()
            except Exception:
                return web.json_response({"error": "expected JSON"}, status=400)
            text = (body.get("text") or "").strip()
            session_key = (body.get("session_key") or "").strip()
            if not session_key and str(body.get("chat_id") or "").strip():
                session_key = f"agent:main:telegram:dm:{str(body['chat_id']).strip()}"
            if not text or not _chat_id_of(session_key):
                return web.json_response({"error": "missing text or telegram dm session"}, status=400)

            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            expected = MARKER + text
            with self._lock:
                self._pending.setdefault(session_key, []).append((expected, loop, fut))
            try:
                try:
                    accepted = self.ctx.inject_message(expected, role="user", session_key=session_key)
                except Exception:
                    accepted = False
                if not accepted:
                    return web.json_response({"error": "turn refused — is the gateway up?"}, status=503)
                try:
                    reply = await asyncio.wait_for(fut, timeout=TURN_TIMEOUT_S)
                except asyncio.TimeoutError:
                    return web.json_response({"status": "queued"}, status=202)
                return web.json_response({"reply": reply or ""})
            finally:
                with self._lock:
                    lst = self._pending.get(session_key)
                    if lst:
                        self._pending[session_key] = [p for p in lst if p[2] is not fut]
                        if not self._pending[session_key]:
                            del self._pending[session_key]

        native.router.add_post("/api/voice/turn", turn)

    # -- reply capture ------------------------------------------------------------

    def on_turn_end(self, assistant_response=None, user_message=None, **_kwargs):
        """post_llm_call hook — resolves the pending voice turn whose injected
        user_message matches this finished turn, keyed by its session."""
        key = caller_session_key()
        if not key or user_message is None:
            return
        with self._lock:
            lst = self._pending.get(key)
            if not lst:
                return
            idx = next((i for i, (msg, _, f) in enumerate(lst)
                        if not f.done()
                        and (msg == user_message or str(user_message).endswith(msg))),
                       None)
            if idx is None:
                return
            _, loop, fut = lst.pop(idx)
            if not lst:
                del self._pending[key]
        loop.call_soon_threadsafe(
            lambda: None if fut.done() else fut.set_result(assistant_response or ""))

    # -- /call command -------------------------------------------------------------

    def on_telegram_connect(self, native=None, adapter=None, **_kwargs):
        """Capture the PTB bot for the /call button post."""
        try:
            self._tg_bot_token = native.bot.token or ""
        except Exception:
            pass

    def command(self, raw_args=""):
        """`/call` — post the 📞 Call web_app button into this DM."""
        key = caller_session_key()
        chat_id = _chat_id_of(key)
        if not chat_id:
            return "Call is for Telegram chats — run /call there."
        url = _env(self.home, "ALAN_CALL_APP_URL").rstrip("/")
        token = self._tg_bot_token or _env(self.home, "TELEGRAM_BOT_TOKEN")
        if not url or not token:
            return "No call app is configured on this install."
        payload = {
            "chat_id": chat_id,
            "text": "📞 Tap to call — I'll hear you, answer here and out loud.",
            "reply_markup": {"inline_keyboard": [[{"text": "📞 Call", "web_app": {"url": url}}]]},
        }
        try:
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    return f"call: Telegram returned {resp.status} posting the button"
        except Exception as exc:
            return f"call: could not post the button ({type(exc).__name__})"
        return ""
