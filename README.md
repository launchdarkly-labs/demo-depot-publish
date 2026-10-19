# Demo Depot: tools for demo owners

Everything a LaunchDarkly Solutions Engineer needs to make a demo **Demo Depot** ready, in one place. Demo Depot is the internal one-click demo catalog on AWS: https://demodepot.launchdarklydemos.com

## Get started (two minutes)

**1. The Claude skill.** In Claude Code:

```
/plugin install demo-depot --marketplace launchdarkly-labs/demo-depot-publish
```

Then, in any demo repo: *"Using the demo-depot skill, make this repo ready for Demo Depot."* The skill inventories the code, writes `demo.yaml`, the seed, `DEMO.md`, the cover and the publish workflow, and validates the result. Updates arrive automatically.

Using claude.ai instead of Claude Code? Download `demo-depot.skill` from the [latest release](https://github.com/launchdarkly-labs/demo-depot-publish/releases/latest) and add it under Settings → Skills (or ask your admin to enable it for the organization).

**2. The `dd` CLI** (optional; Node 20+, Docker only for `dd run`):

```bash
npm i -g https://github.com/launchdarkly-labs/demo-depot-publish/releases/latest/download/demo-depot-cli.tgz
dd --help
```

| Command | What it does |
| --- | --- |
| `dd validate [path]` | Same checks the depot runs at publish time |
| `dd init --slug my-demo --owner you@launchdarkly.com` | Scaffold the depot files into a repo |
| `dd run` | Build and run the demo locally with the depot's network layout |
| `dd ld export --project <key>` | Turn a real LaunchDarkly project into `ld/seed.json` |
| `dd skill install` | Copy the skill into `~/.claude/skills` for other tools |

Re-run the `npm i -g …` line to update.

**3. Publish.** Your repo must live in `launchdarkly-labs` or `launchdarkly-demos` (any visibility). Tag it:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

The depot builds, verifies, and lists the demo; you get a Slack DM when it's live. The full guide is in the portal under *Publish your own demo*.

## What's in this repo

| Path | Purpose |
| --- | --- |
| `.github/workflows/publish-demo.yml` | The reusable workflow demo repos call (`…/publish-demo.yml@v1`). Public so public demo repos can use it. It holds no secrets: it authenticates with GitHub OIDC and the depot's publish role only trusts tag pushes from the two orgs above. |
| `.claude-plugin/marketplace.json`, `plugins/demo-depot/` | The Claude Code plugin marketplace and the skill. |
| Releases | `demo-depot-cli.tgz` (the bundled CLI) and `demo-depot.skill` (the skill zip for claude.ai). |

Everything here is generated from the internal `ld-demodepot` repo by its `pnpm release:public` script. Don't edit it here.
