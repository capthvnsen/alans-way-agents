#!/bin/sh
# mac-watch.sh — VPS-side Mac reachability watcher.
#
# Probes the Mac over ssh on an interval and publishes a small JSON state
# file that the workspace router and the proactive observer read instead of
# probing themselves:
#
#   {"state":"online","since":"<iso>","lastSeenOnline":"<iso>","lastTransition":"<iso>"}
#
# The file is rewritten atomically (tmp + mv), only on transitions plus a
# periodic refresh so a stale mtime distinguishes a dead watcher from a
# steady state. Every transition also appends one line to mac-events.log in
# the same directory.
#
#   mac-watch.sh [--mac-ssh USER@HOST] [--interval SECONDS]
#                [--state-file PATH] [--once]
#
# Env fallbacks: HERMES_WORKSPACE_MAC_SSH, HERMES_MAC_STATE_FILE
# (default /var/lib/hermes-alans-way/mac-state.json).
set -eu

INTERVAL=30
MAC_SSH=${HERMES_WORKSPACE_MAC_SSH:-}
STATE_FILE=${HERMES_MAC_STATE_FILE:-/var/lib/hermes-alans-way/mac-state.json}
ONCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --mac-ssh) MAC_SSH="$2"; shift 2;;
    --interval) INTERVAL="$2"; shift 2;;
    --state-file) STATE_FILE="$2"; shift 2;;
    --once) ONCE=1; shift;;
    *) echo "mac-watch: unknown arg: $1" >&2; exit 2;;
  esac
done
[ -n "$MAC_SSH" ] || { echo "mac-watch: --mac-ssh (or HERMES_WORKSPACE_MAC_SSH) is required" >&2; exit 2; }
case "$INTERVAL" in
  ''|*[!0-9]*) echo "mac-watch: --interval must be a positive integer" >&2; exit 2;;
esac
[ "$INTERVAL" -ge 1 ] || { echo "mac-watch: --interval must be a positive integer" >&2; exit 2; }

STATE_DIR=$(dirname "$STATE_FILE")
EVENTS_LOG="$STATE_DIR/mac-events.log"
mkdir -p "$STATE_DIR"

iso_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

probe() {
  ssh -T -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=yes "$MAC_SSH" true
}

STATE="" SINCE="" LAST_SEEN="" LAST_TRANSITION=""
if [ -f "$STATE_FILE" ] && [ ! -L "$STATE_FILE" ]; then
  previous=$(sed -n 's/.*"state":"\([a-z]*\)".*/\1/p' "$STATE_FILE" | head -n1)
  case "$previous" in
    online|offline)
      STATE="$previous"
      SINCE=$(sed -n 's/.*"since":"\([^"]*\)".*/\1/p' "$STATE_FILE" | head -n1)
      LAST_SEEN=$(sed -n 's/.*"lastSeenOnline":"\([^"]*\)".*/\1/p' "$STATE_FILE" | head -n1)
      LAST_TRANSITION=$(sed -n 's/.*"lastTransition":"\([^"]*\)".*/\1/p' "$STATE_FILE" | head -n1)
      ;;
  esac
fi

write_state() {
  tmp="$STATE_FILE.tmp.$$"
  if [ -n "$LAST_SEEN" ]; then seen="\"$LAST_SEEN\""; else seen=null; fi
  printf '{"state":"%s","since":"%s","lastSeenOnline":%s,"lastTransition":"%s"}\n' \
    "$STATE" "$SINCE" "$seen" "$LAST_TRANSITION" > "$tmp"
  mv "$tmp" "$STATE_FILE"
}

WRITES=0
tick() {
  ts=$(iso_now)
  if probe >/dev/null 2>&1; then current=online; else current=offline; fi
  if [ "$current" != "$STATE" ]; then
    if [ "$current" = "online" ]; then LAST_SEEN="$ts"; fi
    printf '%s %s -> %s\n' "$ts" "${STATE:-unknown}" "$current" >> "$EVENTS_LOG"
    STATE="$current" SINCE="$ts" LAST_TRANSITION="$ts"
    write_state
    WRITES=0
    return
  fi
  if [ "$current" = "online" ]; then LAST_SEEN="$ts"; fi
  WRITES=$((WRITES + 1))
  if [ ! -f "$STATE_FILE" ] || [ "$WRITES" -ge 20 ]; then
    write_state
    WRITES=0
  fi
}

if [ "$ONCE" -eq 1 ]; then
  tick
  exit 0
fi
while :; do
  tick
  sleep "$INTERVAL"
done
