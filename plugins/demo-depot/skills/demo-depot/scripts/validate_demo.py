#!/usr/bin/env python3
"""Validate a demo repo against the Demo Depot contract (demo.yaml schemaVersion 1).

Usage:
    python3 validate_demo.py [repo_root] [--allowed-domain launchdarkly.com] [--json]

Checks:
- The manifest schema.
- Referenced files and media (sizes and dimensions).
- The LaunchDarkly seed.
- Fargate sizing.
- Common depot footguns: build-time keys, amd64 images, service-name URLs,
  hardcoded keys, and flag keys used in code but missing from the seed.

Exits 1 if there are any errors. Warnings don't fail the run.

Keep this in sync with packages/manifest/src/schema.ts in the demo-depot repo.
That schema is the source of truth, and the depot runs it again at ingest.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

try:
    import yaml  # PyYAML
except ImportError:  # pragma: no cover
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

SLUG_RE = re.compile(r"^[a-z0-9-]{3,40}$")
ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+)$")
LD_INJECT_DEFAULTS = {
    "sdkKey": "LD_SDK_KEY", "clientSideId": "LD_CLIENT_SIDE_ID", "mobileKey": "LD_MOBILE_KEY",
    "projectKey": "LD_PROJECT_KEY", "environmentKey": "LD_ENV_KEY", "apiToken": "LD_API_TOKEN",
}
CAPABILITIES = {"bedrock", "s3-scratch"}
KNOWN_TAGS = {
    # Mirror of packages/manifest/src/tags.ts. Unknown tags only warn.
    "ai-configs", "agents", "agentcontrol", "guarded-rollouts", "progressive-rollouts",
    "release-automation", "release-pipelines", "experimentation", "feature-management",
    "observability", "session-replay", "kill-switch", "targeting", "segments", "mobile",
    "migrations", "integrations", "aws", "bedrock", "partners",
    "retail", "fintech", "healthcare", "media", "gaming", "saas", "travel", "wealth-management",
}
MAX_TASK_CPU, MAX_TASK_MEM = 2048, 4096
SRC_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".go", ".java", ".rb", ".cs", ".kt", ".swift"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "out", "coverage", ".venv", "venv", "__pycache__", ".dd", ".claude"}


def fargate_sizes():
    sizes = [(256, m) for m in (512, 1024, 2048)]
    sizes += [(512, m) for m in range(1024, 4097, 1024)]
    sizes += [(1024, m) for m in range(2048, 8193, 1024)]
    sizes += [(2048, m) for m in range(4096, 16385, 1024)]
    sizes += [(4096, m) for m in range(8192, 30721, 1024)]
    return sizes


def task_size(cpu: int, mem: int):
    for c, m in fargate_sizes():
        if c >= cpu and m >= mem:
            return c, m
    return None


def image_dims(path: Path):
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + seg_len
    return None


class Report:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


def iter_files(root: Path, exts=None, names=None):
    for p in root.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        if not p.is_file():
            continue
        if exts and p.suffix in exts:
            yield p
        elif names and p.name in names:
            yield p


def rel(root: Path, p: Path) -> str:
    return str(p.relative_to(root))


def check_path(root: Path, r: Report, value, field, required=True):
    if not value:
        if required:
            r.err(f"{field}: required")
        return None
    p = (root / value).resolve()
    if not p.exists():
        r.err(f"{field}: file not found: {value}")
        return None
    return p


def validate_manifest(root: Path, m: dict, r: Report, allowed_domains: list[str]):
    if m.get("schemaVersion") != 1:
        r.err("schemaVersion: must be 1")
    slug = m.get("slug", "")
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        r.err("slug: must match ^[a-z0-9-]{3,40}$")
    name = m.get("name")
    if not name or len(str(name)) > 60:
        r.err("name: required, at most 60 characters")
    summary = m.get("summary")
    if not summary or len(str(summary)) > 140:
        r.err("summary: required, at most 140 characters")

    owners = m.get("owners") or []
    if not (1 <= len(owners) <= 5):
        r.err("owners: 1–5 emails required")
    for o in owners:
        mm = EMAIL_RE.match(str(o))
        if not mm:
            r.err(f"owners: invalid email {o!r}")
        elif allowed_domains and mm.group(1).lower() not in allowed_domains:
            r.err(f"owners: {o} is not on an allowed domain ({', '.join(allowed_domains)})")
        elif str(o).lower().startswith(("replace", "you@", "owner@")):
            r.err(f"owners: placeholder email {o}. Use the real owner's email.")

    tags = m.get("tags") or []
    if not (1 <= len(tags) <= 8):
        r.err("tags: 1–8 required")
    for t in tags:
        if t not in KNOWN_TAGS:
            r.warn(f"tags: {t!r} is not in the controlled list (allowed, but it won't group with other demos)")

    tier = m.get("tier", 1)
    if tier not in (1, 2):
        r.err("tier: must be 1 or 2")

    desc = check_path(root, r, m.get("description", "./DEMO.md"), "description (DEMO.md)")
    if desc and "REPLACE" in desc.read_text(errors="ignore"):
        r.err("DEMO.md: still contains REPLACE placeholders")

    media = m.get("media") or {}
    cover = check_path(root, r, media.get("cover"), "media.cover")
    if cover:
        if cover.stat().st_size > 2 * 1024 * 1024:
            r.err("media.cover: must be under 2 MB")
        dims = image_dims(cover)
        if not dims:
            r.err("media.cover: must be PNG or JPG")
        else:
            w, h = dims
            if w < 1600 or h < 900:
                r.err(f"media.cover: {w}×{h}; must be at least 1600×900")
            if abs(w / h - 16 / 9) > 0.02:
                r.warn(f"media.cover: {w}×{h} isn't 16:9, so it will be cropped on cards")
    if media.get("loop"):
        loop = check_path(root, r, media.get("loop"), "media.loop")
        if loop and loop.stat().st_size > 10 * 1024 * 1024:
            r.err("media.loop: must be under 10 MB")

    li = m.get("launchdarkly") or {}
    inject = {**LD_INJECT_DEFAULTS, **(li.get("inject") or {})}
    reserved = set(inject.values())
    mode = li.get("mode", "seed")
    if mode not in ("seed", "checkout"):
        r.err("launchdarkly.mode: must be seed or checkout")
    project = li.get("project")
    if mode == "checkout":
        if not isinstance(project, dict) or not project.get("key"):
            r.err("launchdarkly.project: mode: checkout needs launchdarkly.project.key (the existing project the demo is bound to)")
        if li.get("seed"):
            r.err("launchdarkly.seed: mode: checkout can't have a seed; the project already exists and the depot never creates or deletes it")
        if li.get("apiToken", "none") != "none":
            r.err("launchdarkly.apiToken: mode: checkout doesn't issue project-writer tokens for a shared project")
    elif project:
        r.err("launchdarkly.project: only used with mode: checkout")

    params = m.get("parameters") or []
    for i, p in enumerate(params):
        f = f"parameters[{i}]"
        n = p.get("name", "")
        if not ENV_RE.match(n):
            r.err(f"{f}.name: {n!r} must match ^[A-Z][A-Z0-9_]*$")
        if n.startswith("DD_") or n in reserved:
            r.err(f"{f}.name: {n} is reserved")
        if not p.get("label"):
            r.err(f"{f}.label: required")
        ptype = p.get("type")
        if ptype not in ("string", "enum", "boolean"):
            r.err(f"{f}.type: must be string, enum, or boolean")
        if ptype == "enum":
            opts = p.get("options") or []
            if not opts:
                r.err(f"{f}.options: required for enum")
            elif "default" in p and p["default"] not in opts:
                r.err(f"{f}.default: must be one of options")
        if p.get("secret"):
            if ptype != "string":
                r.err(f"{f}.secret: secret parameters must be type string")
            if "default" in p:
                r.err(f"{f}.default: secret parameters can't have a default")

    param_by_name = {p.get("name"): p for p in params if isinstance(p, dict)}
    ilinks = m.get("instanceLinks") or []
    if not isinstance(ilinks, list) or len(ilinks) > 5:
        r.err("instanceLinks: up to 5 {label, url} entries")
        ilinks = []
    for i, l in enumerate(ilinks):
        f = f"instanceLinks[{i}]"
        if not isinstance(l, dict):
            r.err(f"{f}: must be {{label, url}}")
            continue
        label = l.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > 60:
            r.err(f"{f}.label: required, up to 60 characters")
        url = l.get("url")
        if not isinstance(url, str) or not url.strip() or len(url) > 500:
            r.err(f"{f}.url: required")
            continue
        for ref in dict.fromkeys(re.findall(r"\$\{([A-Z][A-Z0-9_]*)\}", url)):
            p = param_by_name.get(ref)
            if p is None:
                r.err(f"{f}.url: references unknown parameter {ref}")
            elif p.get("secret"):
                r.err(f"{f}.url: can't reference secret parameter {ref} (it would be shown in the portal)")

    containers = []
    if tier == 1:
        rt = m.get("runtime") or {}
        containers = rt.get("containers") or []
        if not (1 <= len(containers) <= 5):
            r.err("runtime.containers: 1–5 required")
        names = [c.get("name") for c in containers]
        if len(set(names)) != len(names):
            r.err("runtime.containers: names must be unique")
        tot_cpu = tot_mem = 0
        for i, c in enumerate(containers):
            f = f"runtime.containers[{i}] ({c.get('name')})"
            if not c.get("name") or not re.match(r"^[a-z][a-z0-9-]{0,30}$", c.get("name", "")):
                r.err(f"{f}.name: lowercase, ^[a-z][a-z0-9-]{{0,30}}$")
            cpu, mem = c.get("cpu"), c.get("memory")
            if not isinstance(cpu, int) or cpu < 128:
                r.err(f"{f}.cpu: integer CPU units ≥128 required (1024 = 1 vCPU)")
            else:
                tot_cpu += cpu
            if not isinstance(mem, int) or mem < 128:
                r.err(f"{f}.memory: integer MiB ≥128 required")
            else:
                tot_mem += mem
            build = c.get("build") or {}
            ctx = check_path(root, r, build.get("context"), f"{f}.build.context")
            if ctx:
                df = ctx / build.get("dockerfile", "Dockerfile")
                if not df.exists():
                    r.err(f"{f}: Dockerfile not found at {rel(root, df)}")
            for k in (c.get("env") or {}):
                if k.startswith("DD_") or k in reserved:
                    r.err(f"{f}.env: {k} is reserved")
            for s in c.get("secrets") or []:
                if not ENV_RE.match(s):
                    r.err(f"{f}.secrets: {s!r} must match ^[A-Z][A-Z0-9_]*$")
            for d in c.get("dependsOn") or []:
                if d not in names:
                    r.err(f"{f}.dependsOn: unknown container {d!r}")
        size = task_size(tot_cpu, tot_mem)
        if not size:
            r.err(f"runtime: total {tot_cpu} CPU / {tot_mem} MiB exceeds Fargate limits")
        elif size[0] > MAX_TASK_CPU or size[1] > MAX_TASK_MEM:
            r.err(f"runtime: task size {size[0]} CPU / {size[1]} MiB is over 2 vCPU / 4 GB and needs admin approval. Right-size the containers.")
        ing = rt.get("ingress") or {}
        if ing.get("container") not in names:
            r.err("runtime.ingress.container: must name a declared container")
        if not isinstance(ing.get("port"), int):
            r.err("runtime.ingress.port: integer required")
        hc = (ing.get("healthCheck") or {}).get("path", "")
        if not str(hc).startswith("/"):
            r.err("runtime.ingress.healthCheck.path: required, must start with /")
    else:
        t2 = (m.get("tier2") or {}).get("app")
        check_path(root, r, t2, "tier2.app")

    for cap in m.get("capabilities") or []:
        if cap not in CAPABILITIES:
            r.err(f"capabilities: unknown {cap!r} (allowed: {', '.join(sorted(CAPABILITIES))})")

    if li:
        if li.get("apiToken", "none") not in ("none", "project-writer"):
            r.err("launchdarkly.apiToken: none or project-writer")
    acc = m.get("access") or {}
    if acc.get("default", "sso") not in ("sso", "public"):
        r.err("access.default: sso or public")
    if acc.get("default") == "public" and not acc.get("allowPublic"):
        r.err("access: default is public but allowPublic is false")
    for i, v in enumerate((m.get("verify") or {}).get("http") or []):
        if not str(v.get("path", "")).startswith("/"):
            r.err(f"verify.http[{i}].path: must start with /")
    return containers, inject


def validate_seed(root: Path, m: dict, r: Report):
    li = m.get("launchdarkly") or {}
    if li.get("mode") == "checkout":
        return None  # the project already exists and its flags are owned elsewhere
    if not li.get("seed"):
        r.warn("launchdarkly.seed: none, so instances get no LaunchDarkly project. Is that intended?")
        return None
    p = check_path(root, r, li.get("seed"), "launchdarkly.seed")
    if not p:
        return set()
    try:
        seed = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        r.err(f"seed: invalid JSON ({e})")
        return set()
    if seed.get("seedVersion") != 1:
        r.err("seed.seedVersion: must be 1")
    envs = {e.get("key") for e in seed.get("environments") or [{"key": "demo"}]}
    keys = set()
    wildcard = False
    created = seed.get("createdDuringDemo")
    if created is not None:
        if not isinstance(created, dict) or created.get("by") not in CREATED_DURING_DEMO_BY:
            r.err(f"seed.createdDuringDemo.by: must be one of {sorted(CREATED_DURING_DEMO_BY)}")
        else:
            for kind in ("flags", "aiConfigs", "segments"):
                vals = created.get(kind) or []
                if not isinstance(vals, list) or not all(isinstance(v, str) and v for v in vals):
                    r.err(f"seed.createdDuringDemo.{kind}: must be a list of keys (or [\"*\"])")
                elif kind != "segments":
                    if "*" in vals:
                        wildcard = True
                    keys |= set(vals)
    for kind in ("flags", "segments", "aiConfigs"):
        seen = set()
        for i, item in enumerate(seed.get(kind) or []):
            k = item.get("key")
            if not k:
                r.err(f"seed.{kind}[{i}]: key required")
                continue
            if k in seen:
                r.err(f"seed.{kind}: duplicate key {k!r}")
            seen.add(k)
            if kind == "flags":
                for env in (item.get("environments") or {}):
                    if env not in envs:
                        r.err(f"seed.flags[{k}]: unknown environment {env!r}")
                if not item.get("variations"):
                    r.err(f"seed.flags[{k}]: variations required")
                nvar = len(item.get("variations") or [])
                for env, cfg in (item.get("environments") or {}).items():
                    check_targeting(f"seed.flags[{k}].environments[{env}]", cfg, nvar, r)
            if kind == "segments" and item.get("environment") not in envs:
                r.err(f"seed.segments[{k}]: environment must be one of {sorted(envs)}")
        if kind != "segments":
            keys |= seen
    return None if wildcard else keys


FLAG_CALL_RE = re.compile(r"\b\w*[Vv]ariation(?:Detail)?\s*\(\s*['\"]([A-Za-z0-9][\w.-]*)['\"]")
AI_CALL_RE = re.compile(r"\b\w*ai\w*\.(?:config|completionConfig|agentConfig|agents?)\s*\(\s*['\"]([\w.-]+)['\"]", re.I)
BUILD_TIME_RE = re.compile(r"\b(?:VITE_|NEXT_PUBLIC_|REACT_APP_)\w*(?:LD|LAUNCHDARKLY|CLIENT_SIDE|SDK_KEY)\w*")
HARDCODED_KEY_RE = re.compile(r"['\"]((?:sdk|mob|api)-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})['\"]")
LOOPBACK_LISTEN_RE = re.compile(r"\.listen\(\s*[\w.]+\s*,\s*['\"](?:127\.0\.0\.1|localhost)['\"]")


CREATED_DURING_DEMO_BY = {"github-app", "vega", "terraform", "cli", "api", "presenter", "other"}

CLAUSE_OPS = {"in", "contains", "startsWith", "endsWith", "matches", "lessThan", "lessThanOrEqual", "greaterThan",
              "greaterThanOrEqual", "before", "after", "semVerEqual", "semVerLessThan", "semVerGreaterThan", "segmentMatch"}


def check_rollout(where: str, rollout, nvar: int, r: Report):
    if not isinstance(rollout, dict) or not isinstance(rollout.get("variations"), list) or not rollout["variations"]:
        r.err(f"{where}.rollout: needs variations [{{variation, weight}}]")
        return
    total = 0
    for v in rollout["variations"]:
        if not isinstance(v, dict) or not isinstance(v.get("variation"), int) or not isinstance(v.get("weight"), int):
            r.err(f"{where}.rollout.variations: each entry needs integer variation and weight")
            return
        if v["variation"] >= nvar:
            r.err(f"{where}.rollout: variation {v['variation']} out of range")
        total += v["weight"]
    if total != 100000:
        r.err(f"{where}.rollout: weights must sum to 100000 (thousandths of a percent), got {total}")


def check_targeting(where: str, cfg, nvar: int, r: Report):
    """Rules, fallthrough, targets: the shapes the importer turns into semantic patches."""
    if not isinstance(cfg, dict):
        return
    ft = cfg.get("fallthrough")
    if isinstance(ft, dict):
        if ft.get("variation") is not None and ft.get("rollout") is not None:
            r.err(f"{where}.fallthrough: use variation or rollout, not both")
        if ft.get("rollout") is not None:
            check_rollout(f"{where}.fallthrough", ft["rollout"], nvar, r)
        if isinstance(ft.get("variation"), int) and ft["variation"] >= nvar:
            r.err(f"{where}.fallthrough.variation: out of range")
    if isinstance(cfg.get("offVariation"), int) and cfg["offVariation"] >= nvar:
        r.err(f"{where}.offVariation: out of range")
    for i, rule in enumerate(cfg.get("rules") or []):
        w = f"{where}.rules[{i}]"
        if not isinstance(rule, dict) or not isinstance(rule.get("clauses"), list) or not rule["clauses"]:
            r.err(f"{w}: needs a non-empty clauses array")
            continue
        for j, c in enumerate(rule["clauses"]):
            if not isinstance(c, dict) or not c.get("attribute") or not c.get("op") or not isinstance(c.get("values"), list):
                r.err(f"{w}.clauses[{j}]: needs attribute, op, and values[]")
            elif c["op"] not in CLAUSE_OPS:
                r.warn(f"{w}.clauses[{j}]: unknown op {c['op']!r}")
        has_var, has_roll = rule.get("variation") is not None, rule.get("rollout") is not None
        if has_var == has_roll:
            r.err(f"{w}: needs exactly one of variation or rollout")
        elif has_var and (not isinstance(rule["variation"], int) or rule["variation"] >= nvar):
            r.err(f"{w}.variation: out of range")
        elif has_roll:
            check_rollout(w, rule["rollout"], nvar, r)
    for i, t in enumerate(cfg.get("targets") or []):
        if not isinstance(t, dict) or not isinstance(t.get("variation"), int) or not isinstance(t.get("values"), list):
            r.err(f"{where}.targets[{i}]: needs variation and values[]")
        elif t["variation"] >= nvar:
            r.err(f"{where}.targets[{i}].variation: out of range")


def scan_code(root: Path, containers, seed_keys, r: Report):
    names = [c.get("name") for c in containers if c.get("name")]
    svc_re = re.compile(r"https?://(" + "|".join(map(re.escape, names)) + r"):\d+") if names else None
    used = {}
    for f in iter_files(root, exts=SRC_EXT):
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        rp = rel(root, f)
        for k in FLAG_CALL_RE.findall(text) + AI_CALL_RE.findall(text):
            used.setdefault(k, rp)
        if BUILD_TIME_RE.search(text):
            r.err(f"{rp}: LaunchDarkly value read from a build-time env var ({BUILD_TIME_RE.search(text).group(0)}). Serve it from the server at runtime.")
        if HARDCODED_KEY_RE.search(text):
            r.err(f"{rp}: hardcoded LaunchDarkly key/token. Read it from the injected env var.")
        if svc_re and svc_re.search(text):
            r.err(f"{rp}: {svc_re.search(text).group(0)} uses a container name as a hostname. Containers share localhost in the depot.")
        if LOOPBACK_LISTEN_RE.search(text):
            r.err(f"{rp}: server listens on loopback only. Listen on 0.0.0.0.")
    if seed_keys is not None:
        for k, where in sorted(used.items()):
            if k not in seed_keys:
                r.warn(f"flag/AI Config {k!r} is used in {where} but isn't in the seed")

    dockerfiles = [p for p in iter_files(root, names={"Dockerfile"})] + [p for p in root.rglob("*.Dockerfile") if not any(s in SKIP_DIRS for s in p.relative_to(root).parts)]
    for df in dockerfiles:
        text = df.read_text(errors="ignore")
        rp = rel(root, df)
        if "--platform=linux/amd64" in text:
            r.err(f"{rp}: forces linux/amd64. Fargate runs arm64.")
        for img in re.findall(r"^FROM\s+(?:--\S+\s+)*(\S+)", text, re.M):
            if img.lower() == "scratch" or "@" in img or "$" in img:
                continue
            last = img.rsplit("/", 1)[-1]
            if ":" not in last or last.endswith(":latest"):
                r.warn(f"{rp}: base image {img} isn't pinned to a tag")
        if re.search(r"^(ARG|ENV)\s+LD_", text, re.M):
            r.err(f"{rp}: LaunchDarkly values set at build time (ARG/ENV LD_*). The depot injects them at runtime.")
        if not re.search(r"^USER\s+", text, re.M):
            r.warn(f"{rp}: no USER instruction, so the container runs as root")

    gi = root / ".gitignore"
    gi_text = gi.read_text(errors="ignore") if gi.exists() else ""
    if ".env" not in gi_text:
        r.err(".gitignore: must exclude .env* files")
    elif not re.search(r"^\s*\*?\.env(\*|\.\*)", gi_text, re.M):
        r.warn(".gitignore: ignores .env but not .env.local/.env.production; use .env*")
    contexts = [root] + [root / c["build"]["context"] for c in containers if (c.get("build") or {}).get("context")]
    if not any((ctx / ".dockerignore").exists() for ctx in contexts):
        r.warn(".dockerignore: none found. Exclude .env*, node_modules, and build output.")
    for envf in root.glob(".env*"):
        if envf.name not in (".env.example", ".env.sample"):
            r.warn(f"{envf.name}: make sure this is gitignored and never committed")

    wf_dir = root / ".github" / "workflows"
    wfs = list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml")) if wf_dir.exists() else []
    if not any("publish-demo.yml" in w.read_text(errors="ignore") for w in wfs):
        r.err(".github/workflows: no workflow calls the depot's publish-demo.yml (see assets/publish.yml)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--allowed-domain", action="append", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    domains = [d.lower() for d in (a.allowed_domain or ["launchdarkly.com"])]
    r = Report()

    mf = root / "demo.yaml"
    if not mf.exists():
        r.err("demo.yaml not found at repo root")
    else:
        try:
            m = yaml.safe_load(mf.read_text()) or {}
        except yaml.YAMLError as e:
            r.err(f"demo.yaml: invalid YAML ({e})")
            m = {}
        if "REPLACE" in mf.read_text():
            r.err("demo.yaml: still contains REPLACE placeholders")
        containers, _ = validate_manifest(root, m, r, domains)
        seed_keys = validate_seed(root, m, r)
        scan_code(root, containers, seed_keys if (m.get("launchdarkly") or {}).get("seed") else None, r)

    if a.json:
        print(json.dumps({"errors": r.errors, "warnings": r.warnings}, indent=2))
    else:
        for e in r.errors:
            print(f"ERROR   {e}")
        for w in r.warnings:
            print(f"WARN    {w}")
        print(f"\n{len(r.errors)} error(s), {len(r.warnings)} warning(s)")
        if not r.errors:
            print("Depot-ready ✓ (tag vX.Y.Z to publish)")
    sys.exit(1 if r.errors else 0)


if __name__ == "__main__":
    main()
