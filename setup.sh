#!/bin/sh
# setup.sh — one-command Alan's Way bootstrap for the host running your Hermes
# gateway (usually a VPS). Detects what's missing, installs what it can, and
# prints exact guidance for what it can't.
#
#   curl -fsSL https://raw.githubusercontent.com/capthvnsen/alans-way-agents/main/setup.sh | bash -s -- --bot-id 123456789 --mac-ssh me@mymac
#   ./setup.sh --bot-id 123456789 --mac-ssh me@mymac            # from a clone
#   ./setup.sh --verify                                       # re-check an install
#
# Flags: --bot-id ID --bot-name NAME --mac-ssh HOST --profile NAME
#        --hermes-home DIR --desktop-dir DIR --skip-browser --skip-services
#        --bind --proactive yes|no --timezone IANA --restart --non-interactive --verify
set -eu

REPO_URL="https://github.com/capthvnsen/alans-way-agents"
DESKTOP_REPO_URL="https://github.com/capthvnsen/alans-way"
PLUGIN_NAME="alans-way"

BOT_ID="" BOT_NAME="" MAC_SSH="" PROFILE="" CONFIG="" TIMEZONE="" PROACTIVE=""
HERMES_HOME="" DESKTOP_DIR=""
SKIP_BROWSER=0 SKIP_SERVICES=0 DO_BIND=0 DO_RESTART=0 NON_INTERACTIVE=0 VERIFY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --bot-id) BOT_ID="$2"; shift 2;;
    --bot-name) BOT_NAME="$2"; shift 2;;
    --mac-ssh) MAC_SSH="$2"; shift 2;;
    --profile) PROFILE="$2"; shift 2;;
    --config) CONFIG="$2"; shift 2;;
    --hermes-home) HERMES_HOME="$2"; shift 2;;
    --desktop-dir) DESKTOP_DIR="$2"; shift 2;;
    --skip-browser) SKIP_BROWSER=1; shift;;
    --skip-services) SKIP_SERVICES=1; shift;;
    --bind) DO_BIND=1; shift;;
    --proactive) PROACTIVE="$2"; shift 2;;
    --timezone) TIMEZONE="$2"; shift 2;;
    --restart) DO_RESTART=1; shift;;
    --non-interactive) NON_INTERACTIVE=1; shift;;
    --verify) VERIFY=1; shift;;
    -h|--help)
      cat <<'EOF'
setup.sh — Alan's Way bootstrap for the Hermes gateway host (usually a VPS).
  --bot-id ID      numeric Telegram bot ID that owns browser tabs
  --bot-name NAME  display name on the agent cursor
  --mac-ssh HOST   how this host reaches your Mac over ssh (Tailscale name/IP)
  --profile NAME   Hermes profile to configure (default: main config)
  --bind           bind proactivity to a Telegram DM route (prompted; with
                   --non-interactive, binds the --profile's route, default main)
  --proactive yes|no  answer "turn proactive messages on?" without a prompt
  --timezone IANA  your local zone for proactivity quiet hours, e.g. Europe/Berlin
  --restart        restart the gateway at the end without asking
  --verify         check an existing install without changing anything
  --config FILE    edit this Hermes config.yaml instead of the profile's
  --hermes-home D  Hermes home directory (default: ~/.hermes)
  --desktop-dir D  where the alans-way app checkout lives (cloned if missing)
  --skip-browser / --skip-services / --non-interactive for constrained runs
EOF
      exit 0;;
    *) echo "setup: unknown arg: $1" >&2; exit 2;;
  esac
done

[ -n "$HERMES_HOME" ] || HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
[ "$PROFILE" != default ] || PROFILE=""

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
ok()   { printf '  ok   %s\n' "$*"; }
warn() { printf '  warn %s\n' "$*"; }
skip() { printf '  skip %s\n' "$*"; }
bad()  { printf '  FAIL %s\n' "$*"; FAILS=$((FAILS + 1)); }
FAILS=0

# Agent shells often have a readable /dev/tty node but no terminal behind it;
# only an open that succeeds means a human can answer.
has_tty() { [ "$NON_INTERACTIVE" = 0 ] && { : < /dev/tty; } 2>/dev/null; }
ask() { # ask <prompt> <default> — reads /dev/tty so curl|bash still prompts
  if ! has_tty; then printf '%s' "$2"; return; fi
  printf '%s [%s] ' "$1" "$2" > /dev/tty
  read -r reply < /dev/tty || reply=""
  printf '%s' "${reply:-$2}"
}

confirm() { # confirm <prompt> — empty means no
  reply="$(ask "$1 [y/N]" "n")"
  case "$reply" in y|Y|yes) return 0;; *) return 1;; esac
}

have() { command -v "$1" >/dev/null 2>&1; }

# Resolve the plugin repo: beside this script when run from a clone, else clone.
SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo "")"
if [ -f "$SCRIPT_DIR/setup-workspace.sh" ] && [ -d "$SCRIPT_DIR/alans-way" ]; then
  REPO_DIR="$SCRIPT_DIR"
else
  REPO_DIR=""
fi

# ---------------------------------------------------------------- preflight
step "Preflight"
if ! have hermes; then
  bad "hermes not on PATH — install Hermes >= 0.21 first: https://github.com/NousResearch/hermes-agent"
else
  HERMES_V="$(hermes --version 2>/dev/null | grep -o '[0-9][0-9.]*' | head -1 || true)"
  ok "hermes ${HERMES_V:-unknown version}"
fi
have python3 || bad "python3 required"
MIN_NODE_MAJOR=18
if have node; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || true)"
  if [ -n "$NODE_MAJOR" ] && [ "$NODE_MAJOR" -ge "$MIN_NODE_MAJOR" ] 2>/dev/null; then
    ok "node $(node --version 2>/dev/null | sed 's/^v//') (>= $MIN_NODE_MAJOR required for browser connector scripts)"
  else
    bad "node $(node --version 2>/dev/null | sed 's/^v//') is below $MIN_NODE_MAJOR — upgrade Node before running setup (browser host and router scripts need fetch/AbortSignal.timeout)"
  fi
else
  bad "node not on PATH — Node $MIN_NODE_MAJOR+ required for the browser connector"
fi
[ -d "$HERMES_HOME" ] && ok "HERMES_HOME: $HERMES_HOME" || warn "HERMES_HOME $HERMES_HOME does not exist yet (created on first hermes run)"

if [ "$VERIFY" = 1 ]; then
  # --verify: report state without changing anything
  step "Install state"
  have hermes && hermes plugins list 2>/dev/null | grep -q "$PLUGIN_NAME" \
    && ok "plugin '$PLUGIN_NAME' installed" || bad "plugin '$PLUGIN_NAME' not in hermes plugins list"
  CFG_HOME="${PROFILE:+$HERMES_HOME/profiles/$PROFILE}"; CFG_HOME="${CFG_HOME:-$HERMES_HOME}"
  if have hermes; then
    # Hermes resolves presets and flow/block YAML itself; grepping the config
    # misreads both and matches other sections' telegram lists.
    TOOLS="$(hermes ${PROFILE:+-p "$PROFILE"} tools list --platform telegram 2>/dev/null || true)"
    if printf '%s\n' "$TOOLS" | grep -Eq "enabled[[:space:]]+proactivity([[:space:]]|$)"; then
      ok "proactivity toolset enabled for telegram"
    else
      bad "proactivity toolset not enabled for telegram — proactive wakes would fire but proactive_control won't be callable (run: hermes tools enable proactivity --platform telegram)"
    fi
    if printf '%s\n' "$TOOLS" | grep -Eq "enabled[[:space:]]+browser([[:space:]]|$)"; then
      warn "built-in 'browser' toolset still enabled for telegram — the agent may bypass the workspace browser (run: hermes tools disable browser --platform telegram)"
    else
      ok "built-in browser toolset disabled for telegram"
    fi
  fi
  if have hermes; then
    PSTATE="$(hermes ${PROFILE:+-p "$PROFILE"} proactivity status 2>/dev/null | python3 -c 'import json,sys
try: s=json.load(sys.stdin)
except Exception: s={}
print("bound" if s.get("route_bound") else "unbound", "on" if s.get("enabled") is True else "paused")' 2>/dev/null)"
    case "$PSTATE" in
      "bound on") ok "proactivity on for the bound primary route";;
      "bound paused") warn "proactivity bound but paused — the bot never messages first (run: hermes proactivity probe, then hermes proactivity resume)";;
      *) warn "no primary route bound — proactivity is off (run: setup.sh --bind)";;
    esac
    [ "$(hermes ${PROFILE:+-p "$PROFILE"} config get "plugins.entries.$PLUGIN_NAME.allow_gateway_injection" 2>/dev/null | tail -1)" = true ] \
      && ok "gateway injection allowed for $PLUGIN_NAME" \
      || warn "gateway injection not allowed — proactive turns are dropped (run: hermes config set plugins.entries.$PLUGIN_NAME.allow_gateway_injection true)"
  fi
  [ -f "$HERMES_HOME/hooks/$PLUGIN_NAME/handler.py" ] \
    && ok "gateway hook present" || bad "gateway hook missing at $HERMES_HOME/hooks/$PLUGIN_NAME/"
  for profile_home in "$HERMES_HOME"/profiles/*/; do
    [ -d "$profile_home" ] || continue
    [ -f "$profile_home/hooks/$PLUGIN_NAME/handler.py" ] \
      && ok "gateway hook present for $(basename "$profile_home")" \
      || warn "gateway hook missing for profile $(basename "$profile_home") — a profile-scoped startup emit cannot arm the gateway"
  done
  CONN_DIR="$HOME/.local/share/hermes-alans-way/browser"
  [ -f "$CONN_DIR/connection.json" ] && ok "browser host connection file present" \
    || warn "browser host connection file absent (browser host not started?)"
  PROFS="$HERMES_HOME ${PROFILE:+$HERMES_HOME/profiles/$PROFILE}"
  for home in $PROFS; do
    cfg="$home/config.yaml"
    if [ "$SKIP_BROWSER" = 1 ]; then
      skip "workspace_browser block in $cfg (--skip-browser)"
    elif [ -f "$cfg" ] && grep -q '>>> alans-way workspace_browser managed block >>>' "$cfg"; then
      ok "workspace_browser block in $cfg"
    elif [ -f "$cfg" ] && grep -q '^  workspace_browser:' "$cfg"; then
      bad "workspace_browser entry in $cfg is unmanaged — re-run setup to install the managed block"
    else
      bad "no workspace_browser block in $cfg"
    fi
  done
  [ "$FAILS" = 0 ] && say "setup: all required checks passed" || say "setup: $FAILS check(s) failed"
  exit "$([ "$FAILS" = 0 ] && echo 0 || echo 1)"
fi

# Fetch the repo when running via curl|bash.
if [ -z "$REPO_DIR" ]; then
  step "Fetching alans-way-agents"
  REPO_DIR="$HOME/.local/share/alans-way-agents"
  if [ -d "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" pull --ff-only -q && ok "updated $REPO_DIR" || warn "could not update $REPO_DIR — using existing checkout"
  else
    git clone -q "$REPO_URL" "$REPO_DIR" && ok "cloned to $REPO_DIR" || { bad "git clone failed"; exit 1; }
  fi
fi

derive_bot_id_from_env() {
  _env="$1"
  [ -f "$_env" ] || return 1
  _token="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$_env" 2>/dev/null | head -1 | cut -d= -f2-)"
  _token="${_token#\"}"; _token="${_token%\"}"; _token="${_token#\'}"; _token="${_token%\'}"
  case "$_token" in
    [0-9]*:*)
      BOT_ID="${_token%%:*}"
      ok "using bot id $BOT_ID from $_env (token not printed)"
      return 0;;
  esac
  return 1
}

detect_vps_timezone() {
  [ -n "$TIMEZONE" ] && return
  has_tty && return
  _tz=""
  if have timedatectl; then
    _tz="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  elif [ -f /etc/timezone ]; then
    _tz="$(tr -d ' \n' < /etc/timezone)"
  elif [ -L /etc/localtime ]; then
    _tz="$(readlink -f /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||' || true)"
  fi
  if [ -n "$_tz" ] && [ "$_tz" != "UTC" ]; then
    TIMEZONE="$_tz"
    ok "using VPS timezone $TIMEZONE for quiet hours (non-interactive)"
  fi
}

# ---------------------------------------------------------------- telegram
step "Telegram gateway"
ENV_FILE="$HERMES_HOME/.env"
if [ -n "$PROFILE" ]; then ENV_FILE="$HERMES_HOME/profiles/$PROFILE/.env"; fi
if [ -f "$ENV_FILE" ] && grep -q '^TELEGRAM_BOT_TOKEN=.\+' "$ENV_FILE" 2>/dev/null; then
  ok "TELEGRAM_BOT_TOKEN configured in $ENV_FILE"
elif [ -f "$HERMES_HOME/.env" ] && grep -q '^TELEGRAM_BOT_TOKEN=.\+' "$HERMES_HOME/.env" 2>/dev/null; then
  ok "TELEGRAM_BOT_TOKEN configured in $HERMES_HOME/.env"
else
  warn "No TELEGRAM_BOT_TOKEN found — the gateway has no bot to answer yet."
  say "  Hermes can create one without BotFather: run"
  say "      hermes gateway setup"
  say "  choose Telegram → 'Automatic' → scan the QR code in Telegram."
  if confirm "  Run 'hermes gateway setup' now?"; then
    hermes gateway setup || warn "gateway setup exited non-zero — re-run setup.sh after configuring"
  else
    say "  Skipping. Re-run setup.sh once Telegram is configured."
  fi
fi

# ---------------------------------------------------------------- plugin
step "Plugin"
if hermes plugins list 2>/dev/null | grep -q "$PLUGIN_NAME"; then
  if diff -rq -x __pycache__ "$REPO_DIR/$PLUGIN_NAME" "$HERMES_HOME/plugins/$PLUGIN_NAME" >/dev/null 2>&1; then
    ok "plugin already installed and current"
  else
    hermes plugins install --force "file://$REPO_DIR#$PLUGIN_NAME" >/dev/null 2>&1 \
      && ok "plugin updated from $REPO_DIR (restart the gateway to load it)" \
      || warn "could not update the installed plugin — run: hermes plugins install --force file://$REPO_DIR#$PLUGIN_NAME"
  fi
else
  hermes plugins install "file://$REPO_DIR#$PLUGIN_NAME" && ok "plugin installed from $REPO_DIR" \
    || { bad "plugin install failed"; exit 1; }
fi
hermes plugins enable "$PLUGIN_NAME" >/dev/null 2>&1 || true
# The control tool must be loaded into each messaging session's platform —
# plugin toolsets are skipped when the platform's saved list predates the
# plugin (recorded under known_plugin_toolsets). Enabling is idempotent.
for platform in telegram; do
  hermes tools enable proactivity --platform "$platform" >/dev/null 2>&1 \
    && ok "proactivity toolset enabled for $platform" \
    || warn "could not enable the proactivity toolset for $platform — proactive_control will not be callable in those sessions (run: hermes tools enable proactivity --platform $platform)"
  # The workspace browser replaces Hermes' built-in browser tool: leaving both
  # enabled lets the agent pick a different browser than the user's app.
  # Reversible with: hermes tools enable browser --platform $platform
  hermes tools disable browser --platform "$platform" >/dev/null 2>&1 \
    && ok "built-in browser toolset disabled for $platform (workspace browser is the browser)" \
    || warn "could not disable the built-in browser toolset for $platform — the agent may bypass the workspace browser (run: hermes tools disable browser --platform $platform)"
done

# ---------------------------------------------------------------- hook
step "Gateway hook"
mkdir -p "$HERMES_HOME/hooks"
install_hook() {
  local target="$1"
  mkdir -p "$target"
  if [ -f "$target/handler.py" ] && cmp -s "$REPO_DIR/hooks/$PLUGIN_NAME/handler.py" "$target/handler.py" \
      && cmp -s "$REPO_DIR/hooks/$PLUGIN_NAME/HOOK.yaml" "$target/HOOK.yaml"; then
    ok "hook current in $target"
  else
    cp -r "$REPO_DIR/hooks/$PLUGIN_NAME/." "$target/" && ok "hook installed to $target" \
      || bad "hook copy failed"
  fi
}
install_hook "$HERMES_HOME/hooks/$PLUGIN_NAME"
# Under gateway.multiplex_profiles the single gateway:startup emit can resolve
# a served profile's hooks dir instead of the launch home's — an empty profile
# hooks dir silently leaves the gateway unarmed. Seed every profile so any
# scope the emit lands in still stamps the owner marker.
for profile_home in "$HERMES_HOME"/profiles/*/; do
  [ -d "$profile_home" ] || continue
  install_hook "$profile_home/hooks/$PLUGIN_NAME"
done

# ------------------------------------------------------- browser host (VPS)
if [ "$SKIP_BROWSER" = 0 ]; then
  step "VPS browser host"
  [ -n "$DESKTOP_DIR" ] || DESKTOP_DIR="$([ "$(id -u)" = 0 ] && echo /opt/hermes-alans-way/browser || echo "$HOME/.local/share/hermes-alans-way/app")"
  if [ -f "$DESKTOP_DIR/desktop/scripts/browser-mcp.cjs" ]; then
    if [ -d "$DESKTOP_DIR/.git" ]; then
      OLD_LOCK="$(cksum < "$DESKTOP_DIR/desktop/package-lock.json" 2>/dev/null || true)"
      OLD_REV="$(git -C "$DESKTOP_DIR" rev-parse HEAD 2>/dev/null || true)"
      if git -C "$DESKTOP_DIR" pull --ff-only -q 2>/dev/null; then
        if [ "$OLD_REV" != "$(git -C "$DESKTOP_DIR" rev-parse HEAD)" ]; then
          BROWSER_UPDATED=1; ok "updated browser scripts in $DESKTOP_DIR"
          [ "$OLD_LOCK" = "$(cksum < "$DESKTOP_DIR/desktop/package-lock.json")" ] \
            || rm -rf "$DESKTOP_DIR/desktop/node_modules"
        else
          ok "browser scripts at $DESKTOP_DIR are current"
        fi
      else
        warn "could not update $DESKTOP_DIR (local changes?) — using it as is"
      fi
    else
      warn "browser scripts at $DESKTOP_DIR are not a git checkout, so setup can't update them — move it aside and re-run to reinstall"
    fi
  else
    mkdir -p "$(dirname "$DESKTOP_DIR")"
    SIBLING=""
    for d in "$SCRIPT_DIR/../alans-way" "$SCRIPT_DIR/../hermes-companion"; do
      [ -d "$d/desktop/scripts" ] && { SIBLING="$d"; break; }
    done
    if [ -n "$SIBLING" ]; then
      mkdir -p "$DESKTOP_DIR"
      cp -R "$SIBLING/desktop" "$DESKTOP_DIR/" && ok "copied desktop checkout to $DESKTOP_DIR"
    else
      rm -rf "$DESKTOP_DIR.tmp"
      git clone -q --depth 1 "$DESKTOP_REPO_URL" "$DESKTOP_DIR.tmp" \
        && mv "$DESKTOP_DIR.tmp" "$DESKTOP_DIR" && ok "cloned companion repo to $DESKTOP_DIR" \
        || { rm -rf "$DESKTOP_DIR.tmp"; warn "could not fetch desktop repo — browser host skipped"; }
    fi
  fi
  if [ -f "$DESKTOP_DIR/desktop/scripts/browser-mcp.cjs" ] && [ ! -d "$DESKTOP_DIR/desktop/node_modules/@modelcontextprotocol" ]; then
    say "  installing connector dependencies (npm ci --omit=dev)"
    (cd "$DESKTOP_DIR/desktop" && npm ci --omit=dev --ignore-scripts >/dev/null 2>&1) \
      && ok "dependencies installed" || warn "npm ci failed — connector may not start"
  fi

  DATA_DIR="${HERMES_VPS_BROWSER_DATA:-$HOME/.local/share/hermes-alans-way/browser}"
  mkdir -p "$DATA_DIR" && chmod 700 "$DATA_DIR"
  if [ ! -f "$DATA_DIR/config.json" ]; then
    CHROMIUM="$(command -v chromium || command -v chromium-browser || command -v google-chrome || echo /snap/bin/chromium)"
    cat > "$DATA_DIR/config.json" <<EOF
{
  "port": 9465,
  "cdpUrl": "http://127.0.0.1:9223",
  "browserCommand": "$CHROMIUM",
  "browserArgs": [
    "--user-data-dir=$DATA_DIR/chromium",
    "--remote-debugging-port=9223",
    "--remote-debugging-address=127.0.0.1",
    "--no-first-run",
    "--start-maximized",
    "about:blank"
  ]
}
EOF
    chmod 600 "$DATA_DIR/config.json"
    ok "wrote $DATA_DIR/config.json (chromium: $CHROMIUM)"
  else
    ok "config.json already present"
  fi

  if [ "$SKIP_SERVICES" = 0 ] && have systemctl; then
    NODE_BIN="$(command -v node || echo /usr/bin/node)"
    UNIT_DIR="/etc/systemd/system"; SYSCTL="systemctl"; UNIT_USER="User=$(id -un)"
    if [ "$(id -u)" != 0 ] && systemctl --user list-units >/dev/null 2>&1; then
      UNIT_DIR="$HOME/.config/systemd/user"; SYSCTL="systemctl --user"; UNIT_USER=""
      mkdir -p "$UNIT_DIR"
    fi
    write_unit() { # write_unit <name> <exec> <extra>
      _f="$UNIT_DIR/$1"
      if [ -f "$_f" ]; then return 0; fi
      cat > "$_f" <<EOF
[Unit]
Description=Hermes Alan's Way $1
After=network.target

[Service]
Type=simple
$UNIT_USER
Environment=DISPLAY=:99
Environment=HERMES_VPS_BROWSER_DATA=$DATA_DIR
$3
ExecStart=$NODE_BIN $2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=$([ "$SYSCTL" = "systemctl" ] && echo multi-user.target || echo default.target)
EOF
      ok "wrote $_f"
    }
    write_unit hermes-alans-way-chromium.service "$DESKTOP_DIR/desktop/scripts/vps-chromium-host.cjs" ""
    write_unit hermes-alans-way-browser.service "$DESKTOP_DIR/desktop/scripts/vps-browser-host.cjs serve" ""
    $SYSCTL daemon-reload 2>/dev/null || true
    $SYSCTL enable --now hermes-alans-way-chromium.service hermes-alans-way-browser.service >/dev/null 2>&1 \
      && ok "browser services enabled" \
      || warn "units written but not started — start them after your X11/VNC desktop is up (needs DISPLAY=:99)"
    # Chromium keeps running so open tabs and sign-ins survive an update.
    if [ "${BROWSER_UPDATED:-0}" = 1 ]; then
      $SYSCTL restart hermes-alans-way-browser.service >/dev/null 2>&1 \
        && ok "browser host restarted on the new scripts" \
        || warn "could not restart hermes-alans-way-browser.service — restart it to load the update"
    fi
    # The observer and router read the watcher's default state file under
    # /var/lib, which only a root system unit's StateDirectory provides.
    if [ -n "$MAC_SSH" ] && [ "$SYSCTL" = "systemctl" ] && [ "$(id -u)" = 0 ]; then
      if [ ! -f "$UNIT_DIR/mac-watch.service" ]; then
        MAC_WATCH_USER="$(id -un)"
        if [ "$(id -u)" = 0 ] && [ -d "$HERMES_HOME" ]; then
          _owner=$(stat -c '%U' "$HERMES_HOME" 2>/dev/null || stat -f '%Su' "$HERMES_HOME" 2>/dev/null || true)
          if [ -n "$_owner" ] && [ "$_owner" != root ]; then
            MAC_WATCH_USER="$_owner"
          fi
        fi
        mkdir -p /etc/hermes-alans-way
        printf 'HERMES_WORKSPACE_MAC_SSH=%s\n' "$MAC_SSH" > /etc/hermes-alans-way/mac-watch.env
        cat > "$UNIT_DIR/mac-watch.service" <<EOF
[Unit]
Description=Hermes Alan's Way Mac availability watcher
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$MAC_WATCH_USER
EnvironmentFile=/etc/hermes-alans-way/mac-watch.env
ExecStart=/bin/sh $REPO_DIR/alans-way/scripts/mac-watch.sh --interval 30
Restart=always
RestartSec=5
StateDirectory=hermes-alans-way

[Install]
WantedBy=multi-user.target
EOF
        ok "wrote $UNIT_DIR/mac-watch.service"
      fi
      systemctl daemon-reload 2>/dev/null || true
      systemctl enable --now mac-watch.service >/dev/null 2>&1 \
        && ok "Mac availability watcher enabled" \
        || warn "could not start mac-watch.service — the bot won't notice the Mac going on or offline"
    elif [ -n "$MAC_SSH" ]; then
      warn "Mac availability watcher not installed (needs root + systemd) — see README 'mac-watch'"
    fi
  else
    warn "systemd unavailable or skipped — see desktop/docs/vps-browser.md in the alans-way repo for manual unit setup"
  fi
fi

# ------------------------------------------------------------- desktop prereqs (guided)
if [ "$SKIP_BROWSER" = 0 ]; then
  step "Desktop prerequisites (guided)"
  if have Xvfb || pgrep -f Xvfb >/dev/null 2>&1 || pgrep -f x11vnc >/dev/null 2>&1; then
    ok "an X display stack is present"
  else
    say "  no Xvfb/x11vnc detected — for the VPS desktop, install a display stack:"
    say "    apt-get install xvfb x11vnc websockify chromium-browser"
    say "  then start Xvfb on :99, x11vnc, and a noVNC viewer. The browser services above"
    say "  expect DISPLAY=:99. Full guide: desktop/docs/vps-browser.md in the alans-way repo."
  fi
fi

# ------------------------------------------------------------- workspace config
step "Workspace browser config"
if [ -z "$BOT_ID" ]; then
  derive_bot_id_from_env "$ENV_FILE" || derive_bot_id_from_env "$HERMES_HOME/.env" || true
fi
if [ -z "$BOT_ID" ] && has_tty; then
  BOT_ID="$(ask "  Numeric Telegram bot ID for this agent (empty to skip)" "")"
fi
if [ -n "$BOT_ID" ]; then
  set -- --bot-id "$BOT_ID"
  [ -n "$BOT_NAME" ] && set -- "$@" --bot-name "$BOT_NAME"
  [ -n "$MAC_SSH" ] && set -- "$@" --mac-ssh "$MAC_SSH"
  if [ -n "$PROFILE" ]; then set -- "$@" --profile "$PROFILE"
  elif [ -n "$CONFIG" ]; then set -- "$@" --config "$CONFIG"
  else set -- "$@" --config "$HERMES_HOME/config.yaml"; fi
  sh "$REPO_DIR/setup-workspace.sh" "$@" && ok "workspace_browser configured" || bad "setup-workspace.sh failed"
else
  say "  skipped (no --bot-id). Re-run with --bot-id <numeric-telegram-bot-id>."
fi

# ------------------------------------------------------------- gateway restart
step "Gateway restart"
GW_HINT="A running gateway holds already-imported code — restart it to load the plugin."
if [ "$DO_RESTART" = 1 ] || { has_tty && confirm "  Restart the Hermes gateway now?"; }; then
  if hermes gateway restart >/dev/null 2>&1; then
    ok "hermes gateway restart"
  elif systemctl is-active --quiet hermes-gateway 2>/dev/null; then
    systemctl restart hermes-gateway && ok "systemctl restart hermes-gateway"
  elif systemctl --user is-active --quiet hermes-gateway 2>/dev/null; then
    systemctl --user restart hermes-gateway && ok "systemctl --user restart hermes-gateway"
  elif pgrep -f "gateway run" >/dev/null 2>&1; then
    warn "a supervisor-managed gateway is running — restart it through its owner (PM/launchd), not here"
  else
    warn "no live gateway found — $GW_HINT"
  fi
else
  say "  $GW_HINT"
fi

detect_vps_timezone

# ------------------------------------------------------------- bind proactivity
step "Primary bot binding"
ROUTES="$(python3 - "$HERMES_HOME" <<'PY'
import json, sys, pathlib
home = pathlib.Path(sys.argv[1])
for idx in sorted(home.glob("sessions/sessions.json")) + sorted(home.glob("profiles/*/sessions/sessions.json")):
    try:
        data = json.loads(idx.read_text(encoding="utf-8"))
    except Exception:
        continue
    file_profile = idx.parent.parent.name if "/profiles/" in str(idx) else "default"
    for key, entry in (data.items() if isinstance(data, dict) else []):
        if (isinstance(entry, dict) and entry.get("platform") == "telegram"
                and entry.get("chat_type") == "dm" and entry.get("suspended") is not True):
            agent = key.split(":")[1] if key.count(":") >= 2 else file_profile
            print(f"{file_profile}\t{agent}\t{key}")
PY
)"
if [ -z "$ROUTES" ]; then
  say "  no Telegram DM sessions yet. Message your bot once on Telegram,"
  say "  then re-run:  setup.sh --bind${PROFILE:+ --profile $PROFILE}"
else
  say "  existing Telegram routes (pick which bot is the primary):"
  echo "$ROUTES" | python3 -c 'import sys
for i, line in enumerate(sys.stdin, 1):
    p, a, k = line.rstrip("\n").split("\t", 2)
    print(f"    [{i}] {a}  (home profile: {p})")'
  if [ "$DO_BIND" = 1 ] && ! has_tty; then
    WANT="${PROFILE:-main}"
    SEL="$(echo "$ROUTES" | awk -F '\t' -v want="$WANT" '$2 == want { print NR }')"
    if [ "$(echo "$ROUTES" | wc -l)" = 1 ]; then
      SEL=1
    elif [ "$(printf '%s\n' "$SEL" | grep -c .)" != 1 ]; then
      bad "--bind found no single Telegram DM route for profile '$WANT'. Message that bot once, or bind manually with: hermes${PROFILE:+ -p $PROFILE} proactivity bind --session-key <key>"
      SEL=""
    fi
  else
    SEL="$(ask "  Bind a primary route? [1..N/N]" "N")"
  fi
  case "$SEL" in
    ''|n|N|no) say "  skipped binding — proactivity stays paused.";;
    *[!0-9]*) warn "invalid selection — bind manually with: hermes proactivity bind --session-key <key>";;
    *) SEL_KEY="$(echo "$ROUTES" | sed -n "${SEL}p" | cut -f3)"
       SEL_PROF="$(echo "$ROUTES" | sed -n "${SEL}p" | cut -f1)"
       SEL_AGENT="$(echo "$ROUTES" | sed -n "${SEL}p" | cut -f2)"
       if [ -n "$SEL_KEY" ]; then
         # A multiplexed gateway indexes every profile's sessions at the root;
         # the route's agent segment names the profile that owns it.
         [ "$SEL_PROF" != default ] || [ ! -d "$HERMES_HOME/profiles/$SEL_AGENT" ] || SEL_PROF="$SEL_AGENT"
         if [ "$SEL_PROF" = "default" ]; then BIND_PROF=""; else BIND_PROF="-p $SEL_PROF"; fi
         if hermes $BIND_PROF proactivity bind --session-key "$SEL_KEY" >/dev/null 2>&1; then
           ok "bound primary route: $SEL_AGENT"
           if [ -n "$TIMEZONE" ]; then
             hermes $BIND_PROF proactivity configure --settings "{\"timezone\": \"$TIMEZONE\"}" >/dev/null 2>&1 \
               && ok "quiet hours use $TIMEZONE" \
               || warn "could not set timezone $TIMEZONE — quiet hours stay on the default zone"
           else
             warn "no --timezone given — quiet hours use the default zone (America/Denver)"
           fi
           # Binding always leaves policy paused; turning it on grants the gateway
           # injection permission, so it stays an explicit human choice.
           ON="${PROACTIVE:-$(ask "  Turn proactive messages on now? The bot may then message this chat first. [y/N]" "N")}"
           case "$ON" in
             y|Y|yes)
               if hermes $BIND_PROF config set "plugins.entries.$PLUGIN_NAME.allow_gateway_injection" true >/dev/null 2>&1 \
                   && hermes $BIND_PROF proactivity probe >/dev/null 2>&1 \
                   && hermes $BIND_PROF proactivity resume >/dev/null 2>&1; then
                 ok "proactivity on"
               else
                 bad "could not turn proactivity on — run: hermes $BIND_PROF proactivity probe, then hermes $BIND_PROF proactivity resume"
               fi;;
             *) say "  proactivity stays paused — turn it on later with /proactivity resume";;
           esac
         else
           bad "bind failed — run manually: hermes $BIND_PROF proactivity bind --session-key <key>"
         fi
       else
         warn "invalid selection — bind manually with: hermes proactivity bind --session-key <key>"
       fi;;
  esac
fi

# ---------------------------------------------------------------- verify
step "Verify"
have hermes && hermes plugins list 2>/dev/null | grep -q "$PLUGIN_NAME" && ok "plugin enabled" || bad "plugin missing"
if [ -n "$BOT_ID" ]; then
  CFG="$CONFIG"; [ -n "$CFG" ] || { [ -n "$PROFILE" ] && CFG="$HERMES_HOME/profiles/$PROFILE/config.yaml" || CFG="$HERMES_HOME/config.yaml"; }
  [ -f "$CFG" ] && { grep -q '>>> alans-way workspace_browser managed block >>>' "$CFG" \
    || grep -q '^  workspace_browser:' "$CFG"; } \
    && ok "workspace_browser block in $CFG" || warn "workspace_browser block not found in $CFG"
fi
[ -f "$HOME/.local/share/hermes-alans-way/browser/connection.json" ] && ok "browser host running" \
  || warn "browser host not running yet (start the service or desktop session)"

step "Done"
cat <<'EOF'
  Next:
  • On your Mac: open Hermes — Alan's Way → Settings → Agent setup → save this
    Mac's SSH address → Test agent path.
  • In Telegram: message your primary bot — /proactivity status should report
    'bound' once you've bound a route, and /proactivity resume turns it on.
  • Browser work routes to the Mac while it's reachable, else the VPS host.
EOF
[ "$FAILS" = 0 ] && exit 0 || { say "setup: $FAILS check(s) failed — see above."; exit 1; }
