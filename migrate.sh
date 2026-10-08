#!/usr/bin/env bash
# migrate.sh — move an existing Hermes home to a new computer (an Orgo-hosted
# one, or anything reachable over ssh).
#
# Pack ~/.hermes (minus caches, logs, venvs, node_modules and
# profiles/.deleted), stream it over ssh, unpack on the remote into a
# staging dir, rewrite absolute paths that pointed at the old home, swap
# it into place with a timestamped backup, and only then stop the old
# gateway so the two never poll the same bot at once.
set -eEuo pipefail

TO="" YES=0 DRY_RUN=0
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
REMOTE_HERMES=""

usage() {
    cat <<'EOF'
usage: migrate.sh --to <ssh-host> [--hermes-home DIR] [--remote-home DIR]
       [--yes] [--dry-run]

  --to HOST        ssh destination of the new computer (e.g. a tailscale name)
  --hermes-home    local Hermes home (default $HERMES_HOME or ~/.hermes)
  --remote-home    Hermes home on the new computer (default <remote $HOME>/.hermes)
  --yes            do not ask for confirmation (required when stdin is not a tty)
  --dry-run        print the plan and change nothing
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --to) TO="$2"; shift 2;;
        --hermes-home) HERMES_HOME="$2"; shift 2;;
        --remote-home) REMOTE_HERMES="$2"; shift 2;;
        --yes) YES=1; shift;;
        --dry-run) DRY_RUN=1; shift;;
        -h|--help) usage; exit 0;;
        *) echo "migrate: unknown flag: $1" >&2; usage >&2; exit 2;;
    esac
done

HERMES_HOME="${HERMES_HOME%/}"
REMOTE_HERMES="${REMOTE_HERMES%/}"

log() { printf '[migrate] %s\n' "$*"; }
die() { printf 'migrate: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

bot_token() {
    local d="$1" t=""
    if [ -f "$d/.env" ]; then
        t="$(sed -nE 's/^[[:space:]]*(export[[:space:]]+)?TELEGRAM_BOT_TOKEN=//p' "$d/.env" | tail -n 1 || true)"
        t="$(printf '%s' "$t" | sed -E 's/[[:space:]]+#.*$//' | tr -d "\"' \t")"
    fi
    if [ -z "$t" ] && [ -f "$d/config.yaml" ]; then
        t="$(grep -E '^[[:space:]]*(telegram_bot_token|bot_token):' "$d/config.yaml" 2>/dev/null \
            | head -n 1 | sed -E 's/^[^:]*:[[:space:]]*//' | tr -d "\"' \t" || true)"
    fi
    printf '%s' "$t"
}

# Bot username via getMe when curl is around; skipped silently otherwise.
# The token itself is never printed.
bot_username() {
    local token="$1" user=""
    [ -n "$token" ] && [ "$DRY_RUN" = 0 ] && have curl || { printf '%s' ""; return 0; }
    user="$(printf 'url = "https://api.telegram.org/bot%s/getMe"\n' "$token" \
        | curl -fsS --max-time 8 -K - 2>/dev/null \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["username"])' 2>/dev/null \
        || true)"
    printf '%s' "$user"
}

emit_profile() {
    local name="$1" d="$2" tok user=""
    tok="$(bot_token "$d")"
    user="$(bot_username "$tok")"
    if [ -n "$user" ]; then
        log "  - $name (telegram @$user)"
    elif [ -n "$tok" ]; then
        log "  - $name (telegram bot; username lookup skipped)"
    else
        log "  - $name (no bot token found)"
    fi
}

manifest() {
    log "profiles to migrate:"
    emit_profile "main" "$HERMES_HOME"
    local d f
    for d in "$HERMES_HOME"/profiles/*/; do
        [ -d "$d" ] || continue
        emit_profile "$(basename "$d")" "${d%/}"
    done
    for f in "$HERMES_HOME"/config.yaml "$HERMES_HOME"/profiles/*/config.yaml; do
        [ -f "$f" ] || continue
        if grep -qE 'provider:[[:space:]]*["'"'"']?honcho' "$f"; then
            log "WARNING: $f sets provider: honcho — Honcho memory is not migrated in v1"
        fi
    done
}

profile_names() {
    printf 'main'
    local d
    for d in "$HERMES_HOME"/profiles/*/; do
        [ -d "$d" ] || continue
        printf ', %s' "$(basename "$d")"
    done
}

[ -n "$TO" ] || { usage >&2; exit 2; }
[ -d "$HERMES_HOME" ] || die "no Hermes home at $HERMES_HOME"

# ssh/scp would read a leading '-' as an option (e.g. -oProxyCommand=...).
for v in "$TO" "$HERMES_HOME" "$REMOTE_HERMES"; do
    case "$v" in -*) die "arguments may not start with '-': $v";; esac
done

if [ -z "$REMOTE_HERMES" ]; then
    if [ "$DRY_RUN" = 1 ]; then
        REMOTE_HERMES='<remote-home>/.hermes'
    else
        rhome="$(ssh "$TO" 'printf %s "$HOME"' </dev/null)" \
            || die "cannot reach $TO over ssh"
        [ -n "$rhome" ] || die "remote \$HOME is empty on $TO"
        REMOTE_HERMES="$rhome/.hermes"
        case "$REMOTE_HERMES" in -*) die "remote \$HOME starts with '-': $rhome";; esac
    fi
fi
REMOTE_PARENT="$(dirname "$REMOTE_HERMES")"

manifest

if [ "$DRY_RUN" = 0 ] && [ "$YES" = 0 ]; then
    # The advertised entry is `curl | bash` — stdin is the script pipe, not
    # a terminal, so piping in skips the prompt silently. Ask on a tty,
    # otherwise require an explicit --yes.
    if [ -t 0 ]; then
        printf 'Migrate %s to %s:%s? The old gateway stops once the copy lands. [y/N] ' \
            "$HERMES_HOME" "$TO" "$REMOTE_HERMES"
        read -r reply
        case "$reply" in
            y|Y|yes|YES) ;;
            *) log "aborted"; exit 1;;
        esac
    else
        die "stdin is not a terminal — pass --yes to confirm the migration"
    fi
fi

if [ "$DRY_RUN" = 1 ]; then
    log "would pack $HERMES_HOME (excluding caches, logs, venvs, node_modules, profiles/.deleted)"
    log "would stream the archive to $TO over ssh"
    log "would park the remote gateway, unpack on $TO, rewrite $HERMES_HOME paths to $REMOTE_HERMES in *.yaml/*.yml, back up any existing remote home, and move it into place"
    log "would stop the old gateway (supervisorctl stop, systemctl --user stop, systemctl stop, hermes gateway stop — first that works) or abort"
    log "would ship a fresh sqlite snapshot, then run: ssh $TO supervisorctl start hermes-gateway (verified via status; the old gateway is restarted if it fails)"
    exit 0
fi

TS="$(date +%Y%m%d-%H%M%S)"
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/hermes-migrate.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT
ARCHIVE="$WORKDIR/hermes-$TS.tgz"

tar -czf "$ARCHIVE" -C "$HERMES_HOME" \
    --exclude='./profiles/.deleted' \
    --exclude='./cache' \
    --exclude='./logs' \
    --exclude='./log' \
    --exclude='./node_modules' \
    --exclude='./venv' \
    --exclude='./.venv' \
    --exclude='./__pycache__' \
    --exclude='*/node_modules' \
    --exclude='*/venv' \
    --exclude='*/.venv' \
    --exclude='*/__pycache__' \
    --exclude='*.log' \
    .
log "packed $HERMES_HOME"

REMOTE_ARCHIVE="$REMOTE_PARENT/$(basename "$ARCHIVE")"
# scp switched to SFTP mode in OpenSSH 9 — the remote path goes to
# sftp-server verbatim, so a %q-escaped target would land a literal
# backslash in the name. Stream the archive over ssh instead: the remote
# command uses the same %q quoting model as every other call here.
ssh "$TO" "$(printf 'mkdir -p %q && cat > %q' "$REMOTE_PARENT" "$REMOTE_ARCHIVE")" \
    <"$ARCHIVE" || die "could not copy the archive to $TO"

# Unpack on the remote into a staging dir, rewrite old-home absolute paths
# in every *.yaml, back up an existing remote home, then move into place.
# If this exits non-zero the script stops here — the old gateway stays up.
# ssh joins the command arguments with spaces and the remote shell re-parses
# them, so build one %q-escaped command string — quoting in the paths then
# survives the re-parse instead of splitting or executing.
remote_cmd="$(printf 'bash -s -- %q %q %q %q' \
    "$REMOTE_ARCHIVE" "$REMOTE_HERMES" "$HERMES_HOME" "$TS")"
ssh "$TO" "$remote_cmd" <<'REMOTE'
set -e
archive="$1"; rhermes="$2"; ohermes="$3"; ts="$4"
staging="$rhermes.staging-$ts"
backup=""

# On failure remove the debris (the staging dir, and the archive which
# contains bot tokens), and put an already-swapped-out old home back.
cleanup() {
    rc=$?
    rm -rf "$staging"
    rm -f "$archive"
    if [ -n "$backup" ] && [ ! -e "$rhermes" ]; then
        mv "$backup" "$rhermes"
    fi
    exit "$rc"
}
trap cleanup EXIT

# A bootstrapped gateway wrapper waits for config.yaml and would self-start
# the moment the swap lands, polling the bots while the old gateway is
# still up. Park it before touching anything. No supervisorctl means there
# is no parked gateway to worry about.
if command -v supervisorctl >/dev/null 2>&1; then
    supervisorctl stop hermes-gateway >/dev/null 2>&1 || true
fi

rm -rf "$staging"
mkdir -p "$staging"
tar -xzf "$archive" -C "$staging"

# Literal string replacement, not sed: '.' and '[]' in paths are live regex
# metacharacters (ahermes-backup got mangled, x[1] never matched). The home
# prefix is only assumed when BOTH hermes dirs are the conventional
# ~/.hermes, and it is replaced first — every old hermes path starts with
# the old home, so it lands directly on the new home and the hermes pass
# below never re-matches inside replaced text (no /home/u -> /home/u22).
# Replacements also stop at a path boundary — /home/u inside /home/ubuntu
# is a different directory and must be left alone.
o_home="" r_home=""
if [ "$(basename "$ohermes")" = ".hermes" ] && [ "$(basename "$rhermes")" = ".hermes" ]; then
    o_home="$(dirname "$ohermes")"
    r_home="$(dirname "$rhermes")"
    [ "$o_home" = "/" ] && o_home=""
fi

find "$staging" \( -name '*.yaml' -o -name '*.yml' \) -print0 |
while IFS= read -r -d '' f; do
    python3 - "$f" "$ohermes" "$rhermes" "$o_home" "$r_home" <<'PY'
import re
import sys

path, ohermes, rhermes, o_home, r_home = sys.argv[1:6]
with open(path, encoding="utf-8") as fh:
    text = fh.read()

def reprefix(text, old, new):
    # A match only counts as a path prefix before '/', a quote, whitespace,
    # or the end of the string — anything else is a longer name of its own.
    return re.sub(re.escape(old) + r"(?=[/'\"\s]|$)", lambda _: new, text)

if o_home and ohermes not in r_home:
    text = reprefix(text, o_home, r_home)
text = reprefix(text, ohermes, rhermes)
with open(path, "w", encoding="utf-8") as fh:
    fh.write(text)
PY
done

# Non-yaml files (.env, auth.json, plugin configs) are not rewritten —
# warn about the ones that still point at the old home instead.
find "$staging" -type f ! -name '*.yaml' ! -name '*.yml' \
    -exec grep -lIF "$ohermes" {} + |
while IFS= read -r f; do
    printf 'migrate: WARNING: %s still references %s; fix it by hand\n' "$f" "$ohermes" >&2
done

if [ -e "$rhermes" ]; then
    backup="$rhermes.pre-migrate-$ts"
    mv "$rhermes" "$backup"
fi
mv "$staging" "$rhermes"
touch "$rhermes/.migrated"
rm -f "$archive"
REMOTE

log "remote unpack and move succeeded on $TO"

# Handover: stop the old gateway only now that the new home is in place,
# and it MUST stop — starting the remote gateway while the old one still
# runs leaves both polling the same bot. Remember how to start it again in
# case the remote side never comes up.
stopped="" start_old=""
if have supervisorctl && supervisorctl stop hermes-gateway >/dev/null 2>&1; then
    stopped="supervisorctl stop hermes-gateway"
    start_old="supervisorctl start hermes-gateway"
elif have systemctl && systemctl --user stop hermes-gateway >/dev/null 2>&1; then
    stopped="systemctl --user stop hermes-gateway"
    start_old="systemctl --user start hermes-gateway"
elif have systemctl && systemctl stop hermes-gateway >/dev/null 2>&1; then
    stopped="systemctl stop hermes-gateway"
    start_old="systemctl start hermes-gateway"
elif have hermes && hermes gateway stop >/dev/null 2>&1; then
    stopped="hermes gateway stop"
    # `hermes gateway start` exists in v0.21 but only revives a gateway
    # installed as a service via `hermes gateway install` — `status`
    # answering is the check. Without it there is no restart verb, so
    # rollback must say so instead of claiming a restart that never ran.
    if hermes gateway status >/dev/null 2>&1; then
        start_old="hermes gateway start"
    fi
fi
if [ -z "$stopped" ]; then
    die "could not stop the old gateway — the copy is in place on $TO with its gateway left stopped; stop the old one, then: ssh $TO supervisorctl start hermes-gateway"
fi
log "stopped the old gateway: $stopped"

rollback() {
    log "WARNING: $1"
    if [ -n "$start_old" ]; then
        $start_old >/dev/null 2>&1 || true
        die "$1 — old gateway restarted, remote gateway left stopped"
    fi
    die "$1 — the old gateway was stopped with '$stopped' and has no verified restart verb; bring it back by hand"
}

# The archive was packed while the old gateway was live, so refresh every
# sqlite db (and its wal/shm/journal sidecars) now that it is stopped and
# quiescent — a mid-write copy of state.db is not guaranteed recoverable.
db_list="$WORKDIR/dbs.txt"
( cd "$HERMES_HOME" && find . -type f \
    \( -name '*.db' -o -name '*.db-wal' -o -name '*.db-shm' -o -name '*.db-journal' \) \
    ! -path './profiles/.deleted/*' \
    ! -path './cache/*' ! -path './logs/*' ! -path './log/*' \
    ! -path '*/node_modules/*' ! -path '*/venv/*' ! -path '*/.venv/*' \
    ) >"$db_list" || rollback "could not snapshot the databases"
if [ -s "$db_list" ]; then
    db_archive="$WORKDIR/dbs-$TS.tgz"
    tar -czf "$db_archive" -C "$HERMES_HOME" -T "$db_list" \
        || rollback "could not snapshot the databases"
    remote_db_archive="$REMOTE_HERMES/$(basename "$db_archive")"
    ssh "$TO" "$(printf 'cat > %q' "$remote_db_archive")" <"$db_archive" \
        || rollback "could not copy the database snapshot to $TO"
    ssh "$TO" "$(printf 'tar -xzf %q -C %q && rm -f %q' \
        "$remote_db_archive" "$REMOTE_HERMES" "$remote_db_archive")" </dev/null \
        || rollback "could not unpack the database snapshot on $TO"
    log "synced the quiescent database files"
fi

# Status before start: a park that did not hold leaves the remote gateway
# RUNNING — starting it again only errors, and rolling back then restarts
# the old gateway while the remote still polls the same bot. The pgrep
# fallback catches a remote gateway supervised by something other than
# supervisord (its cmdline is 'hermes gateway run ...').
remote_gateway_running() {
    ssh "$TO" supervisorctl status hermes-gateway </dev/null 2>/dev/null \
        | grep -q 'RUNNING' \
    || ssh "$TO" "pgrep -f 'hermes gatewa[y] run'" </dev/null >/dev/null 2>&1
}

if remote_gateway_running; then
    log "the gateway on $TO is already running — its park did not hold, leaving it up"
else
    ssh "$TO" supervisorctl start hermes-gateway </dev/null >/dev/null 2>&1 || true
    # A slow start or an ssh transport blip can hide a gateway that did
    # come up — retry status before declaring the remote down.
    tries=0
    until remote_gateway_running; do
        tries=$((tries + 1))
        if [ "$tries" -ge 4 ]; then
            rollback "the gateway did not come up on $TO"
        fi
        sleep 3
    done
    log "gateway running on $TO"
fi

log "done: $(profile_names) now run from $TO:$REMOTE_HERMES"
