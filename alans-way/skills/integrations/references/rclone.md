# Cloud files beyond Google

## Recipe: rclone

License: MIT; keep upstream COPYING with the installed binary.
Footprint: estimated 80–150 MiB disk, 80–200 MiB RAM during bounded list/copy,
zero idle RAM. Large file lists/buffers can exceed this; exclude caches/user data.

Install: after consent, install **v1.75.2** as a separate VM toolbox executable.
Reuse a compatible existing binary without replacing it. On Linux select the
official zip for the VM architecture (amd64 or arm64) from
`https://downloads.rclone.org/v1.75.2/`, fetch that release's `SHA256SUMS`, and
verify the selected archive with the system SHA-256 tool before extraction.
Stop on a missing/mismatched checksum or architecture. Place only `rclone` and
COPYING in a dedicated version directory beneath `~/.local/share/alans-tools/`
and select its binary explicitly; do not overwrite a shared rclone or run an
unpinned curl installer. No mount, serve, sync/bisync, scheduler or daemon.

Connect: choose the provider, account and one folder with the user. Define
`RCLONE_CONFIG` as this profile's private `HERMES_HOME/integrations/rclone.conf`
and `FILES_REMOTE` as its selected non-secret remote name. Set `FILES_RESOURCE`
to the agreed full `remote:path`, including the bucket/folder, for example
`files:allowed-bucket/team folder`. Keep both values: resource probes use
`FILES_RESOURCE`; config removal uses only `FILES_REMOTE`. Create the parent
directory mode 0700; configuration mode 0600. Authentication is provider-specific,
not a universal phone device grant.

For OAuth on a phone, use the user's trusted SSH terminal app with local port
forwarding to the VM's loopback port 53682. The **user**, outside the agent
session, runs `rclone --config "$RCLONE_CONFIG" config`, chooses browser auth,
opens its local authorization URL on that same phone and completes provider
consent; the forwarded callback reaches rclone on the VM. Keep the listener
loopback-only and close the tunnel after auth. Config can display credentials,
so the bot must not capture that terminal or its output. A localhost URL sent
to a phone without the tunnel does not work. If the phone cannot forward ports,
offer the documented desktop authorize + private transfer route; pause until
available rather than asking for its token in Telegram.

For WebDAV/S3, the user supplies the provider's secret in that same private
configuration terminal, with least allowed folder/bucket permissions. Enable
rclone's config encryption from its configuration menu. Put the config password
in the owning Hermes profile's `.env` or existing secret source as
`RCLONE_CONFIG_PASS`; grant only that variable through the profile's
`terminal.env_passthrough` after explaining the grant. rclone retains its
encrypted provider tokens natively; do not copy them to a repo or Hermes memory.
The browser credential vault does not export these tokens to a CLI.

Verify: `rclone --config "$RCLONE_CONFIG" lsf "$FILES_RESOURCE" --max-depth 1 --checkers 2 --contimeout 10s --timeout 20s`.
Use the selected pinned binary's path if it is not on PATH. Confirm the selected
account with the user and one familiar folder; no recursive listing or secret
config dump. Run through the parent skill's 30-second execution bound.
Do not substitute the remote root: S3 root listing requires broader ListBuckets
permission and proves nothing about access to the selected bucket/folder.

For an approved transfer, prefer bounded `copyto` to the agreed destination,
checking overwrite explicitly, with `--transfers 1 --checkers 2 --buffer-size 8M`.
Read back destination metadata/content as appropriate; an uncertain transfer
gets reconciled before retry. Sharing/Drive permissions are separate capabilities.

Remove: pause related cron jobs; user revokes the rclone app/key at the provider,
then privately runs `rclone --config "$RCLONE_CONFIG" config delete "$FILES_REMOTE"`.
Remove only this profile's encryption password if no remaining remotes use it.
Delete the dedicated version directory only if no other profile uses that
installation. Preserve cloud files and unrelated remotes.

Sources: [release v1.75.2](https://github.com/rclone/rclone/releases/tag/v1.75.2),
[MIT license](https://github.com/rclone/rclone/blob/v1.75.2/COPYING),
[headless and tunnel setup](https://rclone.org/remote_setup/),
[encrypted config/password environment](https://rclone.org/docs/#configuration-encryption).
