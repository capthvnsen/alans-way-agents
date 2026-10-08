# Orgo system/hermes-agent template sim for bootstrap-orgo.sh / migrate.sh
# integration tests. Mirrors the real template: supervisord is PID 1 (no
# systemd, no cron, no /dev/net/tun), sshd and hermes-gateway are supervisord
# programs from Orgo's own confs, Hermes lives at /usr/local/lib/hermes-agent
# with a /usr/local/bin/hermes shim, and tailscale is installed but NOT
# running (bootstrap-orgo.sh adds the tailscaled program itself).
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Base tools both scripts and the sim need. openssh-server's postinst does
# not run under docker build, so host keys and the priv-sep dir are made
# explicitly below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        supervisor openssh-server openssh-client curl ca-certificates git \
        python3 procps iproute2 tar xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Tailscale from the official apt repo, pinned; the binaries are present but
# tailscaled is never started here — bootstrap-orgo.sh supervises it.
ARG TAILSCALE_VERSION=1.104.1
RUN curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg \
        -o /usr/share/keyrings/tailscale-archive-keyring.gpg \
    && curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list \
        -o /etc/apt/sources.list.d/tailscale.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends tailscale=${TAILSCALE_VERSION} \
    && rm -rf /var/lib/apt/lists/*

# Node 22 (setup.sh requires >= 22; Ubuntu 24.04 ships 18). Official tarball.
ARG NODE_VERSION=v22.23.3
RUN curl -fsSL "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-arm64.tar.xz" \
        | tar -xJ -C /opt \
    && ln -s "/opt/node-${NODE_VERSION}-linux-arm64/bin/node" /usr/local/bin/node \
    && ln -s "/opt/node-${NODE_VERSION}-linux-arm64/bin/npm" /usr/local/bin/npm \
    && ln -s "/opt/node-${NODE_VERSION}-linux-arm64/bin/npx" /usr/local/bin/npx

# Hermes via the official installer, the way Orgo's template has it: a git
# install at /usr/local/lib/hermes-agent. --non-interactive skips the setup
# stages; the browser/computer-use extras are left to `hermes pm install`,
# which the sim never runs. The pinned commit is the main-branch head this
# fixture was built against — install.sh evolves with the repo, so an older
# pin can fail the pm stage even though it still clones.
ARG HERMES_COMMIT=08165d58931841cee713468ae89032af7c57060a
RUN HERMES_INSTALL_DIR=/usr/local/lib/hermes-agent \
    curl -fsSL https://hermes-agent.nousresearch.com/install.sh \
        | bash -s -- --non-interactive --skip-browser --skip-computer-use \
               --dir /usr/local/lib/hermes-agent --commit ${HERMES_COMMIT}

# The real Orgo template files, at the same paths they occupy on a VM:
#   /usr/local/bin/hermes               shim -> /usr/local/lib/hermes-agent
#   /usr/local/bin/orgo-hermes-gateway  supervisord gateway launcher
#   /usr/local/bin/orgo-hermes-env      vault-secret folder for ~/.hermes/.env
#   /etc/supervisor/supervisord.conf    includes /etc/supervisor/conf.d/*.conf
#   /etc/supervisor/conf.d/orgo.conf    [program:hermes-gateway]
#   /etc/supervisor/conf.d/sshd.conf    [program:sshd]
#   /etc/ssh/sshd_config.d/00-orgo.conf key-only sshd hardening drop-in
# websockify.conf is omitted (no VNC in the sim).
COPY files/ /
RUN chmod 755 /usr/local/bin/hermes /usr/local/bin/orgo-hermes-gateway \
              /usr/local/bin/orgo-hermes-env \
    && ssh-keygen -A \
    && mkdir -p /run/sshd /var/log/orgo /var/lib/alan /var/lib/tailscale \
                /var/run/tailscale /var/log/supervisor

EXPOSE 22
CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
