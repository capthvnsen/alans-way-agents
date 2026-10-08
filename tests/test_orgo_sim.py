"""Orgo sim: bootstrap-orgo.sh and migrate.sh run for real in containers.

tests/orgo-sim/Dockerfile builds an image that mirrors Orgo's
system/hermes-agent template — supervisord as PID 1 (no systemd, no cron,
no /dev/net/tun), openssh-server and hermes-gateway as supervisord programs
from Orgo's own confs, Hermes preinstalled at /usr/local/lib/hermes-agent,
and tailscale binaries present but not running.

Everything below is real: supervisord runs the programs, bootstrap runs the
real setup.sh from a mounted copy of this working tree (via the
ALAN_SETUP_SH override), tailscaled really starts and `tailscale up` really
asks the coordination server for a login URL, and migrate.sh really ssh's
between two containers on a docker network. Nothing is stubbed.

Skipped unless ALAN_SIM=1 and docker is available. The image build is heavy
(the Hermes installer clones and venv-syncs), so it is built once and cached
under the tag alans-way-orgo-sim:test; set ALAN_SIM_REBUILD=1 to force it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "alans-way-orgo-sim:test"
SIM_CTX = ROOT / "tests" / "orgo-sim"
# Unique per run: other sim jobs share this docker daemon, and a stale
# container or network left behind by a killed run must not collide with
# this one.
RUN_ID = uuid.uuid4().hex[:8]
NETWORK = f"orgo-sim-{RUN_ID}"
REPO_MOUNT = "/srv/alans-way-agents"

DOCKER = shutil.which("docker")


def docker(*args: str, input_text: str | None = None, timeout: int = 120):
    return subprocess.run(
        [DOCKER, *args], input=input_text, capture_output=True, text=True,
        timeout=timeout)


def docker_exec(name: str, *cmd: str, timeout: int = 120, check: bool = True,
                input_text: str | None = None):
    result = docker("exec", *(["-i"] if input_text is not None else []),
                    name, *cmd, input_text=input_text, timeout=timeout)
    if check and result.returncode != 0:
        raise AssertionError(
            f"docker exec {name} {cmd}: exit {result.returncode}\n"
            f"{result.stdout}\n{result.stderr}")
    return result


def docker_exec_bg(name: str, *cmd: str):
    # docker exec -d returns as soon as the detach is registered.
    return subprocess.run(
        [DOCKER, "exec", "-d", name, *cmd], capture_output=True)


def container_state(name: str, program: str) -> str:
    out = docker_exec(name, "supervisorctl", "status", program,
                      check=False).stdout
    m = re.search(r"\b(RUNNING|STOPPED|STARTING|BACKOFF|EXITED|FATAL)\b", out)
    return m.group(1) if m else f"?{out.strip()}"


def wait_for(predicate, timeout: float, interval: float = 0.5, what=""):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {what or predicate}")


def prepare_repo_source(directory: Path) -> tuple[Path, str]:
    """A git checkout of THIS working tree (tracked + untracked files,
    .gitignore honoured) so setup.sh can resolve REPO_DIR and --repo-ref
    without touching GitHub."""
    src = directory / "repo-src"
    src.mkdir()
    listed = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=True).stdout
    for rel in listed.decode().split("\x00"):
        if not rel or rel.startswith("tests/orgo-sim/"):
            # The fixture never needs to install the sim itself.
            continue
        dest = src / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
    for args in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", "-C", str(src), *args], check=True)
    subprocess.run(
        ["git", "-C", str(src), "-c", "user.email=sim@example.com",
         "-c", "user.name=sim", "commit", "-qm", "sim checkout"], check=True)
    rev = subprocess.run(
        ["git", "-C", str(src), "rev-parse", "HEAD"],
        capture_output=True, check=True, text=True).stdout.strip()
    return src, rev


SEED_PY = """\
import os, sqlite3, time, sys
home = sys.argv[1]          # the seeded hermes home (under the OLD home)
old = os.path.dirname(home) # the old $HOME the yaml paths should reference
os.makedirs(home + "/profiles/work", exist_ok=True)
os.makedirs(home + "/profiles/play", exist_ok=True)
with open(home + "/.env", "w") as f:
    f.write('TELEGRAM_BOT_TOKEN="123456789:AAAAAAA-BBBBBBB_CCCCCCC"  # c\\n')
    f.write("export API_SERVER_KEY='sim-key-0123456789abcdef'\\n")
    f.write('QUOTED="value with spaces"\\n')
    f.write("export SPACED= spaced-value\\n")
    f.write("PLAIN=simple\\n")
for cfg in (home + "/config.yaml", home + "/profiles/work/config.yaml"):
    with open(cfg, "w") as f:
        f.write("state_dir: %s/state\\n" % home)
        f.write("profiles_root: '%s/profiles'\\n" % home)
        f.write("unrelated: /opt/elsewhere\\n")
db = sqlite3.connect(home + "/state.db")
db.execute("PRAGMA journal_mode=WAL")
db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
db.executemany("INSERT INTO kv VALUES (?, ?)", [("route", "primary"), ("seq", "42")])
db.commit()
# Stay alive holding the committed WAL so the -wal/-shm sidecars exist on
# disk while migrate.sh packs and the test copies the tree.
time.sleep(600)
"""


def seed_hermes_home(container: str, home: str) -> subprocess.Popen:
    """Build a real ~/.hermes seed inside the container: a copy of the
    installer-created stock home (the hermes shim execs $HERMES_HOME/tools/
    python, so the tools dir must ride along exactly like a real same-arch
    migration), plus edge-case .env, two profiles, yaml paths under the old
    home, and a live-WAL state.db. Returns the WAL-holder process."""
    docker_exec(container, "mkdir", "-p", str(Path(home).parent))
    docker_exec(container, "cp", "-a", "/root/.hermes", home)
    proc = subprocess.Popen(
        [DOCKER, "exec", "-i", container, "python3", "-", home],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    assert proc.stdin and proc.stdin.write(SEED_PY.encode())
    proc.stdin.close()
    # Wait until the seed exists with its -wal sidecar.
    wait_for(lambda: docker_exec(
        container, "test", "-f", f"{home}/state.db-wal",
        check=False).returncode == 0, 20, what="seeded state.db-wal")
    return proc


@unittest.skipUnless(os.environ.get("ALAN_SIM") == "1", "set ALAN_SIM=1")
@unittest.skipUnless(DOCKER, "docker is required")
class OrgoSim(unittest.TestCase):
    tmp: tempfile.TemporaryDirectory
    repo_src: Path
    repo_rev: str
    containers: list[str]

    @classmethod
    def setUpClass(cls):
        # The scratch dir must live under $HOME: colima only shares /Users
        # with the docker VM, so a /var/folders tmpdir would bind-mount empty.
        cls.tmp = tempfile.TemporaryDirectory(
            prefix="orgo-sim-", dir=os.path.expanduser("~"))
        cls.containers = []
        cls.addClassCleanup(cls.tmp.cleanup)
        if os.environ.get("ALAN_SIM_REBUILD") == "1" or \
                docker("image", "inspect", IMAGE).returncode != 0:
            build = subprocess.run(
                [DOCKER, "build", "-t", IMAGE, str(SIM_CTX)],
                capture_output=True, text=True, timeout=3600)
            if build.returncode != 0:
                raise AssertionError(
                    f"image build failed:\n{build.stdout[-4000:]}\n{build.stderr[-4000:]}")
        net = docker("network", "create", NETWORK)
        if net.returncode != 0:
            raise AssertionError(f"docker network create {NETWORK}: {net.stderr}")
        cls.addClassCleanup(lambda: docker("network", "rm", NETWORK))
        cls.repo_src, cls.repo_rev = prepare_repo_source(Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        for name in cls.containers:
            docker("rm", "-f", name)

    # -- helpers -----------------------------------------------------------

    def start(self, name: str, mounts: tuple = ()) -> str:
        name = f"{name}-{RUN_ID}"
        cmd = [DOCKER, "run", "-d", "--name", name, "--network", NETWORK,
               "-v", f"{self.repo_src}:{REPO_MOUNT}"]
        for src, dst in mounts:
            cmd += ["-v", f"{src}:{dst}:ro"]
        cmd.append(IMAGE)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.fail(f"docker run {name}: {result.stderr}")
        self.containers.append(name)

        # supervisord is PID 1; wait until its RPC answers. `supervisorctl
        # pid` is the right probe — `status` exits nonzero when ANY program
        # is not RUNNING (LSB-style), which conflates daemon readiness with
        # process states.
        wait_for(lambda: docker_exec(
            name, "supervisorctl", "pid", check=False).returncode == 0,
            30, what=f"{name} supervisord")
        return name

    def state_doc(self, name: str) -> dict:
        out = docker_exec(name, "cat", "/var/lib/alan/state.json").stdout
        return json.loads(out)

    def conf_files(self, name: str) -> str:
        return docker_exec(
            name, "sh", "-c",
            "cat /etc/supervisor/conf.d/*.conf").stdout

    # -- bootstrap ----------------------------------------------------------

    def test_bootstrap_real(self):
        name = self.start("orgo-sim-boot")
        docker_exec_bg(name, "python3",
                       "/opt/orgo-sim/callback_server.py",
                       "127.0.0.1", "8799", "/tmp/callback.json")
        # docker exec -d returns as soon as the process is registered, not
        # when it is listening — wait for the port to accept connections
        # before bootstrap can POST to it.
        wait_for(lambda: docker_exec(
            name, "python3", "-c",
            "import socket; socket.create_connection(('127.0.0.1', 8799), 1).close()",
            check=False).returncode == 0, 15, what="callback server on 8799")
        cmd = [
            "env", f"ALAN_SETUP_SH={REPO_MOUNT}/setup.sh",
            "bash", f"{REPO_MOUNT}/bootstrap-orgo.sh",
            "--id", "test123", "--secret", "sim-secret",
            "--callback", "http://127.0.0.1:8799/cb",
            "--repo-ref", self.repo_rev,
        ]
        result = docker_exec(name, *cmd, timeout=900, check=False)
        if result.returncode != 0:
            log = docker_exec(name, "tail", "-n", "80",
                              "/var/lib/alan/bootstrap.log",
                              check=False).stdout
            self.fail(f"bootstrap exited {result.returncode}\n"
                      f"{result.stdout}\n{result.stderr}\n--- bootstrap.log\n{log}")

        doc = self.state_doc(name)
        self.assertEqual("ready", doc["state"])
        self.assertEqual("waiting_for_pairing", doc["step"])

        cb = docker_exec(name, "cat", "/tmp/callback.json").stdout
        payload = json.loads(cb)
        self.assertEqual("test123", payload["id"])
        self.assertEqual("sim-secret", payload["secret"])
        self.assertRegex(payload["url"],
                         r"^https://login\.tailscale\.com/a/[A-Za-z0-9]+$")

        # Poll the one program's state rather than reading the full
        # `supervisorctl status` listing once: that command exits nonzero
        # whenever ANY program is not RUNNING, and the sim's alans-way
        # browser programs go FATAL a few seconds after bootstrap adds
        # them (their host scripts are only installed by hermes pm, which
        # the sim never runs) — a check=True read races that transition.
        wait_for(lambda: container_state(name, "tailscaled") == "RUNNING",
                 30, what="tailscaled RUNNING")
        conf = docker_exec(name, "cat",
                           "/etc/supervisor/conf.d/tailscaled.conf").stdout
        self.assertIn("--tun=userspace-networking", conf)
        self.assertIn("--socks5-server=localhost:1055", conf)

        ssh_cfg = docker_exec(name, "cat", "/root/.ssh/config").stdout
        self.assertEqual(1, ssh_cfg.count(">>> alan tailscale ssh >>>"))
        self.assertIn("Host 100.*", ssh_cfg)
        self.assertIn("ProxyCommand tailscale nc %h %p", ssh_cfg)

        # hermes-gateway is Orgo's own program — bootstrap must not add a
        # second [program:hermes-gateway] anywhere.
        self.assertEqual(1, self.conf_files(name).count("[program:hermes-gateway]"))
        orgo = docker_exec(name, "cat",
                           "/etc/supervisor/conf.d/orgo.conf").stdout
        self.assertIn("/usr/local/bin/orgo-hermes-gateway", orgo)

        # The real setup.sh ran against the mounted checkout: the plugin is
        # installed and the supervisord confs for the browser services exist.
        docker_exec(name, "test", "-d", "/root/.hermes/plugins/alans-way")
        docker_exec(name, "test", "-f",
                    "/etc/supervisor/conf.d/alans-way.conf")

        # Idempotent re-run: same end state, no duplicated program sections
        # or ssh config blocks.
        before = self.conf_files(name)
        result = docker_exec(name, *cmd, timeout=900, check=False)
        self.assertEqual(0, result.returncode,
                         f"re-run failed: {result.stderr}")
        self.assertEqual(before, self.conf_files(name))
        self.assertEqual("ready", self.state_doc(name)["state"])
        ssh_cfg = docker_exec(name, "cat", "/root/.ssh/config").stdout
        self.assertEqual(1, ssh_cfg.count(">>> alan tailscale ssh >>>"))

    # -- migrate ------------------------------------------------------------

    def wire_pair(self, src: str, dst: str):
        docker_exec(src, "ssh-keygen", "-t", "ed25519", "-N", "",
                    "-f", "/root/.ssh/id_ed25519")
        pub = docker_exec(src, "cat", "/root/.ssh/id_ed25519.pub").stdout
        docker("exec", "-i", dst, "sh", "-c",
               "mkdir -p /root/.ssh && chmod 700 /root/.ssh"
               " && cat >> /root/.ssh/authorized_keys"
               " && chmod 600 /root/.ssh/authorized_keys",
               input_text=pub)
        # Wait for the dst sshd (a real supervisord program) to answer and
        # pin exactly the keys the poll observed — a second, unpolled
        # keyscan can catch sshd mid-restart and append nothing, leaving
        # ssh to fail on host-key verification.
        keys: list[str] = []

        def scan() -> bool:
            r = docker_exec(src, "ssh-keyscan", "-T", "5", dst, check=False)
            if r.returncode == 0 and r.stdout.strip():
                keys[:] = [r.stdout]
                return True
            return False

        wait_for(scan, 30, what=f"sshd on {dst}")
        pin = docker("exec", "-i", src, "sh", "-c",
                     "cat >> /root/.ssh/known_hosts", input_text=keys[0])
        self.assertEqual(0, pin.returncode, f"pinning host keys: {pin.stderr}")

    def test_migrate_real(self):
        src = self.start("orgo-sim-src")
        dst = self.start("orgo-sim-dst")
        self.wire_pair(src, dst)

        seed_env = (
            'TELEGRAM_BOT_TOKEN="123456789:AAAAAAA-BBBBBBB_CCCCCCC"  # c\n'
            "export API_SERVER_KEY='sim-key-0123456789abcdef'\n"
            'QUOTED="value with spaces"\n'
            "export SPACED= spaced-value\n"
            "PLAIN=simple\n")
        wal_holder = seed_hermes_home(src, "/root/old-home/.hermes")
        self.addCleanup(lambda: (wal_holder.terminate(), wal_holder.wait()))
        # Both gateways RUNNING (the real orgo-hermes-gateway -> hermes
        # gateway run) before the handover starts.
        wait_for(lambda: container_state(src, "hermes-gateway") == "RUNNING",
                 60, what="source gateway RUNNING")
        wait_for(lambda: container_state(dst, "hermes-gateway") == "RUNNING",
                 60, what="target gateway RUNNING")

        observed: list[tuple[str, str]] = []
        stop = threading.Event()

        def poll():
            while not stop.is_set():
                observed.append((container_state(src, "hermes-gateway"),
                                 container_state(dst, "hermes-gateway")))
                time.sleep(0.25)

        t = threading.Thread(target=poll, daemon=True)
        t.start()
        try:
            result = docker_exec(
                src, "bash", f"{REPO_MOUNT}/migrate.sh",
                "--to", f"root@{dst}",
                "--hermes-home", "/root/old-home/.hermes",
                "--yes", timeout=300, check=False)
        finally:
            stop.set()
            t.join(timeout=10)
        self.assertEqual(0, result.returncode,
                         f"migrate failed:\n{result.stdout}\n{result.stderr}")

        # Files landed; paths rewritten; .env untouched; marker present.
        docker_exec(dst, "test", "-f", "/root/.hermes/.migrated")
        moved_env = docker_exec(dst, "cat", "/root/.hermes/.env").stdout
        self.assertEqual(seed_env, moved_env)
        moved_cfg = docker_exec(dst, "cat", "/root/.hermes/config.yaml").stdout
        self.assertIn("state_dir: /root/.hermes/state", moved_cfg)
        self.assertNotIn("/root/old-home", moved_cfg)
        prof_cfg = docker_exec(
            dst, "cat", "/root/.hermes/profiles/work/config.yaml").stdout
        self.assertNotIn("/root/old-home", prof_cfg)

        rows = docker_exec(
            dst, "python3", "-c",
            "import sqlite3; c=sqlite3.connect('/root/.hermes/state.db');"
            "print(sorted(c.execute('select k,v from kv')))").stdout
        self.assertIn("('route', 'primary')", rows)
        self.assertIn("('seq', '42')", rows)

        self.assertEqual("STOPPED", container_state(src, "hermes-gateway"))
        wait_for(lambda: container_state(dst, "hermes-gateway") == "RUNNING",
                 60, what="target hermes-gateway RUNNING")
        # Both RUNNING is the steady state BEFORE the run — the invariant is
        # that once the target has been observed parked (STOPPED), i.e. the
        # handover has begun, the two gateways are never RUNNING together.
        parked_at = next(
            (i for i, (_, d) in enumerate(observed) if d == "STOPPED"),
            len(observed))
        self.assertLess(parked_at, len(observed),
                        "never observed the target gateway parked — "
                        "the no-overlap check was vacuous")
        for s_state, d_state in observed[parked_at:]:
            self.assertFalse(
                s_state == "RUNNING" and d_state == "RUNNING",
                f"both gateways RUNNING after the target was parked: "
                f"{observed[parked_at:]}")

    def test_migrate_preserves_target_runtime_tools(self):
        """The hermes launcher execs $HERMES_HOME/tools/python-<ver>-<arch>/
        bin/python3, baked into /usr/local/lib/hermes-agent/.hermes/bin/hermes
        at install time. A home migrated cross-arch (Mac -> Orgo) carries the
        SOURCE's tools dir, so the target's runtimes must be restored from the
        pre-migrate backup or the gateway can never spawn."""
        src = self.start("orgo-sim-src3")
        dst = self.start("orgo-sim-dst3")
        self.wire_pair(src, dst)
        wal_holder = seed_hermes_home(src, "/root/old-home/.hermes")
        self.addCleanup(lambda: (wal_holder.terminate(), wal_holder.wait()))

        # Simulate the source being a different arch: rename every runtime
        # dir in the seed's tools/ to a foreign triple.
        docker_exec(src, "sh", "-c",
                    "cd /root/old-home/.hermes/tools && for d in *-linux-arm64;"
                    " do mv \"$d\" \"${d%-linux-arm64}-darwin-arm64\"; done")

        wait_for(lambda: container_state(dst, "hermes-gateway") == "RUNNING",
                 60, what="target gateway RUNNING before migrate")
        result = docker_exec(
            src, "bash", f"{REPO_MOUNT}/migrate.sh",
            "--to", f"root@{dst}",
            "--hermes-home", "/root/old-home/.hermes",
            "--yes", timeout=300, check=False)
        self.assertEqual(0, result.returncode,
                         f"migrate failed:\n{result.stdout}\n{result.stderr}")
        wait_for(lambda: container_state(dst, "hermes-gateway") == "RUNNING",
                 60, what="target hermes-gateway RUNNING")

    def test_migrate_failure_keeps_source_running(self):
        src = self.start("orgo-sim-src2")
        dst = self.start("orgo-sim-dst2")
        self.wire_pair(src, dst)
        wal_holder = seed_hermes_home(src, "/root/old-home/.hermes")
        self.addCleanup(lambda: (wal_holder.terminate(), wal_holder.wait()))

        # Force the remote unpack to fail: shadow tar on the target.
        docker_exec(dst, "sh", "-c",
                    "printf '#!/bin/sh\\nexit 42\\n' > /usr/local/bin/tar"
                    " && chmod 755 /usr/local/bin/tar")
        # RUNNING before the run, so "still RUNNING" afterwards is real.
        wait_for(lambda: container_state(src, "hermes-gateway") == "RUNNING",
                 60, what="source gateway RUNNING")
        result = docker_exec(
            src, "bash", f"{REPO_MOUNT}/migrate.sh",
            "--to", f"root@{dst}",
            "--hermes-home", "/root/old-home/.hermes",
            "--yes", timeout=120, check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("RUNNING", container_state(src, "hermes-gateway"))
        # The park on the remote side fired but nothing restarted it.
        self.assertNotEqual("RUNNING",
                            container_state(dst, "hermes-gateway"))


if __name__ == "__main__":
    unittest.main()
