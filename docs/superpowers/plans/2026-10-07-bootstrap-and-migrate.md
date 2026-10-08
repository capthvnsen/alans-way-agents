# Bootstrap and migrate Implementation Plan

> **For agentic workers:** Implement task by task, test first. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship two public scripts.
- `bootstrap-orgo.sh` takes a fresh Orgo Linux computer to running Hermes plus alans-way plus Tailscale, waiting for pairing.
- `migrate.sh` moves an existing `~/.hermes` to the new computer.

**Architecture:**
- Both are plain bash, set `-euo pipefail`, and are idempotent.
- They reuse `setup.sh` for everything alans-way. Do not duplicate its logic.
- Progress goes to a JSON state file that a remote poller reads.

**Tech Stack:** bash, python3 (for JSON writes, it's already on the computer), and Python `unittest` tests that run the scripts with stubbed commands on `PATH`. Follow the pattern in `tests/test_setup_sh.py`.

## Context you need
- **Orgo computers** run Ubuntu with **supervisord and no systemd or cron**. Programs go in `/etc/supervisor/conf.d/*.conf`, followed by `supervisorctl reread && supervisorctl update`.
- **Alex's working reference computer** is reachable read-only as `ssh orgo`. Read `/etc/supervisor/conf.d/*`, `/usr/local/bin/orgo-hermes-gateway`, and how `hermes` was installed (`which hermes`, `~/.hermes`). Mirror that. Do NOT change anything on it.
- **Hermes layout:**
  - `$HERMES_HOME` defaults to `~/.hermes`.
  - The default profile is `config.yaml`, `.env`, `SOUL.md`, `auth.json`, `state.db`, `MEMORY.md` and `USER.md` at the root.
  - Other profiles live in `profiles/<name>/` with the same files.
  - Plugins are in `plugins/` and skills in `skills/`.
  - Excluded: `profiles/.deleted/`, caches, logs, venvs, `node_modules`.
- `.env` is sourced by bash in the gateway wrapper, so it must stay shell-valid.
- **Never write `ANTHROPIC_API_KEY` or `ANTHROPIC_BASE_URL`** into `.env` from these scripts.
- Commit messages are plain sentences, matching repo style, and end with `Co-Authored-By: Devin SWE-2 <noreply@cognition.ai>`.
- Never use `git stash`, never push.

## Review Focus
1. **Bootstrap re-run after a partial failure,** for example a network drop mid-install. It resumes, and it doesn't reinstall or duplicate supervisord entries.
2. **`tailscale up` printing the login URL on stderr, or after a delay.** The URL is still captured within 120 s, otherwise the state is `failed` with a clear error.
3. **Migrate from a host whose `$HERMES_HOME` isn't `~/.hermes`,** or whose paths are under `/root` against `/home/user`. All absolute paths in `config.yaml` and `profile.yaml` get rewritten.
4. **Migrate where the remote unpack fails.** The old gateway must still be running when the script exits non-zero.
5. **A profile `.env` containing quotes or spaces.** It survives byte-for-byte.

---

### Task 1: `bootstrap-orgo.sh` state file and step runner
- Flags: `--callback URL`, `--secret S`, `--id ID`, `--hermes-home`, `--repo-ref` (default `main`), and `--dry-run` (prints the commands it would run).
- Function `state <state> <step> [error]` atomically writes `/var/lib/alan/state.json` as `{state, step, error, updated_at}`. Use a tmp file plus `mv`. `ALAN_STATE_DIR` overrides the directory for tests.
- An `ERR` trap writes `state failed <step> "<last line of log>"`.
- Each step checks whether it's already done before acting.

**Tests:** the state file is written with valid JSON, the failure trap fires, and the steps run in order under `--dry-run`.

### Task 2: Install steps
1. **`hermes`:** if `hermes` isn't on PATH, install it the same way as on `ssh orgo` (document the exact installer URL found). Add a supervisord program `hermes-gateway`, mirroring Orgo's `orgo.conf` / `orgo-hermes-gateway` approach. If Orgo's own `orgo.conf` already exists, reuse it and don't add a duplicate.
2. **`alans-way`:** `curl -fsSL https://raw.githubusercontent.com/capthvnsen/alans-way-agents/<ref>/setup.sh | bash -s -- --non-interactive --repo-ref <ref>`. Read `setup.sh` first, and if it assumes systemd for the browser service, add a supervisord path there (`--skip-services` plus your own supervisord conf is acceptable).
3. **`tailscale`:** install with the official script if missing, then start `tailscaled` under supervisord (`tailscaled --state=/var/lib/tailscale/tailscaled.state --tun=userspace-networking` if `/dev/net/tun` is absent). Run `tailscale up --hostname alan-<id> --timeout=0` in the background. Grep `https://login.tailscale.com/a/[A-Za-z0-9]+` from its output for up to 120 s. If `--callback` is set, POST `{id, secret, url}` as JSON. Otherwise print it.
4. **`ready`:** set `state ready waiting_for_pairing`. A follow-up `--wait-paired` mode polls `tailscale status --json` until `BackendState=Running`, then writes the step `paired`.

**Tests:** stub `hermes`, `curl`, `tailscale`, `tailscaled` and `supervisorctl` on PATH. Cover the URL capture when it's on stderr, a re-run not duplicating conf files, and the timeout leading to `failed`.

### Task 3: `migrate.sh`
- Usage: `migrate.sh --to <ssh-host> [--hermes-home DIR] [--remote-home DIR] [--yes] [--dry-run]`.
- **Pack:** build a tar of `$HERMES_HOME` using the exclusions above, and print a manifest of profiles plus bot usernames. The bot username comes from `getMe` if `curl` works, and is skipped otherwise. Warn if any `config.yaml` has `provider: honcho`.
- **Ship:** `scp` the archive to `--to`, then over ssh: unpack into the remote home as a staging dir, rewrite absolute old-home paths to the new home in `*.yaml` (sed on exact old-prefix only), and move the staging dir into place. Back up any existing remote `~/.hermes` to `~/.hermes.pre-migrate-<ts>` first.
- **Handover:** only after the remote unpack exits 0:
  1. Stop the old gateway: try `supervisorctl stop`, `systemctl --user stop hermes-gateway`, `systemctl stop hermes-gateway` and `hermes gateway stop`, in that order. Each one may be missing.
  2. Restart the remote gateway with `supervisorctl restart`.
  3. Print a summary of which bots now run where.
- `--dry-run` prints the plan and changes nothing.

**Tests:**
- A fixture `HERMES_HOME` with 2 profiles and `.env` edge cases. Stub `ssh`/`scp` to operate on a local temp "remote".
- Assert the paths are rewritten, the excludes are respected, `.env` is byte-identical, and the old gateway is NOT stopped when the remote fails.

### Task 4: Docs
Add a "Hosted / Orgo" section to `README.md`: what bootstrap does, the DIY one-liner `curl -fsSL openalan.com/bootstrap | bash`, and the migrate one-liner `curl -fsSL openalan.com/migrate | bash -s -- --to <host>`. Run `python scripts/check_publication.py` and the full `python -m unittest discover -s tests`.
