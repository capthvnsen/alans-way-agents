# Secure Form spike — do not merge or deploy

Question: can a Telegram Mini App send a login password to a fixed Hermes vault
sink without putting it into the model conversation?

Run the **offline fixture** from the repository root:

```sh
python3 prototype/secure-form/service.py
```

Open the printed loopback URL; enter **a synthetic value only**. The named form,
password field, “Save securely”, and “Submitted” exercise the interaction.
The prominent fixture notice is intentional: the fixture discards the value
and does not provide encrypted storage. Ctrl-C stops the server and removes its
temporary home. It loads no Telegram SDK, contacts no bot, and configures no
tunnel. There are no token/profile/home arguments on this demo command.

```sh
python3 -m unittest discover -s tests -p test_secure_form_spike.py
```

`service.py` contains HMAC validation, trusted private request issuance,
single-use/replay/expiry state, exact Host/Origin checks, the HTML form, a dry
Bot API `web_app` payload, and a stdin-only bridge to the public interactive
`hermes vault add --kind login` CLI. The demo points that bridge exclusively at
`fixture_vault_cli.py`. No private Hermes imports or vault file writes.

`make_server(..., public_origin="https://form.example")` describes the exact
Host/Origin contract for a future dedicated TLS proxy. It **still binds only
loopback** and does not make anything publicly reachable. The HTTP fixture test
simulates those headers locally. Non-fixture HTML reads `Telegram.WebApp.initData`
through Telegram's SDK; this mode was not run against Telegram.

The real CLI invocation, encrypted storage, private-chat launch and recorder
redaction have not been exercised. Interactive prompt compatibility is a
production blocker; do not treat the CLI fixture as proof of Hermes encryption.
See [the go/no-go assessment](../../docs/research/secure-form.md) and its upstream
issue draft before considering a production implementation.
