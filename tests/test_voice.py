"""Texting voice: the Telegram note, the send-time polish, and the on/off switch."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
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
        for rule in ("user-facing text", "tool names", "tool calls", "file paths",
                     "unless they ask for technical detail"):
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
        for rule in ("1-3 short sentences", "contractions", "'Certainly!', 'Great question' or 'I'd be happy to'",
                     "never headings", "emoji only if they use them", "only when they ask for steps",
                     "never at their expense and never with bad news", "pick one and say why",
                     "stay complete: lead with a one-line answer", "user owns a decision",
                     "approvals, CAPTCHA handbacks and safety checks work exactly as before",
                     "say plainly when something failed", "theirs wins"):
            self.assertIn(rule, V.NOTE)

    def test_quiet_policy_replaces_progress_narration(self):
        note = self.turn(voice(), "telegram")["context"]
        for rule in ("stay quiet through routine reads, navigation, saving, retries that succeed"
                     " and step transitions",
                     "interrupt only for a decision, approval or handback they own, a blocker or"
                     " failed step",
                     "information you can't safely guess (never invent it)",
                     "one concise verified result and any real caveat, not a step-by-step log",
                     "no play-by-play bubbles while a task runs",
                     "activity indicator already shows it working",
                     "Narrate your steps only when they ask for live updates",
                     "side effects and mistakes right away",
                     "acknowledge it in one line and fold it into the running task",
                     "don't restart"):
            self.assertIn(rule, note)
        for dropped in ("Before each multi-step chunk", "one update per roughly two actions",
                        "first-person action and say what's next"):
            self.assertNotIn(dropped, note)

    def test_truth_rules_for_tools_and_exact_claims(self):
        note = self.turn(voice(), "telegram")["context"]
        for rule in ("Use the tools you're given before saying you can't",
                     "never invent tool errors, output or a blocker that didn't happen",
                     "Claim an exact result only when the results show it",
                     "display decoration, not the file's bytes",
                     "a write's verified confirmation means the text you sent landed, not that"
                     " it matched the source"):
            self.assertIn(rule, note)

    def test_same_note_on_every_chat_surface(self):
        notes = {p: self.turn(voice(), p)["context"] for p in ("telegram", "desktop", "tui", "bot_room")}
        self.assertEqual(len(set(notes.values())), 1)
        for platform in ("cli", "discord", "slack", "cron", "api_server", "webhook",
                         "subagent", "", None):
            self.assertIsNone(self.turn(voice(), platform))

    def test_check_ins_share_the_same_rules(self):
        for shared in (V.TEXTING, V.PLAIN, V.FORMAT):
            self.assertIn(shared, P.VOICE)
            self.assertIn(shared, V.NOTE)


class RecapLengthTests(unittest.TestCase):
    """Prompt-order regressions at the hook, not generated-reply compliance tests."""

    turn = NoteTests.turn

    def test_quick_recap_length_is_last_after_general_detail_and_list_guidance(self):
        for chat in ("dm", "group"):
            with self.subTest(chat=chat):
                note = self.turn(voice(), "telegram", chat,
                                 "hey, quick one: what did you get done today?")["context"]
                start = note.index("Casual replies:")
                for competing in ("Long answers (code, plans, research) stay complete",
                                  "Use a list only", V.SAFE):
                    self.assertGreater(start, note.index(competing))
                tail = note[start:]
                self.assertIn("at most 3 sentences total, including any offer of detail", tail)
                self.assertIn("no lists unless asked", tail)
                self.assertIn("without per-item evidence or history", tail)
                self.assertIn("theirs wins", tail)
                self.assertIn(V.RECAP, tail)
                self.assertTrue(note.endswith(
                    "theirs wins." + (V.GROUP if chat == "group" else "")
                    + "\nThis one wants a short answer: at most 3 sentences, the headline only,"
                    " then offer detail."))

    def test_length_default_preserves_explicit_detail_and_persona_requests(self):
        for text in ("Give me a detailed recap with evidence for every item.",
                     "Give me the full step-by-step plan and runnable code.",
                     "My persona says to write detailed reports; use it for this recap."):
            with self.subTest(text=text):
                note = self.turn(voice(), "telegram", text=text)["context"]
                tail = note[note.index("Casual replies:"):]
                self.assertIn("their own persona or instructions ask for a different style or more detail", tail)
                self.assertIn("theirs wins", tail)
                self.assertIn("Long answers (code, plans, research) stay complete", note)

    def test_long_recap_is_never_silently_shortened_at_output(self):
        text = ("I checked the calendar. I compared the available options. Nothing was booked.\n\n"
                "I checked the installed versions. The reminder is set. One check failed.\n\n"
                "The draft is still waiting for approval. Want details?")
        self.assertIsNone(voice().on_output(response_text=text, platform="telegram"))


class ShortReplyIntentTests(unittest.TestCase):
    """The hook scopes an extra reminder; it does not enforce generated reply length."""

    turn = NoteTests.turn
    reminder = ("This one wants a short answer: at most 3 sentences, the headline only,"
                " then offer detail.")

    def test_short_reply_requests_get_one_reminder_at_the_very_end(self):
        for text in ("hey, quick one: what did you get done today?",
                     "Quick question: recap?", "TL;DR: what's the status?",
                     "What did you get done today?", "Recap today's work.",
                     "Can you give me a recap?", "How’s it going?", "how's it going",
                     "hi", "Hey!", "Good morning!", "thanks", "Thank you!",
                     "Thanks, that's helpful."):
            for chat in ("dm", "group", "forum", "channel"):
                with self.subTest(text=text, chat=chat):
                    note = self.turn(voice(), "telegram", chat, text)["context"]
                    self.assertEqual(note.count(self.reminder), 1)
                    self.assertTrue(note.endswith("\n" + self.reminder))

    def test_reviewer_corpus_at_decided_expectations(self):
        # Whole-message recap/social intent only: generic status questions and
        # "send me a recap" are left uncapped under the lead's conservative rule.
        cases = json.loads(Path(__file__).with_name("voice_short_reply_corpus.json").read_text())
        self.assertEqual(len(cases), 72)
        for case in cases:
            text, expected = case["text"], case["expected"]
            with self.subTest(text=text):
                self.assertEqual(V.wants_short_reply(text), expected)
            for chat in ("dm", "group", "forum", "channel"):
                with self.subTest(text=text, chat=chat):
                    note = self.turn(voice(), "telegram", chat, text)["context"]
                    base = V.NOTE + (V.GROUP if chat != "dm" else "")
                    self.assertEqual(note, base + ("\n" + self.reminder if expected else ""))

    def test_standalone_recaps_social_replies_and_acknowledgments(self):
        for text in ("recap", "tl;dr", "Hi 👋, quick question: recap?",
                     "Hey! What did you get done?", "Hello, how’s it going today?",
                     "Thanks! That's helpful 😊", "ok", "Okay 👍", "Got it!",
                     "Understood.", "Sounds good!", "Hey, thanks 🙏"):
            with self.subTest(text=text):
                note = self.turn(voice(), "telegram", text=text)["context"]
                self.assertTrue(note.endswith("\n" + self.reminder))

    def test_any_second_request_or_task_object_prevents_the_cap(self):
        for opener in ("recap", "tl;dr", "what did you get done today?",
                       "how's it going?", "Hi 👋", "Thanks, that's helpful", "Got it!"):
            for task in ("book a flight", "find flights", "send the report", "fix this bug",
                         "write a script", "explain OAuth", "compare these options"):
                for separator in (". ", "; ", "\n", " and ", " 😊 "):
                    text = opener + separator + task
                    with self.subTest(text=text):
                        self.assertEqual(self.turn(voice(), "telegram", text=text)["context"], V.NOTE)
        for text in ("quick one", "quick question", "Quick question: is it ready?",
                     "Quick one: find flights", "Recap how to book a flight",
                     "Recap and send it", "TL;DR: fix the bug", "hi <= fix the bug",
                     "What did you get done today? Also recap the meeting."):
            with self.subTest(text=text):
                self.assertEqual(self.turn(voice(), "telegram", text=text)["context"], V.NOTE)

    def test_detail_words_anywhere_prevent_the_cap(self):
        for word in ("long", "extensive", "extensively", "everything", "all of it", "full", "complete",
                     "detail", "detailed", "details", "thoroughly", "comprehensive"):
            for text in (f"{word}: recap", f"recap {word}", f"Hi, {word}, how's it going?"):
                with self.subTest(text=text):
                    self.assertEqual(self.turn(voice(), "telegram", text=text)["context"], V.NOTE)

    def test_raw_input_limit_does_not_truncate_or_normalize_away_tasks(self):
        at_limit = "recap" + " " * 195
        self.assertEqual(len(at_limit), 200)
        self.assertTrue(V.wants_short_reply(at_limit))
        for text in (at_limit + " ", at_limit + "fix this bug", " " * 196 + "recap",
                     "recap" + "." * 1000000, "hey" + " 👋" * 100000):
            with self.subTest(length=len(text)):
                self.assertFalse(V.wants_short_reply(text))

    def test_detail_requests_override_short_reply_cues(self):
        for text in ("Quick question: explain in detail how this works.",
                     "Quick one: walk me through the deployment.",
                     "Recap today in detail.", "TL;DR first, then a detailed explanation.",
                     "What did you get done? Include details and evidence.",
                     "How's it going? Give me the full report.",
                     "Recap the changes step-by-step.",
                     "Quick question: give me a comprehensive comparison.",
                     "Recap everything thoroughly.",
                     "Quick one: explain in depth.",
                     "My persona says to write detailed reports; use it for this recap."):
            with self.subTest(text=text):
                note = self.turn(voice(), "telegram", text=text)["context"]
                self.assertEqual(note, V.NOTE)

    def test_unmatched_turns_add_no_reminder_and_do_not_inherit_previous_intent(self):
        v = voice()
        self.turn(v, "telegram", text="quick one: recap?")
        for text in ("Explain the architecture.", "Write the implementation plan.",
                     "Check my calendar tomorrow.", "hey can you check my calendar tomorrow",
                     "Thanks! Please write the migration script.",
                     "Hello, research available flights.", "Hi, compare these options.",
                     "Add a recap endpoint to the service.",
                     'Translate "quick question" into French.',
                     'The document says "recap". Check its claims.',
                     "How's it going to handle retries?",
                     "Run the quick questionnaire.", "Recapitalize the company.", "", None):
            for chat in ("dm", "group"):
                with self.subTest(text=text, chat=chat):
                    note = self.turn(v, "telegram", chat, text)["context"]
                    self.assertEqual(note, V.NOTE + (V.GROUP if chat == "group" else ""))

    def test_short_intent_respects_existing_platform_mode_and_injected_turn_exclusions(self):
        for platform in ("cli", "cron", "discord", "", None):
            self.assertIsNone(self.turn(voice(), platform, text="quick question: recap?"))
        self.assertIsNone(self.turn(voice("default"), "telegram", text="quick question: recap?"))
        for marker in (P.MARKER, P.BRIEF_MARKER):
            self.assertIsNone(self.turn(voice(), "telegram", text=marker + " quick question: recap?"))


class CorpusRuleTests(unittest.TestCase):
    """Offline prompt fixtures, not a claim about generated replies."""

    def prompts(self):
        p = P.Proactivity(SimpleNamespace(state=FakeState()))
        s, now = P.Settings(timezone="UTC"), datetime(2026, 10, 7, 11, tzinfo=timezone.utc)
        return {"chat": V.note_for("hey", platform="telegram"),
                "group": V.note_for("hey", platform="telegram", chat_type="group"),
                "check-in": p.prompt(s, timedelta(hours=3), now),
                "asked": p.prompt(s, timedelta(hours=3), now, asked=True),
                "brief": p.brief_prompt(s, now)}

    def assert_rules(self, *rules):
        for name, text in self.prompts().items():
            for rule in rules:
                with self.subTest(prompt=name, rule=rule):
                    self.assertIn(rule, text)

    def test_status_precedes_evidence_or_caveat(self):
        self.assert_rules("Lead with the concrete status, then evidence or a caveat")

    def test_progress_is_quiet_and_interrupts_only_for_theirs(self):
        self.assert_rules("Mid-task, stay quiet through routine reads, navigation, saving, retries"
                          " that succeed and step transitions",
                          "interrupt only for a decision, approval or handback they own",
                          "never invent it",
                          "one concise verified result and any real caveat, not a step-by-step log")

    def test_narrates_only_user_world_actions_not_internal_loading(self):
        self.assert_rules("Never narrate loading skills, instructions, memory or tools",
                          "Narrate only actions in the user's world")

    def test_questions_name_a_user_owned_decision(self):
        self.assert_rules("Ask only when the user owns a decision; name the choice or needed detail",
                          "Otherwise give a next step or caveat when useful, then stop")

    def test_owns_limits_failures_and_side_effects(self):
        self.assert_rules("Own limits, failures and side effects plainly")

    def test_exact_claims_need_exact_evidence_in_every_prompt(self):
        self.assert_rules("never invent tool errors, output or a blocker that didn't happen",
                          "Claim an exact result only when the results show it",
                          "a write's verified confirmation means the text you sent landed, not"
                          " that it matched the source")

    def test_warmth_and_openers_are_sparse(self):
        self.assert_rules("Mild warmth is fine; use a short opener sparingly")

    def test_casual_chat_is_one_to_three_short_sentences(self):
        self.assertIn("Casual replies: 1-3 short sentences", self.prompts()["chat"])

    def test_recaps_lead_with_headlines_and_offer_detail(self):
        self.assert_rules("Recaps: 2-3 headline outcomes in 1-3 sentences; no bullets",
                          "Offer detail ('want the details on any of these?')")

    def test_quick_daily_recap_gets_the_rule_on_the_actual_turn(self):
        note = V.note_for("hey, quick one: what did you get done today?", platform="telegram")
        self.assertIn("Recaps: 2-3 headline outcomes in 1-3 sentences; no bullets", note)
        self.assertIn("Offer detail ('want the details on any of these?')", note)

    def test_internals_stay_out_of_user_text_unless_technical_detail_is_requested(self):
        self.assert_rules("In user-facing text, use task words, never tool names, tool calls,"
                          " file paths, scripts, job or session IDs unless they ask for technical detail")


class OutputTests(unittest.TestCase):
    TIC = "Certainly! ## Plan\nShip it."

    def test_polishes_the_final_reply_on_chat_surfaces_only(self):
        for platform in ("telegram", "desktop", "tui", "bot_room"):
            with self.subTest(platform=platform):
                self.assertEqual(voice().on_output(response_text=self.TIC, platform=platform),
                                 "## Plan\nShip it.")
        for platform in ("discord", "cli", "cron", "api_server"):
            with self.subTest(platform=platform):
                self.assertIsNone(voice().on_output(response_text=self.TIC, platform=platform))
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
                # Dormant cross-bot export adds no tool to secondary profiles.
                self.assertEqual(("tool", "proactivity") in calls, primary)
                self.assertEqual(("hook", "pre_llm_call", "Proactivity") in calls, primary)

    def test_manifest_declares_the_voice_hooks(self):
        text = (Path(V.__file__).parent / "plugin.yaml").read_text(encoding="utf-8")
        self.assertIn("- transform_llm_output", text)
        self.assertNotIn("- pre_tool_call", text)


if __name__ == "__main__":
    unittest.main()
