#!/usr/bin/env python3
"""Validate source-unit reuse receipts and the assets in actual release archives."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LEDGER = "docs/integrations/reuse-ledger.json"
REQUIRED_BLOCKS = set(
    "renderer-grant mcptube-grant imagebind-commercial musicgen-commercial qwen-uncleared-assets foreign-runtime-transitives community-qwen-grant".split()
)
BLOCKED_COPY_REPOS = {
    "0xchamin/mcptube",
    "prajwal-y/video_explainer",
    "HKUDS/VideoRAG",
    "QwenLM/Qwen-MM-Plugins",
}
ROUTES = {
    "own-source",
    "independent-implementation",
    "independent-adapter",
    "copy",
    "adapt",
    "import",
}
ASSET_SUFFIXES = set(
    ".ttf .otf .woff .woff2 .mp3 .wav .ogg .flac .m4a .mp4 .webm .mov .png .jpg .jpeg .gif .webp .svg .pt .pth .onnx .safetensors .bin .exe .dll .so .dylib .zip .gz .pdf .docx .blend .fcstd .glb .gltf".split()
)


def sha256(data: bytes) -> str:
    """Return the content digest used by file and lock receipts."""
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    """Reject a failed receipt requirement."""
    if not condition:
        raise ValueError(message)


def safe_path(name: str) -> bool:
    """Allow only relative POSIX paths without traversal or alternate separators."""
    return (
        not PurePosixPath(name).is_absolute()
        and ".." not in PurePosixPath(name).parts
        and "\\" not in name
    )


def validate_file_receipt(root: Path, receipt: dict, notices: str) -> None:
    """Check an actual transfer or bundled asset against its reproduced grant."""
    path = receipt["target_path"]
    require(safe_path(path), "Unsafe receipt target path")
    require(
        sha256((root / path).read_bytes()) == receipt["target_sha256"], f"Target hash drift: {path}"
    )
    require(receipt["commercial_redistribution"] is True, f"Uncleared commercial asset: {path}")
    require(
        "-NC" not in receipt["license"].upper() and "UNKNOWN" not in receipt["license"].upper(),
        f"Restricted asset license: {path}",
    )
    for field in ("license_text", "copyright", "change_notice"):
        require(
            bool(receipt[field].strip()) and receipt[field] in notices,
            f"Missing {field} notice: {path}",
        )
    require(
        bool(receipt["license_source"]) and bool(receipt["license"]),
        f"Missing grant source: {path}",
    )


def validate_adoption(root: Path, unit: dict, component: dict, notices: str, imports: set) -> None:
    """Require real file/import evidence and block uncleared copying routes."""
    key, route = unit["unit_key"], unit["permitted_route"]
    require(route in ROUTES, f"Unknown route: {key}")
    require(
        route != "own-source" or unit["source_repo"] == "Galbaz1/video-research-mcp",
        f"Foreign source labelled own: {key}",
    )
    require(unit["adoption"] in {"not-adopted", "adopted"}, f"Unknown adoption state: {key}")
    receipts = unit["transfers"] + unit["imports"] + unit["implementations"]
    adopted = unit["adoption"] == "adopted"
    require(bool(receipts) == adopted, f"Missing or premature adoption receipt: {key}")
    if route in {"copy", "adapt", "import"}:
        require(adopted, f"Missing adoption receipt: {key}")
        require(
            component["clearance"] == "verified-code-grant", f"Blocked component clearance: {key}"
        )
        require(component["commercial_code_use"] is True, f"Blocked source grant: {key}")
        require(
            component["repo"] not in BLOCKED_COPY_REPOS,
            f"Per-file grant not cleared for copying: {key}",
        )
    require(
        not unit["transfers"] or route in {"copy", "adapt", "own-source"},
        f"Transfer contradicts route: {key}",
    )
    require(not unit["imports"] or route == "import", f"Import contradicts route: {key}")
    for implementation in unit["implementations"]:
        path = implementation["target_path"]
        require(safe_path(path), "Unsafe implementation path")
        require(
            sha256((root / path).read_bytes()) == implementation["target_sha256"],
            f"Implementation hash drift: {key}",
        )
    for transfer in unit["transfers"]:
        require(len(transfer["source_sha256"]) == 64, f"Missing source hash: {key}")
        source = transfer["source_path"]
        require(
            any(
                source == p or source.startswith(p.rstrip("/") + "/") for p in unit["source_paths"]
            ),
            f"Source path outside unit: {key}",
        )
        validate_file_receipt(root, transfer, notices)
    for imported in unit["imports"]:
        require((imported["name"], imported["version"]) in imports, f"Unreceipted import: {key}")


def validate_units(root: Path, ledger: dict, notices: str) -> None:
    """Keep every pinned unit accounted for without treating plans as adoption."""
    inventory = json.loads((root / ledger["inventory"]).read_text())
    audited = {u["key"]: u for lane in inventory["source_lanes"].values() for u in lane["units"]}
    units = {u["unit_key"]: u for u in ledger["units"]}
    require(len(units) == len(ledger["units"]), "Duplicate source unit")
    require(units.keys() == audited.keys(), "Source-unit coverage differs from pinned inventory")
    components = {c["repo"] + "@" + c["revision"]: c for c in ledger["components"]}
    imports = {(p["name"], p["version"]) for p in ledger["dependency_packages"]}
    for key, unit in units.items():
        for field in ("source_repo", "source_revision", "source_paths"):
            require(unit[field] == audited[key][field], f"Source contract drift: {key}/{field}")
        component = components[unit["component"]]
        require(component["repo"] == unit["source_repo"], f"Component mismatch: {key}")
        require(
            component["revision"] == unit["source_revision"], f"Component revision mismatch: {key}"
        )
        require(bool(component["license_receipts"]), f"Missing component grant receipt: {key}")
        validate_adoption(root, unit, component, notices, imports)


def validate_locks(root: Path, ledger: dict) -> None:
    """Bind exact Python locks and registry artifacts to observation receipts."""
    expected = {
        "uv.lock",
        "packages/video-agent-mcp/uv.lock",
        "packages/video-explainer-mcp/uv.lock",
    }
    require(
        {r["path"] for r in ledger["dependency_locks"]} == expected,
        "Missing dependency lock receipt",
    )
    packages = {(p["name"], p["version"]): p for p in ledger["dependency_packages"]}
    seen = set()
    for receipt in ledger["dependency_locks"]:
        path = root / receipt["path"]
        data = path.read_bytes()
        require(sha256(data) == receipt["sha256"], f"Dependency lock hash drift: {path}")
        locked = [
            p for p in tomllib.loads(data.decode())["package"] if "registry" in p.get("source", {})
        ]
        identities = sorted(
            [{"name": p["name"], "version": p["version"]} for p in locked],
            key=lambda p: (p["name"], p["version"]),
        )
        require(identities == receipt["registry_packages"], f"Dependency population drift: {path}")
        for package in locked:
            key = package["name"], package["version"]
            require(key in packages, f"Missing dependency package receipt: {key}")
            seen.add(key)
            evidence = packages[key]
            require(
                evidence["registry_url"].startswith("https://pypi.org/pypi/"),
                f"Non-authoritative registry receipt: {key}",
            )
            require(len(evidence["registry_sha256"]) == 64, f"Missing registry digest: {key}")
            hashes = {a["hash"].removeprefix("sha256:") for a in package.get("wheels", [])}
            if "sdist" in package:
                hashes.add(package["sdist"]["hash"].removeprefix("sha256:"))
            require(
                hashes <= set(evidence["registry_artifact_hashes"]),
                f"Unreceipted dependency artifact: {key}",
            )
    require(seen == packages.keys(), "Dependency receipt population differs from locks")


def validate_ledger(root: Path = ROOT, ledger: dict | None = None) -> dict:
    """Validate the current source population, dispositions and dependency locks."""
    if ledger is None:
        ledger = json.loads((root / LEDGER).read_text())
    require(ledger["schema_version"] == 1, "Unsupported reuse ledger schema")
    notices = (root / "THIRD_PARTY_NOTICES.md").read_text()
    require(
        {b["id"] for b in ledger["blocks"]} == REQUIRED_BLOCKS, "Missing operational disposition"
    )
    for block in ledger["blocks"]:
        require(
            bool(block["blocked"]) and bool(block["alternative"]),
            f"Incomplete disposition: {block['id']}",
        )
    validate_units(root, ledger, notices)
    validate_locks(root, ledger)
    agents = next(p for p in ledger["dependency_packages"] if p["name"] == "weaviate-agents")
    grant = agents["source_grant"]
    require(sha256(grant["text"].encode()) == grant["sha256"], "Dependency grant hash drift")
    require(grant["text"].strip() in notices, "Missing full verified dependency grant")
    for asset in ledger["bundled_assets"]:
        validate_file_receipt(root, asset, notices)
    require(
        not ledger["optional_runtime_receipts"],
        "Optional runtime activation requires its own programme gate",
    )
    return ledger


def archive_members(path: Path) -> list[tuple[str, bytes]]:
    """Read regular members without extracting links, unsafe paths or duplicates."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [m.filename for m in archive.infolist()]
            require(
                all((m.external_attr >> 16) & 0o170000 != 0o120000 for m in archive.infolist()),
                "Archive contains a symlink",
            )
            items = [(m.filename, archive.read(m)) for m in archive.infolist() if not m.is_dir()]
    else:
        with tarfile.open(path) as archive:
            names = [m.name for m in archive.getmembers()]
            require(
                all(m.isdir() or m.isfile() for m in archive.getmembers()),
                "Archive contains a link or special member",
            )
            items = [
                (m.name, archive.extractfile(m).read()) for m in archive.getmembers() if m.isfile()
            ]
        require(len({n.split("/")[0] for n in names}) == 1, "Archive has multiple package roots")
    require(len(names) == len(set(names)), "Archive contains duplicate members")
    require(all(safe_path(n) for n in names), "Archive contains an unsafe path")
    return items


def archive_package(members: dict, is_wheel: bool) -> str:
    """Identify the package from its actual embedded metadata."""
    if is_wheel:
        metadata = [data for n, data in members.items() if n.endswith(".dist-info/METADATA")]
        require(len(metadata) == 1, "Expected one wheel package metadata")
        name = BytesParser().parsebytes(metadata[0])["Name"]
    elif "package.json" in members:
        name = json.loads(members["package.json"])["name"]
    else:
        require("pyproject.toml" in members, "Missing archive package metadata")
        name = tomllib.loads(members["pyproject.toml"].decode())["project"]["name"]
    require(
        name in {"video-research-mcp", "video-explainer-mcp", "video-agent-mcp"},
        "Unknown archive package",
    )
    return name


def check_archive(path: Path, root: Path = ROOT, ledger: dict | None = None) -> dict:
    """Reject unreceipted archive assets and missing or stale distribution notices."""
    ledger = validate_ledger(root, ledger)
    members = archive_members(path)
    assets = {r["target_path"]: r for r in ledger["bundled_assets"]}
    is_wheel = path.suffix == ".whl"
    normalized = [(n if is_wheel else n.split("/", 1)[-1], data) for n, data in members]
    by_name = dict(normalized)
    if archive_package(by_name, is_wheel) == "video-research-mcp":
        required = {
            "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.md",
            "reuse-ledger.json" if is_wheel else LEDGER: LEDGER,
        }
        for name, source in required.items():
            require(
                by_name.get(name) == (root / source).read_bytes(),
                f"Missing or stale archive receipt: {name}",
            )
    require(
        any(
            PurePosixPath(n).name == "LICENSE" and b"MIT License" in data for n, data in normalized
        ),
        "Missing archive MIT grant",
    )
    for name, data in normalized:
        binary = b"\x00" in data
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            binary = True
        if binary or PurePosixPath(name).suffix.lower() in ASSET_SUFFIXES:
            require(name in assets, f"Unreceipted archive asset: {name}")
            require(
                sha256(data) == assets[name]["target_sha256"], f"Archive asset hash drift: {name}"
            )
    return {
        "archive": str(path),
        "sha256": sha256(path.read_bytes()),
        "files": len(members),
        "assets": len(assets),
    }


def main() -> None:
    """Run the offline source/lock gate and optional exact archive checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, action="append", default=[])
    args = parser.parse_args()
    try:
        ledger = validate_ledger()
        archives = [check_archive(path, ledger=ledger) for path in args.archive]
    except (
        ValueError,
        KeyError,
        OSError,
        json.JSONDecodeError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as exc:
        parser.exit(1, f"Reuse gate failed: {exc}\n")
    print(
        json.dumps(
            {
                "status": "pass",
                "units": len(ledger["units"]),
                "dependency_locks": len(ledger["dependency_locks"]),
                "archives": archives,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
