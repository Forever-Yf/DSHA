#!/usr/bin/env python3
"""Fail closed on stale DSHA Android builtin peer requirements.

Run from the checked-out repository, against the locked DSH 0.2.2 dependency tree.
This is a manifest contract, NOT a substitute for real DSH profile startup.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "app/src/main/assets/builtin-plugins"
LOCK = ROOT / "tools/dsh-runtime/package-lock.json"
TARGET = "0.2.2-rc.1"
EXPECTED = {
    "dsh-device-shell-guide": {
        "version": "0.1.20",
        "peers": ("@deepseek-ai/dsh-system-prompt", "@deepseek-ai/dsh-llm"),
    },
    "dsh-computer-use-android": {
        "version": "0.1.2",
        "peers": ("@deepseek-ai/dsh-computer-use", "@deepseek-ai/dsh-mcp-client"),
    },
    "dsh-auto-review": {
        "version": "0.1.1",
        "peers": ("@deepseek-ai/dsh-experimental-auto-review",),
    },
    "dsh-tool-vscreen": {
        "version": "0.1.2",
        "peers": ("@deepseek-ai/dsh-mcp-client",),
    },
}


def validate():
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    packages = lock["packages"]
    if (packages["node_modules/@deepseek-ai/dsh"]["version"] != TARGET
            or packages[""]["dependencies"]["@deepseek-ai/dsh"] != TARGET):
        raise ValueError("DSHA_BUILTIN_PEER_LOCK_VERSION")
    evidence = {}
    for name, expected in EXPECTED.items():
        path = ASSETS / name / "package.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc["name"] != name or doc["version"] != expected["version"]:
            raise ValueError("DSHA_BUILTIN_VERSION_MISMATCH: " + name)
        peer = doc.get("peerDependencies", {})
        pinned = {k: v for k, v in peer.items() if k.startswith("@deepseek-ai/dsh-")}
        if set(pinned) != set(expected["peers"]):
            raise ValueError("DSHA_BUILTIN_PEERS_CHANGED: " + name)
        for package, requirement in pinned.items():
            if requirement != TARGET:
                raise ValueError("DSHA_BUILTIN_PEER_STALE: " + name + " " + package)
            entry = packages.get("node_modules/" + package)
            if not entry or entry.get("version") != TARGET:
                raise ValueError("DSHA_BUILTIN_PEER_MODULE_MISSING: " + package)
        if not (ASSETS / name / "lib/index.js").is_file():
            raise ValueError("DSHA_BUILTIN_ENTRY_MISSING: " + name)
        if not (ASSETS / name / "cordis.patch.yml").is_file():
            raise ValueError("DSHA_BUILTIN_PATCH_MISSING: " + name)
        evidence[name] = dict(version=doc["version"], peers=pinned)
    for name in ("dsh-computer-use-android", "dsh-tool-vscreen"):
        if not (ASSETS / name / "lib/server.cjs").is_file():
            raise ValueError("DSHA_BUILTIN_MCP_MISSING: " + name)
    return dict(status="PASS", dshVersion=TARGET, builtinCount=len(EXPECTED), evidence=evidence)


if __name__ == "__main__":
    try:
        print(json.dumps(validate(), ensure_ascii=False, sort_keys=True))
    except (OSError, KeyError, TypeError, ValueError) as error:
        print("BUILTIN_PEERS_INVALID: " + str(error), file=sys.stderr)
        raise SystemExit(1)
