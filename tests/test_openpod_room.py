"""OpenPod room bridge: #262 rules, dedupe, fencing and untrusted delivery, all offline."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("openpod_room", ROOT / "alans-way" / "openpod_room.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

CONFIG = {"pod_id": "pod1", "hermes_agent": "agH", "grok_agent": "agG", "grok_member": "memA",
          "owner_member": "memA", "openpod": "openpod"}
KEY = "agent:main:telegram:dm:42"


class FakeCLI:
    def __init__(self):
        self.log, self.checked, self.posts, self.fail_events = [], [], [], False

    def check_in(self, wake_id):
        self.checked.append(wake_id)

    def events_after(self, after):
        return [e for e in self.log if e["seq"] > after]

    def events(self, pod, after):
        if self.fail_events:
            raise RuntimeError("down")
        return self.events_after(after), {"after": max([after] + [e["seq"] for e in self.log]), "has_more": False}

    def post(self, pod, body, reply_to, mention=None):
        self.posts.append((body, reply_to, mention))


class FakeCtx:
    def __init__(self, accept=True):
        self.sent, self.accept = [], accept

    def inject_message(self, content, role="user", *, session_key=None):
        self.sent.append((content, session_key))
        return self.accept


def msg(seq, body, *, agent=None, member="memA", to=()):
    return {"id": "ev%d" % seq, "seq": seq, "type": "message",
            "actor": {"memberId": member, **({"agentId": agent} if agent else {})},
            "data": {"body": body, "mentions": [{"memberId": "memA", "agentId": a} for a in to]}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.json"
        self.cli, self.ctx = FakeCLI(), FakeCtx()
        self.bridge = self.make()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, key=KEY):
        return R.Bridge(self.ctx, CONFIG, R.RoomState(self.path), self.cli, lambda: key)

    def wake(self, *events):
        self.cli.log.extend(events)
        return self.bridge.on_wake("OpenPod wake wake_abc (mention): 1 new events in 1 pods, 0 invites.\n")

    def finish(self, seq, reply):
        self.bridge.on_turn_end(user_message="%s %d\nx" % (R.MARKER, seq), assistant_response=reply)


class Rules(Base):
    def test_wake_checks_in_first_and_owner_mention_delivers_untrusted_prompt(self):
        self.assertEqual(self.wake(msg(1, "@Hermes draft a plan", to=["agH"])), [1])
        self.assertEqual(self.cli.checked, ["wake_abc"])
        prompt, key = self.ctx.sent[0]
        self.assertEqual(key, KEY)
        self.assertTrue(prompt.startswith(R.MARKER + " 1\n"))
        self.assertIn("untrusted", prompt)

    def test_non_wake_lines_do_nothing(self):
        self.assertEqual(self.bridge.on_wake("No more wakes before --max-minutes ran out."), [])
        self.assertEqual(self.cli.checked, [])

    def test_unaddressed_ambiguous_and_grok_only_owner_messages_do_not_wake_hermes(self):
        amb = msg(3, "both of you")
        amb["data"]["mentions"] = [{"memberId": "memA"}]
        self.assertEqual(self.wake(msg(1, "just a note"), msg(2, "@Grok Bot go", to=["agG"]), amb,
                                   msg(4, "two", to=["agH", "agG"])), [])
        self.assertEqual(self.ctx.sent, [])

    def test_reply_is_posted_and_handoff_only_with_leading_grok_mention(self):
        self.wake(msg(1, "@Hermes go", to=["agH"]))
        self.finish(1, "Here is a draft. @Grok Bot might disagree.")
        self.assertEqual(self.cli.posts[-1], ("Here is a draft. @Grok Bot might disagree.", 1, None))
        self.wake(msg(2, "@Hermes again", to=["agH"]))
        self.finish(2, "@Grok Bot, please review.")
        self.assertEqual(self.cli.posts[-1][2], {"memberId": "memA", "agentId": "agG"})

    def test_six_turn_cap_per_owner_instruction(self):
        self.wake(msg(1, "@Hermes start", to=["agH"]))
        seq, delivered = 2, [1]
        for turn in range(1, 8):
            bot = "agH" if turn % 2 else "agG"
            peer = "agG" if bot == "agH" else "agH"
            delivered += self.wake(msg(seq, "turn %d" % turn, agent=bot, to=[peer]))
            seq += 1
        self.assertEqual(delivered, [1, 3, 5])  # Hermes turns 1, 3, 5; Grok's 6th handoff is refused
        self.assertIsNone(self.bridge.state.value["active"])
        self.assertEqual(self.wake(msg(seq, "@Hermes new task", to=["agH"])), [seq])
        self.assertEqual(self.bridge.state.value["turns"], 0)

    def test_stale_or_foreign_bot_messages_are_ignored(self):
        self.wake(msg(1, "@Hermes go", to=["agH"]))
        self.assertEqual(self.wake(msg(2, "jumping in", agent="agG", to=["agH"])), [])
        self.assertEqual(self.wake(msg(3, "stranger", agent="agX", member="memB", to=["agH"])), [])

    def test_stopped_pod_fences_turn_and_late_reply_and_start_needs_new_mention(self):
        self.wake(msg(1, "@Hermes go", to=["agH"]))
        self.wake({"id": "ev2", "seq": 2, "type": "podStopped", "data": {}})
        self.finish(1, "late reply")
        self.assertEqual(self.cli.posts, [])
        self.assertEqual(self.wake(msg(3, "@Hermes while paused", to=["agH"])), [])
        self.wake({"id": "ev4", "seq": 4, "type": "podStarted", "data": {}})
        self.assertEqual(self.bridge.state.value["active"], None)
        self.assertEqual(self.wake(msg(5, "@Hermes resume", to=["agH"])), [5])

    def test_newer_owner_instruction_fences_old_reply(self):
        self.wake(msg(1, "@Hermes one", to=["agH"]))
        self.wake(msg(2, "@Grok Bot instead", to=["agG"]))
        self.finish(1, "old answer")
        self.assertEqual(self.cli.posts, [])


class Durability(Base):
    def test_dedupe_and_cursor_survive_restart(self):
        self.wake(msg(1, "@Hermes go", to=["agH"]))
        self.assertEqual(json.loads(self.path.read_text())["seen"], ["ev1"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.bridge = self.make()
        self.cli.events_after = lambda after: list(self.cli.log)  # server replays everything
        self.assertEqual(self.wake(), [])
        self.assertEqual(len(self.ctx.sent), 1)

    def test_uncertain_delivery_never_resends_and_no_binding_delivers_nothing(self):
        self.ctx.accept = False
        self.assertEqual(self.wake(msg(1, "@Hermes go", to=["agH"])), [])
        self.assertIsNone(self.bridge.state.value["active"])
        self.ctx.accept = True
        self.assertEqual(self.wake(), [])
        self.bridge = self.make(key="")
        self.assertEqual(self.wake(msg(2, "@Hermes go", to=["agH"])), [])
        self.assertEqual(len(self.ctx.sent), 1)

    def test_read_failure_raises_after_check_in(self):
        self.cli.fail_events = True
        with self.assertRaises(RuntimeError):
            self.wake(msg(1, "@Hermes go", to=["agH"]))
        self.assertEqual(self.cli.checked, ["wake_abc"])

    def test_only_marked_turns_post(self):
        self.bridge.on_turn_end(user_message="hello", assistant_response="hi")
        self.finish(99, "unknown turn")
        self.assertEqual(self.cli.posts, [])


class Secrets(Base):
    def test_keys_are_redacted_in_prompts_and_posts(self):
        key = "opk_" + "A" * 30
        self.wake(msg(1, "@Hermes use " + key, to=["agH"]))
        self.assertNotIn(key, self.ctx.sent[0][0])
        self.finish(1, "my key is " + key)
        self.assertNotIn(key, self.cli.posts[0][0])
        self.assertIn("[redacted]", self.cli.posts[0][0])


class Config(unittest.TestCase):
    def test_inert_without_config_and_rejects_incomplete(self):
        self.assertIsNone(R.load_config({}))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text(json.dumps({"pod_id": "x"}))
            with self.assertRaises(ValueError):
                R.load_config({"ALANS_WAY_OPENPOD_CONFIG": str(p)})
            p.write_text(json.dumps(CONFIG))
            self.assertEqual(R.load_config({"ALANS_WAY_OPENPOD_CONFIG": str(p)})["state"],
                             str(Path(d) / "openpod-room-state.json"))

    def test_cli_wrapper_shapes_commands_without_shell(self):
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            out = json.dumps({"data": [], "list_metadata": {"after": 3}}) if argv[1] == "events" else ""
            return type("R", (), {"returncode": 0, "stdout": out})()
        cli = R.CLI("/bin/openpod", run=run)
        cli.check_in("wake_1")
        self.assertEqual(cli.events("pod1", 2), ([], {"after": 3}))
        cli.post("pod1", "hi; rm -rf /", 2, {"memberId": "m", "agentId": "a"})
        self.assertEqual(calls[0], ["/bin/openpod", "check-in", "wake_1"])
        self.assertEqual(calls[1], ["/bin/openpod", "events", "pod1", "--after", "2"])
        self.assertEqual(calls[2][:3], ["/bin/openpod", "call", "post_message"])
        self.assertEqual(json.loads(calls[2][3])["mentions"], [{"memberId": "m", "agentId": "a"}])

    def test_watch_feeds_wake_lines_and_terminates(self):
        seen = []
        class P:
            def __init__(self, argv, **kw):
                self.argv, self.stdout, self.done = argv, iter(["OpenPod wake wake_x (m): 1\n", "noise\n"]), False
            def terminate(self):
                self.done = True
        bridge = type("B", (), {"on_wake": lambda self, line: seen.append(line)})()
        R.watch(bridge, "openpod", popen=P)
        self.assertEqual(len(seen), 2)


if __name__ == "__main__":
    unittest.main()
