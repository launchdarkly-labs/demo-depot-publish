---
name: demo-depot
description: Build LaunchDarkly SE demos that are ready to publish to Demo Depot, the one-click demo catalog on AWS. Use this skill whenever you build, scaffold, containerize, or refactor any SE or sales demo; whenever you create or edit a demo.yaml, a DEMO.md, or an ld/seed.json; whenever someone says "make this depot-ready", "publish to the depot", or "add this to Demo Depot"; and whenever you build a demo app that uses LaunchDarkly flags, AI Configs, guarded rollouts, or experiments, even if the depot is never mentioned. Without this skill, demos usually break in the depot because of build-time keys, amd64 images, hostname-based service discovery, or missing seed flags.
---

# Building depot-ready demos

Demo Depot launches a fresh, isolated copy of a demo for each SE. Every launch gets its own Fargate task, its own HTTPS URL, and its own brand-new LaunchDarkly project.

That changes how a demo has to be built. A demo that works on your laptop with a hand-configured LaunchDarkly project will often fail in the depot. This skill lists the rules that prevent that, explains why each one exists, and ends with the files to produce and a validator to run.

## Two ways in

- **Existing repo** ("make this repo depot-ready"): follow *Retrofit an existing repo* below. Change as little application code as the contract allows; the manifest adapts to the app, not the other way round.
- **New demo**: follow *Build a new demo*. Plan the story first, then build against the runtime contract from the start.

Either way the result is the same set of files (see *Files to produce*) and the same gate: `python3 scripts/validate_demo.py <repo>` with 0 errors.

## Retrofit an existing repo

1. **Inventory before you touch anything.** Run `python3 scripts/inventory_repo.py <repo> --report` (and without `--report` for JSON). It is read-only and lists: Dockerfiles and compose services (base images, exposed ports, health checks, arm64 concerns), the app's language, framework, and listen port, every env var the code reads (marking LaunchDarkly keys and secret-looking names), the LaunchDarkly SDKs in use, every flag evaluation and where its key comes from (literal, constant, or env var), AI Config calls, context attributes the code sets, and targeting hints from the README and code comments. Read the whole report. It is evidence, not decisions.
2. **Containers.** Reuse the repo's Dockerfile: `build.context` is the directory it lives in (often `.`), the ingress port is what the app actually listens on (the report's `listen`/`EXPOSE`), and `cpu`/`memory` start at 512/1024 unless the app is clearly heavier. If there is a compose file with several services, each becomes a container; they talk over `localhost`. Fix only what the contract requires: `0.0.0.0`, arm64-safe base image, a cheap health route, no secrets baked in. Point the Dockerfile `HEALTHCHECK` at the same health route. Companion shell scripts (rollout scripts, seeders) keep working as-is; the report lists the env they use separately, and names like `LD_ENVIRONMENT_KEY` are a script's, not the app's. Real-time apps (Socket.IO, SSE) work unchanged: one task per instance, no sticky sessions, and the load balancer's idle timeout is 120 s, so default heartbeats are fine.
3. **Health route.** If the report found none of `/healthz`, `/health`, `/api/health`, add `/healthz` returning 200 with no external calls. Reference it in `runtime.ingress.healthCheck` and in `verify.http`.
4. **LaunchDarkly key names.** If the code already reads `SDK_KEY`, `LAUNCHDARKLY_SDK_KEY`, or similar, don't rename the code: map it with `launchdarkly.inject` (for example `inject: { sdkKey: SDK_KEY }`). Same for client-side IDs. The report's "LaunchDarkly" env list tells you which names to map.
5. **Decide who creates each flag before you seed anything.** Read the report's "Who creates the flags" section. The seed is only for resources that must exist *before* the demo starts. A flag that the demo's own story creates live belongs **out** of the seed: the LaunchDarkly GitHub App / Release AutoPilot proposing and creating a flag on a pull request, Vega committing the wrapper, a Terraform apply, an `ldcli` or API call in a script the SE runs, an AI Config the presenter builds on stage. Pre-creating one of those breaks the demo (the App finds the key taken, the "create" beat has nothing to show). Signals: README or runbook text like "the App creates the flag", `@launchdarkly approve`, `.launchdarkly/coderefs.yaml`, `*.tf`, scripts that POST to `/api/v2/flags`, and evaluation calls whose key is a variable rather than a literal (the code is flag-agnostic on purpose). Record the decision per flag in `DEMO.md` under a "Created during the demo" table (key or pattern, created by what, at which beat), and in the seed's `createdDuringDemo` block so the validator stops warning. If the tool that creates them is bound to one specific project, the demo is a checkout demo (see below), with no seed at all. The same applies to AI Configs, segments, and metrics. When literal keys in the code were themselves added by one of those tools (a merged PR the App wrapped), they are demo-time flags too; the owner's baseline branch or tag tells you which.
6. **Flags, segments, AI Configs → the seed.** Every key in the report's literal and constant lists that you classified as pre-existing goes into `ld/seed.json`. For keys that come from an env var (the demo lets the user choose the flag), create a sensible default flag in the seed and expose the env var as a `parameters[]` entry whose `default` is that key. For each flag, derive the starting state and rules from the targeting hints: attributes the code sets on contexts (`plan`, `role`, `metro`, …) and anything the README or comments describe ("premium users see…", "25% rollout", "beta segment"). Encode them as seed `rules` (clauses on those attributes), `segments`, and `fallthrough` rollouts. Write one sentence of rationale per flag/rule in `DEMO.md` so the owner can confirm or correct it. Start each flag where the story begins: a "ship a new feature" story starts off; a targeting or rollout story starts on with the rules seeded, so the first launch shows something and the SE edits live. When a hint is ambiguous, prefer the simplest rule that does that, and say so. `references/seed.md` has the exact `rules`, `rollout`, and `targets` shapes; the validator checks them.
7. **Parameters and secrets.** Every env var the app reads that isn't a LaunchDarkly key, isn't infrastructure (`PORT`, `NODE_ENV`), and would reasonably differ per launch becomes a `parameters[]` entry (`CUSTOMER_NAME`-style personalization, the flag key above, mode switches as `enum`). Secret-looking names (`*_PASSWORD`, `*_TOKEN`, `*_API_KEY`, `*_SECRET`) become `parameters[]` with `secret: true` when the SE should supply them per launch (a database password, a prospect's API key), or `containers[].secrets` when the demo owner sets them once for everyone (a shared third-party key). Internal secrets the app only needs for itself (a Flask `SECRET_KEY`, a session or CSRF key) are neither: generate them at startup if the env var is unset, and don't expose them. Never put a default on a secret, never commit a value. Fixed non-secret settings go in `containers[].env`.
8. **Manifest.** Fill `assets/demo.yaml.template` from the inventory. `slug` names the demo, not the repo (`targeting-visualization`, not `ld-targeting-icons`); use the repo name only when it already reads that way, and confirm it with the owner, because the first publish owns the slug. `name`/`summary` from the README's first heading and paragraph, `tags` from the LaunchDarkly capabilities the seed uses, `owners` = the requesting SE (ask if unknown), `verify.http` = the health route plus one real page or API route with an `expectBodyContains` the app always returns, `access.allowPublic: true` only if the README says the demo is meant to be shared, `lifecycle.pausable: false` only if the app can't survive a restart.
9. **Docs and media.** `DEMO.md` from `assets/DEMO.md.template`: the story in beats, which flag to flip at each beat, the rationale for the seeded rules, and the parameters' meaning. Cover: a 1600×900 PNG under 2 MB; use a real screenshot if the app runs locally, otherwise run `python3 scripts/make_cover.py --name "…" --summary "…" [--image screenshot-or-logo.png] media/cover.png` for a clean title card (never a stretched logo).
10. **Publish workflow** from `assets/publish.yml`; `.gitignore`/`.dockerignore` must exclude `.env*`, `node_modules`, build output.
11. **Validate, run, hand off.** `python3 scripts/validate_demo.py <repo>` must report 0 errors; fix warnings unless there's a reason not to. If Docker is available, build for `linux/arm64` and `curl` the health route. Then tell the owner: what you inferred and want confirmed (rules, parameters, slug), which secrets they or the SE must supply, and that tagging `v0.1.0` publishes. The *Make demos SE-friendly* ideas below (a `CUSTOMER_NAME` parameter, a reset action, visible flag state) are app changes: in a retrofit, offer them in the hand-off rather than adding them unasked. The repo must live under the `launchdarkly-labs` or `launchdarkly-demos` GitHub org (any visibility) for publishing to be allowed.

## Publish and watch (with the Demo Depot MCP server)

If the `demo-depot` MCP server is connected, finish the job end to end instead of handing off. It's available two ways: the Claude Code plugin registers `ddu mcp` (needs `ddu auth login` once with a token from the portal's Settings › API tokens), and the depot itself is a remote MCP server at `https://demodepot.launchdarklydemos.com/mcp` (claude.ai / Claude Desktop: Settings › Connectors › Add custom connector; Claude Code: `claude mcp add --transport http demo-depot <that URL>`, then `/mcp` to sign in). Same tools either way.

1. `publish_instructions` tells you the allowed orgs and the tag command for this depot. `whoami` tells you whether the owner still needs to save a LaunchDarkly token.
2. `validate_manifest` with demo.yaml (parsed to JSON) and the seed catches contract errors before the tag; `ddu validate` or `scripts/validate_demo.py` still covers Dockerfiles, cover, and code.
3. Commit, tag (`git tag v0.1.0 && git push origin v0.1.0`), then poll `publish_status` every minute or so: the Actions run takes 2 to 5 minutes, verification about one more. `failed` comes with a reason; fix it, bump the patch version, push the tag again.
4. When the version is `verified`, `launch_demo` it with a note like "skill check", wait for `get_instance` to report `ready`, open the URL, then `teardown`. Tell the owner the demo is live in the catalog.

Without the MCP server, hand off as before: tell the owner what to confirm and that tagging publishes.

## Build a new demo

1. **Plan the story first.** Decide which LaunchDarkly features the demo shows, what the SE clicks in what order, and what the "aha" moment is. That story becomes `DEMO.md` and the seed file.
2. **Build the app against the runtime contract** below. Retrofitting is harder than starting right.
3. **Write the manifest** from `assets/demo.yaml.template`. See `references/manifest.md` for every field.
4. **Write `ld/seed.json`** with every flag, segment, and AI Config that must exist before the demo starts. Anything the story creates live (GitHub App, Vega, Terraform, CLI, an AI Config built on stage) stays out and is listed in `DEMO.md` as created during the demo. See `references/seed.md`.
5. **Containerize** using `assets/Dockerfile.node` or `assets/Dockerfile.python` as the starting point: arm64-safe, pinned base, non-root, `HEALTHCHECK` on the health route.
6. **Add the media and `DEMO.md`**, using `assets/DEMO.md.template`.
7. **Add the publish workflow** from `assets/publish.yml`.
8. **Validate:** `python3 scripts/validate_demo.py <repo-root>`. Fix every error, and fix the warnings unless you have a reason not to.
9. **Run it locally** with `ddu run` if the CLI is installed, and walk through the story end to end.
10. **Hand off.** Tell the owner what to set in the portal (demo secrets), which `secret: true` parameters SEs will be asked for at launch, and to tag `v0.1.0` to publish.

## The runtime contract

These rules exist because of how the depot runs demos. Each one explains the failure it prevents.

### 1. Read every key and setting from env vars at runtime, never at build time

Images are built once at publish time and reused by every launch. Each launch then gets a different LaunchDarkly project, so different keys.

Anything baked in at build time is wrong for every instance. That includes Vite `import.meta.env.VITE_*`, Next.js `NEXT_PUBLIC_*`, CRA `REACT_APP_*`, and Docker `ARG`/`ENV` used for keys.

For browser code, have the server hand config to the client at request time:

```ts
// server: one endpoint (or server-render it into the HTML)
app.get("/api/config", (_req, res) => res.json({
  ldClientSideId: process.env.LD_CLIENT_SIDE_ID,
  customerName: process.env.CUSTOMER_NAME ?? "Acme Corp",
}));
// client: fetch /api/config before initializing the LaunchDarkly JS/React SDK
```

In Next.js, read `process.env` in a server component or route handler and pass the values down. Never use `NEXT_PUBLIC_` for depot-injected values.

### 2. Use the injected variable names

These are the defaults. A manifest can rename them under `launchdarkly.inject`, but don't do that without a reason.

| Variable | Contents |
| --- | --- |
| `LD_SDK_KEY` | Server SDK key |
| `LD_CLIENT_SIDE_ID` | Client-side ID |
| `LD_MOBILE_KEY` | Mobile key |
| `LD_PROJECT_KEY` | Project key |
| `LD_ENV_KEY` | Environment key |
| `LD_API_TOKEN` | API token, only when `apiToken: project-writer` is set |
| `DD_INSTANCE_ID`, `DD_PUBLIC_URL`, `DD_OWNER_EMAIL`, `DD_DEMO_VERSION` | Always present |

Names starting with `DD_`, and the LaunchDarkly names above, are reserved. Don't declare them yourself.

### 3. Use `DD_PUBLIC_URL` for anything that needs the demo's absolute URL

That includes OAuth redirects, webhook targets, share links, and email links. Everywhere else in the frontend, use relative URLs.

TLS terminates at the load balancer, so the app sees plain HTTP. Trust `X-Forwarded-Proto` (for example, `app.set("trust proxy", true)` in Express), and never hardcode `https://localhost`.

### 4. Containers talk over `localhost`, not service names

All of a demo's containers run in one Fargate task and share a network namespace. A Docker Compose hostname like `http://api:4000` does not resolve there.

Use `http://localhost:4000`, read from an env var with that default, for example `API_URL`. Give every container a distinct port. `ddu run` mirrors this by sharing one network namespace locally.

### 5. Listen on `0.0.0.0` on the declared ingress port, and expose a cheap health endpoint

The health check path (usually `/healthz`) must return 200 within a second, as soon as the server can serve traffic. It must not depend on LaunchDarkly, an LLM, or any network call. If the health check depends on an external service, a blip there takes the demo down.

Put deeper checks in a separate endpoint such as `/api/health`, and reference it from `verify.http` instead.

The demo should be healthy within 60 seconds of starting.

### 6. Build arm64-compatible images

Fargate runs on Graviton (ARM64). To stay compatible:

- Don't use `--platform=linux/amd64`.
- Don't download amd64-only binaries.
- Pin base images to a specific tag (for example, `node:22-slim`), never `latest`.
- Prefer slim or distroless images.

Native npm modules must build on arm64, which most do.

### 7. Treat the container as disposable

Pausing a demo scales it to zero, and Resume starts a fresh container. The LaunchDarkly project survives, but local state (SQLite files, in-memory stores, uploaded files) does not.

- Seed demo data on boot so every start looks the same.
- If the demo genuinely can't survive a restart, set `lifecycle.pausable: false`.
- If the demo truly needs object storage, use the `s3-scratch` capability and write under the `${DD_INSTANCE_ID}/` prefix.

### 8. Use flags exactly as the seed defines them, and handle the fallback gracefully

Each launch starts from an empty LaunchDarkly project, so the seed has to contain everything. Every flag key, AI Config key, and segment the code references must be in `ld/seed.json`.

Hardcoded fallbacks in SDK calls must produce a sensible "off" experience, never a crash. The validator scans the code for flag keys that are missing from the seed.

The easiest correct path is to build the demo against a real LaunchDarkly project, then run `ddu ld export --project <key>` to generate the seed.

### 9. Keep third-party secrets out of the repo

If the demo needs an external API key, list its name under the container's `secrets`. The owner sets the value in the portal under `/owners/<slug>`.

Never commit `.env` files, and never paste a key into the code or the manifest. Add `.env*` to `.gitignore` and `.dockerignore`.

For LLM calls, prefer Bedrock with `capabilities: [bedrock]`. The task role then provides credentials automatically, so there's no key to manage. Use the AWS SDK's default credential chain and the `AWS_REGION` env var.

### 10. Size for the default limits

Start each container at `cpu: 512` and `memory: 1024`. A task over 2 vCPU or 4 GB needs admin approval.

Log to stdout and stderr, as JSON lines if convenient. The portal tails these logs for the SE.

## Make demos SE-friendly

- **Personalize with `parameters`.** A `CUSTOMER_NAME` parameter, and optionally a logo URL or industry enum, lets an SE tailor the demo on the launch form. Read them as env vars. Mark passwords and keys the SE types at launch with `secret: true`: masked on the form, delivered to the container as an ECS secret, never stored on the instance.
- **Every launch is attributed to the SE.** Projects are created in the shared Demo Engineering LaunchDarkly account with the SE's own API token, so the demo shouldn't assume a particular account or project key: read `LD_PROJECT_KEY` and `LD_ENV_KEY` from env if it needs them.
- **Simulate traffic.** Demos for guarded rollouts, experiments, or metrics need events flowing to produce interesting charts. Add a small `traffic` sidecar container that drives realistic requests, with `dependsOn: [web]`. Make its intensity a parameter if that helps the story.
- **Keep the SE in control during a call.** Show the current flag state in the UI, and offer a visible "reset demo" action that restores seed data.
- **Fail visibly but gracefully.** If an LLM call or the LaunchDarkly connection fails, show a clear in-app banner. Never show a blank page.

## Demos bound to one LaunchDarkly project (checkout mode)

The depot normally creates a fresh project per launch. Some demos can't work that way because another system owns one particular project: the LaunchDarkly GitHub App maps the repository to it, Terraform holds its state, Vega commits against it. Spot it from `.env.example` naming a real project key, docs that say "the project's policy", or a reset script that deletes "the project's flags". For those, write the manifest in **checkout mode** and no seed:

```yaml
launchdarkly:
  mode: checkout
  project: { key: kevinc-release-autopilot-demo, environment: production }
```

What that means, and what to tell the owner: one SE holds the demo at a time (the portal shows who, and lets others ask for it over Slack); the depot reads the environment's keys with the SE's own API token at launch, so SEs need read access to that project; at teardown the app and AWS resources go away and the demo is checked back in, the project untouched. Flags in such a project are created by whatever owns it; describe them in `DEMO.md` under "Created during the demo" and, if you keep a seed file at all for `createdDuringDemo`, don't reference it from the manifest. Launch parameters, secrets, and `inject` names work exactly as in seed mode.

## Files to produce

```
demo.yaml                        manifest (assets/demo.yaml.template)
DEMO.md                          detail-page content (assets/DEMO.md.template)
ld/seed.json                     LaunchDarkly seed (references/seed.md)
media/cover.png                  16:9, ≥1600×900, <2 MB
media/loop.mp4                   optional: 5–15 s, muted, <10 MB
<container>/Dockerfile           one per container (assets/Dockerfile.node)
.github/workflows/publish.yml    assets/publish.yml
.dockerignore / .gitignore       must exclude .env*, node_modules, build output
```

**Cover image.** If the app runs locally and Playwright is available, take a 1600×900 screenshot of the most visually compelling screen, with a flag in its "on" state, and save it as `media/cover.png`. If you can't, run `python3 scripts/make_cover.py --name "<name>" --summary "<summary>" [--image <screenshot-or-logo>] media/cover.png` (Pillow; the script prints a one-line Docker fallback if Pillow is missing) and tell the owner to replace it with a real screenshot before tagging a release. Don't leave the cover missing, because the validator fails without it.

**Slug, name, and summary.** The slug is kebab-case, 3–40 characters, and describes the demo, for example `ai-configs-support-agent`. The summary is one sentence of 140 characters or fewer that names the LaunchDarkly capability and the outcome.

**Owners.** Use the requesting SE's email address. If you don't know it, ask. Don't invent one.

## Final checklist

Before you call a demo done:

- [ ] `python3 scripts/inventory_repo.py .` was read before changing an existing repo, and every flag key it found (literal, constant, or env-driven) is accounted for: in the seed, as a parameter, or listed in `DEMO.md` as created during the demo (GitHub App, Vega, Terraform, CLI). Nothing the story creates live is pre-created.
- [ ] `python3 scripts/validate_demo.py .` reports 0 errors.
- [ ] Every flag, AI Config, and segment the code uses is in the seed. The app also works with every flag at its fallback.
- [ ] No keys or URLs are baked in at build time. The browser gets its config from the server.
- [ ] Containers reach each other through `localhost`, and the health check has no external dependencies.
- [ ] The Dockerfiles are arm64-safe, use pinned bases, run as non-root, and don't bake in LaunchDarkly keys (multi-stage for new Node demos; an existing single-stage Dockerfile is fine).
- [ ] `DEMO.md` walks through the story beat by beat, including which flags to toggle and when.
- [ ] Per-launch credentials (database passwords, prospect API keys) are `parameters[]` with `secret: true`; shared third-party keys are `containers[].secrets`. Neither has a value in the repo.
- [ ] Inferred targeting rules are written down in `DEMO.md` with their rationale, for the owner to confirm.
- [ ] The owner knows which demo secrets to set in the portal, and that tagging `vX.Y.Z` publishes the demo (from a repo under `launchdarkly-labs` or `launchdarkly-demos`).
