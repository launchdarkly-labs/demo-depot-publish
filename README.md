# Demo Depot: tools for demo owners

Everything a LaunchDarkly Solutions Engineer needs to make a demo **Demo Depot** ready, in one place. Demo Depot is the internal one-click demo catalog on AWS: https://demodepot.launchdarklydemos.com

## Get started (two minutes)

**1. The Claude skill.** In Claude Code:

```
/plugin install demo-depot --marketplace launchdarkly-labs/demo-depot-publish
```

Then, in any demo repo: *"Using the demo-depot skill, make this repo ready for Demo Depot."* The skill inventories the code, writes `demo.yaml`, the seed, `DEMO.md`, the cover and the publish workflow, and validates the result. Updates arrive automatically.

Using claude.ai instead of Claude Code? Download `demo-depot.skill` from the [latest release](https://github.com/launchdarkly-labs/demo-depot-publish/releases/latest) and add it under Settings → Skills (or ask your admin to enable it for the organization).

**2. The `ddu` CLI** (optional; Node 20+, Docker only for `ddu run`):

```bash
npm i -g https://github.com/launchdarkly-labs/demo-depot-publish/releases/latest/download/demo-depot-cli.tgz
ddu --help
```

| Command | What it does |
| --- | --- |
| `ddu validate [path]` | Same checks the depot runs at publish time |
| `ddu init --slug my-demo --owner you@launchdarkly.com` | Scaffold the depot files into a repo |
| `ddu run` | Build and run the demo locally with the depot's network layout |
| `ddu ld export --project <key>` | Turn a real LaunchDarkly project into `ld/seed.json` |
| `ddu skill install` | Copy the skill into `~/.claude/skills` for other tools |

Re-run the `npm i -g …` line to update. If npm says `EACCES` on `/usr/local/lib/node_modules`, your Node is system-wide: prefix the command with `sudo`, or give npm a user-owned prefix once (`npm config set prefix ~/.npm-global` and add `~/.npm-global/bin` to your PATH). (Releases before 0.3.0 installed the command as `dd`, which shadowed the Unix `dd` utility; upgrading replaces it with `ddu` and removes the old link.)

**2b. Let Claude drive the depot (MCP).** The plugin also registers a `demo-depot` MCP server that runs through the `ddu` CLI. Once per machine:

```bash
ddu auth login        # paste a token from the portal: Settings › API tokens
```

Then Claude can list the catalog, launch and tear down demos, watch a publish, and validate a manifest, all as you. Without the plugin: `claude mcp add demo-depot -- ddu mcp`.

No CLI? The depot is also a remote MCP server at `https://demodepot.launchdarklydemos.com/mcp`:

- **claude.ai / Claude Desktop:** Settings → Connectors → *Add custom connector*, paste the URL, then click **Allow** on the Demo Depot page that opens.
- **Claude Code:** `claude mcp add --transport http demo-depot https://demodepot.launchdarklydemos.com/mcp`, then `/mcp` to sign in.

Each connection appears under the portal's Settings › API tokens; revoke it there to disconnect.

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
