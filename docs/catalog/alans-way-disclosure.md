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

## Reviewed scanner inventory

Previous candidate: `f7de103a3f895f97986f45bfa76e302d31dcbe64`.
Original plugin baseline: `fb3571cb70b7f65e57a31c328ba14e7662ecff9c`.
Unmodified upstream scanner: `6e7b83a2f1c093e992a8d838ed77ea320fbd8e51`,
`tools/plugin_guard.py`, `tools/plugin_guard_context.py`, `tools/skills_guard.py`.
Paths below are relative to `alans-way/`. The remaining five matches are true
capabilities and their commands are preserved; no scanner rule was changed.
LOW findings document the loopback-only forward/check/app examples. The only
HIGH finding (`python_os_environ` at the former
`skills/integrations/references/mastodon.md:45`) is gone because the plugin no
longer ships the recipe. Its environment-reading command remains visible in
the human-run document outside the plugin.

| File:line | Rule | Severity | Matched text | Before → after |
|---|---|---|---|---|
| `skills/workspace-setup/SKILL.md:180` | `python_subprocess` | MEDIUM | `return subprocess.run(["git", "-C", path, *args], check=True, timeout=5,` | 1 → 1 |
| `skills/workspace-setup/SKILL.md:235` | `python_subprocess` | MEDIUM | `return subprocess.run(["git", "-C", path, *args], check=True, timeout=5,` | 1 → 1 |
| `skills/workspace-setup/SKILL.md:339` | `hardcoded_ip_port` | LOW | `-L 127.0.0.1:16080:127.0.0.1:<viewer-port> <vm-user>@<vm-tailnet-host> 'sleep 1800'` | 1 → 1 |
| `skills/workspace-setup/SKILL.md:345` | `hardcoded_ip_port` | LOW | `curl --fail --connect-timeout 5 --max-time 10 http://127.0.0.1:16080/vnc.html -o /dev/null` | 1 → 1 |
| `skills/workspace-setup/SKILL.md:348` | `hardcoded_ip_port` | LOW | `http://127.0.0.1:16080/vnc.html` in Remote desktop connection | 1 → 1 |

Verdict: **CAUTION → SAFE**. Inventory: 1 HIGH + 2 MEDIUM + 3 LOW →
0 HIGH + 2 MEDIUM + 3 LOW. Scanner output: `verdict: safe`.
There are no remaining false positives to reword.

`tests/test_plugin_scan.py` asserts exact counts by rule, severity and file,
plus SAFE allowance, CAUTION/confirmation and DANGEROUS rejection gates. Supply
the three upstream files under `$HERMES_SCANNER_ROOT/tools/` to run it locally; it skips
when those files are absent. The inventory assertion requires review of any
added or removed occurrence, even when it shares a previously allowed rule
and file.
