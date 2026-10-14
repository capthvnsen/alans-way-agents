"""Texting voice: the Telegram note, the send-time polish, and the on/off switch."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib
import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_proactivity import FakeState, P  # noqa: E402  (loads the plugin package once)

V = importlib.import_module("alans_way_idle_test.voice")


QUOTES = ("'", '"', "“", "”", "‘", "’", "«", "»", "‹", "›", "„", "‚", "〝", "〞", "〟", "⸂", "⸃",
          "「", "」", "『", "』", "＂", "＇", "❝", "❞")


class PolishTests(unittest.TestCase):
    def test_drops_a_known_opener_at_the_very_start(self):
        for raw, want in (
            ("Certainly! The deploy is green.", "The deploy is green."),
            ("Great question! Obsidian, because your notes stay local.",
             "Obsidian, because your notes stay local."),
            ("Absolutely!\nDone.", "Done."),
            ("Of course!   Done.", "Done."),
            ("Certainly! ## Plan\n**Ship** it.", "## Plan\n**Ship** it."),   # no flattening
            ("Sure thing! Great question. Done.", "Great question. Done."),  # only the first one
        ):
            self.assertEqual(V.polish(raw), want)

    def test_everything_else_is_byte_identical(self):
        for text in ("Sure, but only if the card is yours.", "Absolutely. Delete it.",
                     "Certainly not: that would delete prod.", "Great question for Sam, not me.",
                     "As an AI, I can't feel the rain.", "Done. Certainly! More later.",
                     "I'd be happy to help with that. Standup is at 9:30.",   # the apostrophe blocks it
                     " Certainly! Leading space.", "Certainly!", "## Plan\n**a** **b** **c** **d** **e**",
                     "Absolutely!\n\nDone.", "Certainly!\tDone.", "Certainly! \nDone.\n ",
                     "# 4417 is the ticket", "Total: $1,249.99 for 3 seats, ref #4417.", ""):
            self.assertEqual(V.polish(text), text)

    def test_any_indented_line_backtick_or_quote_blocks_the_opener(self):
        for rest in ("    code = 1", "\tcode = 1", "Run `ls`.", *[f"Say {q}hi{q}." for q in QUOTES],
                     "It's done.", "»x«", "〝x〟", "⸂x⸃"):
            with self.subTest(rest):
                text = "Certainly!\n" + rest
                self.assertEqual(V.polish(text), text)

    def test_any_other_line_break_blocks_the_opener(self):
        for sep in ("\r", "\r\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"):
            for text in (f"Certainly!{sep}    def f():{sep}        return 1",   # the reviewer's case
                         f"Certainly!{sep}Done.", f"Certainly! Done.{sep}"):
                with self.subTest(sep=repr(sep), text=text[:20]):
                    self.assertEqual(V.polish(text), text)

    def test_the_line_break_set_matches_splitlines(self):
        breaks = {chr(c) for c in range(0x3000) if len(("a" + chr(c) + "b").splitlines()) > 1}
        self.assertEqual(breaks - {"\n"}, set(V._OTHER_LINE_BREAKS))

    def test_reviewer_cases(self):
        for text in (
            "Certainly!\n    def f():\n        return 1",       # an opener must not eat code indentation
            "Certainly! 〝quoted〟 text",
            "Certainly! ⸂substituted⸃ text",
            "'Certainly!\n## Keep this heading'",
            "[docs](relative(path)/**one**/**two**/**three**/**four**/**five**)",
            "See [the docs][d].\n\n[d]: ./guide/**one**/**two**/**three**/**four**/**five**",
            "'## unclosed **a** **b** **c** **d** **e**\n## still kept",
            "»## reverse **a** **b** **c** **d** **e**«",
            "Use ``a ** b ** c ** d ** e ** f`` here.",
            "Run `cat <<EOF\n## header line\nEOF` and done.",
            "```md\n## inside a fence\n```",
            "    ## indented code\n    x = **a** **b** **c** **d** **e**",
        ):
            with self.subTest(text=text[:40]):
                self.assertEqual(V.polish(text), text)

    def test_property_code_links_and_quotes_come_back_byte_identical(self):
        rng = random.Random(93)
        nasty = ["## h", "**a** **b** **c** **d** **e**", "Certainly!", "# x", "**", "~~", "\n## n\n"]

        def bit():
            return rng.choice(nasty + ["x", "y z", "42", "(p)", "/a/", "#1"])

        def inner():
            return "".join(bit() + rng.choice(["", " ", "\n"]) for _ in range(rng.randint(1, 4))).strip() or "x"

        protected = [
            lambda: "`" + inner().replace("`", "") + "`",
            lambda: "``" + inner().replace("`", "") + " ` " + "``",
            lambda: "```\n" + inner() + "\n```",
            lambda: "    " + inner().replace("\n", "\n    "),
            lambda: "\t" + inner().replace("\n", " "),
            *[lambda sep=sep: inner() + sep + "    " + inner() for sep in
              ("\r", "\r\n", "\v", "\f", "\x85", "\u2028", "\u2029")],
            lambda: "[t](" + inner().replace(")", "").replace("\n", "") + ")",
            lambda: "[t](https://e.io/" + inner().replace(" ", "").replace("\n", "") + ")",
            lambda: "\n[ref]: ./" + inner().replace(" ", "").replace("\n", "") + "\n",
            *[lambda o=o, c=c: o + inner() + c for o, c in
              (("'", "'"), ('"', '"'), ("«", "»"), ("»", "«"), ("‹", "›"), ("“", "”"), ("‘", "’"),
               ("„", "“"), ("「", "」"), ("〝", "〟"), ("⸂", "⸃"), ("'", ""), ('"', ""))],
        ]
        checked = 0
        for n in range(300):
            pieces = [rng.choice(protected)() for _ in range(rng.randint(1, 3))]
            parts = pieces + [inner() for _ in range(rng.randint(0, 3))]
            rng.shuffle(parts)
            body = "\n".join(parts).lstrip("\n")
            opener = rng.choice(["", "Certainly! ", "Great question.\n", "Of course!\n\n"])
            text = opener + body
            if not body.strip() or V._SILENCE.search(text) or V._OPENER.match(body):
                continue
            out = V.polish(text)
            risky = ("`" in text or any(ch in "\r\v\f\x1c\x1d\x1e\x85\u2028\u2029" for ch in text)
                     or any(line[:1].isspace() for line in text.splitlines())
                     or any(V._is_quote(ch) for ch in text))
            with self.subTest(n=n, text=text[:60]):
                for piece in pieces:
                    self.assertIn(piece.strip(), out)
                self.assertTrue(text.endswith(out))   # only ever a prefix is removed
                m = V._OPENER.match(text)
                rest = text[m.end():] if m else ""
                stripped = not risky and rest.strip() and not rest[:1].isspace()
                self.assertEqual(out, rest if stripped else text)
            checked += 1
        self.assertGreaterEqual(checked, 200)

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

    def test_never_empties_or_silences_a_reply(self):
        for text in ("", "Certainly!", "Certainly!   ", "Certainly! NO_REPLY", "Certainly! The silent auction is at 6."):
            self.assertEqual(V.polish(text), text)


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
    def test_user_facing_narration_uses_task_words(self):
        note = self.turn(voice(), "telegram")["context"]
        for rule in ("user-facing text", "workflow", "tool call", "MCP", "tab id",
                     "I'm checking the airline's prices now"):
            self.assertIn(rule, note)

    def test_recommendations_require_facts_read_live_this_turn(self):
        note = self.turn(voice(), "telegram")["context"]
        for rule in ("Prices, availability and policies", "page read live this turn",
                     "label anything else unconfirmed", "never recommend using an unconfirmed number"):
            self.assertIn(rule, note)

    def turn(self, v, platform, chat_type="dm", text="hey can you check my calendar tomorrow"):
        with env(HERMES_SESSION_CHAT_TYPE=chat_type):
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

    def test_cron_keeps_the_default_voice(self):
        self.assertIsNone(self.turn(voice(), "cron", ""))

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

    def test_live_progress_note_reaches_the_telegram_turn(self):
        note = self.turn(voice(), "telegram")["context"]
        for rule in ("Before each multi-step chunk", "what you're doing now and what comes next",
                     "email sent, form submitted, or page they must act on", "side effects and mistakes",
                     "at most one update per roughly two actions", "one quick action",
                     "no tool names", "acknowledge it in one line and fold it into the running task",
                     "don't restart"):
            self.assertIn(rule, note)

    def test_check_ins_share_the_same_rules(self):
        for shared in (V.TEXTING, V.PLAIN, V.FORMAT):
            self.assertIn(shared, P.VOICE)
            self.assertIn(shared, V.NOTE)


class OutputTests(unittest.TestCase):
    TIC = "Certainly! ## Plan\nShip it."

    def test_polishes_the_final_telegram_reply_only(self):
        self.assertEqual(voice().on_output(response_text=self.TIC, platform="telegram"), "## Plan\nShip it.")
        self.assertIsNone(voice().on_output(response_text=self.TIC, platform="discord"))
        self.assertIsNone(voice("default").on_output(response_text=self.TIC, platform="telegram"))
        self.assertIsNone(voice().on_output(response_text="All good.", platform="telegram"))

    def test_cron_results_are_not_polished(self):
        self.assertIsNone(voice().on_output(response_text=self.TIC, platform="cron", session_id="cron_j_20261013_081000"))

    def test_silence_markers_pass_through(self):
        for marker in ("[SILENT]", "SILENT", "NO_REPLY", "NO REPLY", "[静默]", "沉默"):
            self.assertIsNone(voice().on_output(response_text=marker, platform="telegram"))


class SwitchTests(unittest.TestCase):
    def test_tone_command(self):
        v = voice()
        self.assertIn("on", v.command(""))
        off = v.command("default")
        self.assertIn("default voice", off)
        self.assertIn("Check-ins and the morning brief keep their own short style", off)
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
                for hook in ("pre_llm_call", "transform_llm_output"):
                    self.assertIn(("hook", hook, "Voice"), calls)
                self.assertNotIn(("hook", "pre_tool_call", "Voice"), calls)
                self.assertIn(("command", "tone"), calls)
                self.assertIn(("cli", "tone"), calls)
                self.assertEqual(("tool", "proactivity") in calls, primary)

    def test_manifest_declares_the_voice_hooks(self):
        text = (Path(V.__file__).parent / "plugin.yaml").read_text(encoding="utf-8")
        self.assertIn("- transform_llm_output", text)
        self.assertNotIn("- pre_tool_call", text)


if __name__ == "__main__":
    unittest.main()
