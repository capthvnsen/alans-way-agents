# Alan's Way catalog disclosure supplement

Draft text for the next `alans-way` catalog submission. This supplements the
existing setup/service/router disclosures; it does not change the published
catalog entry or its reviewed pin. The release lead must select and review the
final submission commit.

## Disclosure text

The bundled skills include optional integrations and local setup commands.
After dependency and account consent, the Mastodon recipe runs a library
identity probe that reads `MASTODON_API_BASE_URL` and `MASTODON_ACCESS_TOKEN`
from its process environment and authenticates to the user's chosen HTTPS
instance. The user enters the token privately and explicitly grants only that
profile's token passthrough. The probe prints only the account handle; it does
not dump the environment or print the token. Posting requires separately
agreed scopes and fresh explicit approval.

Workspace setup's two Git subprocess helpers perform read-only local checks
with five-second timeouts: one validates the setup checkout's origin and
cleanliness; the other validates a file-source plugin install's recorded and
effective origin before using its installed revision. Viewer handoff can, with
explicit consent, ask the human to run a temporary SSH forward bound to the
computer's loopback interface, verify the viewer URL with curl, and enter that
URL in the app. The forward ends after 30 minutes or Ctrl-C. The human enters
the VNC password privately.

Manual/file installs of this candidate receive CAUTION from the scanner below
and need review and explicit confirmation of the exact tree. Setup consent,
dependency consent and `--enable` are separate. `--force` confirms CAUTION and
can replace an install; it cannot override DANGEROUS. Catalog installs use the
catalog's reviewed commit, which does not approve arbitrary newer revisions.

## Reviewed scanner inventory

Plugin baseline: `fb3571cb70b7f65e57a31c328ba14e7662ecff9c`.
Unmodified upstream scanner: `6e7b83a2f1c093e992a8d838ed77ea320fbd8e51`,
`tools/plugin_guard.py`, `tools/plugin_guard_context.py`, `tools/skills_guard.py`.
Paths below are relative to `alans-way/`. All six matches are true capabilities
and are preserved; no scanner rule or matched example was changed. The HIGH
rule's potential-environment-dump label is broader than the two-key probe,
but its environment access is real. LOW findings document the loopback-only
forward/check/app examples.

| File:line | Rule | Severity | Matched text | Before → after |
|---|---|---|---|---|
| `skills/integrations/references/mastodon.md:45` | `python_os_environ` | HIGH | `os.environ["MASTODON_API_BASE_URL"]`, `os.environ["MASTODON_ACCESS_TOKEN"]` in the identity probe | 1 → 1 |
| `skills/workspace-setup/SKILL.md:181` | `python_subprocess` | MEDIUM | `return subprocess.run(["git", "-C", path, *args], check=True, timeout=5,` | 1 → 1 |
| `skills/workspace-setup/SKILL.md:236` | `python_subprocess` | MEDIUM | `return subprocess.run(["git", "-C", path, *args], check=True, timeout=5,` | 1 → 1 |
| `skills/workspace-setup/SKILL.md:340` | `hardcoded_ip_port` | LOW | `-L 127.0.0.1:16080:127.0.0.1:<viewer-port> <vm-user>@<vm-tailnet-host> 'sleep 1800'` | 1 → 1 |
| `skills/workspace-setup/SKILL.md:346` | `hardcoded_ip_port` | LOW | `curl --fail --connect-timeout 5 --max-time 10 http://127.0.0.1:16080/vnc.html -o /dev/null` | 1 → 1 |
| `skills/workspace-setup/SKILL.md:349` | `hardcoded_ip_port` | LOW | `http://127.0.0.1:16080/vnc.html` in Remote desktop connection | 1 → 1 |

Verdict before and after: **CAUTION**, 1 HIGH + 2 MEDIUM + 3 LOW.
There are no false positives to reword without hiding actual instructions.

`tests/test_plugin_scan.py` asserts exact counts by rule, severity and file,
plus the CAUTION/confirmation and DANGEROUS rejection gates. Supply the three
upstream files under `$HERMES_SCANNER_ROOT/tools/` to run it locally; it skips
when those files are absent. The inventory assertion requires review of any
added or removed occurrence, even when it shares a previously allowed rule
and file.
