# Mastodon social account

## Recipe: Mastodon.py

License: MIT. Footprint: estimated 5–20 MiB incremental dependencies and
30–80 MiB RAM during on-demand calls, zero idle RAM. Python/venv adds disk
overhead; no Mastodon server, bot daemon or callback service is installed.

Install: after consent, use a dedicated VM toolbox environment, preserving
Hermes' own Python dependencies:

```sh
python3 -m venv "$HOME/.local/share/alans-tools/mastodon-2.2.2"
"$HOME/.local/share/alans-tools/mastodon-2.2.2/bin/python" -m pip install 'Mastodon.py==2.2.2'
```

Check the package version and upstream MIT notice. This pins the main library;
pip resolves its requests/dateutil/decorator dependencies. Record resolved
versions in the VM's installation receipt, not credentials, and do not claim a
fully locked dependency graph. Native Hermes does not bundle a Mastodon helper;
the CLI here is an on-demand library call, not a fictitious MCP tool.

Connect: ask which instance and account, then send its Settings → Development
page link to the phone. The user creates a personal application with only
`read:accounts` for the identity probe plus the specific read scope needed for
the requested task. Posting later needs separately agreed `write:statuses`;
do not request follow/admin/write-all access by default. Supported instance
scopes vary; confirm them on that instance.

The user generates the application's **user** access token in that UI (an
app-only token is insufficient for account identity), then enters it privately
into the owning Hermes profile's `.env` or existing secret source as
`MASTODON_ACCESS_TOKEN`. Export non-secret `MASTODON_API_BASE_URL` in the tool's
shell to the intended HTTPS instance. A phone SSH app/user-controlled terminal
or an already supported masked secret-manager UI completes this without chat
entry. If neither is
available, pause setup; this recipe implements no OAuth callback/device grant.
Never paste a generated token/OOB authorization code into Telegram.

Explain and obtain consent for the profile's `terminal.env_passthrough` grant
of `MASTODON_ACCESS_TOKEN` to this library process. Hermes strips managed secrets
from child environments otherwise; do not read `.env` or inline a token to work
around that. The existing secret source injects it, scoped to this profile.

Verify: `"$HOME/.local/share/alans-tools/mastodon-2.2.2/bin/python" -c 'import os; from mastodon import Mastodon; m = Mastodon(api_base_url=os.environ["MASTODON_API_BASE_URL"], access_token=os.environ["MASTODON_ACCESS_TOKEN"], request_timeout=15, ratelimit_method="throw"); print(m.account_verify_credentials()["acct"])'`.
Confirm the returned account on the selected instance. Only the account handle
is printed; do not dump the full credential/account response or HTTP headers.
401/403 means revoked/missing scope; 429 means back off, not automatic retry of
a post. Identity alone does not prove timeline/search access: probe only the
requested read with its documented method before promising the task.

For posting, stage exact text, attachments, audience and content warning for
explicit approval in the live conversation. Keep it draft-only until scope and
approval are complete. A library/API call has no browser commit receipt. Return
the published URL only from a successful response; reconcile an ambiguous
response before any repeat. Use the existing web-errands gate for UI posting.
If that commit returns `declined`, `approval_timeout` or `approval_unavailable`,
never complete it through another tool, including this API. Tell the user what
is staged and let them finish. A later API post requires its own fresh explicit
approval in the live conversation; the refused UI commit grants no API approval.

Remove: user revokes this application/token in the instance's Development or
Authorized applications UI, privately removes this profile's token and
passthrough grant, and pauses dependent jobs. Remove the dedicated environment
if not shared. Preserve existing posts; deleting them is a separate request.

Sources: [v2.2.2 dependency/license manifest](https://github.com/halcy/Mastodon.py/blob/v2.2.2/pyproject.toml#L5),
[maintainer authentication guidance](https://mastodonpy.readthedocs.io/en/stable/),
[Mastodon OAuth and scopes](https://docs.joinmastodon.org/client/token/),
[Hermes child credential scoping](https://github.com/NousResearch/hermes-agent/blob/1f6c02c07c697026888f1c66e634534fa2aae358/website/docs/user-guide/secrets/index.md#L54).
