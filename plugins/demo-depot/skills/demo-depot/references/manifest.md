<!-- Generated from docs/MANIFEST.md in the demo-depot repo. Don't edit by hand; regenerate it when the schema changes. -->
# demo.yaml field reference (schemaVersion 1)

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `schemaVersion` | `1` | yes | |
| `slug` | string | yes | `^[a-z0-9-]{3,40}$`. Globally unique. The first repo to publish a slug owns it. |
| `name` | string | yes | Up to 60 characters |
| `summary` | string | yes | Up to 140 characters. Shown on the card. |
| `description` | path | no | Defaults to `./DEMO.md` |
| `owners` | email[] | yes | 1–5 entries, all on a domain in `config.auth.allowedDomains` |
| `tags` | string[] | yes | 1–8 entries, from the controlled list in `packages/manifest/src/tags.ts`. Unknown tags are a warning, not an error. |
| `tier` | `1` \| `2` | no | Defaults to `1` |
| `media.cover` | path | yes | |
| `media.loop` | path | no | |
| `links.talkTrack` / `links.video` / `links.docs` | url | no | |
| `instanceLinks[]` | object | no | Up to 5 `{label, url}` shown on each running instance beside its URL (My Demos card, instance page, MCP `get_instance`), for systems the SE supplied at launch. `url` may reference **non-secret** parameters as `${NAME}` (e.g. `"${SF_INSTANCE_URL}/lightning/n/Triage_Demo"`); referencing a secret or unknown parameter is a validation error. Resolved once at launch: values are trimmed, `https://` is assumed when no scheme is given, doubled slashes are collapsed, and a link whose parameter is empty is omitted. |
| `parameters[]` | object | no | Fields shown on the launch form. Each is `{name, label, type: string\|enum\|boolean, default?, options?, required?}`. Injected as env var `name`, which must match `^[A-Z][A-Z0-9_]*$`. Add `secret: true` for passwords and API keys: the launch form masks the field, the value is stored in the instance's params secret and delivered as an ECS secret, and it never appears on the instance record, in events, or in logs. Secret parameters must be `type: string` and can't have a `default`. The depot's verifier launches every version with **no** parameter values and waives `required`, so the app must still start and answer its health route when required parameters are absent (degrade to a setup message, don't crash). |
| `runtime.ingress.container` / `.port` | string / int | Tier 1 | The container and port the ALB routes to |
| `runtime.ingress.healthCheck` | `{path, intervalSeconds?=15, healthyThreshold?=2}` | Tier 1 | |
| `runtime.containers[]` | object | Tier 1 | 1–5 containers. Each is `{name, build: {context, dockerfile?}, cpu, memory, env?, secrets?, command?, dependsOn?}`. `cpu` is in CPU units (1024 = 1 vCPU) and `memory` is in MiB. The task size is the smallest valid Fargate size that fits the sum of the containers, and the rate estimate is based on that task size. |
| `runtime.containers[].secrets` | string[] | no | Names of demo secrets. Owners set the values in the portal at `/owners/{slug}`. |
| `capabilities` | (`bedrock` \| `s3-scratch`)[] | no | Selects the task role |
| `launchdarkly.mode` | `seed` \| `checkout` | no | Defaults to `seed`: a project is created per instance from the seed and deleted at teardown. `checkout`: the demo is bound to one existing project; instances check it out one at a time and check it back in at teardown (see *Checkout demos*) |
| `launchdarkly.project.key` | string | with `checkout` | The existing project the demo is bound to |
| `launchdarkly.project.environment` | string | no | Environment whose keys are injected; defaults to `production` |
| `launchdarkly.seed` | path | no | If present, a project is created for every instance. Not allowed with `mode: checkout` |
| `launchdarkly.apiToken` | `none` \| `project-writer` | no | Defaults to `none` |
| `launchdarkly.inject` | map | no | Env var names. Defaults: `sdkKey: LD_SDK_KEY`, `clientSideId: LD_CLIENT_SIDE_ID`, `mobileKey: LD_MOBILE_KEY`, `projectKey: LD_PROJECT_KEY`, `environmentKey: LD_ENV_KEY`, `apiToken: LD_API_TOKEN` |
| `access.default` | `sso` \| `public` | no | Defaults to `sso` |
| `access.allowPublic` | bool | no | Defaults to `false` |
| `lifecycle.pausable` | bool | no | Defaults to `true`. If `false`, the auto-pause timer terminates the instance instead. |
| `verify.http[]` | object | no | Each is `{path, expectStatus?=200, expectBodyContains?, timeoutSeconds?=10}`. Runs against the ingress container. If empty, the health check is the only check. |
| `tier2.app` | path | Tier 2 | Directory of the CDK app. Its stack must extend `DemoDepotStack`. |

**Reserved env var names.** Names starting with `DD_`, and the LaunchDarkly inject names, are reserved. Validation fails if a manifest's `env` or `parameters` uses one.

## Versioning rules

- The git tag `vX.Y.Z` becomes the manifest version. Versions are immutable, so republishing the same version is rejected.
- Release notes come from the GitHub release body. If there isn't one, the tag annotation is used.
- Running instances stay on the version they launched with. New launches default to the latest verified version.
- Schema changes must be additive within `schemaVersion: 1`. A breaking change requires `schemaVersion: 2`, a migration note here, and ingest support for both versions for 90 days.

## Owner CLI (`dd`)

| Command | What it does |
| --- | --- |
| `ddu init [dir] [--tier 2] [--slug --name --summary --owner]` | Scaffolds `demo.yaml`, `DEMO.md`, a seed, a cover placeholder, a Dockerfile, the publish workflow, and `.gitignore` entries into the repo, and copies the Claude skill into `.claude/skills/demo-depot/`. Existing files are never overwritten without `--force`. |
| `ddu validate [path]` | Validates the schema, checks that every referenced file exists, checks media sizes and dimensions, validates the seed, and scans code and Dockerfiles for depot footguns (build-time keys, amd64 images, container-name URLs, loopback listeners). `path` is a repo directory or a `demo.yaml`. `--json` for machine output, `--manifest-only` to skip the scans. |
| `ddu run` | Generates `.dd/docker-compose.yaml` from the manifest and runs the demo locally. All containers share one network namespace, as in Fargate, so they reach each other on `localhost:<port>`. LaunchDarkly keys come from `.env.local`, or `--ld-project <key> [--ld-env <key>]` uses the owner's own account through `LD_API_TOKEN`. `--port`, `--param NAME=value`, `--dry-run`, and `--no-build` are available. |
| `ddu ld export --project <key> [--env <key>]` | Writes `ld/seed.json` from an existing LaunchDarkly project |
| `ddu skill install` | Installs the `demo-depot` Claude skill into `~/.claude/skills/`, so Claude builds depot-ready demos by default |
