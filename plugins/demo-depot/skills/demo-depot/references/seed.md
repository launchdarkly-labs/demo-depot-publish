<!-- Generated from docs/MANIFEST.md in the demo-depot repo. Don't edit by hand; regenerate it when the schema changes. -->
# LaunchDarkly seed format (seedVersion 1)

```json
{
  "seedVersion": 1,
  "environments": [{ "key": "demo", "name": "Demo", "color": "7B42BC" }],
  "flags": [
    {
      "key": "new-checkout",
      "name": "New checkout",
      "kind": "boolean",
      "variations": [{ "value": true }, { "value": false }],
      "defaults": { "onVariation": 0, "offVariation": 1 },
      "clientSideAvailability": { "usingEnvironmentId": true },
      "environments": {
        "demo": { "on": false, "fallthrough": { "variation": 1 }, "rules": [] }
      }
    }
  ],
  "segments": [
    { "key": "beta-users", "name": "Beta users", "environment": "demo", "included": ["user-123"] }
  ],
  "aiConfigs": [
    {
      "key": "support-agent",
      "name": "Support agent",
      "variations": [
        {
          "key": "default",
          "model": { "id": "anthropic.claude-sonnet" },
          "messages": [{ "role": "system", "content": "You are a helpful support agent." }]
        }
      ]
    }
  ]
}
```

### Targeting shapes (per flag environment)

The importer turns these into LaunchDarkly semantic-patch instructions. Variations are referenced by index into the flag's `variations` array; rollout weights are in thousandths of a percent and must sum to 100000.

```json
"demo": {
  "on": true,
  "offVariation": 1,
  "fallthrough": { "rollout": { "contextKind": "user", "variations": [ { "variation": 0, "weight": 25000 }, { "variation": 1, "weight": 75000 } ] } },
  "targets": [ { "contextKind": "user", "variation": 0, "values": ["user-123"] } ],
  "rules": [
    {
      "description": "Platinum plan",
      "clauses": [ { "contextKind": "user", "attribute": "plan", "op": "in", "values": ["platinum"], "negate": false } ],
      "variation": 0
    },
    {
      "description": "Beta segment, 50% rollout",
      "clauses": [ { "contextKind": "user", "attribute": "segmentMatch", "op": "segmentMatch", "values": ["beta-users"] } ],
      "rollout": { "contextKind": "user", "variations": [ { "variation": 0, "weight": 50000 }, { "variation": 1, "weight": 50000 } ] }
    }
  ]
}
```

- `fallthrough` is either `{ "variation": n }` or `{ "rollout": {...} }`. Seed the default rule as a rollout (even `0`/`100000`) if the story later changes weights through the API.
- A rule needs `clauses` (each with `attribute`, `op`, `values`; `contextKind` defaults to `user`, `negate` to `false`) and exactly one of `variation` or `rollout`. Clause ops are the LaunchDarkly ones: `in`, `contains`, `startsWith`, `endsWith`, `matches`, `lessThan`, `greaterThan`, `before`, `after`, `semVerEqual`, `segmentMatch`.
- Segments support `included` and `excluded` context keys (kind `user`) today. Rule-based segments are not applied yet; use flag rules instead.
- Rules, targets, and fallthrough are applied only when the import creates the flag, so re-running a seed never overwrites targeting an SE changed during a demo.

### Resources created during the demo

Flags, AI Configs, or segments that the demo's own story creates live (the GitHub App on a pull request, Vega, Terraform, a CLI step, an AI Config built on stage) must **not** be seeded; pre-creating them breaks the beat. Declare them so the validators don't warn about keys used in code but missing from the seed, and so the depot and DEMO.md can say who creates them:

```json
"createdDuringDemo": {
  "by": "github-app",
  "flags": ["*"],
  "note": "Release AutoPilot proposes and creates one flag per pull request"
}
```

`by` is one of `github-app`, `vega`, `terraform`, `cli`, `api`, `presenter`, `other`. `flags`, `aiConfigs`, and `segments` list keys, or `["*"]` when the keys are decided at demo time. The importer ignores this block.

How the importer applies a seed:

1. It applies the environments, then segments, then flags (including targeting), then AI Configs.
2. Each item is idempotent, keyed by `key`.
3. Map the AI Configs shape to the current LaunchDarkly API at implementation time. `dd ld export` must round-trip whatever shape the importer accepts.

## Authoring tips

- Generate the seed from a working project with `dd ld export --project <key>` rather than writing it by hand.
- Give flags a `name` and `description`, because SEs see them in the LaunchDarkly UI during the call.
- Set each flag's starting state (`on`, `fallthrough`) to where the story begins. Usually that means the new experience is off.
- For guarded rollouts or experiments, also seed the metrics the demo emits, once the importer supports them. Until then, document them in DEMO.md under "Setup the SE does".
