# Alan's Way catalog disclosure supplement

Draft text for the next `alans-way` catalog submission. This supplements the
existing setup/service/router disclosures; it does not change the published
catalog entry or its reviewed pin. The release lead must select and review the
final submission commit.

## Disclosure text

The bundled skills include optional integrations and local setup commands.
Social posting is not built into the plugin. The Mastodon recipe was removed
from `alans-way/` and moved to `docs/integrations/mastodon.md` as human-run
repository documentation. The bot no longer ships that connector or its
identity probe, and the integration skill only points the user to the document.
The human-run recipe still discloses its two-key environment access and account
scopes; moving it drops a plugin capability rather than hiding an executable
bot instruction from scanning.

Workspace setup's two Git subprocess helpers perform read-only local checks
with five-second timeouts: one validates the setup checkout's origin and
cleanliness; the other validates a file-source plugin install's recorded and
effective origin before using its installed revision. Viewer handoff can, with
explicit consent, ask the human to run a temporary SSH forward bound to the
computer's loopback interface, verify the viewer URL with curl, and enter that
URL in the app. The forward ends after 30 minutes or Ctrl-C. The human enters
the VNC password privately.

Manual/file installs of this candidate receive SAFE from the scanner below;
MEDIUM/LOW findings alone require no scanner confirmation. Setup and dependency
consent remain separate. If a later revision receives CAUTION, it needs review
and explicit confirmation of the exact tree. `--enable` does not confirm a
scanner warning. `--force` confirms CAUTION and can replace an install; it
cannot override DANGEROUS. Catalog installs use the catalog's reviewed commit,
which does not approve arbitrary newer revisions.

Optional cross-bot proactivity reads bounded recent owner-DM excerpts exported by all enabled profiles on one gateway. It stores sanitized digests for 24 hours and queued asks for up to 2 hours in a shared plugin-owned directory (private files). Exchanges that look like they contain credentials or payment details are skipped entirely. It may automatically inject one read-only or draft-only ask per primary check-in into another bot's bound Telegram DM. Results appear there with primary attribution. Existing approvals still govern consequential actions. Disable cross-bot proactivity per bot with /proactivity cross off; copied context may remain in Hermes history, memory-provider records and model-provider retention after digest expiry.

Short helper outcomes require a separate `/proactivity cross results on` choice in
both bots' bound owner chats. This is off by default, including for existing
cross-bot users. Future asks may return a sanitized done/blocked summary of up to
280 UTF-8 bytes, correlated to one ask and expiring two hours after that ask.
The asking bot consumes it once at its next owner turn or permitted check-in.
This creates no wake, retry or delivery receipt. Use `/proactivity cross results off`
to stop and purge pending outcomes; cross-bot opt-out also revokes this choice.
Previously copied chat and provider context may remain after expiry or opt-out.

Default off; `/proactivity cross on|off|status` controls each bot. Sanitization
cannot guarantee detection of every secret. No historical backfill, attachment
or tool-history export. Digest context is supplied only to permitted primary check-ins;
other profiles' exports are JSON-escaped as untrusted observations. The instruction
not to save excerpts to memory is model policy, not enforced deletion. Normal
Hermes/provider history, sidecars and compaction can retain copied context.
`sent` means scheduled, not delivered or completed; no replay or receipt store.
Imported turns allow reviewed reads/drafting and existing gated browser calls;
terminal/code, delegation, scheduling and unknown connectors are blocked. Existing
browser approval/CAPTCHA/ownership gates remain. This is not universal read-only
enforcement. Offline files are pruned when an explicitly activated profile starts,
then every 60 seconds while connected. Dormant profiles perform no store access.

Remote agents: `scripts/setup-remote-agent.sh` runs only when the operator runs
it. It creates one ed25519 key per bot ID under `~/.ssh` and adds an
`authorized_keys` line restricted (`restrict,command=...`) to the workspace
router, backing the file up first; `--remove` deletes only that line. The
opt-in `scripts/remote-agent-bridge.cjs` serves the same router over HTTP only
when `ALANS_WAY_REMOTE_BRIDGE=1` and a bearer token are set, and binds to
loopback or a private address. Neither changes Hermes config or opens a firewall.

## Reviewed scanner inventory

Previous candidate: `f7de103a3f895f97986f45bfa76e302d31dcbe64`.
Original plugin baseline: `fb3571cb70b7f65e57a31c328ba14e7662ecff9c`.
Unmodified upstream scanner: `6e7b83a2f1c093e992a8d838ed77ea320fbd8e51`,
`tools/plugin_guard.py`, `tools/plugin_guard_context.py`, `tools/skills_guard.py`.
Stage 2 base: `f6bd48069a45342dff8a42f144b49ee635d59484` (`release/plugin-0.21.7`; includes #114 export/control).
Paths below are relative to `alans-way/`. Sixteen reviewed matches remain; no scanner
rule was changed. Queue/receiver and primary check-in dispatch code add no findings.
LOW findings document the loopback-only forward/check/app examples. The only
HIGH finding (`python_os_environ` at the former
`skills/integrations/references/mastodon.md:45`) is gone because the plugin no
longer ships the recipe. Its environment-reading command remains visible in
the human-run document outside the plugin.

| File:line | Rule | Severity | Matched text | Before → after |
|---|---|---|---|---|
| `skills/workspace-setup/SKILL.md:249` | `python_subprocess` | MEDIUM | `return subprocess.run(["git", "-C", path, *args], check=True, timeout=5,` | 1 → 1 |
| `skills/workspace-setup/SKILL.md:304` | `python_subprocess` | MEDIUM | `return subprocess.run(["git", "-C", path, *args], check=True, timeout=5,` | 1 → 1 |
| `skills/workspace-setup/SKILL.md:408` | `hardcoded_ip_port` | LOW | `-L 127.0.0.1:16080:127.0.0.1:<viewer-port> <vm-user>@<vm-tailnet-host> 'sleep 1800'` | 1 → 1 |
| `skills/workspace-setup/SKILL.md:414` | `hardcoded_ip_port` | LOW | `curl --fail --connect-timeout 5 --max-time 10 http://127.0.0.1:16080/vnc.html -o /dev/null` | 1 → 1 |
| `skills/workspace-setup/SKILL.md:417` | `hardcoded_ip_port` | LOW | `http://127.0.0.1:16080/vnc.html` in Remote desktop connection | 1 → 1 |
| `scripts/setup-remote-agent.sh:37,56,73,82,83` | `ssh_backdoor` | MEDIUM | `authorized_keys` read, backup and atomic replace for the restricted router key | 0 → 5 |
| `scripts/setup-remote-agent.sh:65` | `ssh_backdoor` | LOW | comment naming `authorized_keys` | 0 → 1 |
| `scripts/setup-remote-agent.sh:146,147` | `ssh_keygen` | MEDIUM | `ssh-keygen` creating and reading the bot's ed25519 key | 0 → 2 |
| `scripts/setup-remote-agent.sh:146,147,160` | `python_subprocess` | MEDIUM | `ssh-keygen` calls and the local `--probe` run of the forced command | 0 → 3 |

Verdict: **SAFE**. Current baseline → completed cross-bot proactivity: 0 HIGH + 2 MEDIUM + 3 LOW
→ 0 HIGH + 2 MEDIUM + 3 LOW. Remote-agent setup adds 0 HIGH + 10 MEDIUM + 1 LOW
(above; the HTTP bridge adds none) → 0 HIGH + 12 MEDIUM + 4 LOW. Scanner output: `verdict: safe`.
Historically, removing the Mastodon recipe changed CAUTION to SAFE.

`tests/test_plugin_scan.py` asserts exact counts by rule, severity and file,
plus SAFE allowance, CAUTION/confirmation and DANGEROUS rejection gates. Supply
the three upstream files under `$HERMES_SCANNER_ROOT/tools/` to run it locally; it skips
when those files are absent. The inventory assertion requires review of any
added or removed occurrence, even when it shares a previously allowed rule
and file.
