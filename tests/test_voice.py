"""Texting voice: the Telegram note, the send-time polish, and the on/off switch."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_proactivity import FakeState, P  # noqa: E402  (loads the plugin package once)

V = importlib.import_module("alans_way_idle_test.voice")


class PolishTests(unittest.TestCase):
    def test_strips_leading_tics(self):
        for raw, want in (
            ("Certainly! The deploy is green.", "The deploy is green."),
            ("Great question! Obsidian, because your notes stay local.",
             "Obsidian, because your notes stay local."),
            ("Sure thing! Great question. I'd be happy to help with that. It's at 3pm.", "It's at 3pm."),
            ("As an AI, I can't feel the rain, but it's 12°C there.", "I can't feel the rain, but it's 12°C there."),
            ("Absolutely! Done.", "Done."),
            ("Certainly! iPhone 17 ships Friday.", "iPhone 17 ships Friday."),
            ("Great question. `git push` first.", "`git push` first."),
        ):
            self.assertEqual(V.polish(raw), want)

    def test_keeps_tic_words_that_carry_meaning(self):
        for text in ("Sure, but only if the card is yours.", "I'd be happy to book it once you approve.",
                     "Absolutely. Delete it.", "Of course. It's safe.",
                     "Certainly not: that would delete prod.", "Great question for Sam, not me."):
            self.assertEqual(V.polish(text), text)

    def test_headings_become_plain_lines(self):
        self.assertEqual(V.polish("## Plan\nShip it.\n### Risks ###\nNone."), "Plan\nShip it.\nRisks\nNone.")

    def test_collapses_bold_walls_but_keeps_one_emphasis(self):
        wall = "**Status:** **green**. **Tests:** **passing**. **Next:** **deploy**."  # six spans
        self.assertEqual(V.polish(wall), "Status: green. Tests: passing. Next: deploy.")
        self.assertEqual(V.polish("**Everything here is bold because the model got excited about it.**"),
                         "Everything here is bold because the model got excited about it.")
        one = "The deploy failed at **step 3**, the migration. Want me to roll back?"
        self.assertEqual(V.polish(one), one)

    def test_never_touches_code_links_numbers_or_quotes(self):
        cases = [
            "```python\n# Certainly! a comment\n## not a heading\nx = **kwargs\n```",
            "Run `**/*.py` then `## keep`.",
            "See https://example.com/a**b**c#Certainly and [the docs](https://example.com/#heading).",
            "> **Great question!** said nobody\n> ## quoted heading",
            'He wrote "**Certainly!** ## Done" and left.',
            "Total: $1,249.99 for 3 seats, 12.5% off, ref #4417.",
            "~~~\n**bold** in a tilde fence\n~~~",
            "# 4417 is the ticket",
            "    ## indented code\n    x = **a** **b** **c** **d** **e**",
            "````md\n```\n## inside a nested fence\n```\n````",
            "a**2 + b**2 = c**2 and d**2 + e**2 = f**2 + g**2",
            "**Do not** pay it. **Only** I approve. **Never** share the code.",
            "bad\x009\x00 input **x**",
        ]
        for text in cases:
            with self.subTest(text=text[:30]):
                self.assertEqual(V.polish(text), text)

    def test_mixed_reply_only_changes_prose(self):
        raw = ("Certainly! Here's the fix.\n\n## Steps\n\n```sh\n## keep me\ngit push\n```\n\n"
               "Docs: https://example.com/**x**")
        self.assertEqual(V.polish(raw), "Here's the fix.\n\nSteps\n\n```sh\n## keep me\ngit push\n```\n\n"
                                        "Docs: https://example.com/**x**")

    def test_approval_and_handback_texts_pass_unchanged(self):
        for text in (
            # Hermes' Telegram approval prompt and an N1 commit-gate request, buttons included.
            "⚠️ *Dangerous command requires approval:*\n```\nrm -rf /tmp/build\n```\nReason: recursive delete",
            "Approve purchase on amazon.com: Kindle Paperwhite, $149.99 to card ending 4242?\n"
            "[Approve] [Deny]",
            "Google wants a CAPTCHA before I can search. Can you tap through it? "
            "https://vps.example.ts.net/viewer/tab-7?token=abc**123**",
            "[SILENT]",
        ):
            self.assertEqual(V.polish(text), text)

    def test_never_empties_a_reply(self):
        self.assertEqual(V.polish("Certainly!"), "Certainly!")
        self.assertEqual(V.polish(""), "")
        self.assertEqual(V.polish("## "), "## ")
        self.assertEqual(V.polish("## SILENT"), "## SILENT")


def voice(mode=None):
    ctx = SimpleNamespace(state=FakeState())
    v = V.Voice(ctx)
    if mode:
        v.set(mode)
    return v


def env(**values):
    """Stand-in for the gateway's per-turn session variables."""
    return patch.object(V, "session_env", side_effect=lambda name: values.get(name, ""))


class NoteTests(unittest.TestCase):
    def turn(self, v, platform, chat_type="dm", deliver="", text="hey can you check my calendar tomorrow"):
        with env(HERMES_SESSION_CHAT_TYPE=chat_type, HERMES_CRON_AUTO_DELIVER_PLATFORM=deliver):
            return v.on_turn_start(user_message=text, platform=platform, session_id="s", sender_id="42")

    def test_on_by_default_for_every_telegram_chat(self):
        for chat in ("dm", "group", "forum", "channel"):
            with self.subTest(chat):
                note = self.turn(voice(), "telegram", chat)["context"]
                self.assertTrue(note.startswith(V.NOTE_MARKER))
                self.assertEqual("group chat" in note, chat != "dm")

    def test_never_for_other_platforms_or_the_default_voice(self):
        for platform in ("cli", "discord", "slack", "subagent", "", None):
            self.assertIsNone(self.turn(voice(), platform))
        self.assertIsNone(self.turn(voice("default"), "telegram"))

    def test_cron_only_when_it_delivers_to_telegram(self):
        self.assertIn("sent to them as a Telegram message", self.turn(voice(), "cron", "", "telegram")["context"])
        self.assertIsNone(self.turn(voice(), "cron", "", "discord"))
        self.assertIsNone(self.turn(voice(), "cron", "", ""))

    def test_check_ins_and_the_brief_keep_their_own_prompt(self):
        for text in (P.MARKER + " It has been 3 hours", P.BRIEF_MARKER + " The user's day is starting"):
            self.assertIsNone(self.turn(voice(), "telegram", text=text))

    def test_note_carries_the_rules(self):
        for rule in ("1-4 sentences", "contractions", "'Certainly!', 'Great question' or 'I'd be happy to'",
                     "never headings", "emoji only if they use them", "only when they ask for steps",
                     "never at their expense and never with bad news", "pick one and say why",
                     "stay complete: lead with a one-line answer", "real next step",
                     "approvals, CAPTCHA handbacks and safety checks work exactly as before",
                     "say plainly when something failed", "theirs wins"):
            self.assertIn(rule, V.NOTE)

    def test_check_ins_share_the_same_rules(self):
        for shared in (V.TEXTING, V.PLAIN, V.FORMAT):
            self.assertIn(shared, P.VOICE)
            self.assertIn(shared, V.NOTE)


class OutputTests(unittest.TestCase):
    TIC = "Certainly! ## Plan\nShip it."

    def test_polishes_the_final_telegram_reply_only(self):
        self.assertEqual(voice().on_output(response_text=self.TIC, platform="telegram"), "Plan\nShip it.")
        self.assertIsNone(voice().on_output(response_text=self.TIC, platform="discord"))
        self.assertIsNone(voice("default").on_output(response_text=self.TIC, platform="telegram"))
        self.assertIsNone(voice().on_output(response_text="All good.", platform="telegram"))

    def test_cron_reports_to_telegram_are_polished(self):
        with env(HERMES_CRON_AUTO_DELIVER_PLATFORM="telegram"):
            self.assertEqual(voice().on_output(response_text=self.TIC, platform="cron"), "Plan\nShip it.")
        with env(HERMES_CRON_AUTO_DELIVER_PLATFORM="email"):
            self.assertIsNone(voice().on_output(response_text=self.TIC, platform="cron"))

    def test_silence_markers_pass_through(self):
        for marker in V.SILENT:
            self.assertIsNone(voice().on_output(response_text=marker, platform="telegram"))

    def test_send_message_to_telegram_is_polished(self):
        args = {"action": "send", "target": "telegram:42", "message": "Certainly! Google wants a CAPTCHA. Can you tap through it?"}
        self.assertEqual(voice().on_tool_call(tool_name="send_message", args=args),
                         {"action": "modify", "args": {"message": "Google wants a CAPTCHA. Can you tap through it?"}})
        for other in ({**args, "target": "discord:1"}, {**args, "action": "react"}):
            self.assertIsNone(voice().on_tool_call(tool_name="send_message", args=other))
        self.assertIsNone(voice().on_tool_call(tool_name="terminal", args={"command": "echo Certainly!"}))
        self.assertIsNone(voice("default").on_tool_call(tool_name="send_message", args=args))


class SwitchTests(unittest.TestCase):
    def test_tone_command(self):
        v = voice()
        self.assertIn("on", v.command(""))
        self.assertIn("default voice", v.command("default"))
        self.assertEqual(v.mode(), "default")
        self.assertIn("is on", v.command("TEXTING"))
        self.assertIn("usage", v.command("loud"))
        self.assertIn("usage", v.command("texting now"))
        self.assertEqual(v.mode(), "texting")

    def test_corrupt_state_means_on(self):
        v = voice()
        v.ctx.state.set(V.STATE_KEY, "garbage")
        self.assertTrue(v.on())

    def test_never_touches_soul_or_system_prompt(self):
        """Every hook and the switch run against a real Hermes home: only plugin state changes."""
        with tempfile.TemporaryDirectory() as home:
            soul, config = Path(home, "SOUL.md"), Path(home, "config.yaml")
            soul.write_text("You are my blunt assistant.\n", encoding="utf-8")
            config.write_text("agent:\n  system_prompt: Always answer in British English.\n", encoding="utf-8")
            before = {p: p.read_bytes() for p in (soul, config)}
            v = voice()
            with patch.dict("os.environ", {"HERMES_HOME": home}), env(HERMES_SESSION_CHAT_TYPE="dm"):
                result = v.on_turn_start(user_message="hi", platform="telegram")
                v.on_output(response_text="Certainly! Hi.", platform="telegram")
                v.on_tool_call(tool_name="send_message", args={"target": "telegram", "message": "## Hi"})
                v.command("default")
                v.command("texting")
            self.assertEqual({p: p.read_bytes() for p in (soul, config)}, before)
            self.assertEqual(sorted(os.listdir(home)), ["SOUL.md", "config.yaml"])
            # Hook context is appended to the user turn by Hermes, never the system prompt.
            self.assertEqual(set(result), {"context"})
            self.assertNotIn("system_prompt", json.dumps(v.ctx.state.data))


class RegisterTests(unittest.TestCase):
    def test_every_profile_gets_the_voice(self):
        for profile, primary in (("default", True), ("delta", False)):
            calls = []
            ctx = SimpleNamespace(
                profile_name=profile, state=FakeState(),
                register_tool=lambda **kw: calls.append(("tool", kw["name"])),
                register_hook=lambda name, fn: calls.append(("hook", name, getattr(fn, "__self__", None).__class__.__name__)),
                register_platform_handler=lambda platform, fn: None,
                register_skill=lambda name, path: None,
                register_cli_command=lambda name, *a: calls.append(("cli", name)),
                register_command=lambda name, fn, **kw: calls.append(("command", name)),
                on_unload=lambda fn: None)
            with tempfile.TemporaryDirectory() as d:
                sys.modules["alans_way_idle_test"].register(ctx, legacy_home=d)
            with self.subTest(profile):
                for hook in ("pre_llm_call", "transform_llm_output", "pre_tool_call"):
                    self.assertIn(("hook", hook, "Voice"), calls)
                self.assertIn(("command", "tone"), calls)
                self.assertIn(("cli", "tone"), calls)
                self.assertEqual(("tool", "proactivity") in calls, primary)

    def test_manifest_declares_the_voice_hooks(self):
        text = (Path(V.__file__).parent / "plugin.yaml").read_text(encoding="utf-8")
        for name in ("transform_llm_output", "pre_tool_call"):
            self.assertIn(f"- {name}", text)


if __name__ == "__main__":
    unittest.main()
