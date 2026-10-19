"""Router cache binding at the actual subprocess/MCP seam.

Real Chromium coverage lives in desktop/test/plugin-target-binding-headless.cjs.
These smaller fixtures pin cache equality, narrowing, and refusal before forwarding.
"""
import json
import unittest

import test_commit_gate as gate

PURCHASE = gate.PURCHASE


class TargetBindingTests(unittest.TestCase):
    def setUp(self):
        self.router = gate.CommitGateTests("runTest")
        self.router.setUp()

    def tearDown(self):
        self.router.tearDown()

    def open(self, elements, elicitation=True, **env):
        t = self.router
        t.start(MAC_COMMIT_ELEMENTS=json.dumps(elements), **env)
        t.handshake(elicitation)
        t.send("tools/call", name="cua_alans_way_open", arguments={"url": "https://shop.example/"})
        t.recv()
        self.snapshot()

    def snapshot(self, **args):
        t = self.router
        t.send("tools/call", name="cua_alans_way_snapshot", arguments={"tabId": "mac-tab-1", **args})
        t.recv()

    @staticmethod
    def link(href="https://shop.example/pay", **extra):
        return {"ref": "e8001", "role": "a", "name": "Buy it again", "href": href, **extra}

    def test_older_host_proof_is_refused_without_breaking_ordinary_work(self):
        self.open([self.link()], MAC_OLD_APPROVAL="1")
        t = self.router
        msg = t.refused(t.act(action="click", ref="e8001", commit=PURCHASE), "approval_binding_unavailable")
        self.assertIn("Update", t.text(msg))
        self.assertEqual(t.actions(), [])
        t.ran(t.act(action="navigate", url="https://shop.example/help"))
        self.assertEqual(len(t.actions()), 1)

    def test_a_later_snapshot_without_proof_cannot_reuse_cached_document_proof(self):
        file = self.router.dir / "mac-stub.cjs"
        source = file.read_text().replace("const a = (m.params && m.params.arguments) || {};",
            "const a = (m.params && m.params.arguments) || {}; if(a.maxElements===294) process.env.MAC_OLD_APPROVAL='1';")
        file.write_text(source)
        self.open([self.link()])
        self.snapshot(maxElements=294)
        t = self.router
        t.refused(t.act(action="eval", code="1", commit=PURCHASE), "approval_binding_unavailable")
        self.assertEqual(t.actions(), [])

    def test_pending_proof_is_immutable_across_fresh_same_url_snapshot(self):
        for change in ("document", "target", "unrelated"):
            with self.subTest(change=change):
                if change != "document":
                    self.tearDown()
                    self.setUp()
                file = self.router.dir / "mac-stub.cjs"
                source = file.read_text().replace("...(navs[a.tabId] || pages[a.tabId]), tab:",
                    "...(navs[a.tabId] || pages[a.tabId]), ...(a.maxElements === 297 ? {approvalContext:{version:1,documentId:'c'.repeat(32),url:pages[a.tabId].url}} : {}), tab:")
                # The fixture annotator normally adds the document field; keep
                # a deliberately supplied identity and token for this probe.
                source = source.replace("if (page) value.approvalContext =", "if (page && !value.approvalContext) value.approvalContext =")
                source = source.replace("const a = (m.params && m.params.arguments) || {};",
                    "const a = (m.params && m.params.arguments) || {}; if(a.maxElements===296) pages['mac-tab-1'].elements[0].approvalTarget='d'.repeat(32);")
                file.write_text(source)
                self.open([self.link()])
                t = self.router
                call = t.act(action="click", ref="e8001", commit=PURCHASE)
                ask = t.recv()
                self.assertEqual(ask["method"], "elicitation/create")
                self.snapshot(maxElements={"document": 297, "target": 296, "unrelated": 295}[change])
                t.answer(ask, "accept", {})
                if change == "unrelated":
                    t.ran(call)
                    [sent] = t.actions()
                    proof = sent["approval"]["binding"]
                    self.assertEqual(proof["documentId"], "a" * 32)
                    self.assertEqual(proof["steps"][0]["targets"][0]["ref"], "e8001")
                else:
                    t.refused(call, "page_changed")
                    self.assertEqual(t.actions(), [])

    def test_equivalent_names_share_the_same_action_href(self):
        self.open([self.link()])
        t = self.router
        for target in [{"ref": "e8001"}] + [{"name": n} for n in
                       ["Buy it again", " Buy it again ", "BUY IT AGAIN", "Buy  it again",
                        "Buy\tit again", "Buy\u00a0it again", "Buy\u2003it again", "Buy\nit again"]]:
            with self.subTest(target=target):
                t.refused(t.act(action="click", **target), "commit_required")
        self.assertEqual(t.actions(), [])

    def test_equality_does_not_broaden_to_hyphens_width_or_near_names(self):
        self.open([self.link()])
        t = self.router
        for name in ["Buy-it-again", "Ｂｕｙ it again", "Missing harmless label"]:
            t.refused(t.act(action="click", name=name), "snapshot_required")
        # The accepted anchored classifier separately refuses a longer label.
        t.refused(t.act(action="click", name="Buy it again help"), "commit_required")
        self.assertEqual(t.actions(), [])

    def test_role_and_row_narrow_before_uniqueness_and_href_judgment(self):
        self.open([self.link(row="Lamp order"),
                   self.link(ref="e8002", href="https://shop.example/help", row="Chair order"),
                   {"ref": "e8003", "role": "button", "name": "Buy it again", "row": "Settings"}])
        t = self.router
        t.refused(t.act(action="click", name="Buy it again"), "snapshot_required")
        t.refused(t.act(action="click", name="Buy it again", role="link"), "snapshot_required")
        t.refused(t.act(action="click", name="Buy\tit again", role="LINK", row="Lamp  order"), "commit_required")
        t.ran(t.act(action="click", name="Buy\u00a0it again", role="a", row="Chair\torder"))
        t.ran(t.act(action="click", name="Buy it again", role="button"))
        t.refused(t.act(action="click", name="Buy it again", role="checkbox"), "snapshot_required")
        self.assertEqual(len(t.actions()), 2)

    def test_missing_or_ambiguous_binding_cannot_be_approved_away(self):
        self.open([self.link(), self.link(ref="e8002", name="Buy  it again")])
        t = self.router
        for name in ["Buy it again", "Missing harmless label"]:
            t.refused(t.act(action="click", name=name, commit=PURCHASE), "snapshot_required")
        # An invented label cannot launder an unobserved ref.
        t.refused(t.act(action="click", ref="e9999", name="Help", commit=PURCHASE), "snapshot_required")
        self.assertEqual(t.actions(), [])

    def test_partial_or_loading_snapshot_does_not_prove_name_uniqueness(self):
        t = self.router
        file = t.dir / "mac-stub.cjs"
        source = file.read_text().replace("...(navs[a.tabId] || pages[a.tabId]), tab:",
            "...(navs[a.tabId] || pages[a.tabId]), ...(a.maxElements === 1 ? {truncated:{elements:true}} : a.maxElements === 2 ? {loading:true} : {}), tab:")
        file.write_text(source)
        self.open([self.link(href="https://shop.example/help")])
        for max_elements in [1, 2]:
            self.snapshot(maxElements=max_elements)
            t.refused(t.act(action="click", name="Buy it again", commit=PURCHASE), "snapshot_required")
        self.assertEqual(t.actions(), [])

    def test_full_snapshots_and_removed_deltas_retire_stale_names_and_refs(self):
        t = self.router
        file = t.dir / "mac-stub.cjs"
        source = file.read_text().replace("const a = (m.params && m.params.arguments) || {};",
            "const a = (m.params && m.params.arguments) || {};\n"
            "if (a.maxElements === 299) pages['mac-tab-1'].elements = [];\n"
            "if (a.maxElements === 298) return reply(m.id, JSON.stringify({removed:['e8001'],generation:2,tab:{id:a.tabId,epoch:1}}));")
        file.write_text(source)
        self.open([self.link(href="https://shop.example/help")])
        self.snapshot(maxElements=298)
        t.refused(t.act(action="click", name="Buy it again"), "snapshot_required")
        t.refused(t.act(action="click", ref="e8001"), "snapshot_required")
        self.snapshot()
        self.snapshot(maxElements=299)
        t.refused(t.act(action="click", name="Buy it again"), "snapshot_required")
        t.refused(t.act(action="click", ref="e8001"), "snapshot_required")
        self.assertEqual(t.actions(), [])

    def test_ordinary_exact_labels_and_navigation_still_forward(self):
        self.open([self.link(href="https://shop.example/orders/reorder"),
                   self.link(ref="e8002", name="Book a demo", href="https://shop.example/map"),
                   self.link(ref="e8003", name="Subscribe and save", href="https://shop.example/catalog")])
        t = self.router
        for name in ["Buy it again", "Book a demo", "Subscribe and save"]:
            t.ran(t.act(action="click", name=name))
        t.ran(t.act(action="navigate", url="https://shop.example/help"))
        self.assertEqual(len(t.actions()), 4)

    def test_equivalent_name_approval_still_forwards_once_with_public_receipt(self):
        self.open([self.link()])
        t = self.router
        call = t.act(action="click", name="Buy\u00a0it again", role="link", commit=PURCHASE)
        ask = t.recv()
        self.assertEqual(ask["method"], "elicitation/create")
        self.assertEqual(t.actions(), [])
        t.answer(ask, "accept", {})
        done = t.recv()
        self.assertEqual(done["id"], call)
        t.answer(ask, "accept", {})
        t.send("tools/call", name="cua_alans_way_status", arguments={})
        t.recv()  # ordered barrier after the duplicate approval
        [sent] = t.actions()
        self.assertEqual(sent["name"], "Buy\u00a0it again")
        self.assertNotIn("commit", sent)
        self.assertEqual(set(sent["approval"]), {"nonce", "kind", "summary", "issuedAt", "tabId", "epoch", "binding"})


if __name__ == "__main__":
    unittest.main()
