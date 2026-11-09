#!/usr/bin/env python3
"""Read-only audit of a candidate DSH npm tree against DSHA's exact-byte patches.

This tool never mutates the production runtime, patch recipes, or user data.
The output is a compatibility *triage*, not an approval to ship an APK.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "app/src/main/assets"
TARGET = "0.2.2-rc.1"
BASE = "0.2.1-rc.2"
REQUIRED_BUILDER_FILES = (
    "@deepseek-ai/dsh/lib/bin.js",
    "@deepseek-ai/dsh-llm-deepseek/lib/index.js",
    "@deepseek-ai/dsh-client-modules/lib/index.js",
    "@deepseek-ai/dsh-client-ui-conversation/lib/client.js",
    "@deepseek-ai/dsh-settings/lib/index.js",
    "@deepseek-ai/dsh-storage-json/lib/index.js",
    "@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js",
    "@deepseek-ai/dsh-session-format-v2-to-v3/lib/index.js",
)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def safe_path(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Unsafe or missing relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("Unsafe relative path: " + value)
    return path


def find_module(install, module):
    relative = safe_path(module)
    candidates = (
        install / "node_modules" / str(relative),
        install / "node_modules/@deepseek-ai/dsh/node_modules" / str(relative),
    )
    for path in candidates:
        if path.is_file() and not path.is_symlink():
            return path
    return None


def patch_plan():
    registry = read_json(ASSETS / "runtime-patches.json")
    if registry.get("schema") != 1 or registry.get("dshVersion") != BASE:
        raise ValueError("Refusing to audit an unexpected or edited DSHA patch baseline")
    groups = defaultdict(list)
    seen = set()
    for row in registry["active"]:
        name = str(safe_path(row["asset"]))
        if name in seen:
            raise ValueError("Duplicate active patch: " + name)
        seen.add(name)
        spec = read_json(ASSETS / name)
        if spec.get("dshVersion") != BASE:
            raise ValueError("Unexpected patch version: " + name)
        module = str(safe_path(row.get("module", spec.get("module"))))
        groups[module].append((name, row, spec))
    return registry, groups


def test_patch_chain(data, steps):
    text = data.decode("utf-8")
    results = []
    for name, row, spec in steps:
        markers = row.get("markers", [])
        if markers and all(marker in text for marker in markers):
            results.append({"asset": name, "status": "already-present", "patches": len(spec["patches"])})
            continue
        if spec.get("canonicalSourceSha256"):
            original_sha = hashlib.sha256(data).hexdigest()
            if original_sha != spec["canonicalSourceSha256"]:
                results.append({"asset": name, "status": "source-sha-changed",
                                "patches": len(spec["patches"])})
                continue
        applied = 0
        issue = None
        for item in spec["patches"]:
            before, after = item["before"], item["after"]
            if "prependAsset" in item:
                helper = ASSETS / safe_path(item["prependAsset"])
                after = helper.read_text(encoding="utf-8") + "\n" + after
            if not before or not after or before == after:
                issue = "invalid-recipe"
                break
            n_before = text.count(before)
            n_after = text.count(after)
            # Mirroring stable-patch idempotency: the replacement may contain
            # the old anchor, but exactly one complete after-form must exist.
            if n_after == 1 and n_before == after.count(before):
                continue
            if n_before != 1 or n_after != 0:
                issue = "anchor-mismatch"
                break
            text = text.replace(before, after)
            applied += 1
        results.append({"asset": name, "status": issue or "applicable",
                        "patches": len(spec["patches"]), "applied": applied})
    return results


def audit(install):
    expected = read_json(ROOT / "tools/dsh-upgrade-candidate/package.json")
    if expected["version"] != TARGET or expected["dependencies"].get("@deepseek-ai/dsh") != TARGET:
        raise ValueError("Candidate manifest version drift")
    package = read_json(install / "package.json")
    lock = read_json(install / "package-lock.json")
    installed = read_json(install / "node_modules/@deepseek-ai/dsh/package.json")
    if package != expected or lock.get("version") != TARGET:
        raise ValueError("Candidate manifest/lock mismatch")
    if lock.get("lockfileVersion") != 3 or lock["packages"][""].get("dependencies") != expected["dependencies"]:
        raise ValueError("Candidate lock root differs from the pinned manifest")
    if lock["packages"].get("node_modules/@deepseek-ai/dsh", {}).get("version") != TARGET:
        raise ValueError("Candidate npm lock does not pin the requested DSH")
    if installed.get("version") != TARGET or installed.get("name") != "@deepseek-ai/dsh":
        raise ValueError("Actual npm installation is not the requested DSH")

    registry, grouped = patch_plan()
    results = []
    for module, steps in sorted(grouped.items()):
        file = find_module(install, module)
        if file is None:
            results.extend({"module": module, "asset": name, "status": "missing-module"}
                           for name, _, _ in steps)
            continue
        original = file.read_bytes()
        try:
            for row in test_patch_chain(original, steps):
                results.append({"module": module, **row})
        except (UnicodeError, KeyError, TypeError, ValueError):
            results.extend({"module": module, "asset": name, "status": "invalid-recipe"}
                           for name, _, _ in steps)
    required = [{"module": module, "present": find_module(install, module) is not None}
                for module in REQUIRED_BUILDER_FILES]
    specialized = registry.get("specialized", [])
    if not isinstance(specialized, list):
        raise ValueError("Invalid specialized-patch registry")
    stats = dict(Counter(row["status"] for row in results))
    blockers = sum(count for key, count in stats.items()
                   if key not in ("applicable", "already-present"))
    blockers += sum(not row["present"] for row in required)
    return {
        "schema": 1, "target": TARGET, "baseline": BASE,
        "source": "upstream npm-installed compiled JS (not upstream TS)",
        "caveat": "Anchor checks are necessary, not sufficient: behavior, native modules, data readers and Android integration remain unverified.",
        "activePatchCount": len(registry["active"]),
        "specializedNeedsManualReview": specialized,
        "patchResults": results, "patchSummary": stats,
        "builderRequiredFiles": required,
        "blockerCount": blockers,
        "promotionReady": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", type=Path, required=True,
                        help="Isolated npm install under app/build, not production assets")
    parser.add_argument("--output", type=Path, required=True,
                        help="JSON report under app/build")
    args = parser.parse_args()
    install = args.install.resolve()
    output = args.output.resolve()
    build = (ROOT / "app/build").resolve()
    if build not in install.parents or build not in output.parents:
        parser.error("Install and report must remain under app/build")
    report = audit(install)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print("DSH compatibility audit: " + json.dumps({
        "target": report["target"], "active": report["activePatchCount"],
        "statuses": report["patchSummary"], "blockers": report["blockerCount"],
        "needsManualReview": len(report["specializedNeedsManualReview"]),
        "report": str(output),
    }, ensure_ascii=False))
    for row in report["patchResults"]:
        if row["status"] not in ("applicable", "already-present"):
            print("BLOCKED patch:", row["asset"], "module:", row["module"],
                  "reason:", row["status"])
    for row in report["builderRequiredFiles"]:
        if not row["present"]:
            print("BLOCKED builder module:", row["module"])
    for item in report["specializedNeedsManualReview"]:
        print("REVIEW specialized:", item)
    if report["blockerCount"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
