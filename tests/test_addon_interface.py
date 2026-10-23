"""Regression tests for docs/addon-interface.md — the stable interface a
private add-on script run after bootstrap-orgo.sh may rely on.

Reuses the fixtures in test_bootstrap_orgo.py and test_migrate.py rather
than duplicating the stub plumbing; see those modules for the fixture/stub
helpers themselves.
"""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_bootstrap_orgo as bo
import test_migrate as mg

ROOT = Path(__file__).resolve().parents[1]


class CliFlagsTests(unittest.TestCase):
    """--callback --secret --id --hermes-home --repo-ref --dry-run
    --wait-paired are the stable bootstrap-orgo.sh flags."""

    def test_usage_mentions_every_stable_flag(self):
        result = bo.run("--help", check=False)
        for flag in ("--callback", "--secret", "--id", "--hermes-home",
                     "--repo-ref", "--dry-run", "--wait-paired"):
            self.assertIn(flag, result.stdout, flag)

    def test_dry_run_and_wait_paired_are_accepted_alone(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = bo.fixture(directory)
            result = bo.run("--dry-run", env=env)
            self.assertEqual(result.returncode, 0)


class StatusFileKeysTests(unittest.TestCase):
    """state.json always has state/step/error/warnings/updated_at, and an
    add-on's own key survives every subsequent bootstrap write."""

    def test_every_write_has_the_stable_keys(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = bo.fixture(directory)
            bo.curl_stub(stub_bin)
            bo.tailscale_stub(stub_bin, url="https://login.tailscale.com/a/addon1")
            result = bo.run(env=env)
            self.assertEqual(result.returncode, 0)
            doc = json.loads(
                (directory / "state" / "state.json").read_text(encoding="utf-8"))
            for key in ("state", "step", "error", "warnings", "updated_at"):
                self.assertIn(key, doc)
            self.assertEqual(doc["warnings"], [])

    def test_an_addons_own_key_survives_a_later_bootstrap_write(self):
        """Merge semantics: a key no step of bootstrap-orgo.sh owns must
        not be erased by a later state() call."""
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = bo.fixture(directory)
            bo.curl_stub(stub_bin)
            bo.tailscale_stub(stub_bin, url="https://login.tailscale.com/a/addon2")
            # A dry run writes nothing, so bootstrap for real once first to
            # create the state dir and an initial state.json.
            result = bo.run(env=env)
            self.assertEqual(result.returncode, 0)
            state_file = directory / "state" / "state.json"
            doc = json.loads(state_file.read_text(encoding="utf-8"))
            doc["addon_myservice"] = "installed"
            state_file.write_text(json.dumps(doc), encoding="utf-8")

            # Re-run: every step is already done, so every step's state()
            # call fires again on top of the add-on's key.
            second = bo.run(env=env)
            self.assertEqual(second.returncode, 0)
            doc2 = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(doc2.get("addon_myservice"), "installed")
            self.assertEqual(doc2["state"], "ready")

    def test_a_failed_run_also_preserves_an_addons_key(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = bo.fixture(directory)
            env["ALAN_TAILSCALE_URL_TIMEOUT"] = "2"
            bo.curl_stub(stub_bin)
            bo.tailscale_stub(stub_bin, url="", up_extra="sleep 30")
            result = bo.run(env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            state_file = directory / "state" / "state.json"
            doc = json.loads(state_file.read_text(encoding="utf-8"))
            doc["addon_myservice"] = "installed"
            state_file.write_text(json.dumps(doc), encoding="utf-8")

            del env["ALAN_TAILSCALE_URL_TIMEOUT"]
            bo.tailscale_stub(stub_bin, url="https://login.tailscale.com/a/addon3")
            second = bo.run(env=env)
            self.assertEqual(second.returncode, 0)
            doc2 = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(doc2.get("addon_myservice"), "installed")

    def test_wait_paired_also_preserves_an_addons_key(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = bo.fixture(directory)
            bo.curl_stub(stub_bin)
            bo.tailscale_stub(stub_bin, url="https://login.tailscale.com/a/addon4")
            run1 = bo.run(env=env)
            self.assertEqual(run1.returncode, 0)
            state_file = directory / "state" / "state.json"
            doc = json.loads(state_file.read_text(encoding="utf-8"))
            doc["addon_myservice"] = "installed"
            state_file.write_text(json.dumps(doc), encoding="utf-8")

            bo.tailscale_stub(stub_bin, backend="Running")
            run2 = bo.run("--wait-paired", env=env)
            self.assertEqual(run2.returncode, 0)
            doc2 = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(doc2["state"], "ready")
            self.assertEqual(doc2["step"], "paired")
            self.assertEqual(doc2.get("addon_myservice"), "installed")


class HermesGatewayProgramTests(unittest.TestCase):
    """The supervisord hermes-gateway program is reused, never duplicated,
    and carries the drain-safe stopwaitsecs an add-on's own stop/restart
    should respect."""

    def test_reuses_an_existing_gateway_program_definition(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = bo.fixture(directory)
            bin_dest = directory / "sbin"
            (directory / "svconf" / "orgo.conf").write_text(
                "[program:hermes-gateway]\n"
                f"command={bin_dest}/orgo-hermes-gateway\n",
                encoding="utf-8",
            )
            (bin_dest / "orgo-hermes-gateway").write_text("#!/bin/sh\n", encoding="utf-8")
            (bin_dest / "orgo-hermes-gateway").chmod(0o755)
            bo.curl_stub(stub_bin)
            bo.tailscale_stub(stub_bin, url="https://login.tailscale.com/a/gw1")
            result = bo.run(env=env)
            self.assertEqual(result.returncode, 0)
            self.assertFalse((directory / "svconf" / "hermes-gateway.conf").exists())

    def test_generated_program_sets_the_drain_safe_stopwaitsecs(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, log, stub_bin = bo.fixture(directory)
            bo.curl_stub(stub_bin)
            bo.tailscale_stub(stub_bin, url="https://login.tailscale.com/a/gw2")
            result = bo.run(env=env)
            self.assertEqual(result.returncode, 0)
            conf = (directory / "svconf" / "hermes-gateway.conf").read_text(encoding="utf-8")
            self.assertIn("stopwaitsecs=180", conf)
            self.assertEqual(conf.count("[program:hermes-gateway]"), 1)


class MigratePreMigrateBackupTests(unittest.TestCase):
    """migrate.sh parks an existing remote Hermes home at
    $HERMES_HOME.pre-migrate-<timestamp> rather than overwriting it."""

    def test_an_existing_remote_home_is_backed_up_by_that_name(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            env, home, hermes, remote_home, local_calls, remote_calls, calls = mg.fixture(directory)
            existing = remote_home / ".hermes"
            existing.mkdir()
            (existing / "config.yaml").write_text("old: true\n", encoding="utf-8")
            mg.run("--to", "fakehost", "--yes", env=env)
            backups = list(remote_home.glob(".hermes.pre-migrate-*"))
            self.assertEqual(len(backups), 1)
            self.assertRegex(backups[0].name, r"\.hermes\.pre-migrate-\d{8}-\d{6}$")


class HermesHomeLayoutTests(unittest.TestCase):
    """.env stays at mode 0600; config.yaml changes documented for add-ons
    go through `hermes config set`, not a raw file edit."""

    def test_docs_tell_addons_to_use_hermes_config_set(self):
        doc = (ROOT / "docs" / "addon-interface.md").read_text(encoding="utf-8")
        self.assertIn("hermes config set", doc)
        self.assertIn("0600", doc)


class DocLinkedFromReadmeTests(unittest.TestCase):
    def test_addon_interface_doc_is_linked_from_the_readme_or_contributing(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertTrue(
            "docs/addon-interface.md" in readme or "docs/addon-interface.md" in contributing)


if __name__ == "__main__":
    unittest.main()
