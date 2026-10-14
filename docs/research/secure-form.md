# Telegram Secure Form: conditional GO for a login-vault MVP

**Spike, do not merge.** A model-blind phone form is feasible without a Hermes
fork. **NO-GO for production today:** this spike verifies synthetic Telegram
data and a CLI-shaped sink fixture, not a real encrypted vault, Telegram client,
public endpoint, or recorder. Keep Workspace sign-in handback as the default.
Do not claim that a vault write means the user has signed in.

## Evidence and scope

Inspected 2026-10-14 after fetching origin. Plugin baseline:
`0d1f1c04e42de2e1c44474d7c5ba0c78a1f2a43d`. Hermes source baseline:
`0e427d788d253630d38a3a51cd76849e73cd6925` (H below), fetched into a scratch
source-only clone. Also fetched the requested earlier pin
`6e7b83a2f1c093e992a8d838ed77ea320fbd8e51`; its vault store and vault CLI
diff against H is empty. These are source pins, not deployed-version claims.

Design inputs were the L9 transport assessment and GrokBot form corpus. The
visible card establishes named input / “Save securely” / “Submitted” wording;
it does not establish GrokBot's backend guarantees. No scraped/private messages
are included here. Prior [vault spike #87](https://github.com/capthvnsen/alans-way-agents/pull/87)
at `6b39149b49b788e6a58b072d93453cd19d306512` established a separate VPS browser
experiment and identified missing Telegram masked prompts. Its scoped CDP proxy
was explicitly not a security boundary. This spike neither reuses nor changes it.

Only `prototype/secure-form/`, this assessment, and the spike's fixture tests are
added. No setup, plugin registration, broker, approval/commit gate, CAPTCHA,
auto-takeover, recorder redaction or ownership/epoch code is changed. No service
installation, live bot request, gateway restart, Orgo access or tunnel occurs.

## Trigger without changing Hermes

**Pick a plugin hook plus one explicit Bot API `sendMessage` call.** Hermes's
Telegram adapter has no `web_app` occurrence and no generic reply-markup argument
on [H `plugins/platforms/telegram/adapter.py:3618`](https://github.com/NousResearch/hermes-agent/blob/0e427d788d253630d38a3a51cd76849e73cd6925/plugins/platforms/telegram/adapter.py#L3618).
Clarify creates callback buttons, not arbitrary link/web-app buttons
([`:4266`](https://github.com/NousResearch/hermes-agent/blob/0e427d788d253630d38a3a51cd76849e73cd6925/plugins/platforms/telegram/adapter.py#L4266)).

Use public `ctx.register_hook("post_gateway_admission", ...)` to handle an
explicit private-chat `/secure-form` request. That hook receives a source
snapshot after authorization/admission, in routed profile scope
([H `gateway/run_inbound_consumer.py:1`](https://github.com/NousResearch/hermes-agent/blob/0e427d788d253630d38a3a51cd76849e73cd6925/gateway/run_inbound_consumer.py#L1),
[`hermes_cli/plugins.py:933`](https://github.com/NousResearch/hermes-agent/blob/0e427d788d253630d38a3a51cd76849e73cd6925/hermes_cli/plugins.py#L933)).
Source chat/user/profile fields are serialized by
[`gateway/session.py:126`](https://github.com/NousResearch/hermes-agent/blob/0e427d788d253630d38a3a51cd76849e73cd6925/gateway/session.py#L126).
**Do not issue from `pre_gateway_dispatch`: it runs before auth**
([`hermes_cli/plugins.py:136`](https://github.com/NousResearch/hermes-agent/blob/0e427d788d253630d38a3a51cd76849e73cd6925/hermes_cli/plugins.py#L136)).
Older Hermes without the admitted hook must use handback until upgraded through
the ordinary release process; this spike performs no upgrade.

`register_trigger` is dependency-injected and tested against a fake context and
fake sender. `button_payload` builds a real Bot API payload with an HTTPS
`web_app` URL and opaque request ID. It never sends anything. Production would
inject a bounded, rate-limited sender using the receiving profile's own bot
token, not a second bot or `getUpdates` consumer. Disclose this new outbound
call. No credential/config-reading implementation is shipped in this spike;
token provisioning remains a production task. Never log token-bearing Bot API
URLs, HTTP traces or exceptions. Send failure expires the newly issued request.

Telegram permits inline web-app buttons in user↔bot private chats, excluding
business-account sends. Plain HTTPS links are not an authenticated substitute.
Inline initData normally has signed user/query identity, not signed chat ID;
bind that user to the trusted private-chat issuance context, checking signed
chat data too if supplied. [Telegram button contract](https://core.telegram.org/bots/api#inlinekeyboardbutton)
and [launch data](https://core.telegram.org/bots/webapps#webappinitdata).

## Form and sink

The stdlib service binds **127.0.0.1 only**. One instance fixes bot/profile and
sink; HTTP cannot issue requests or choose a profile, executable, URL, selector
or path. Each random request ID binds user/private chat, label, issuance and
120-second expiry. HMAC verifies raw initData using Telegram's two-stage SHA-256
scheme, rejects duplicate fields, and checks 300-second freshness plus 30-second
clock skew. Never trust `initDataUnsafe`.
[Telegram validation](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).

State: `pending → writing → submitted|failed`; pending requests can expire.
The lock claims both request and signed launch query ID before writing, stopping
double-submit and cross-request replay. A fresh launch may read status without
reposting the secret. Restart drops all IDs and fails closed. A write claimed
before expiry may finish afterward. Failed or uncertain writes are terminal;
check the vault before creating another request. The service emits only
`{label, request_id, status}`. It retains no secret in request/status state.

POST goes directly to the fixed sink. **No `sendData`, chat answer, tool argument,
URL, argv or secret-bearing environment variable.** No access/body/exception logs,
analytics, browser broker or recorder is used. Exact Host/Origin checks reject
cross-origin requests and rebinding; size limits, read timeouts, no-store,
no-referrer and restrictive CSP reduce web exposure. Public-origin header
handling is tested by a local proxy simulation, with no trust in forwarded
headers. Only non-fixture HTML includes Telegram's required SDK; demo loads none.

`VaultCliSink` drives the **public** `hermes vault add --kind login` wizard
through an isolated stdin pipe in a detached process session, with fixed home,
origin and identifier. There are no private Hermes imports or direct vault
writes. Reject CR/LF/NUL in a password because the wizard is line-oriented.
The source wizard uses getpass, then calls `agent/vault_store.py.add_item`
([H `hermes_cli/vault.py:70`](https://github.com/NousResearch/hermes-agent/blob/0e427d788d253630d38a3a51cd76849e73cd6925/hermes_cli/vault.py#L70)).
It can exit zero on a vault error, so the bridge also requires the positive
`Stored. handle=... kind=login origin=...` receipt
([`:105`](https://github.com/NousResearch/hermes-agent/blob/0e427d788d253630d38a3a51cd76849e73cd6925/hermes_cli/vault.py#L105)).
All child output stays captured and is discarded. “Submitted” appears only
after that acknowledgement. Prompt drift, line wrapping, timeouts or a crash
may leave an unconfirmed write; do not retry automatically.

**The demo sink is a discarding fixture, not encryption.** Real CLI execution,
encrypted persistence and receipt compatibility were not verified. A stable
noninteractive contract is required before shipping this bridge. Hermes's
store encrypts secrets and exposes metadata, but its Python implementation is
not a documented plugin integration contract
([H `agent/vault_store.py:1`](https://github.com/NousResearch/hermes-agent/blob/0e427d788d253630d38a3a51cd76849e73cd6925/agent/vault_store.py#L1),
[`:304`](https://github.com/NousResearch/hermes-agent/blob/0e427d788d253630d38a3a51cd76849e73cd6925/agent/vault_store.py#L304)).
This MVP is login passwords only: no arbitrary DB connection strings/API tokens,
manager unlock, codes, payment values, or direct browser fill. Identifiers are
ordinary Hermes vault metadata, distinct from the three-field form status.

## Threat model and residual risks

Protect against forged/stale Telegram identity, forwarded/replayed form URLs,
wrong user/chat/profile, repeated/concurrent submission, client-chosen sinks,
cross-site POSTs, accidental secret logging and false success on sink failure.
Request IDs alone confer no write authority. Issuance identity comes from the
admitted hook, never model-provided Telegram IDs. A model could still ask for a
misleading label: production must show a fixed destination and operation from
trusted configuration and require the human to approve the intended account.

Trusted: Telegram client/webview and SDK, form host/helper and CLI, vault host
administrator and chosen TLS terminator. HMAC requires the bot token in helper
memory; Telegram's Ed25519 third-party scheme could remove that custody but is
not implemented. A compromised same-user/root agent or host can inspect memory
or the local vault key; model-blind messages are not a host privilege boundary.
Use a separate helper UID, narrow authenticated issuance IPC and pinned CLI
executable/profile in production. Python/JS memory is not reliably zeroized;
captured child output can contain secrets even though it is never surfaced.

No guarantee against malicious target sites, device screenshots/keyloggers,
browser extensions, host backups/crash dumps, or a compromised Telegram SDK.
Phone-webview/recording leakage remains untested. Production must prevent
secret DOM/tool/screenshot/recorder capture before any agent resumes. This
spike never opens the form inside Workspace's recorded browser. The stdlib
HTTP server has no production concurrency/rate controls; request count is
bounded at 128 and needs retention/reaping, abuse limits and service isolation.

## HTTPS recommendation and exact future consent

| Option | Decision and trust |
| --- | --- |
| Tailscale Funnel | Preferred optional phone pilot on a dedicated form port. Public HTTPS, relay cannot decrypt; TLS ends on the user's tailscaled host. Requires MagicDNS, HTTPS and Funnel policy permission; ports/bandwidth are limited. Never expose CDP, broker or the general toolbox. [Funnel docs](https://tailscale.com/docs/features/tailscale-funnel) |
| Cloudflare Quick Tunnel | Development-only, random/restart-sensitive hostname, no SLA, 200 in-flight requests/no SSE. Cloudflare edge plaintext processing adds trust beyond the helper host; encrypted tunnel transport does not remove it. [Quick Tunnel docs](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/), [HTTP processing](https://developers.cloudflare.com/data-localization/regional-services/http-requests/) |
| Workspace | Default/fallback; existing app and human browser sign-in, with no new public credential endpoint. Its loopback/SSH broker is not a phone-facing Mini App service. [Plugin baseline `workspace-router.cjs:686`](https://github.com/capthvnsen/alans-way-agents/blob/0d1f1c04e42de2e1c44474d7c5ba0c78a1f2a43d/alans-way/scripts/workspace-router.cjs#L686) |

Before any later enablement, obtain this concrete consent (fill placeholders):

> Allow a dedicated Secure Form helper on [host/profile/loopback port] to be
> reachable by the public HTTPS URL [hostname] through [provider], for [lifetime],
> with [stop/revoke procedure]. Allow the stated MagicDNS/HTTPS/Funnel policy
> changes and publication of the device hostname in certificate-transparency
> logs. Allow a new Telegram sendMessage call using this profile's bot token to
> deliver the form label and request URL. Passwords will pass through [TLS
> terminator/helper host] and be encrypted in [Hermes profile]'s login vault
> for [exact site/account]; saving does not itself sign in or submit a site form.

For Cloudflare also explicitly consent to credential plaintext processing at
its edge. An optional email-OTP gate would need separate email disclosure and
Telegram-webview validation; it does not replace Telegram HMAC auth.
Certificate-transparency publication persists after disabling Funnel
([Tailscale HTTPS](https://tailscale.com/docs/how-to/set-up-https-certificates)).
**Documented only: no consent is sought or ingress enabled by this spike.**

## Upstream issue draft (not filed)

**Title:** Supported model-blind vault write/elicitation contract for messaging plugins.

Problem: Telegram plugins can issue a web-app request, but the supported vault
CLI is an interactive wizard without structured acknowledgement/idempotency;
plugins must not import private vault modules or scrape terminal prompts.

Requested contract: profile-scoped login-only write through bounded stdin JSON
or a documented authenticated local API; no secret argv/env/stdout; explicit
success/failure JSON with opaque handle/status and meaningful exit code;
request-ID idempotency and status lookup after uncertain writes; documented
bot-token provisioning or Ed25519 validation guidance. Preserve redaction,
payment approval, masked elicitation and exact-origin fill guarantees. A public
gateway send API accepting restricted `web_app` markup would remove the extra
Bot API sender. Generic secret kinds require separate scope/design.

Acceptance: scratch-profile tests for encrypted persistence, wrong profile,
duplicate/uncertain write, malformed/oversize stdin, value absence from logs,
argv/tool/chat/recording and unsupported headless elicitation. If eventual
Workspace fill is requested, require an authenticated origin/tab/epoch-bound
broker API with recorder masking first; no arbitrary selector/script endpoint.

## Production size, fallback and checks

Estimate: 700–1,200 service/UI/IPC lines and 150–300 plugin/setup lines, plus
security tests and packaging; roughly 1–2 weeks **after** the vault contract,
followed by security review/live fixture QA. Ed25519 auth and direct fill add
scope. This is an engineering estimate, not evidence of production readiness.

When phone HTTPS, private launch, vault write or freshness is unavailable,
offer Workspace sign-in handback: release the tab to the human, pause snapshots
and actions, and resume only after human completion with refreshed ownership
epoch. Apply existing handback mechanics without changing CAPTCHA handling
([baseline skill `:388`](https://github.com/capthvnsen/alans-way-agents/blob/0d1f1c04e42de2e1c44474d7c5ba0c78a1f2a43d/alans-way/skills/workspace-operations/SKILL.md#L388)).
Never ask the user to paste a password into Telegram. If their computer is
unavailable, leave the request pending/expired and wait; do not fall back to
model-visible entry. Verify credential-specific recorder masking separately.

Run the fixture with `python3 prototype/secure-form/service.py`; stop with
Ctrl-C. Tests: `python3 -m unittest discover -s tests -p test_secure_form_spike.py`.
They cover valid/tampered/stale/future initData, wrong bot/user/chat/profile,
duplicate/malformed data, expiry, single use/replay/restart/concurrency,
stdin-only CLI receipt/failure/timeout, secret canaries in logs/status,
Host/Origin/type/size guards and admitted-hook payload delivery.
Browser fixture showed masked input, cleared field and “Submitted”; screenshot
capture timed out after semantic verification. No live Telegram, actual vault,
tunnel, browser fill, recorder or cross-host test was run. Full-suite and CI
results are recorded in the PR evidence and worker report.
