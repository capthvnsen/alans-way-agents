# Contributing

You need Python 3.11+ and Node 18+ (the router and VPS browser host scripts use fetch and AbortSignal.timeout; Electron is only for the Mac app). The tests use only the standard library, so no virtual environment or install step is needed.

```sh
git clone https://github.com/capthvnsen/alans-way-agents && cd alans-way-agents
python3 -m unittest discover -s tests -v
python3 scripts/check_publication.py
```

CI runs those two commands on every push and pull request. To try a change against a real gateway, run `./setup.sh --verify` on a Hermes `>= 0.21` host first, then `./setup.sh` from your branch; it backs up every config file it edits.

## Rules

- Keep Hermes authoritative. Use documented plugin, hook and MCP interfaces; no forks, runtime monkey-patches, direct session/database writes or private Hermes imports.
- Preserve one conversation owner. The plugin adds tools and a review loop inside the existing gateway; it never starts a second one.
- Write a failing regression test before new behavior, then implement the smallest fix. Changes to `setup-workspace.sh` need a case in `tests/test_setup_workspace.py`.
- Keep host keys checked (`StrictHostKeyChecking=yes`), timeouts bounded, and check-ins inside the user's waking hours.
- Never commit personal paths, machine IPs, Telegram IDs, credentials, transcripts or unredacted logs. Use generic placeholders; `check_publication.py` enforces the common cases.
- Pull requests must not deploy, restart gateways, or install services on anyone's host.
