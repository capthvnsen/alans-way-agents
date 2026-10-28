# Remote agents (any MCP client)

Another agent can use the same router, with its own bot ID, tabs and desktop
input (`HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS=1`). Hermes config is never
changed. Run the commands on the VM as the user Hermes runs as.

**SSH over Tailscale (primary).** For a client that can run a stdio command.
Put the client on your tailnet and use the VM's Tailscale name or IP as
`HOST`. Grok Bot's computer reaches the VM this way (tested Oct 26-27, 2026,
14 tools).

```sh
sh ~/.hermes/plugins/alans-way/scripts/setup-remote-agent.sh --bot-id BOT_ID --bot-name "BOT NAME" --user VM_USER
```

It creates `~/.ssh/alans-way-remote-agent-BOT_ID` (ed25519) and an
`authorized_keys` line restricted to the router (`restrict,command=...`),
copying the Mac SSH settings from the `workspace_browser` block. It prints the
client JSON (`{"command": "ssh", "args": [... "VM_USER@HOST"]}`): replace
`HOST` with the VM's address and give the client the private key file through
its own secret store; never paste it into a chat. `--print --probe` checks
`initialize` + `tools/list` locally without writing anything, and `--remove`
deletes only that bot's line.

**HTTP bridge (off by default).** For a client that cannot hold an SSH
session. `remote-agent-bridge.cjs` serves MCP over HTTP at `/mcp` and starts
one router per session with its own arguments and environment:

```sh
(umask 077; openssl rand -hex 32 > ~/.alans-way-bridge-token)
ALANS_WAY_REMOTE_BRIDGE=1 ALANS_WAY_REMOTE_BRIDGE_TOKEN_FILE=~/.alans-way-bridge-token \
  HERMES_WORKSPACE_MAC_SSH=you@your-mac HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS=1 \
  node ~/.hermes/plugins/alans-way/scripts/remote-agent-bridge.cjs --bot-id BOT_ID --bot-name "BOT NAME"
```

Take the `HERMES_*` values from the forced command `setup-remote-agent.sh
--print` shows. Client config: `{"url": "https://YOUR-PROXY/mcp", "headers":
{"Authorization": "Bearer YOUR_TOKEN"}}`.

- `ALANS_WAY_REMOTE_BRIDGE=1` is required to start it.
- `ALANS_WAY_REMOTE_BRIDGE_TOKEN_FILE` (mode 0600) or
  `ALANS_WAY_REMOTE_BRIDGE_TOKEN`: at least 32 characters. The bridge never
  logs it or passes it to the router.
- `ALANS_WAY_REMOTE_BRIDGE_HOST` (default `127.0.0.1`) accepts only loopback,
  private, tailnet or IPv6 unique-local addresses. `ALANS_WAY_REMOTE_BRIDGE_PORT`
  defaults to `8790`.
- Plain HTTP only: put a TLS proxy you control in front (for example one
  reachable only on your tailnet). The bridge never opens a public port, and
  you should decide on purpose before making it reachable from the internet.
- Limits: 1 MiB per request, 4 sessions, 15 minutes idle per session, 5 minutes
  per reply. Replies are JSON (no SSE stream), so approval prompts cannot reach
  the client: commit actions (buy, send, post...) are refused, as for any
  client without MCP elicitation.
