---
name: workspace-setup
description: Set up the Alan's Way Plugin after this plugin is installed: connect the user's computer (Mac, Windows PC or Linux), install the Alan's Workspace desktop app, wire the workspace browser, and bind proactivity. Use when the user asks to install, connect, onboard, or repair Alan's Way.
---

# Workspace setup

This plugin is the piece that runs inside Hermes. Alan's Workspace (the desktop app) and the
machine-to-machine setup live in a separate repo. Do not copy that app into
this plugin, and do not replace this plugin with a git checkout.

The user's computer may be a Mac (`--host-os mac`, the default), a Windows
PC (`--host-os windows`) or a Linux desktop (`--host-os linux`). The computer
Hermes runs on may be a Linux VPS, a macOS virtual machine or a Windows PC. Host scripts
differ per OS: use `connect-mac.sh` on a Mac, `connect-windows.ps1` on Windows
and `connect-linux.sh` on Linux; everything else in this skill is the same.

Browser-only setup needs stock Hermes `>= 0.21.5`. Desktop control through
`alans-way-computer` also needs `tools.computer_use.backend.ComputerUseProvider`,
introduced in Hermes commit
[`63f5e0ea45726c5d8d7d207d140613997730aab3`](https://github.com/NousResearch/hermes-agent/commit/63f5e0ea45726c5d8d7d207d140613997730aab3)
and verified in `6e7b83a2f1`. A version string alone does not establish this API.
Set `HERMES_PYTHON` to the interpreter belonging to the selected Hermes install
(`python.exe` on Windows); setup probes that interpreter with a bounded timeout.
“API absent” means the provider module/class is missing; “probe failed”,
“timed out”, or “probe unavailable” means support is unknown, so check the
interpreter/dependencies before retrying. For an absent API, offer a supported
Hermes upgrade with the user's consent, then rerun setup and
`hermes -p <profile> computer-use doctor`. Browser setup can finish meanwhile;
do not claim desktop control is ready until the provider is selected and its
doctor succeeds.

## Reviewed plugin install confirmation

For a manual/file install, Hermes scans the candidate tree before installing.
--enable does not confirm a security warning; dependency consent is separate.
If a non-interactive install stops at CAUTION, review every finding against
its exact source revision and explain the capabilities to the user. The pin
resolver starts bounded, read-only local Git commands; the SSH-forward
examples name only loopback endpoints. This candidate scans SAFE with only
MEDIUM/LOW findings; later candidates can require confirmation. Obtain
explicit consent for that reviewed tree before retrying the same identifier
and exact `--ref <40-character SHA>` with `hermes -p <profile> plugins install
<identifier> --ref <SHA> --enable --force`. `--force` confirms a caution verdict
and can replace an existing install; inspect that replacement too. It cannot
override a dangerous verdict. Stop for unknown findings or absent consent.
Never disable scanning. Review changed revisions again; setup consent alone
is neither scan confirmation nor dependency consent.

## Drive the other repo; don't reimplement it

Fetch this page and follow it for Tailscale, the Mac app, and SSH keys. Both
remotes stay pinned to the commits the catalog submission was reviewed
against: do not substitute `main` or a newer tip. This repo's clone is pinned
to the commit this install was reviewed and checked out at. A catalog install
records that sha in the profile's `plugins/.install-metadata.json`; read it,
check it out and hand it to `setup.sh` as `--repo-ref`, which hard-stops if
the clone is not at that commit: fix the checkout, never drop the flag.
Validated file:// and direct Git installs use the installer-recorded `revision`
instead. For file sources, require a Git repository with exactly one recorded
origin URL; both that URL and Git's effective fetch URL after `insteadOf` must
identify this repository, as in the aw#156 origin rules. Foreign push URLs do
not change fetch identity. Reject invalid records without tag fallback. Only
when there is no installer record (an unrecorded manual install) is the pin the
release tag matching this plugin's `version:` field in plugin.yaml (`v` + that
version): the tag must exist, and if the clone cannot resolve it the release
was never tagged, so stop and report instead of checking out `main`.

https://raw.githubusercontent.com/capthvnsen/alans-way/b9f571d7d8ef762f0a243989e3aa096171300c5e/docs/setup-prompt.md

Repo: https://github.com/capthvnsen/alans-way

The Mac app requires an Apple Silicon Mac; the Windows app requires Windows
10/11 x64. This plugin is already installed, so do not run a `setup.sh` line
from that page that omits `--skip-plugin`. Use this command instead.
`--non-interactive` means you do not wait for `setup.sh` prompts; ask the
proactivity question yourself first. The bots text on Telegram in the plugin's
texting voice by default; pass `--tone default` only when the user asked for
Hermes' own voice (they can also send `/tone default` any time). Add `--profile <name>` unless the profile
is `default`. Give `--mac-ssh` the computer's Tailscale name or IP; `setup.sh`
refuses anything else.

**Messages while working (before setup and the gateway restart).** For each
Telegram profile using this plugin, read `hermes -p <profile> config get
display.busy_input_mode` (use `-p default` for the default profile). Use the
effective value, including Hermes's defaults when no key is stored. If it is
already `steer` or `queue`, continue without asking. Preserve unknown values and
unreadable config. If it is `interrupt`, first read `hermes -p <profile> config
get skills.config.workspace-setup.busy_input_choice`. A recorded `keep-interrupt`
means the user already chose to keep it; continue without asking or rewriting
busy mode. An absent marker means ask once in plain words:
“When you message me while I'm working, should I fold it into the current task (recommended) or stop and start over?”
Explain that the choice applies to every platform in that profile and takes
effect after the current step finishes; guidance waits for the current tool
batch to return. Apply only the answered choice with the supported CLI:
`hermes -p <profile> config set display.busy_input_mode steer` for folding it
in, or `hermes -p <profile> config set display.busy_input_mode interrupt` for
stopping and starting over. Read back that key and report a failure before
continuing. Never treat silence or non-interactive runs as consent; with no
answer, leave the mode and marker untouched and continue the other setup work.
General setup or proactivity consent does not answer this question.

Use no marker for `steer`: the value itself makes this check stateless. To avoid
re-asking a user who explicitly keeps `interrupt` on every setup rerun, disclose
that you will remember that answer in this profile's `config.yaml`, then run
`hermes -p <profile> config set skills.config.workspace-setup.busy_input_choice keep-interrupt`
only after that answer and a successful mode readback. If the marker cannot be
read except for a confirmed “Config key not set” result, skip the question and
report the unknown state. If its write fails, report that the answer could not
be remembered; never invent a successful choice. This marker records only the
setup answer: never restore a mode from it or override later user changes.
The user can explicitly revisit the choice at any time, or remove the marker
with `hermes -p <profile> config unset skills.config.workspace-setup.busy_input_choice`.

**Make Telegram feel right.** Before setup and restart, for each Telegram
profile read `hermes -p <profile> config get <key>` for the leaves below and
`hermes -p <profile> config get timezone`; use `-p default` for the default.
Resolve effective platform display values in order: platform override → global value →
Telegram default → global default; read the corresponding global keys when
inherited. For memory/skill notices, use the global `display.memory_notifications`
directly; boolean `false` means `off`, and absent or null values default to `on`.
For tool progress, also read
`hermes -p <profile> config get display.tool_progress_overrides.telegram`:
platform override → legacy Telegram override → global value → Telegram default
→ global default. Absent or null legacy values inherit; unreadable or unknown
legacy values make the effective value unknown unless a valid platform override
wins. A global `off` plus legacy `all` still enables progress; after consent to
hide it, write `display.platforms.telegram.tool_progress off` through the CLI
below and re-resolve after readback. Preserve the legacy key and global value.
Preserve existing user values unless the answer explicitly includes
changing them; show current values that differ before asking. Preserve unknown
values and unreadable config: report the unknown state and skip that choice.
Only a confirmed “Config key not set” result is an absent key; null display
values inherit. Leave other global display settings and other platforms untouched.

Read `hermes -p <profile> config get skills.config.workspace-setup.telegram_feel_choice`.
A recorded `keep-current` or `chosen` means continue without asking or rewriting
presentation settings. Both presentation markers govern only that question:
perform the timezone check below even when a saved answer skips the offer.
Preserve unknown markers and unreadable config; report the unknown state.
If that marker is absent, read
`hermes -p <profile> config get skills.config.workspace-setup.busy_steer_ack_choice`.
A legacy answer of `keep-ack` or `own-ack` means continue without asking or rewriting
Telegram presentation settings unless the user explicitly revisits the choices.
Preserve unknown legacy markers and unreadable config; report the unknown state
and skip the question. These answers record consent, not desired settings:
never migrate the legacy marker automatically or restore settings from it.
An absent marker means ask once (only when both markers are confirmed absent),
as one grouped question in plain words:
“Want Telegram to show typing and my short updates, hide mechanical tool progress,
keep routine updates quiet, use plain words when work takes a while, show just
my own acknowledgment when you add something, send scheduled messages without
job IDs, hide memory/skill bookkeeping notices,
and react 👀 while working then 👍/👎 when processing succeeds/fails?
Keep your current choices, use these recommendations, or tell me which to change.”
Explain that typing and short updates are already on by default, mechanical
progress is off, routine updates have no sound (`important`; visual notifications
can still appear), and finals/approval prompts remain eligible for sound.
Plain long-work status replaces internal tool names; my own acknowledgment
comes at the next opportunity and cannot reply immediately while a tool is blocked.
Hermes' extra steer notice and scheduled-message wrapper are on by default.
Memory/skill notices default on (`off|on|verbose`); hiding them changes only
chat presentation, and background review still runs.
Hiding “💾 Memory updated / Self-improvement review” notices affects every platform
this profile uses, not only Telegram.
Reactions default off; cancellation clears 👀 and 👍 does not verify the user's goal.
Removing the scheduled-message header, job IDs and management footer is
**profile-wide**, across all delivery targets; timezone is also profile-wide.
Disclose that you will remember the answer in this profile's `config.yaml`.

| Key | Recommended value |
| --- | --- |
| `platforms.telegram.typing_indicator` | `true` |
| `display.platforms.telegram.interim_assistant_messages` | `true` |
| `display.platforms.telegram.tool_progress` | `off` |
| `display.platforms.telegram.notifications` | `important` |
| `display.platforms.telegram.long_running_notifications` | `generic` |
| `display.platforms.telegram.busy_steer_ack_enabled` | `false` |
| `display.memory_notifications` | `off` |
| `cron.wrap_response` | `false` |
| `platforms.telegram.reactions` | `true` |

A Telegram-only memory/skill notice switch isn't supported by Hermes yet.

If timezone is empty or a fixed abbreviation (MST, EST, PST, CST, UTC offsets)
rather than an IANA zone, explain “Fixed timezones do not follow daylight-saving
changes, so reminders can be an hour off.” In the grouped question, ask the user's
city; don't guess, then offer the matching IANA
zone for an explicit answer (clarify ambiguous cities). If the presentation offer
was skipped, ask only the separate timezone question. Preserve an existing IANA
zone unless the user explicitly revisits it. Never change it silently. With
no city or explicit zone answer, leave timezone untouched and
continue the other setup work. Pass only the confirmed zone to setup's
`--timezone`; if timezone is unresolved, defer the setup invocation that requires
it rather than using a guessed value.

Apply only the answered choice with the supported CLI:
`hermes -p <profile> config set <key> <answered-value>` for each chosen leaf,
writing only leaves whose effective value differs from the answered choice,
and `hermes -p <profile> config set timezone <answered-IANA-zone>` only after
that separate zone answer. Read back each changed key with `config get <key>`
and read back `timezone` if changed; re-resolve effective Telegram display values.
When hiding notices, `display.memory_notifications` must read back `off` (or
`false`); report only that stored value, not verified banner suppression.
If a presentation write fails or its readback differs, report the mismatch and
leave the marker untouched; do not claim success or undo user choices.
Remember the completed presentation answer independently of timezone: an
unresolved timezone or a failed timezone write/readback does not block the
presentation marker. Report timezone failures separately and defer setup until
its zone requirement is met. Environment overrides
(`HERMES_GATEWAY_BUSY_STEER_ACK_ENABLED`, `HERMES_TELEGRAM_NOTIFICATIONS`,
`TELEGRAM_REACTIONS`) can defeat YAML: disclose known conflicts without reading
secret/auth files or altering the environment; a CLI readback proves storage,
not live delivery. Remember `chosen` only after that answer and successful readbacks:
`hermes -p <profile> config set skills.config.workspace-setup.telegram_feel_choice chosen`.
An explicit no records `keep-current` with the same marker key and preserves
all settings. Read back the marker too and report failed writes/readbacks.
Never treat silence or non-interactive runs as consent; with no answer, leave
the settings and marker untouched and continue the other setup work.
General setup, proactivity or busy-mode consent does not answer this question.
This marker records only the setup answer: never restore settings from it or
override later user changes. The user can revisit the choice or run
`hermes -p <profile> config unset skills.config.workspace-setup.telegram_feel_choice`.
Neither `setup.sh` nor `setup-workspace.sh` writes these Telegram choices.

Verified against stock Hermes `6e7b83a2f1c093e992a8d838ed77ea320fbd8e51`:
[display defaults/resolver](https://github.com/NousResearch/hermes-agent/blob/6e7b83a2f1c093e992a8d838ed77ea320fbd8e51/gateway/display_config.py#L51),
[typing](https://github.com/NousResearch/hermes-agent/blob/6e7b83a2f1c093e992a8d838ed77ea320fbd8e51/gateway/config.py#L472),
[reactions/notifications](https://github.com/NousResearch/hermes-agent/blob/6e7b83a2f1c093e992a8d838ed77ea320fbd8e51/plugins/platforms/telegram/adapter.py#L7109),
[steer notice](https://github.com/NousResearch/hermes-agent/blob/6e7b83a2f1c093e992a8d838ed77ea320fbd8e51/gateway/run_busy.py#L893),
[memory/skill notices](https://github.com/NousResearch/hermes-agent/blob/6e7b83a2f1c093e992a8d838ed77ea320fbd8e51/gateway/run_turn_runner.py#L1289),
[cron wrapper](https://github.com/NousResearch/hermes-agent/blob/6e7b83a2f1c093e992a8d838ed77ea320fbd8e51/cron/scheduler_delivery.py#L2011).
Use the keys on that build or newer; suppressing the steer notice preserves
steering. Load changes at the already-planned gateway restart.

```sh
# Prepare a new checkout, or validate and reuse the app setup prompt's clone.
if [ ! -e ~/alans-way-agents ] && [ ! -L ~/alans-way-agents ]; then
    mkdir ~/alans-way-agents || exit 1
    git -C ~/alans-way-agents init || exit 1
    git -C ~/alans-way-agents remote add origin https://github.com/capthvnsen/alans-way-agents || exit 1
fi
# Check the destination before any fetch, including effective insteadOf rewrites.
python3 -c 'import os, subprocess, sys
path = os.path.expanduser("~/alans-way-agents")
def stop(reason):
    sys.exit("Setup checkout unavailable: " + reason + "; preserve it and resolve before retrying.")
def git(*args):
    return subprocess.run(["git", "-C", path, *args], check=True, timeout=5,
                          capture_output=True, text=True).stdout.splitlines()
try:
    if not os.path.exists(os.path.join(path, ".git")) or git("rev-parse", "--is-inside-work-tree") != ["true"]:
        stop("existing path is not a working clone")
    raw = git("config", "--get-all", "remote.origin.url")
    effective = git("remote", "get-url", "origin")
    allowed = {prefix + "capthvnsen/alans-way-agents" + suffix
               for prefix in ("https://github.com/", "git@github.com:", "ssh://git@github.com/")
               for suffix in ("", ".git")}
    if len(raw) != 1 or len(effective) != 1 or raw[0] not in allowed or effective[0] not in allowed:
        stop("origin must have one canonical recorded and effective fetch URL")
    if git("status", "--porcelain", "--untracked-files=all"):
        stop("clone has local changes or untracked files")
except (OSError, subprocess.SubprocessError):
    stop("clone inspection failed or timed out")' || exit 1
# The commit this install was reviewed and checked out at, from Hermes' own
# install record (catalog pin first, then a source-validated revision).
# Inside a profile's gateway HERMES_HOME already points at that profile's home;
# outside it, for --profile <name> read profiles/<name>/plugins/ instead.
PIN=$(python3 -c 'import json, os, re, subprocess, sys
from urllib.parse import urlsplit, unquote
home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
def stop():
    sys.exit("Setup pin unavailable: review installer metadata/source origin; do not fall back to a tag.")
try:
    rows = json.load(open(os.path.join(home, "plugins", ".install-metadata.json")))
except FileNotFoundError:
    rows = {}
except (OSError, ValueError):
    stop()
if not isinstance(rows, dict):
    stop()
row = rows.get("alans-way", {})
if not isinstance(row, dict):
    stop()
cat = row.get("catalog")
if isinstance(cat, dict):
    sha = str(cat.get("sha") or cat.get("pin") or "")
elif row.get("catalog_name"):
    sha = str(row.get("revision") or "")
elif row:
    allowed = {prefix + "capthvnsen/alans-way-agents" + suffix
               for prefix in ("https://github.com/", "git@github.com:", "ssh://git@github.com/")
               for suffix in ("", ".git")}
    source = str(row.get("source") or "")
    base, _, fragment = source.partition("#")
    if fragment not in ("", "alans-way"):
        stop()
    if base.startswith("file://"):
        url = urlsplit(base)
        path = unquote(url.path)
        if url.netloc or url.query or not os.path.isabs(path) or not os.path.exists(os.path.join(path, ".git")):
            stop()
        def git(*args):
            return subprocess.run(["git", "-C", path, *args], check=True, timeout=5,
                                  capture_output=True, text=True).stdout.splitlines()
        try:
            raw = git("config", "--get-all", "remote.origin.url")
            effective = git("remote", "get-url", "origin")
        except (OSError, subprocess.SubprocessError):
            stop()
        if len(raw) != 1 or len(effective) != 1 or raw[0] not in allowed or effective[0] not in allowed:
            stop()
    elif base not in allowed:
        stop()
    sha = str(row.get("revision") or "")
else:
    sha = ""
if row and not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
    stop()
print(sha)') || exit 1
# No installer record: the release tag is the pin. It must exist; if the checkout
# below cannot resolve it the tag was never pushed, so stop and report.
[ -n "$PIN" ] || PIN=v0.21.7
case "$PIN" in v*) FETCH_REF="refs/tags/$PIN:refs/tags/$PIN";; *) FETCH_REF="$PIN";; esac
git -C ~/alans-way-agents fetch --depth=1 origin "$FETCH_REF" || exit 1
git -C ~/alans-way-agents checkout "$PIN" || exit 1
~/alans-way-agents/setup.sh --skip-plugin \
    --repo-ref "$PIN" \
    --desktop-ref b9f571d7d8ef762f0a243989e3aa096171300c5e \
    --bot-id <numeric-telegram-bot-id> \
    --mac-ssh <user>@<host> --host-os <mac|windows|linux> \
    --timezone <IANA-zone> --non-interactive \
    --bind --proactive <yes|no> [--tone default] [--profile <name>] --restart
```

`setup.sh` is idempotent. Re-run it, or run `setup.sh --verify` alone, to
audit with the same profile and any browser/service skip flags. `--verify`
returns 0 for a complete local audit, 1 for failed required checks, and 2 for
a partial install (warnings or skipped browser/services); report pending
capabilities explicitly. A local audit does not verify computer-side viewing,
desktop permissions or Telegram delivery. With `--restart` it restarts the
gateway last, detached, about ten
seconds after it prints its summary. If it asks which Telegram route is the primary, pick the bot matching
the conversation you're in unless the user said otherwise: do not bind a
different bot's route silently.

**Long chats (before the gateway restart).** Hermes can prune old tool output early to reduce context buildup without another summarizer. For each Alan's Way profile, follow [the long-chat setup procedure](references/long-chats.md): report the effective compression threshold and `auxiliary.compression` route, then obtain explicit user consent before enabling pruning at 48,000 tokens with 8,000-character eligibility and 4,096-token minimum reclaim. Preserve customized values, leave `micro_compact` unchanged, and use the supported profile-scoped Hermes config CLI. Only suggest a dedicated summary model; never switch it automatically.

## Order of work

1. **Tailscale first when the two machines can't see each other.** If the VPS
   can't reach the Mac (or vice versa) and neither is on a tailnet, install
   `tailscale`/`tailscaled`, `tailscale up`, and report both tailnet addresses.
   Use the tailnet name for `--mac-ssh`, not a public IP.
2. **Telegram gateway must exist before the plugin matters.** If the script
   reports no `TELEGRAM_BOT_TOKEN`, tell the user to run
   `hermes gateway setup` → Telegram → Automatic (QR scan): that step needs a
   human holding a phone; don't work around it.
3. **SSH trust runs both ways, with pinned keys.** This host reaches the
   user's computer for the browser and the computer reaches back for its
   preview and path test, all with `BatchMode=yes` and
   `StrictHostKeyChecking=yes`. Have the human run the connect script from the
   alans-way repo on their computer with this host's address, host key and
   public key: `scripts/connect-mac.sh` on a Mac, `scripts/connect-linux.sh`
   on Linux, or `scripts/connect-windows.ps1` in an elevated PowerShell on
   Windows (it installs OpenSSH Server and sets PowerShell as the default
   shell). It prints `MAC_KEY` and `MAC_HOST_KEY` to pin here: pass them to
   `setup.sh` as `--mac-key "<MAC_KEY>"` and `--mac-host-key "<MAC_HOST_KEY>"`
   (with `--mac-ssh`). It checks that each is one plain public key line and
   adds it once; do not append pasted values to the SSH key list or
   the known-hosts list yourself. On Windows, computer-use calls run through
   the app's local API: an SSH session cannot reach the desktop: so the app
   must be running for computer control even when the PC is reachable.
   Follow the steps in the app's `docs/setup-prompt.md`. Never use
   `StrictHostKeyChecking=accept-new` or ask for a password.
4. **A Windows guest runs `setup.sh` from Git Bash.** Hermes' terminal tool
   already uses Git Bash on native Windows, so run the same command there (WSL2
   counts as Linux). It needs Node 22+, Python 3 (or `HERMES_PYTHON` pointing at
   a `python.exe`), Tailscale and Chrome or Edge. It registers Scheduled Tasks
   instead of systemd units, which start at logon, so tell the user to keep the PC
   awake and turn on automatic sign-in (`netplwiz`). Relay the OpenSSH Server lines
   it prints verbatim: they need an elevated PowerShell that only the human can open.
5. **The display stack is guided, never auto-installed.** On a Linux guest
   that means X11/VNC: if the bootstrap prints display-stack instructions,
   relay them verbatim; browser services without a display fail-loop quietly.
   A macOS guest needs no X11: `scripts/mac-guest-services.sh` installs
   launchd agents, and the user grants Accessibility and Screen Recording
   once in the VM's System Settings (cannot be scripted; TCC is
   SIP-protected).
   When a VNC server and a websockify/noVNC bridge already run on this
   host, the app's VM preview needs wiring, not packages: find the
   websockify listener (`ss -ltn`, or the supervisor's program list) and
   report `http://<this host's tailnet IP>:<its port>/vnc.html`, plus where
   the VNC password lives (the VNC server's `-PasswordFile` argument, or the
   startup config that writes it). The human pastes the URL and password
   into the app's Settings (Remote desktop connection); tell them where the
   password is, do not paste its value into chat.
   If the viewer binds **127.0.0.1 only**, that tailnet URL will fail.
   Offer a temporary SSH forward over the already paired tailnet; obtain
   explicit consent before starting it, and never change the listener or
   expose a public port automatically. Have the human run this in a terminal
   on their computer (a Linux VM with `sleep`), using their existing pinned
   VM host key and available local port 16080:

   ```sh
   ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 \
     -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=2 \
     -L 127.0.0.1:16080:127.0.0.1:<viewer-port> <vm-user>@<vm-tailnet-host> 'sleep 1800'
   ```

   It forwards only to computer loopback and ends after 30 minutes; Ctrl-C
   closes it sooner. If SSH/key trust is not ready, finish that human handoff
   first. In another terminal, verify **from the user's computer**:
   `curl --fail --connect-timeout 5 --max-time 10 http://127.0.0.1:16080/vnc.html -o /dev/null`
   (Windows: `curl.exe` and `-o NUL`). Then open that URL in the computer's
   browser and confirm the VM desktop appears. Only after both succeed, use
   `http://127.0.0.1:16080/vnc.html` in Remote desktop connection and let the
   human enter the VNC password privately. If unavailable or expired, report
   the pending handoff; do not claim preview readiness. A persistent tailnet
   listener is a separate exposure change needing separate consent and a
   computer-side check; this temporary forward does not change VM config.
6. **The gateway restart ends your own session, so it comes last.** You are
   most likely running inside this gateway. `setup.sh --restart` installs,
   binds, sets the timezone and verifies first, prints its summary, and only
   then schedules the restart, detached, about ten seconds later. As soon as
   `setup.sh` returns, send your final message to the user with the summary and
   what to check next, and start no further tool calls: the restart can cut the
   conversation off. It goes through the gateway's real owner (`hermes gateway
   restart`, or the supervisor that owns it), so never kill -9 a gateway
   mid-message. Restarting one by hand on a supervisord host: `supervisorctl
   restart` escalates SIGTERM to SIGKILL after `stopwaitsecs` (10s by default)
   and a kill mid-checkpoint corrupts the gateway's `state.db` — signal the drain
   instead (`supervisorctl signal USR1 <program>` on the program whose command
   runs `hermes gateway run`), wait for the new pid, and use `start`/`restart`
   only as fallbacks. If the restart was skipped, a check failed: say which one.
7. **Bind only after a real DM route exists.** If no routes are listed, the
   user messages the bot once, then `setup.sh --bind`. By hand:
   `hermes proactivity bind --session-key '<key>' --timezone <IANA-zone>`,
   tune with `hermes proactivity set --settings '<json>'`, and check with
   `hermes proactivity status`.
   After setup binds successfully, the same primary DM becomes Hermes' Telegram
   home channel for scheduled and cross-platform delivery. Setup uses the
   profile-scoped `config set TELEGRAM_HOME_CHANNEL` interface and clears an old
   topic with `config set TELEGRAM_HOME_CHANNEL_THREAD_ID ''`; this loads on
   gateway restart. Hermes `6e7b83a2f1` reads these settings at
   [`config_env.py:515`](https://github.com/NousResearch/hermes-agent/blob/6e7b83a2f1/gateway/config_env.py#L515).
   If you bound by hand or setup reports a home-channel failure, tell the user
   to send `/sethome` in that DM and check the confirmation before claiming
   delivery is ready.

## Moved your agent to a new VM?

The VM's address is saved in several places and they mostly do not update
each other. After a move, check each one; a stale copy fails quietly:

- **The app's Settings** on the user's computer: the VM SSH host and the
  Remote desktop URL are separate fields (`vpsBrowser.sshHost` and
  `remoteUrl` in the app's `preferences.json`, under `Hermes Workspace` in
  the app-data directory, readable over the same ssh path the workspace
  uses). Current builds re-derive the URL when it was empty or still on
  the old host; repoint it only if it was meant to follow the VM and
  stayed stale: `http://<new tailnet IP>:<websockify port>/vnc.html`. A
  URL that names the same VM differently (a MagicDNS name where the SSH
  host uses the tailnet IP) never auto-follows, so check it by eye.
- **The Hermes desktop app's saved remote**, on each computer that runs
  it: `connection.json` and `connections.json` under the `Hermes` app-data
  directory keep the old VM's URL until a new remote is saved. A stale
  entry is inert until remote mode is selected.
- **Any phone client**: the saved server URL lives only on the device; the
  user updates it there.
- **The VM's API server binding**: `API_SERVER_HOST` in the profile's private environment configuration or
  `platforms.api_server` in `config.yaml`. Pinned to the old tailnet
  address it fails to bind (`Could not bind` in `gateway.log`); `ss -tln`
  shows where it actually listens.
- **`tailscale serve` exposure**: `tailscale serve status` on the new VM;
  nothing published on the old host follows. Republish the ports the
  preview or remote mode needs.

## Report, don't claim

`setup.sh` ends with its own Verify section before the restart. Report that
output verbatim in your final message: plugin enabled, workspace browser block,
browser host state, and any FAIL lines. "Installed" means the verify output
says so, not that the commands ran without visible errors. After the gateway has
restarted (the next time the user writes to you), run `setup.sh --verify` for a
full audit of the running install. Remind the user that check-ins are on once bound and are
tuned by talking to the bot ("stop checking in" pauses them; `/proactivity resume` starts them
again), and that desktop control asks
for approval per action unless they re-run setup with `--allow-desktop-actions`
(offer that, never add it yourself: on a Hermes without the computer-use
provider API it also exposes a desktop-input tool that runs with no approval
at all). Tell the user that setup turned off Hermes'
built-in browser toolset for Telegram and cron so you use their workspace
browser, and that `--keep-browser` undoes that. Setup never turns off the
built-in `computer_use` toolset: desktop input always goes through it. If setup
warns about a `cua-driver` MCP server the user added, leave it and tell them the
`hermes -p <profile> mcp remove <name>` command from the warning.
