#!/bin/sh
# mac-watch.sh — compatibility wrapper. The host availability watcher lives in
# workspace-router.cjs (--watch), the same node script on every OS; this just
# runs it with your arguments.
#
#   mac-watch.sh [--mac-ssh USER@HOST] [--host-os mac|windows|linux]
#                [--interval SECONDS] [--hysteresis N] [--state-file PATH] [--once]
#
# Env fallbacks: HERMES_WORKSPACE_MAC_SSH, HERMES_WORKSPACE_HOST_OS,
# HERMES_MAC_STATE_FILE. Exit status 2 is a configuration error a restart
# cannot fix.
command -v node >/dev/null 2>&1 || { echo "mac-watch: node not found on PATH. Put node on this service's PATH. Not retrying." >&2; exit 2; }
exec node "$(dirname "$0")/workspace-router.cjs" --watch "$@"
