#!/usr/bin/env python3
"""Verify published DSH LAN client semantics without weakening the Android host guard.

Use against the npm-ci-installed compiled JS, NOT an unbuilt TypeScript source file.
Unknown upstream versions or byte changes must fail closed and require a new review.
"""
import argparse
import hashlib
import json
from pathlib import Path

CANONICAL_MODULE = "@deepseek-ai/dsh-client-ui-settings/lib/client.js"
VERIFIED_VERSIONS = ["0.2.1-rc.2", "0.2.2-rc.1"]


def validate(source: bytes, contract: dict) -> None:
    if (contract.get("schema") != 1
            or contract.get("module") != CANONICAL_MODULE
            or contract.get("dshVersion") != VERIFIED_VERSIONS[0]
            or contract.get("verifiedDshVersions") != VERIFIED_VERSIONS):
        raise ValueError("LAN_SETTINGS_CONTRACT")
    if hashlib.sha256(source).hexdigest() != contract.get("sourceSha256"):
        raise ValueError("LAN_SETTINGS_SOURCE_MISMATCH")
    decoded = source.decode("utf-8", errors="strict")
    if (not isinstance(contract.get("requiredAnchors"), list)
            or len(contract["requiredAnchors"]) != 4
            or not isinstance(contract.get("forbiddenAnchors"), list)
            or len(contract["forbiddenAnchors"]) != 2):
        raise ValueError("LAN_SETTINGS_CONTRACT")
    if any(not isinstance(a, str) or not a or decoded.count(a) != 1
           for a in contract["requiredAnchors"]):
        raise ValueError("LAN_SETTINGS_HOST_SEMANTICS")
    if any(not isinstance(a, str) or not a or a in decoded
           for a in contract["forbiddenAnchors"]):
        raise ValueError("LAN_SETTINGS_HOST_SEMANTICS")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-modules", type=Path, required=True)
    parser.add_argument("--contract", type=Path,
                        default=Path("app/src/main/assets/lan-settings-upstream-contract.json"))
    args = parser.parse_args()
    manifest = args.node_modules / "@deepseek-ai/dsh/package.json"
    package = json.loads(manifest.read_text(encoding="utf-8"))
    if package.get("name") != "@deepseek-ai/dsh" or package.get("version") != "0.2.2-rc.1":
        raise ValueError("LAN_SETTINGS_RUNTIME_VERSION")
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    source = (args.node_modules / CANONICAL_MODULE).read_bytes()
    validate(source, contract)
    # Negative controls: approval must depend on source bytes and exact version list.
    try:
        validate(source + b"\n", contract)
        raise AssertionError("LAN_SETTINGS_MUTATION_FALSE_ACCEPT")
    except ValueError as error:
        if str(error) != "LAN_SETTINGS_SOURCE_MISMATCH":
            raise
    changed = dict(contract, verifiedDshVersions=["0.2.1-rc.2", "0.2.3-rc.1"])
    try:
        validate(source, changed)
        raise AssertionError("LAN_SETTINGS_VERSION_FALSE_ACCEPT")
    except ValueError as error:
        if str(error) != "LAN_SETTINGS_CONTRACT":
            raise
    print(json.dumps({
        "status": "PASS",
        "dshVersion": package["version"],
        "module": CANONICAL_MODULE,
        "moduleSha256": hashlib.sha256(source).hexdigest(),
        "verifiedDshVersions": VERIFIED_VERSIONS,
        "negativeControls": ["byte-drift", "unsupported-version"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
