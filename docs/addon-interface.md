# Stable interface for add-on scripts

A private add-on script that runs on a computer right after
`bootstrap-orgo.sh` finishes can rely on the items below. They are covered
by tests in this repo (`tests/test_addon_interface.py` and the existing
`tests/test_bootstrap_orgo.py` / `tests/test_migrate.py`), and a change to
any of them is a **breaking change**: it needs a version note in the
changelog or release notes, same as any other breaking change to this repo.
Everything else, internal step names, log line wording, timing, is not
part of the interface and may change at any time.

## `bootstrap-orgo.sh` CLI

The flags below, their names and meaning, are stable:

- `--callback URL`: POST `{"id","secret","url"}` with the Tailscale login URL.
- `--secret S`: the callback's shared secret.
- `--id ID`: computer id; becomes part of the tailnet hostname.
- `--hermes-home DIR`: Hermes home directory.
- `--repo-ref REF`: the ref of this repo used for `setup.sh`.
- `--dry-run`: print the planned commands, write nothing.
- `--wait-paired`: poll until the tailnet reports the computer paired, then
  write `{state: "ready", step: "paired"}` to the status file.

Exit code `0` means the step sequence (or `--wait-paired`) finished
successfully; non-zero means it failed, and the status file's `state` is
`"failed"`. `-h`/`--help` and unknown-flag/usage errors are not guaranteed
stable text, only the non-zero exit code on a bad invocation.

## The status file

Default path `$ALAN_STATE_DIR/state.json`, default `$ALAN_STATE_DIR`
`/var/lib/alan`. A poller or an add-on may read it at any time; the file is
replaced with an atomic temp-file-plus-rename on every write, so a reader
never observes a half-written document. Bootstrap holds an exclusive
`flock` on `$ALAN_STATE_DIR/.state.lock` while it reads and replaces the
file; an add-on that writes its own key must hold the same lock and also
write through a temp file plus rename, for example
`flock "$ALAN_STATE_DIR/.state.lock" python3 my-addon-write.py`. A file
that cannot be read as a JSON object is moved to `state.json.corrupt`
rather than overwritten, and the next write notes that in `warnings`.

Keys the bootstrap itself owns and always sets on every write:

- `state`: one of `"running"`, `"ready"`, `"failed"`.
- `step`: the name of the step in progress, or the terminal step name
  (e.g. `"waiting_for_pairing"`, `"paired"`) once `state` is `"ready"`.
- `error`: the last log line when `state` is `"failed"`, otherwise `null`.
- `warnings`: a list, always present (empty by default). Add-ons and
  pollers that expect this key never need to special-case its absence.
- `updated_at`: an ISO-8601 UTC timestamp of the write.

**Merge semantics.** The bootstrap only ever sets the five keys above. Any
other top-level key already in the file, in particular a key an add-on
wrote for itself, is read back and carried forward unchanged on the next
bootstrap write. An add-on may therefore safely add its own key (e.g.
`{"addon_myservice": "installed"}`) to this file and expect the bootstrap's
own subsequent writes not to erase it. Treat the document as a flat map of
top-level keys each owner is responsible for; do not nest add-on state
under one of the bootstrap's own keys.

## The `hermes-gateway` supervisord program

`bootstrap-orgo.sh` runs the gateway under supervisord (it requires
`supervisorctl` and fails without it) and makes sure a program named
`hermes-gateway` exists and is reread/updated. It never
installs a second `[program:hermes-gateway]` section: if one is already
defined anywhere under the supervisor conf directory (default
`/etc/supervisor/conf.d`), the bootstrap reuses that file's `command=`
as long as the referenced binary exists, rather than writing a conf of
its own. Only when no conf defines the program does it write
`hermes-gateway.conf` with a generated wrapper script (reusing an
existing `orgo-hermes-gateway`-style wrapper on the host when present,
otherwise writing `alan-hermes-gateway`) and `stopwaitsecs=180`. An
add-on may rely on `supervisorctl status hermes-gateway` once the
bootstrap has finished. The 180-second drain window is guaranteed only for
a conf bootstrap wrote; a reused conf keeps its own `stopwaitsecs`, so
prefer `supervisorctl signal USR1 hermes-gateway` (drain, then restart)
over `stop`, which can end the gateway mid-checkpoint. An add-on should never write its own
`[program:hermes-gateway]` section; use `supervisorctl signal`/`stop`/
`start` on the existing one instead.

## `migrate.sh`

Moving an existing Hermes home to a new computer parks the old home at
`$HERMES_HOME.pre-migrate-<timestamp>` on the destination only when a
Hermes home already existed there, an add-on that watches for a fresh
install vs. a migrated-in one can rely on that backup directory's naming
convention to tell the two apart. The backup is a full copy of what used
to be at `$HERMES_HOME` on the destination, left in place (never deleted
automatically).

## The `HERMES_HOME` layout

Two files at the root of `$HERMES_HOME` have a stable meaning that an
add-on may depend on:

- `.env`: key=value secrets and environment overrides, owned by Hermes.
  An add-on should keep its mode at `0600` (never loosen it) and should
  never write secrets anywhere with broader permissions.
- `config.yaml`: Hermes' own configuration. An add-on should make
  configuration changes through `hermes config set <key> <value>` rather
  than editing this file directly: it keeps the file's structure and
  comments intact and is itself stable across Hermes releases in a way a
  hand-rolled YAML edit is not.

## What is *not* part of this interface

Anything not listed above, internal bash function names inside
`bootstrap-orgo.sh`/`migrate.sh`, the exact wording of log lines, the
order steps run in beyond what their names imply, supervisord conf file
names other than `hermes-gateway.conf`/`alans-way.conf`, and the private
add-on scripts themselves, may change without notice and is not covered
by the tests in this file's companion test module.
