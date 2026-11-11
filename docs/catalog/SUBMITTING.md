# Submitting the catalog re-pins

Both plugins are already listed in `NousResearch/hermes-agent/plugin-catalog/`:
`alans-way` at 0.21.9 (`0f65549`) and `alans-way-computer` at 0.21.10
(`23cce29`). Each update is its own PR, opened by the repository owner, that
changes exactly one file.

The drafts here pin `957d07fd7f93e17d38af30c6a6abbcd7bd05f4f8`, but the plugin
README disclosures they rely on land with the PR that adds this file. Pin the
main commit that includes them (step 2).

## Checklist

1. Wait until the PR that adds this file is merged into `main` of
   capthvnsen/alans-way-agents.
2. In a clean checkout of that `main`, get the full commit and re-pin both drafts:
   ```sh
   git pull && PIN=$(git rev-parse HEAD) && echo $PIN
   sed -i '' "s/957d07fd7f93e17d38af30c6a6abbcd7bd05f4f8/$PIN/g" docs/catalog/alans-way.yaml docs/catalog/alans-way-computer.yaml
   ```
   Success: `grep -c $PIN docs/catalog/alans-way*.yaml` prints 2 for each file
   (the `sha:` line and `docs_url`).
3. Check that `version` and `requires_hermes` in each draft still equal the
   plugin's `plugin.yaml` (`0.21.14`; `>=0.21.5` for alans-way, `>=0.21.6` for
   alans-way-computer). If a plugin changed after `957d07f`, its disclosures need
   another look before you submit.
4. Run the catalog CI's check on each plugin and keep the output:
   ```sh
   hermes plugins validate alans-way --install-deps
   hermes plugins validate alans-way-computer --install-deps
   ```
   Success: both end with `Validation passed.` The computer plugin warns about a
   private import; that warning is already in its known issues.
5. Open the first PR on NousResearch/hermes-agent from your fork:
   - Copy `docs/catalog/alans-way.yaml` over `plugin-catalog/alans-way.yaml`,
     then delete its first two `#` comment lines.
   - Use `docs/catalog/catalog-pr-alans-way.md` as the PR description: replace
     every `<PIN>` with the commit from step 2 and `<paste result>` with the step 4
     output.
   - Change nothing else. Leave `tier: community` as it is.
   Success: the catalog CI job goes green.
6. Open the second PR the same way, with `alans-way-computer.yaml` and
   `catalog-pr-alans-way-computer.md`.
7. Answer reviewer questions from `alans-way-disclosure.md`. If a reviewer asks
   for a change in the plugin itself, fix it in alans-way-agents, then re-pin
   (steps 2-4) in the same catalog PR.

## Grok Bot: no catalog entry

`alans-way-grok-bot/` is not a Hermes plugin. It has no `plugin.yaml` and none
of the entrypoints the catalog requires (`__init__.py`, `desktop/plugin.js`,
`plugin.json`, `dashboard/manifest.json`), so `hermes plugins validate` and
catalog CI cannot load it. It is a skill and a settings file for the Grok Bot
desktop app, which cannot load Hermes plugins. It is generated from the shared
config by `scripts/generate_grok_bot.py` and installed by hand in Grok Bot.
Hermes users already get the same shared preferences through `alans-way`. List
it only if it becomes an installable Hermes plugin; until then, its README in
this repository is the place to find it.
