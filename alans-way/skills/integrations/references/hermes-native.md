# Reuse Hermes first

Verified source baseline: Hermes MIT at
[`1f6c02c07c697026888f1c66e634534fa2aae358`](https://github.com/NousResearch/hermes-agent/tree/1f6c02c07c697026888f1c66e634534fa2aae358),
descendant of `6e7b83a2f1`. This is source evidence, not the installed VM version.
Google Workspace, Himalaya and xurl are bundled skills; their external binaries
are not necessarily installed. Home Assistant and Honcho are separately
installable catalog plugins, formerly in core. Discover first; add no replacement
auth flow, Gmail MCP, home bridge or memory server.

All footprint numbers below are planning estimates excluding user data, not
benchmarks. All installation steps, including upstream wizards that install
dependencies, require consent under the parent skill.

## Recipe: Google Workspace

License: Hermes skill/Python route MIT; optional upstream gws Apache-2.0.
Footprint: existing Hermes Python route, no extra daemon; optional gws roughly
20–40 MiB disk and 20–80 MiB RAM during calls. gws is not required here.

Connect: load `google-workspace`. Resolve its script directory and use Hermes'
Python environment. In command examples, `GSETUP` and `GAPI` are shell arrays
containing that Python executable and the resolved setup.py/google_api.py path;
the bot sets these from installed skill metadata, not chat credentials.
Use `"${GSETUP[@]}" --help` to check supported flags.

At this baseline the prose describes `--services`/`--format`, but
[`setup.py:417`](https://github.com/NousResearch/hermes-agent/blob/1f6c02c07c697026888f1c66e634534fa2aae358/skills/productivity/google-workspace/scripts/setup.py#L417)
accepts neither. It requests its fixed SCOPES list, including write access.
Disclose the actual consent screen; request only needed scopes if the installed
version supports selection. If the user declines broader access, stop and offer
the supported mailbox-only/browser alternative rather than altering Hermes.

Run `"${GSETUP[@]}" --check`. If unauthenticated, follow the native Cloud project,
Desktop OAuth client and API enablement instructions; this can take several
minutes and may require an admin. The user securely transfers the downloaded
client JSON to the VM and runs the native `--client-secret` step outside the
agent session. Do not ask for JSON contents in chat.

Run `"${GSETUP[@]}" --auth-url` and send only the consent URL to Telegram.
This is link + PKCE authorization, not device-code OAuth. After phone consent,
the expected redirect to localhost port 1 fails to load. Its returned URL/code
is private: the user completes `--auth-code` in their own VM terminal using a
hidden prompt and shell variable, with shell tracing/history disabled, then
clears the variable. Do not ask them to paste the redirect in Telegram, even
though the upstream prose permits it. Without that private terminal handback,
pause; no callback receiver is shipped by this plugin.

Credential location: native setup stores `google_client_secret.json`,
`google_token.json` and pending OAuth state under the resolved profile's
`HERMES_HOME`; let Hermes manage them and refresh tokens. Optional gws uses the
existing bridge token, with no second login. External OAuth clients in Testing
can require reauthorization after seven days; explain this before scheduling.

Verify: `"${GSETUP[@]}" --check` must succeed; then one requested-service read,
for example `"${GAPI[@]}" calendar list` or `"${GAPI[@]}" contacts list --max 1`.
For mail use `gmail search "in:inbox" --max 1`; for files use a user-selected
Drive file's `drive get` metadata. These verify that scope/resource only. A
partial auth warning needs a service read, not an automatic request for all scopes.

Remove: after user approval, `"${GSETUP[@]}" --revoke`; user removes this client's
access in Google account settings if remote revocation fails, and deletes only
this profile's client/pending files privately. Pause dependent cron jobs first.

Source: [skill setup/usage](https://github.com/NousResearch/hermes-agent/blob/1f6c02c07c697026888f1c66e634534fa2aae358/skills/productivity/google-workspace/SKILL.md#L35),
[profile paths:45](https://github.com/NousResearch/hermes-agent/blob/1f6c02c07c697026888f1c66e634534fa2aae358/skills/productivity/google-workspace/scripts/setup.py#L45),
[gws token bridge:103](https://github.com/NousResearch/hermes-agent/blob/1f6c02c07c697026888f1c66e634534fa2aae358/skills/productivity/google-workspace/scripts/gws_bridge.py#L103).

## Recipe: Himalaya

License: Hermes skill MIT; Himalaya binary MIT OR Apache-2.0.
Footprint: roughly 20–50 MiB disk, 20–80 MiB RAM while invoked, no daemon.

Connect: load `himalaya` and its configuration reference. Use the existing
mailbox and supported installed v1 CLI; the bundled examples target v1.2.0.
Do not run its unpinned install script or silently upgrade to v2: v2 changes
configuration/auth. If no compatible binary exists, offer a separately reviewed
v1.2.0 binary install after consent, or Google/browser access; this router adds
no parallel mail implementation.

The user can open their provider's app-password page on their phone and complete
account configuration from a private VM terminal. Use Himalaya's existing
`backend.auth.cmd`/SMTP equivalent to retrieve the password from the user's
existing secret manager, not a literal password in config/chat. Where using
Hermes startup secret sources, declare only the mail credential in the profile's
`terminal.env_passthrough`; the auth command consumes it without output to the
model. CLI configuration goes in that profile's explicitly selected config
path, not the shared default when multiple bots use the same OS account.
No universal IMAP OAuth device flow is provided. Pause if private entry is unavailable.

Verify: `himalaya --config "$MAIL_CONFIG" --account "$MAIL_ACCOUNT" envelope list --page-size 1 --output json`.
Set both variables from the selected profile config path and account name.
This proves inbox read, not SMTP send. Use the plural `folder.aliases` syntax:
an incorrect Sent folder can fail after delivery. Never retry that send blindly.

Remove: user revokes the provider app password/OAuth grant, removes only the
selected account configuration and associated secret in private setup, and
pauses dependent jobs. Remove a binary only if installed solely for this account.

Source: [bundled skill and alias warning:30–103](https://github.com/NousResearch/hermes-agent/blob/1f6c02c07c697026888f1c66e634534fa2aae358/skills/email/himalaya/SKILL.md#L30).

## Recipe: Home Assistant

License: official Hermes adapter MIT. Footprint: roughly 1–15 MiB incremental
disk, 10–40 MiB RAM inside Hermes, excluding the user's existing HA server.

Connect: reuse installed `homeassistant`; if absent, offer the catalog install
`hermes plugins install homeassistant` after consent and review the current
catalog disclosure/compatibility. Reviewed version 2.0.1 is pinned at
`a4e311e433f1470b1fec15434deea6a05e8644eb`; stop if the offered catalog version
differs until its disclosure is reviewed. Do not install Home Assistant core.

User opens their existing HA Profile → Long-Lived Access Tokens on the phone,
creates a token and privately enters `HASS_TOKEN` into the owning profile's
`.env` or existing Hermes secret source; set `HASS_URL` to their reachable
instance. There is no device grant in this adapter. Enable its toolset through
Hermes' own configuration flow for Telegram; preserve the existing platform and
watch filters. Any required gateway reload belongs to the normal owner-approved
restart procedure, not this recipe. Existing HA access is required from the VM.

Verify: `ha_get_state(entity_id="sensor.home_temperature")` for an entity the
user selected (the entity ID here is illustrative). Tool: `ha_get_state`.
If needed Tool: `ha_list_entities` discovers available sensors. Success must
include a recent state for the intended home/entity; unknown/unavailable is not
a successful temperature report. Read-only setup does not grant actuation.

Remove: disable the toolset/plugin through Hermes, revoke this token in HA,
privately remove its secret and pause dependent cron jobs. Preserve other
platform configuration. Do not stop the user's HA server.

Source: [catalog:1](https://github.com/NousResearch/hermes-agent/blob/1f6c02c07c697026888f1c66e634534fa2aae358/plugin-catalog/homeassistant.yaml#L1),
[adapter configuration and guards:36–129](https://github.com/NousResearch/hermes-official-plugins/blob/a4e311e433f1470b1fec15434deea6a05e8644eb/homeassistant/README.md#L36).

## Recipe: Honcho

License: catalog adapter MIT; existing separately run backend AGPL-3.0.
Footprint: estimated 10–50 MiB SDK/dependencies and 20–80 MiB incremental RAM;
zero new backend instances. A fresh backend is outside this recipe.

Connect: reuse the existing provider/backend first. Honcho is now a community
catalog adapter, not a bundled core provider. Reviewed adapter 1.0.0 pin:
`e2d2aba182862deeb846e5cd4a30a41bce0ed82a`. If absent, offer the native catalog
install after consent and disclosure review, then `hermes memory setup honcho`.
The native wizard owns auth: cloud supports OAuth or a device code/link the user
can approve on their phone. Only share the display link/user code, never the
returned grant. Self-hosting uses the existing base URL and any required scoped
secret, privately entered through Hermes' setup/.env/secret source mechanism.
Do not replace an active external memory provider without explicit agreement.

Disclose before enabling: conversation turns, derived conclusions and peer/session
IDs go to the chosen Honcho API; version/OS/plugin headers are also sent. Cloud
credits are not a promise of a permanently free service.

Verify: `hermes honcho status | sed '/^[[:space:]]*Auth:/d'` after permission to
read this profile's memory. The filter removes the auth line (upstream prints a
key suffix); status attempts live peer-card reads. Inspect the
profile, enablement and actual peer-read result, not just exit zero or its final
OK: at this pin the peer-card helper catches failures internally. Confirm a
harmless fact previously stored for this profile through the installed provider's
documented recall interface. Mark connected only when the backend returns the
intended profile's result; do not print config secrets or other peers' history.

Remove: `hermes honcho disable` for this profile, then native memory setup to
choose the user's desired provider; revoke that profile's grant privately.
Preserve the backend and other profiles' data; data deletion is a separate request.

Source: [catalog data disclosure:1](https://github.com/NousResearch/hermes-agent/blob/1f6c02c07c697026888f1c66e634534fa2aae358/plugin-catalog/honcho.yaml#L1),
[native wizard:16–38](https://github.com/plastic-labs/honcho/blob/e2d2aba182862deeb846e5cd4a30a41bce0ed82a/hermes-plugin-honcho/README.md#L16).

## Recipe: X

License: Hermes xurl skill and external CLI MIT. Footprint: existing CLI only;
no new process while idle. Account/API entitlements are separate, may cost money.

Connect: load the bundled `xurl` skill; use its installed CLI and private auth
procedure. The user registers credentials and authorizes outside the agent
session, using their phone browser and a private terminal with callback access
when needed. A localhost URL on the VM is not reachable by opening it on a phone.
Do not read its `~/.xurl` store or invoke inline-secret/verbose flags. If absent,
route installation to the upstream skill with consent; this recipe adds nothing.

Verify: `xurl whoami` after `xurl auth status`; confirm the intended default app
and account. This proves identity/read reachability, not posting entitlement.

Remove: user revokes the app in X settings and removes its credential entry
privately using xurl's documented auth management; pause related jobs. Preserve
other apps/accounts. No automatic uninstall of a shared CLI.

Source: [bundled secret safety:37–57](https://github.com/NousResearch/hermes-agent/blob/1f6c02c07c697026888f1c66e634534fa2aae358/skills/social-media/xurl/SKILL.md#L37).

## Shared credential mechanisms

[Hermes configuration:62–67](https://github.com/NousResearch/hermes-agent/blob/1f6c02c07c697026888f1c66e634534fa2aae358/website/docs/user-guide/configuration.md#L62):
secrets in profile `.env`, non-secret settings in config. Existing
[secret sources and child-process scoping](https://github.com/NousResearch/hermes-agent/blob/1f6c02c07c697026888f1c66e634534fa2aae358/website/docs/user-guide/secrets/index.md#L1)
inject selected values; declare only needed variables for CLI children, never
dump them. Private files remain mode 0600, directories 0700. CLI-owned OAuth
stores remain native/profile-scoped; do not export them into chat or browser vaults.
