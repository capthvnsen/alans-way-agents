# Let the agent set it up

The setup prompt lives with the app, so there is one copy to keep correct:
[alans-way/docs/setup-prompt.md](https://github.com/capthvnsen/alans-way/blob/main/docs/setup-prompt.md).
It is also in the [app README](https://github.com/capthvnsen/alans-way#connect-your-agents).

Paste it to the agent that has a terminal on the server running your Hermes
gateway (your Hermes bot itself works). It connects that server and your
computer (Mac or Windows PC) over Tailscale with pinned SSH keys in both
directions, installs the app and
this plugin through `setup.sh --non-interactive`, and proves both ends work.
It never asks for a secret; the only decisions it brings to you are the
Tailscale login, whether the bot may message you first, and installing a
display stack.

`setup.sh` is idempotent, so a run that stops halfway is safe to repeat.
