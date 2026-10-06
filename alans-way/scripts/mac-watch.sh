#!/bin/sh
# mac-watch.sh — VPS-side Mac reachability watcher.
#
# Probes the user's computer on an interval and publishes a small JSON state
# file that the workspace router and the proactive observer read instead of
# probing themselves:
#
#   {"state":"online","since":"<iso>","lastSeenOnline":"<iso>","lastTransition":"<iso>"}
#
# "online" means the app answers, not just sshd: the probe is the router's own
# (workspace-router.cjs --probe): ssh in, find the connector, and check the
# app's loopback API accepts its token. A flip needs --hysteresis consecutive
# reads (default 2) so one dropped probe does not move the agent between
# machines; the pending count rides in the state file ("pending",
# "pendingCount"), so it survives --once runs and restarts.
#
# The file is rewritten atomically (tmp + mv) every tick, so a stale mtime
# distinguishes a dead watcher from a steady state — the workspace router
# only trusts an offline verdict while the file is fresh. Every transition
# also appends one line to mac-events.log in the same directory.
#
#   mac-watch.sh [--mac-ssh USER@HOST] [--host-os mac|windows|linux]
#                [--interval SECONDS] [--hysteresis N] [--state-file PATH] [--once]
#
# Env fallbacks: HERMES_WORKSPACE_MAC_SSH, HERMES_WORKSPACE_HOST_OS,
# HERMES_MAC_STATE_FILE (default /var/lib/hermes-alans-way/mac-state.json).
# Exit status 2 means a configuration error that a restart cannot fix.
set -eu

INTERVAL=30
HYSTERESIS=2
export HERMES_WORKSPACE_HOST_OS=${HERMES_WORKSPACE_HOST_OS:-mac}
MAC_SSH=${HERMES_WORKSPACE_MAC_SSH:-}
STATE_FILE=${HERMES_MAC_STATE_FILE:-/var/lib/hermes-alans-way/mac-state.json}
ONCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --mac-ssh) MAC_SSH="$2"; shift 2;;
    --interval) INTERVAL="$2"; shift 2;;
    --hysteresis) HYSTERESIS="$2"; shift 2;;
    --host-os) HERMES_WORKSPACE_HOST_OS="$2"; shift 2;;
    --state-file) STATE_FILE="$2"; shift 2;;
    --once) ONCE=1; shift;;
    *) echo "mac-watch: unknown arg: $1" >&2; exit 2;;
  esac
done
[ -n "$MAC_SSH" ] || {
  echo "mac-watch: HERMES_WORKSPACE_MAC_SSH is not set. Set it to user@host-of-your-computer (in /etc/hermes-alans-way/mac-watch.env for the systemd unit), or pass --mac-ssh. Not retrying." >&2
  exit 2
}
for n in "$INTERVAL" "$HYSTERESIS"; do
  case "$n" in
    ''|*[!0-9]*|0) echo "mac-watch: --interval and --hysteresis must be positive integers" >&2; exit 2;;
  esac
done

STATE_DIR=$(dirname "$STATE_FILE")
EVENTS_LOG="$STATE_DIR/mac-events.log"
mkdir -p "$STATE_DIR"

iso_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

ROUTER="$(dirname "$0")/workspace-router.cjs"

# Overall cap so a hung ssh can never stall the loop. macOS has no timeout(1).
limited() {
  if command -v timeout >/dev/null 2>&1; then timeout 15 "$@"; else "$@"; fi
}

probe() {
  if command -v node >/dev/null 2>&1 && [ -f "$ROUTER" ]; then
    out=$(limited node "$ROUTER" --probe --mac-ssh "$MAC_SSH") || return 1
    case "$out" in ''|vps*) return 1;; *) return 0;; esac
  fi
  # No node here: all that can be proven is that sshd answers.
  # 'echo ok' not 'true' — PowerShell (a Windows host's ssh shell) has no true.
  limited ssh -T -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=yes "$MAC_SSH" echo ok
}

STATE="" SINCE="" LAST_SEEN="" LAST_TRANSITION="" PENDING="" PENDING_N=0
if [ -f "$STATE_FILE" ] && [ ! -L "$STATE_FILE" ]; then
  previous=$(sed -n 's/.*"state":"\([a-z]*\)".*/\1/p' "$STATE_FILE" | head -n1)
  case "$previous" in
    online|offline)
      STATE="$previous"
      SINCE=$(sed -n 's/.*"since":"\([^"]*\)".*/\1/p' "$STATE_FILE" | head -n1)
      LAST_SEEN=$(sed -n 's/.*"lastSeenOnline":"\([^"]*\)".*/\1/p' "$STATE_FILE" | head -n1)
      LAST_TRANSITION=$(sed -n 's/.*"lastTransition":"\([^"]*\)".*/\1/p' "$STATE_FILE" | head -n1)
      PENDING=$(sed -n 's/.*"pending":"\([a-z]*\)".*/\1/p' "$STATE_FILE" | head -n1)
      PENDING_N=$(sed -n 's/.*"pendingCount":\([0-9]*\).*/\1/p' "$STATE_FILE" | head -n1)
      PENDING_N=${PENDING_N:-0}
      ;;
  esac
fi

write_state() {
  tmp="$STATE_FILE.tmp.$$"
  if [ -n "$LAST_SEEN" ]; then seen="\"$LAST_SEEN\""; else seen=null; fi
  if [ -n "$PENDING" ]; then
    pend=$(printf ',"pending":"%s","pendingCount":%s' "$PENDING" "$PENDING_N")
  else
    pend=""
  fi
  printf '{"state":"%s","since":"%s","lastSeenOnline":%s,"lastTransition":"%s"%s}\n' \
    "$STATE" "$SINCE" "$seen" "$LAST_TRANSITION" "$pend" > "$tmp"
  mv "$tmp" "$STATE_FILE"
}

tick() {
  ts=$(iso_now)
  if probe >/dev/null 2>&1; then current=online; LAST_SEEN="$ts"; else current=offline; fi
  if [ -n "$STATE" ] && [ "$current" != "$STATE" ]; then
    if [ "$current" = "$PENDING" ]; then PENDING_N=$((PENDING_N + 1)); else PENDING="$current"; PENDING_N=1; fi
    if [ "$PENDING_N" -lt "$HYSTERESIS" ]; then
      write_state
      return
    fi
  fi
  PENDING="" PENDING_N=0
  if [ "$current" != "$STATE" ]; then
    printf '%s %s -> %s\n' "$ts" "${STATE:-unknown}" "$current" >> "$EVENTS_LOG"
    STATE="$current" SINCE="$ts" LAST_TRANSITION="$ts"
    write_state
    return
  fi
  write_state
}

if [ "$ONCE" -eq 1 ]; then
  tick
  exit 0
fi
while :; do
  tick
  sleep "$INTERVAL"
done
