"""PROTOTYPE (N6 spike, do not merge): a CDP proxy that scopes one Hermes browser session to
the targets it creates on the shared workspace VPS Chromium.

Hermes drives whatever CDP endpoint a BrowserProvider returns browser-wide: the supervisor
attaches to the FIRST page target and vault fills scan ALL page targets by origin. Pointed
straight at the workspace Chromium, that is the router's tabs. Through this proxy the session
sees, attaches to and closes only targets it created (plus pop-ups they open), while staying in
the default browser context so the workspace tabs share its cookies.

Runs in the Hermes process (websockets is already a Hermes dependency). One ScopedProxy per
provider session; every connection to it (agent-browser daemon, supervisor) shares `owned`.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
from http import HTTPStatus

import websockets

# Commands that name a targetId the caller must own.
_TARGET_SCOPED = {"Target.attachToTarget", "Target.closeTarget", "Target.activateTarget",
                  "Target.getTargetInfo", "Target.exposeDevToolsProtocol"}
_REFUSED = {"Browser.close", "Browser.crash"}
_INTERNAL_ID = 1 << 30  # ids the proxy itself uses upstream; never collide with client ids


class ScopedProxy:
    def __init__(self, upstream_ws: str):
        self.upstream_ws = upstream_ws
        self.token = secrets.token_hex(16)
        self.owned: set[str] = set()
        self.loop = asyncio.new_event_loop()
        self.port = 0
        self._server = None
        self._started = threading.Event()

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/devtools/browser/{self.token}"

    def start(self) -> "ScopedProxy":
        threading.Thread(target=self._thread, daemon=True, name="scoped-cdp-proxy").start()
        if not self._started.wait(10):
            raise RuntimeError("scoped CDP proxy did not start")
        return self

    def stop(self) -> None:
        if self._server is not None:
            self.loop.call_soon_threadsafe(self._server.close)

    def _thread(self) -> None:
        asyncio.set_event_loop(self.loop)

        async def main():
            self._server = await websockets.serve(self._client, "127.0.0.1", 0, max_size=None,
                                                  process_request=self._http)
            self.port = self._server.sockets[0].getsockname()[1]
            self._started.set()
            await self._server.wait_closed()

        self.loop.run_until_complete(main())

    def _http(self, connection, request):
        # Only the tokened path is served: the port alone grants nothing.
        if request.path in ("/json/version", "/json/version/"):
            response = connection.respond(HTTPStatus.OK, json.dumps(
                {"Browser": "alans-way-workspace (scoped)", "webSocketDebuggerUrl": self.ws_url}))
            response.headers["Content-Type"] = "application/json"
            return response
        if request.path != f"/devtools/browser/{self.token}":
            return connection.respond(HTTPStatus.NOT_FOUND, "not found\n")
        return None

    async def _client(self, client):
        async with websockets.connect(self.upstream_ws, max_size=None) as upstream:
            try:
                await _Link(self, client, upstream).run()
            except websockets.ConnectionClosed:
                pass  # either side went away; the other closes with this handler


class _Link:
    """One client connection and its own upstream connection."""

    def __init__(self, proxy: ScopedProxy, client, upstream):
        self.proxy, self.client, self.upstream = proxy, client, upstream
        self.sessions: set[str] = set()      # flat sessions this client may use
        self.pending: dict[int, str] = {}    # client call id -> method, for result rewriting
        self.parked: list[dict] = []         # events for targets whose createTarget reply is pending
        self.next_internal = _INTERNAL_ID

    async def run(self) -> None:
        await asyncio.gather(self._from_client(), self._from_upstream())

    async def _internal(self, method: str, params: dict, session_id: str | None = None) -> None:
        self.next_internal += 1
        msg = {"id": self.next_internal, "method": method, "params": params}
        if session_id:
            msg["sessionId"] = session_id
        await self.upstream.send(json.dumps(msg))

    async def _from_client(self) -> None:
        async for raw in self.client:
            msg = json.loads(raw)
            method, params, sid = msg.get("method", ""), msg.get("params") or {}, msg.get("sessionId")
            refusal = None
            if sid and sid not in self.sessions:
                refusal = "session not owned by this scoped browser"
            elif method in _REFUSED:
                refusal = f"{method} is not allowed on the shared workspace browser"
            elif not sid and method in _TARGET_SCOPED and params.get("targetId") not in self.proxy.owned:
                refusal = "target not owned by this scoped browser"
            if refusal:
                await self.client.send(json.dumps({"id": msg.get("id"), "error": {"code": -32000, "message": refusal},
                                                   **({"sessionId": sid} if sid else {})}))
                continue
            if not sid:
                self.pending[msg.get("id")] = method
            await self.upstream.send(raw)

    def _owned(self, info: dict) -> bool:
        owned = self.proxy.owned
        if info.get("targetId") in owned:
            return True
        if info.get("openerId") in owned:  # a pop-up of ours is ours
            owned.add(info["targetId"])
            return True
        return False

    async def _deliver_event(self, msg: dict) -> None:
        method, params = msg["method"], msg.get("params") or {}
        if method == "Target.attachedToTarget":
            info, child = params.get("targetInfo") or {}, params.get("sessionId")
            if info.get("type") in ("page", "tab") and not self._owned(info):
                if any(m == "Target.createTarget" for m in self.pending.values()):
                    self.parked.append(msg)
                    return
                # Auto-attach caught a foreign tab: let it run and let go, never surface it.
                if params.get("waitingForDebugger"):
                    await self._internal("Runtime.runIfWaitingForDebugger", {}, child)
                await self._internal("Target.detachFromTarget", {"sessionId": child})
                return
            self.sessions.add(child)
        elif method in ("Target.targetCreated", "Target.targetInfoChanged"):
            info = params.get("targetInfo") or {}
            if info.get("type") in ("page", "tab") and not self._owned(info):
                if method == "Target.targetCreated" and any(m == "Target.createTarget" for m in self.pending.values()):
                    self.parked.append(msg)
                return
        elif method in ("Target.targetDestroyed", "Target.targetCrashed"):
            if params.get("targetId") not in self.proxy.owned:
                return
        elif method == "Target.detachedFromTarget":
            if params.get("sessionId") not in self.sessions:
                return
        await self.client.send(json.dumps(msg))

    async def _from_upstream(self) -> None:
        async for raw in self.upstream:
            msg = json.loads(raw)
            sid, mid = msg.get("sessionId"), msg.get("id")
            if mid is not None and mid > _INTERNAL_ID:
                continue  # reply to the proxy's own housekeeping
            if sid:
                if sid in self.sessions:
                    await self.client.send(raw)
                continue
            if mid is None:
                await self._deliver_event(msg)
                continue
            method = self.pending.pop(mid, "")
            result = msg.get("result") or {}
            if method == "Target.createTarget" and result.get("targetId"):
                self.proxy.owned.add(result["targetId"])
            elif method == "Target.attachToTarget" and result.get("sessionId"):
                self.sessions.add(result["sessionId"])
            elif method == "Target.getTargets":
                result["targetInfos"] = [t for t in result.get("targetInfos", [])
                                         if t.get("type") not in ("page", "tab") or self._owned(t)]
                raw = json.dumps(msg)
            await self.client.send(raw)
            if method == "Target.createTarget":
                parked, self.parked = self.parked, []
                for event in parked:
                    await self._deliver_event(event)
