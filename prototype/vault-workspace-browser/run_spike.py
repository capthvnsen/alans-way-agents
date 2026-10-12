"""PROTOTYPE (N6 spike, do not merge): end-to-end check of Hermes vault logins on the workspace
VPS browser.

Runs everything throwaway under one temp dir: a Chromium standing in for the workspace browser,
the real Alan's Workspace VPS browser host (vps-browser-host.cjs) on top of it, and a scratch
HERMES_HOME. Then, with Hermes' own tool functions (no model, no gateway):

  1. the host opens a bot tab on a neutral page (a router-owned tab);
  2. a login with an authenticator key is saved in the scratch vault;
  3. Hermes signs in to the TOTP test site: navigate, type the identifier, browser_vault_fill,
     browser_vault_enter_code, submit;
  4. the host opens a new bot tab on the site and checks it is signed in;
  5. the router-owned tab is checked for interference.

--mode naive  points Hermes straight at the workspace Chromium (browser.cdp_url).
--mode scoped uses the alans-way-workspace BrowserProvider (scoped CDP proxy).

Usage (on the VPS, from the Hermes checkout, with its venv):
  SPIKE_EMAIL=... SPIKE_PASSWORD=... SPIKE_TOTP_SECRET=... \
  venv/bin/python /path/to/run_spike.py --mode scoped --app /path/to/alans-way \
      --chrome /path/to/chrome
The SPIKE_* values are the public test account published on https://authenticationtest.com/totpChallenge/.
Secrets are never printed: vault tool results carry only counts and origins.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SITE = "https://authenticationtest.com"
CDP_PORT, HOST_PORT = 9333, 9467
HERE = Path(__file__).resolve().parent


def log(step, data=""):
    print(f"[{time.strftime('%H:%M:%S')}] {step}" + (f": {data}" if data != "" else ""), flush=True)


def get_json(url, method="GET", body=None, headers=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {url} -> {e.code}: {e.read()[:300]!r}")


def wait_for(fn, what, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if (v := fn()):
                return v
        except Exception:
            pass
        time.sleep(0.25)
    raise SystemExit(f"timed out waiting for {what}")


def pages():
    return [t for t in get_json(f"http://127.0.0.1:{CDP_PORT}/json/list") if t["type"] == "page"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["naive", "scoped"], required=True)
    ap.add_argument("--app", required=True, help="alans-way app checkout (for desktop/scripts/vps-browser-host.cjs)")
    ap.add_argument("--chrome", required=True)
    ap.add_argument("--profile", help="Chromium profile dir (snap Chromium only opens ones under ~/snap/chromium/common)")
    args = ap.parse_args()
    email, password, seed = (os.environ[k] for k in ("SPIKE_EMAIL", "SPIKE_PASSWORD", "SPIKE_TOTP_SECRET"))

    tmp = Path(tempfile.mkdtemp(prefix="n6-spike-"))
    procs = []
    try:
        # Workspace stand-in: Chromium + the real VPS browser host.
        profile = Path(args.profile) if args.profile else tmp / "profile"
        shutil.rmtree(profile, ignore_errors=True)
        procs.append(subprocess.Popen([args.chrome, "--headless=new", "--no-sandbox", f"--remote-debugging-port={CDP_PORT}",
                                       "--remote-debugging-address=127.0.0.1", f"--user-data-dir={profile}",
                                       "--no-first-run", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        wait_for(lambda: get_json(f"http://127.0.0.1:{CDP_PORT}/json/version"), "Chromium")
        host_data = tmp / "host"
        host_data.mkdir()
        (host_data / "config.json").write_text(json.dumps({"port": HOST_PORT, "cdpUrl": f"http://127.0.0.1:{CDP_PORT}"}))
        procs.append(subprocess.Popen(["node", str(Path(args.app) / "desktop/scripts/vps-browser-host.cjs"), "serve"],
                                      env={**os.environ, "HERMES_VPS_BROWSER_DATA": str(host_data)},
                                      stdout=open(tmp / "host.out", "w"), stderr=subprocess.STDOUT))
        conn = wait_for(lambda: json.loads((host_data / "connection.json").read_text()), "VPS browser host")
        bot = {"Authorization": f"Bearer {conn['token']}", "X-Hermes-Bot": "spike-bot"}
        host = f"http://127.0.0.1:{HOST_PORT}"

        time.sleep(2)  # the host answers before its first browser-wide subscriptions settle
        router_tab = get_json(f"{host}/v1/tabs", "POST", {"url": "https://example.com/"}, bot)
        wait_for(lambda: any("example.com" in p["url"] for p in pages()), "router tab load")
        router_target = next(p["id"] for p in pages() if "example.com" in p["url"])
        log("1. router-owned bot tab", {"tab": router_tab["id"], "url": router_tab["url"]})

        # Scratch Hermes home. Import Hermes only after HERMES_HOME points here.
        home = tmp / "hermes"
        home.mkdir()
        if args.mode == "naive":
            browser = {"cdp_url": f"http://127.0.0.1:{CDP_PORT}"}
            plugins = {}
        else:
            shutil.copytree(HERE / "alans-way-workspace", home / "plugins/browser/alans-way-workspace")
            os.environ["ALANS_WAY_WORKSPACE_CDP"] = f"http://127.0.0.1:{CDP_PORT}"
            browser = {"cloud_provider": "alans-way-workspace"}
            plugins = {"plugins": {"enabled": ["alans-way-workspace"]}}
        import yaml
        (home / "config.yaml").write_text(yaml.safe_dump({"browser": {**browser, "use_real_profile": False}, **plugins}))
        os.environ["HERMES_HOME"] = str(home)
        os.environ.pop("BROWSER_CDP_URL", None)
        sys.path.insert(0, os.getcwd())

        from hermes_cli.plugins import discover_plugins
        discover_plugins()
        from agent.vault_store import get_vault_store
        from tools import browser_tool as bt
        from tools.browser_vault_tool import browser_vault_enter_code, browser_vault_fill, browser_vault_list

        meta = get_vault_store().add_item("login", "authenticationtest", {
            "identifier_type": "email", "identifier": email, "password": password, "otp_secret": seed}, origin=SITE)
        log("2. vault item saved", {"handle": meta.id, "origin": meta.origin, "has_otp": meta.has_otp})
        log("   browser_vault_list", json.loads(browser_vault_list())["items"])

        task = "spike"
        nav = json.loads(bt.browser_navigate(f"{SITE}/totpChallenge/", task_id=task))
        log("3a. browser_navigate", {"success": nav.get("success"), "url": nav.get("url"), "error": nav.get("error")})
        log("    workspace Chromium pages now", [(p["id"][:8], p["url"]) for p in pages()])
        snap = json.loads(bt.browser_snapshot(task_id=task)).get("snapshot", "")
        ref = re.search(r'textbox "E-Mail Address".*?\[ref=(e\d+)\]', snap)
        log("3b. browser_type identifier", json.loads(bt.browser_type(f"@{ref.group(1)}", email, task_id=task)).get("success") if ref else "no email field")
        log("3c. browser_vault_fill", json.loads(browser_vault_fill(meta.id, task_id=task)))
        log("3d. browser_vault_enter_code", json.loads(browser_vault_enter_code(meta.id, task_id=task)))
        snap = json.loads(bt.browser_snapshot(task_id=task)).get("snapshot", "")
        ref = re.search(r'button "Log In".*?\[ref=(e\d+)\]', snap)
        log("3e. submit", json.loads(bt.browser_click(f"@{ref.group(1)}", task_id=task)).get("success") if ref else "no Log In button")
        time.sleep(3)
        log("    workspace Chromium pages now", [(p["id"][:8], p["url"]) for p in pages()])

        cont = get_json(f"{host}/v1/tabs", "POST", {"url": f"{SITE}/"}, bot)
        time.sleep(3)
        text = json.dumps(get_json(f"{host}/v1/tabs/{cont['id']}/snapshot", headers=bot))
        log("4. new workspace bot tab on the site", {"url": cont["url"], "signed_in": "Sign Out" in text,
                                                       "shows_sign_in": "Sign In" in text})

        router_now = next((p for p in pages() if p["id"] == router_target), None)
        log("5. router-owned tab afterwards", {"still_open": router_now is not None,
                                               "url": router_now and router_now["url"],
                                               "host_view": get_json(f"{host}/v1/tabs/{router_tab['id']}", headers=bot).get("url")})
        if args.mode == "scoped":
            from websockets.sync.client import connect
            with connect(bt._active_sessions[bt._last_session_key(task)]["cdp_url"]) as ws:
                ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
                seen = [t["url"] for t in json.loads(ws.recv())["result"]["targetInfos"] if t["type"] == "page"]
                ws.send(json.dumps({"id": 2, "method": "Target.attachToTarget", "params": {"targetId": router_target, "flatten": True}}))
                log("6. scoped view", {"pages_visible_to_hermes": seen, "attach_router_tab": json.loads(ws.recv()).get("error")})
    finally:
        for p in reversed(procs):
            p.terminate()
        log("host log tail", (tmp / "host.out").read_text()[-600:] if (tmp / "host.out").exists() else "")
        shutil.rmtree(tmp, ignore_errors=True)
        if args.profile:
            shutil.rmtree(args.profile, ignore_errors=True)


if __name__ == "__main__":
    main()
