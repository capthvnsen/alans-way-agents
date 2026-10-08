#!/usr/bin/env bash
# migrate.sh — move an existing Hermes home to a new computer (an Orgo-hosted
# one, or anything reachable over ssh).
#
# Pack ~/.hermes (minus caches, logs, venvs, node_modules and
# profiles/.deleted), scp it over, unpack on the remote into a staging dir,
# rewrite absolute paths that pointed at the old home, swap it into place
# with a timestamped backup, and only then stop the old gateway so the two
# never poll the same bot at once.
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
  --yes            do not ask for confirmation
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
        t="$(sed -n 's/^[[:space:]]*TELEGRAM_BOT_TOKEN=//p' "$d/.env" | tail -n 1 || true)"
        t="$(printf '%s' "$t" | tr -d "\"' \t")"
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
    user="$(curl -fsS --max-time 8 "https://api.telegram.org/bot$token/getMe" 2>/dev/null \
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

if [ "$DRY_RUN" = 0 ] && [ "$YES" = 0 ] && [ -t 0 ]; then
    printf 'Migrate %s to %s:%s? The old gateway stops once the copy lands. [y/N] ' \
        "$HERMES_HOME" "$TO" "$REMOTE_HERMES"
    read -r reply
    case "$reply" in
        y|Y|yes|YES) ;;
        *) log "aborted"; exit 1;;
    esac
fi

if [ "$DRY_RUN" = 1 ]; then
    log "would pack $HERMES_HOME (excluding caches, logs, venvs, node_modules, profiles/.deleted)"
    log "would scp the archive to $TO:$REMOTE_PARENT/"
    log "would unpack on $TO, rewrite $HERMES_HOME paths to $REMOTE_HERMES in *.yaml, back up any existing remote home, and move it into place"
    log "would stop the old gateway (supervisorctl stop, systemctl --user stop, systemctl stop, hermes gateway stop — first that works)"
    log "would run: ssh $TO supervisorctl restart hermes-gateway"
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
scp "$ARCHIVE" "$TO:$(printf %q "$REMOTE_PARENT/")" </dev/null \
    || die "scp to $TO failed"

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
rm -rf "$staging"
mkdir -p "$staging"
tar -xzf "$archive" -C "$staging"

# Literal string replacement, not sed: '.' and '[]' in paths are live regex
# metacharacters (ahermes-backup got mangled, x[1] never matched). The home
# prefix is only assumed when BOTH hermes dirs are the conventional
# ~/.hermes, and it is replaced first — every old hermes path starts with
# the old home, so it lands directly on the new home and the hermes pass
# below never re-matches inside replaced text (no /home/u -> /home/u22).
o_home="" r_home=""
if [ "$(basename "$ohermes")" = ".hermes" ] && [ "$(basename "$rhermes")" = ".hermes" ]; then
    o_home="$(dirname "$ohermes")"
    r_home="$(dirname "$rhermes")"
    [ "$o_home" = "/" ] && o_home=""
fi

find "$staging" \( -name '*.yaml' -o -name '*.yml' \) -print0 |
while IFS= read -r -d '' f; do
    python3 - "$f" "$ohermes" "$rhermes" "$o_home" "$r_home" <<'PY'
import sys

path, ohermes, rhermes, o_home, r_home = sys.argv[1:6]
with open(path, encoding="utf-8") as fh:
    text = fh.read()
if o_home and ohermes not in r_home:
    text = text.replace(o_home, r_home)
text = text.replace(ohermes, rhermes)
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
    mv "$rhermes" "$rhermes.pre-migrate-$ts"
fi
mv "$staging" "$rhermes"
rm -f "$archive"
REMOTE

log "remote unpack and move succeeded on $TO"

# Handover: stop the old gateway only now that the new home is in place.
# Each supervisor may be missing; take the first that works, in this order.
stopped=""
if have supervisorctl && supervisorctl stop hermes-gateway >/dev/null 2>&1; then
    stopped="supervisorctl stop hermes-gateway"
elif have systemctl && systemctl --user stop hermes-gateway >/dev/null 2>&1; then
    stopped="systemctl --user stop hermes-gateway"
elif have systemctl && systemctl stop hermes-gateway >/dev/null 2>&1; then
    stopped="systemctl stop hermes-gateway"
elif have hermes && hermes gateway stop >/dev/null 2>&1; then
    stopped="hermes gateway stop"
fi
if [ -n "$stopped" ]; then
    log "stopped the old gateway: $stopped"
else
    log "WARNING: could not stop the old gateway — stop it yourself or both hosts will poll the same bot"
fi

if ssh "$TO" supervisorctl restart hermes-gateway </dev/null >/dev/null 2>&1; then
    log "restarted the gateway on $TO"
else
    log "WARNING: supervisorctl restart hermes-gateway failed on $TO — start it there yourself"
fi

log "done: $(profile_names) now run from $TO:$REMOTE_HERMES"
