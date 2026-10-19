#!/usr/bin/env python3
"""
Inventory a demo repo for Demo Depot. Read-only. Prints JSON (or a report with --report) that the
demo-depot skill turns into demo.yaml, ld/seed.json, and DEMO.md.

    python3 inventory_repo.py <repo-root> [--report]

It collects: containers (Dockerfiles, compose services, exposed ports, health checks, base images,
arm64 concerns), app entry points (framework, listen port, host), env var names the code reads,
LaunchDarkly usage (SDKs, evaluation calls and their keys, keys that come from env/constants, AI
Config calls), targeting hints from README/docs/comments (attributes, segments, rollouts), secrets
and credentials the app expects, and any depot files already present. Nothing here is a decision;
the skill confirms each inferred item with the owner.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".next", "dist", "build", "out", "__pycache__", ".venv", "venv",
             "vendor", "target", ".turbo", "coverage", ".dd", "cdk.out", ".claude"}
CODE_EXTS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".go", ".java", ".kt", ".rb", ".cs",
             ".php", ".rs", ".swift", ".dart", ".vue", ".svelte", ".html"}
DOC_EXTS = {".md", ".txt", ".rst"}
MAX_FILE = 400_000

LD_SDK_PACKAGES = {
    "@launchdarkly/node-server-sdk": "node-server", "launchdarkly-node-server-sdk": "node-server",
    "@launchdarkly/js-client-sdk": "js-client", "launchdarkly-js-client-sdk": "js-client",
    "launchdarkly-react-client-sdk": "react-client", "@launchdarkly/react-native-client-sdk": "react-native",
    "@launchdarkly/server-sdk-ai": "node-ai", "@launchdarkly/observability": "observability",
    "launchdarkly-server-sdk": "python-server", "launchdarkly_server_sdk": "python-server",
    "launchdarkly-server-sdk-ai": "python-ai",
    "github.com/launchdarkly/go-server-sdk": "go-server", "com.launchdarkly:launchdarkly-java-server-sdk": "java-server",
    "LaunchDarkly.ServerSdk": "dotnet-server", "launchdarkly-server-sdk-ruby": "ruby-server", "ldclient-rb": "ruby-server",
}

# Evaluation calls: capture the first argument (a string literal, an identifier, or an env lookup).
EVAL_CALL_RE = re.compile(
    r"\b(?:ld\w*|client|ldClient|ldclient\.get\(\)|LD|flags?)?\.?\s*"
    r"(?P<fn>(?:bool|string|int|float|number|json|double)?[Vv]ariation(?:Detail)?|BoolVariation|StringVariation|IntVariation|JsonVariation|variation_detail)"
    r"\s*\(\s*(?P<arg>\"[^\"]+\"|'[^']+'|`[^`]+`|[A-Za-z_][\w.]*(?:\[[^\]]+\])?(?:\([^)]*\))?)",
)
AI_CALL_RE = re.compile(r"\b\w*ai\w*\.(?:config|completionConfig|agentConfig|agents?|model_config)\s*\(\s*(\"[^\"]+\"|'[^']+'|[A-Za-z_][\w.]*)", re.I)
ENV_READ_RES = [
    re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)"),
    re.compile(r"process\.env\[['\"]([A-Z][A-Z0-9_]*)['\"]\]"),
    re.compile(r"os\.environ(?:\.get)?\s*[\[(]\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
    re.compile(r"os\.getenv\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
    re.compile(r"os\.Getenv\(\s*\"([A-Z][A-Z0-9_]*)\""),
    re.compile(r"System\.getenv\(\s*\"([A-Z][A-Z0-9_]*)\""),
    re.compile(r"Environment\.GetEnvironmentVariable\(\s*\"([A-Z][A-Z0-9_]*)\""),
    re.compile(r"ENV(?:\.fetch)?\s*[\[(]\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
    re.compile(r"\$\{?([A-Z][A-Z0-9_]{2,})\}?", ),  # shell / compose
]
SECRETISH_RE = re.compile(r"(PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|PRIVATE_KEY|CREDENTIAL|ACCESS_KEY)", re.I)
LD_INJECTED = {"LD_SDK_KEY", "LD_CLIENT_SIDE_ID", "LD_MOBILE_KEY", "LD_PROJECT_KEY", "LD_ENV_KEY", "LD_API_TOKEN",
               "SDK_KEY", "LAUNCHDARKLY_SDK_KEY", "LD_CLIENT_ID", "CLIENT_SIDE_ID", "LAUNCHDARKLY_CLIENT_SIDE_ID"}
LISTEN_RES = [
    (re.compile(r"\.listen\(\s*(\d{2,5})"), "listen"),
    (re.compile(r"\.listen\(\s*(?:process\.env\.(\w+)\s*(?:\|\||\?\?)\s*)?(\d{2,5})"), "listen-env"),
    (re.compile(r"\.run\([^)]*port\s*=\s*(\d{2,5})"), "flask/fastapi run"),
    (re.compile(r"uvicorn\.run\([^)]*port\s*=\s*(\d{2,5})"), "uvicorn"),
    (re.compile(r"http\.ListenAndServe\(\s*\"[^\"]*:(\d{2,5})\""), "go ListenAndServe"),
    (re.compile(r"PORT\s*[=:]\s*(\d{2,5})"), "PORT constant"),
]
HOST_LOOPBACK_RE = re.compile(r"(?:host\s*=\s*|\.listen\([^)]*)['\"](127\.0\.0\.1|localhost)['\"]")
ROUTE_RES = [
    re.compile(r"@\w+\.(?:route|get)\(\s*['\"](/[^'\"]*)['\"]"),           # flask / fastapi
    re.compile(r"\b(?:app|router|r)\.(?:get|use)\(\s*['\"](/[^'\"]*)['\"]"),  # express / koa
    re.compile(r"HandleFunc\(\s*\"(/[^\"]*)\""),                           # go
    re.compile(r"\[Http(?:Get|Route)\(\s*\"(/[^\"]*)\""),                  # dotnet
]
HEALTH_PATHS = {"/healthz", "/health", "/api/health", "/_health", "/ping", "/ready", "/livez"}
TARGETING_HINT_RE = re.compile(
    r"\b(targeting|target(?:ed)? (?:by|on)|segment|rollout|percentage|rule|variation|attribute|context kind|multi-?context|"
    r"beta|plan|tier|region|metro|country|role|organization|org\b|device|opt[- ]in|kill switch|experiment|guarded)",
    re.I)
ATTR_HINT_RE = re.compile(r"\b(plan|tier|role|metro|region|country|org(?:anization)?|device|email|company|beta|segment)\b", re.I)
# Something other than the depot's seed creates flags while the demo runs. Each match is evidence that
# the keys involved must NOT be pre-created in ld/seed.json.
DEMO_TIME_RE = re.compile(
    r"(GitHub App|Release Auto-?Pilot|auto-?flagg|\bVega\b|@launchdarkly\s+(?:approve|plan|refine)|"
    r"creates? (?:the|a|one|each) (?:feature )?flag|flag (?:is |gets |was )?created|"
    r"launchdarkly_feature_flag|\bldcli\b|ld-cli|/api/v2/flags|flags/\$\{?\w*PROJECT|"
    r"Terraform|created (?:live|during the demo|at demo[- ]time)|chooses? (?:the )?flag keys?)",
    re.I,
)
DEMO_TIME_FILE_RE = re.compile(r"(\.launchdarkly/coderefs\.ya?ml$|\.tf$|terraform/)")


def read(p: Path) -> str:
    try:
        if p.stat().st_size > MAX_FILE:
            return ""
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git")]
        for f in filenames:
            yield Path(dirpath) / f


def rel(root: Path, p: Path) -> str:
    return str(p.relative_to(root)).replace(os.sep, "/")


def strip_quotes(s: str) -> str:
    return s[1:-1] if len(s) >= 2 and s[0] in "\"'`" and s[-1] == s[0] else s


def inventory(root: Path) -> dict:
    out: dict = {
        "root": str(root),
        "containers": {"dockerfiles": [], "compose": []},
        "apps": [],
        "env": {"read": {}, "secretish": [], "launchdarkly": [], "declared": {}},
        "launchdarkly": {"sdks": [], "evaluations": [], "keys": {"literal": [], "fromEnv": [], "fromConstant": []},
                          "aiConfigs": [], "contextAttributes": [], "unresolved": []},
        "hints": [],
        "flagCreation": {"mode": "unknown", "signals": []},
        "routes": [],
        "health": {"routes": [], "docker": []},
        "existing": {},
        "notes": [],
    }
    files = list(walk(root))
    by_name = {}
    for p in files:
        by_name.setdefault(p.name, []).append(p)

    # ---- existing depot files ----
    for name in ["demo.yaml", "DEMO.md", "ld/seed.json", "media/cover.png", ".github/workflows/publish.yml", ".dd/context.example.json"]:
        out["existing"][name] = (root / name).exists()

    # ---- package manifests: languages + LD SDKs ----
    def add_sdk(kind, source):
        if {"kind": kind, "source": source} not in out["launchdarkly"]["sdks"]:
            out["launchdarkly"]["sdks"].append({"kind": kind, "source": source})

    for p in by_name.get("package.json", []):
        try:
            pkg = json.loads(read(p))
        except Exception:
            continue
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        app = {"path": rel(root, p.parent), "language": "node", "name": pkg.get("name"),
               "scripts": {k: v for k, v in (pkg.get("scripts") or {}).items() if k in ("start", "dev", "build")},
               "framework": next((f for f in ["next", "express", "fastify", "koa", "@remix-run/node", "nuxt", "vite", "react"] if f in deps), None)}
        out["apps"].append(app)
        for d in deps:
            if d in LD_SDK_PACKAGES:
                add_sdk(LD_SDK_PACKAGES[d], f"{rel(root, p)} ({d})")
    for p in by_name.get("requirements.txt", []) + by_name.get("pyproject.toml", []) + by_name.get("Pipfile", []):
        text = read(p)
        out["apps"].append({"path": rel(root, p.parent), "language": "python",
                            "framework": next((f for f in ["flask", "fastapi", "django", "streamlit", "gradio"] if re.search(rf"^\s*{f}\b", text, re.I | re.M)), None)})
        for d, kind in LD_SDK_PACKAGES.items():
            if re.search(rf"^\s*{re.escape(d)}\b", text, re.I | re.M):
                add_sdk(kind, rel(root, p))
        if re.search(r"^\s*ldclient\s*(==|>=|$)", text, re.M):
            out["notes"].append(f"{rel(root, p)}: pins `ldclient`, which on PyPI is an unrelated package that shadows the LaunchDarkly SDK's module; remove it (the SDK is launchdarkly-server-sdk)")
    for p in by_name.get("go.mod", []):
        text = read(p)
        out["apps"].append({"path": rel(root, p.parent), "language": "go"})
        if "github.com/launchdarkly/go-server-sdk" in text:
            add_sdk("go-server", rel(root, p))

    # ---- Dockerfiles ----
    for p in files:
        if p.name.lower() in ("dockerfile",) or p.name.lower().startswith("dockerfile."):
            text = read(p)
            info = {
                "path": rel(root, p),
                "context": rel(root, p.parent),
                "base": re.findall(r"^FROM\s+(\S+)", text, re.M),
                "expose": [int(x) for x in re.findall(r"^EXPOSE\s+(\d+)", text, re.M)],
                "cmd": (re.findall(r"^(?:CMD|ENTRYPOINT)\s+(.+)$", text, re.M) or [None])[-1],
                "healthcheck": (re.findall(r"^HEALTHCHECK.*?CMD\s+(.+)$", text, re.M | re.S) or [None])[0],
                "user": bool(re.search(r"^USER\s+\S+", text, re.M)),
                "multiStage": len(re.findall(r"^FROM\s", text, re.M)) > 1,
                "arm64Concerns": [],
            }
            if re.search(r"--platform=linux/amd64", text):
                info["arm64Concerns"].append("hardcodes --platform=linux/amd64")
            for b in info["base"]:
                if re.search(r"(^|/)(?:[\w.-]+-)?(alpine|slim|bookworm|bullseye)", b) is None and ":" not in b:
                    info["arm64Concerns"].append(f"unpinned base {b}")
            if info["healthcheck"]:
                m = re.search(r"(https?://[^\s\"']+)", info["healthcheck"])
                if m:
                    out["health"]["docker"].append({"dockerfile": info["path"], "url": m.group(1)})
                    if re.search(r"://[^/]+/?$", m.group(1)):
                        out["notes"].append(f"{info['path']}: HEALTHCHECK probes / (a full page render); point it at a cheap health route such as /healthz")
            out["containers"]["dockerfiles"].append(info)

    # ---- docker-compose ----
    for p in files:
        if re.match(r"(docker-)?compose.*\.ya?ml$", p.name):
            text = read(p)
            svc_block = re.search(r"^services:\s*\n((?:[ \t]+.*\n|\n)*)", text, re.M)
            services = re.findall(r"^\s{2}([\w-]+):\s*$", svc_block.group(1) if svc_block else text, re.M)
            ports = re.findall(r"-\s*['\"]?(\d+):(\d+)['\"]?", text)
            env_keys = re.findall(r"^\s+-\s*([A-Z][A-Z0-9_]*)=", text, re.M) + re.findall(r"^\s+([A-Z][A-Z0-9_]*):\s*\S", text, re.M)
            out["containers"]["compose"].append({"path": rel(root, p), "services": services,
                                                 "ports": [{"host": int(h), "container": int(c)} for h, c in ports],
                                                 "env": sorted(set(env_keys))})

    # ---- .env examples ----
    for p in files:
        if re.match(r"\.env(\.example|\.sample|\.template)?$", p.name) and p.name != ".env":
            for line in read(p).splitlines():
                m = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)", line)
                if m:
                    out["env"]["declared"][m.group(1)] = {"file": rel(root, p), "example": m.group(2)[:40]}

    # ---- code scan ----
    env_counts: dict[str, set] = {}
    attrs: set = set()
    for p in files:
        if p.suffix not in CODE_EXTS:
            continue
        text = read(p)
        if not text:
            continue
        r = rel(root, p)
        for rx in ENV_READ_RES[:-1]:
            for name in rx.findall(text):
                env_counts.setdefault(name, set()).add(r)
        for m in EVAL_CALL_RE.finditer(text):
            arg = m.group("arg")
            line = text.count("\n", 0, m.start()) + 1
            entry = {"file": r, "line": line, "call": m.group("fn"), "arg": arg}
            if arg[0] in "\"'`":
                key = strip_quotes(arg)
                entry["key"] = key
                out["launchdarkly"]["keys"]["literal"].append(key)
            else:
                # identifier: look for a constant or env assignment in the same file
                ident = arg.split(".")[-1].split("[")[0]
                const = re.search(rf"(?:const|let|var)?\s*\b{re.escape(ident)}\s*=\s*(\"[^\"]+\"|'[^']+')", text)
                envm = re.search(rf"\b{re.escape(ident)}\s*=\s*(?:process\.env\.(\w+)|os\.environ(?:\.get)?\s*[\[(]\s*['\"](\w+)['\"]|os\.getenv\(\s*['\"](\w+)['\"])", text)
                if const:
                    entry["key"] = strip_quotes(const.group(1)); entry["via"] = f"constant {ident}"
                    out["launchdarkly"]["keys"]["fromConstant"].append(entry["key"])
                elif envm:
                    env_name = next(g for g in envm.groups() if g)
                    entry["envVar"] = env_name; entry["via"] = f"env {env_name}"
                    out["launchdarkly"]["keys"]["fromEnv"].append(env_name)
                else:
                    entry["via"] = f"identifier {ident} (unresolved)"
                    out["launchdarkly"]["unresolved"].append(entry)
            out["launchdarkly"]["evaluations"].append(entry)
        for m in AI_CALL_RE.finditer(text):
            out["launchdarkly"]["aiConfigs"].append({"file": r, "arg": strip_quotes(m.group(1))})
        for m in re.finditer(r"\.set\(\s*['\"](\w+)['\"]\s*,", text):  # Context.builder().set("plan", ...)
            if m.group(1) not in ("kind", "key", "anonymous"):
                attrs.add(m.group(1))
        for m in re.finditer(r"kind\s*[:=]\s*['\"](\w+)['\"]", text):
            attrs.add(f"kind:{m.group(1)}")
        for rx, how in LISTEN_RES:
            for m in rx.finditer(text):
                port = next((g for g in reversed(m.groups()) if g and g.isdigit()), None)
                if port:
                    out.setdefault("_ports", []).append({"file": r, "port": int(port), "how": how})
        if HOST_LOOPBACK_RE.search(text):
            out["notes"].append(f"{r}: binds to loopback; the depot needs 0.0.0.0")
        for rx in ROUTE_RES:
            for m in rx.finditer(text):
                out["routes"].append({"file": r, "path": m.group(1)})
                if m.group(1) in HEALTH_PATHS:
                    out["health"]["routes"].append({"file": r, "path": m.group(1)})
        # comments that hint at targeting, and anything that says flags get created at demo time
        for i, line in enumerate(text.splitlines(), 1):
            if re.match(r"\s*(#|//|/\*|\*|'''|\"\"\")", line) and TARGETING_HINT_RE.search(line):
                out["hints"].append({"file": r, "line": i, "text": line.strip()[:160], "kind": "comment"})
            if DEMO_TIME_RE.search(line):
                out["flagCreation"]["signals"].append({"file": r, "line": i, "text": line.strip()[:160]})
    # companion shell scripts (rollout scripts, seeders): env they use is not the app's env
    script_env: dict[str, set] = {}
    for p in files:
        if p.suffix == ".sh" or p.name.lower() in ("makefile", "justfile"):
            for name in re.findall(r"\$\{?([A-Z][A-Z0-9_]{2,})\}?", read(p)):
                script_env.setdefault(name, set()).add(rel(root, p))
    out["env"]["scripts"] = {k: sorted(v) for k, v in sorted(script_env.items()) if k not in env_counts}
    # Flag helper wrappers: a module that imports the SDK and exports functions calling variation().
    # Demos often route every evaluation through one (isEnabled("key", ctx)); follow those names.
    wrappers: dict[str, str] = {}
    for p in files:
        if p.suffix not in CODE_EXTS:
            continue
        text = read(p)
        if not re.search(r"launchdarkly|ldclient", text, re.I) or not re.search(r"\b[Vv]ariation(?:Detail)?\s*\(", text):
            continue
        for m in re.finditer(r"export\s+(?:async\s+)?function\s+(\w+)\s*\(\s*(\w+)", text):
            fn, first = m.group(1), m.group(2)
            body_start = text.find("{", m.end())
            body = text[body_start : body_start + 2500]
            if re.search(r"[Vv]ariation(?:Detail)?\s*\(\s*" + re.escape(first) + r"\b", body):
                wrappers[fn] = rel(root, p)
        for m in re.finditer(r"(?:export\s+)?(?:def|func)\s+(\w+)\s*\(\s*(?:self,\s*)?(\w+)", text):
            fn, first = m.group(1), m.group(2)
            body = text[m.end() : m.end() + 2500]
            if re.search(r"[Vv]ariation(?:_detail)?\s*\(\s*" + re.escape(first) + r"\b", body):
                wrappers[fn] = rel(root, p)
    if wrappers:
        out["launchdarkly"]["wrappers"] = wrappers
        call_re = re.compile(r"\b(" + "|".join(map(re.escape, wrappers)) + r")\s*\(\s*(\"[^\"]+\"|'[^']+'|`[^`]+`)")
        for p in files:
            if p.suffix not in CODE_EXTS:
                continue
            text = read(p)
            r = rel(root, p)
            if re.search(r"(^|/)(tests?|__tests__|spec)/|\.(test|spec)\.", r):
                continue  # test fixtures aren't the demo's flags
            for m in call_re.finditer(text):
                if r == wrappers.get(m.group(1)):
                    continue  # the wrapper's own definition
                key = strip_quotes(m.group(2))
                line = text.count("\n", 0, m.start()) + 1
                out["launchdarkly"]["evaluations"].append({"file": r, "line": line, "call": m.group(1), "arg": m.group(2), "key": key, "via": f"wrapper {m.group(1)}"})
                out["launchdarkly"]["keys"]["literal"].append(key)
        # the wrapper's own variable-key call is not an unresolved evaluation
        out["launchdarkly"]["unresolved"] = [u for u in out["launchdarkly"]["unresolved"] if u["file"] not in set(wrappers.values())]
    out["env"]["read"] = {k: sorted(v) for k, v in sorted(env_counts.items())}
    injected = {"LD_SDK_KEY", "LD_CLIENT_SIDE_ID", "LD_MOBILE_KEY", "LD_PROJECT_KEY", "LD_ENV_KEY", "LD_API_TOKEN", "DD_PUBLIC_URL", "DD_INSTANCE_ID"}
    for name in sorted(set(env_counts) | set(script_env)):
        if name in injected or not re.search(r"LD_|LAUNCHDARKLY", name):
            continue
        near = {"LD_ENVIRONMENT_KEY": "LD_ENV_KEY", "LD_ENV": "LD_ENV_KEY", "LD_PROJECT": "LD_PROJECT_KEY", "LAUNCHDARKLY_SDK_KEY": "LD_SDK_KEY",
                "LD_SERVER_KEY": "LD_SDK_KEY", "LD_CLIENT_ID": "LD_CLIENT_SIDE_ID", "LD_CLIENT_KEY": "LD_CLIENT_SIDE_ID",
                "LAUNCHDARKLY_CLIENT_SIDE_ID": "LD_CLIENT_SIDE_ID", "LD_ACCESS_TOKEN": "LD_API_TOKEN"}.get(name)
        if near:
            who = "the app" if name in env_counts else "a script"
            out["notes"].append(f"{who} reads {name}; the depot injects {near}. Map it with launchdarkly.inject (app) or pass it explicitly (script).")
    out["env"]["secretish"] = sorted(k for k in env_counts if SECRETISH_RE.search(k) and k not in LD_INJECTED)
    out["env"]["launchdarkly"] = sorted(k for k in env_counts if k in LD_INJECTED or "LD_" in k or "LAUNCHDARKLY" in k)
    out["launchdarkly"]["contextAttributes"] = sorted(attrs)
    ports = out.pop("_ports", [])
    if ports:
        out["apps"].append({"path": ".", "language": "ports", "listen": ports})

    # ---- docs: README and friends ----
    for p in files:
        if p.suffix in DOC_EXTS and p.name.lower() not in ("demo.md",):
            text = read(p)
            for i, line in enumerate(text.splitlines(), 1):
                if TARGETING_HINT_RE.search(line) and ATTR_HINT_RE.search(line):
                    out["hints"].append({"file": rel(root, p), "line": i, "text": line.strip()[:200], "kind": "doc"})
                if DEMO_TIME_RE.search(line):
                    out["flagCreation"]["signals"].append({"file": rel(root, p), "line": i, "text": line.strip()[:200]})
    # shell scripts and infra files that create or delete flags outside the seed
    for p in files:
        r = rel(root, p)
        if DEMO_TIME_FILE_RE.search(r):
            out["flagCreation"]["signals"].append({"file": r, "line": 0, "text": "file present: flags are managed by a tool other than the seed"})
        elif p.suffix == ".sh":
            for i, line in enumerate(read(p).splitlines(), 1):
                if re.search(r"/api/v2/flags|ldcli|ld-cli|launchdarkly_feature_flag", line):
                    out["flagCreation"]["signals"].append({"file": r, "line": i, "text": line.strip()[:160]})
    # verdict: dynamic keys + creation signals => demo-time; literal keys only => seed; both => mixed
    ld = out["launchdarkly"]
    literal = bool(ld["keys"]["literal"] or ld["keys"]["fromConstant"])
    dynamic = bool(ld["unresolved"] or ld["keys"]["fromEnv"])
    signals = len(out["flagCreation"]["signals"]) > 0
    if signals and not literal:
        out["flagCreation"]["mode"] = "demo-time"
    elif signals and literal:
        out["flagCreation"]["mode"] = "mixed"
    elif literal:
        out["flagCreation"]["mode"] = "seed"
    elif dynamic:
        out["flagCreation"]["mode"] = "dynamic"
    out["flagCreation"]["dynamicKeys"] = dynamic
    for k in ("literal", "fromEnv", "fromConstant"):
        out["launchdarkly"]["keys"][k] = sorted(set(out["launchdarkly"]["keys"][k]))
    return out


def report(inv: dict) -> str:
    L = []
    L.append(f"# Inventory of {inv['root']}")
    L.append("\n## Containers")
    for d in inv["containers"]["dockerfiles"]:
        L.append(f"- {d['path']}: base {', '.join(d['base']) or '?'}; EXPOSE {d['expose'] or '?'}; CMD {d['cmd'] or '?'}; "
                 f"healthcheck {'yes' if d['healthcheck'] else 'no'}; non-root {'yes' if d['user'] else 'no'}"
                 + (f"; arm64: {', '.join(d['arm64Concerns'])}" if d['arm64Concerns'] else ""))
    for c in inv["containers"]["compose"]:
        L.append(f"- {c['path']}: services {c['services']}; ports {c['ports']}; env {c['env']}")
    if not inv["containers"]["dockerfiles"]:
        L.append("- no Dockerfile: one has to be written (see assets/Dockerfile.node)")
    L.append("\n## Apps and ports")
    for a in inv["apps"]:
        L.append(f"- {json.dumps(a)}")
    L.append("\n## Routes (candidates for verify.http)")
    seen = []
    for r in inv["routes"]:
        if r["path"] not in seen:
            seen.append(r["path"])
    L.append(f"- {seen[:30] or 'none found'}")
    L.append("\n## Health")
    L.append(f"- routes: {inv['health']['routes'] or 'none found; add /healthz'}")
    L.append(f"- docker: {inv['health']['docker'] or 'none'}")
    L.append("\n## Env vars the code reads")
    for k, v in inv["env"]["read"].items():
        tag = " (LaunchDarkly)" if k in inv["env"]["launchdarkly"] else (" (secret-like → parameters[].secret or container secrets)" if k in inv["env"]["secretish"] else "")
        L.append(f"- {k}{tag}: {', '.join(v[:3])}")
    if inv["env"].get("scripts"):
        L.append(f"- used only by shell scripts (not the app): {', '.join(sorted(inv['env']['scripts']))}")
    if inv["env"]["declared"]:
        L.append(f"- declared in env examples: {', '.join(sorted(inv['env']['declared']))}")
    L.append("\n## LaunchDarkly")
    L.append(f"- SDKs: {inv['launchdarkly']['sdks'] or 'none detected'}")
    if inv["launchdarkly"].get("wrappers"):
        L.append(f"- flag helper wrappers followed: {inv['launchdarkly']['wrappers']}")
    L.append(f"- flag keys (literal): {inv['launchdarkly']['keys']['literal'] or '-'}")
    L.append(f"- flag keys from constants: {inv['launchdarkly']['keys']['fromConstant'] or '-'}")
    L.append(f"- flag keys from env vars: {inv['launchdarkly']['keys']['fromEnv'] or '-'}  ← these need a default key in the seed and a parameter (or a fixed value)")
    L.append(f"- AI Configs: {inv['launchdarkly']['aiConfigs'] or '-'}")
    L.append(f"- context attributes set in code: {inv['launchdarkly']['contextAttributes'] or '-'}")
    if inv["launchdarkly"]["unresolved"]:
        L.append(f"- unresolved evaluation arguments: {[(u['file'], u['line'], u['arg']) for u in inv['launchdarkly']['unresolved']]}")
    fc = inv["flagCreation"]
    L.append("\n## Who creates the flags")
    verdict = {
        "seed": "the seed: every key is a literal in code and nothing else creates flags",
        "demo-time": "SOMETHING ELSE creates flags while the demo runs (GitHub App, Vega, Terraform, CLI, API script). Do NOT put those flags in ld/seed.json; document them in DEMO.md as created during the demo",
        "mixed": "both: some keys are literals in code AND the docs describe flags being created during the demo. Read the signals and decide per flag; anything the story creates live stays out of the seed",
        "dynamic": "flag keys are decided at runtime (env var or computed), no creation signals found. Seed a default key and expose the env var as a parameter, or confirm with the owner",
        "unknown": "no flag keys and no creation signals found",
    }[fc["mode"]]
    L.append(f"- verdict: {fc['mode']} → {verdict}")
    for sgn in fc["signals"][:15]:
        L.append(f"- {sgn['file']}:{sgn['line']}: {sgn['text']}")
    if len(fc["signals"]) > 15:
        L.append(f"- … {len(fc['signals']) - 15} more")
    L.append("\n## Targeting hints (from docs and comments)")
    for h in inv["hints"][:40]:
        L.append(f"- {h['file']}:{h['line']} ({h['kind']}): {h['text']}")
    if len(inv["hints"]) > 40:
        L.append(f"- … {len(inv['hints']) - 40} more")
    L.append("\n## Existing depot files")
    L.append("- " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in inv["existing"].items()))
    if inv["notes"]:
        L.append("\n## Notes")
        L.extend(f"- {n}" for n in inv["notes"])
    return "\n".join(L)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0] if args else ".").resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        sys.exit(2)
    inv = inventory(root)
    if "--report" in sys.argv:
        print(report(inv))
    else:
        print(json.dumps(inv, indent=2))


if __name__ == "__main__":
    main()
