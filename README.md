# demo-depot-publish

The reusable GitHub Actions workflow that publishes a demo to **Demo Depot**, LaunchDarkly's internal one-click demo catalog.

Demo repos in `launchdarkly-labs` call it from `.github/workflows/publish.yml`:

```yaml
name: Publish to Demo Depot
on:
  push:
    tags: ["v*"]
jobs:
  publish:
    uses: launchdarkly-labs/demo-depot-publish/.github/workflows/publish-demo.yml@v1
    permissions:
      id-token: write
      contents: read
```

Tagging `vX.Y.Z` validates the manifest, builds `linux/arm64` images, pushes them to the depot's registry, uploads the manifest and media, and signals the depot, which verifies the version before listing it.

This repo is public so that public, internal, and private demo repos can all call the workflow. It contains no secrets: the workflow authenticates with GitHub OIDC, and the depot's publish role only trusts tag pushes from repos in the `launchdarkly-labs` org.

The source of truth is the internal `ld-demodepot` repo; this copy is pushed by its `pnpm sync:publish` script, which also moves the `v1` tag. Don't edit it here.
