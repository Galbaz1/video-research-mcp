"""Atomically package only explicitly validated host-skill resources."""

import argparse
import json
import os
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

import yaml

if __package__:
    from .validate_video_skill import _validate, facts
    from .video_skill_contract import MAX_BYTES, MAX_FILES, InvalidSkill, canonical, require, sha
else:
    from validate_video_skill import _validate, facts
    from video_skill_contract import MAX_BYTES, MAX_FILES, InvalidSkill, canonical, require, sha


def _output_path(directory, output):
    path = Path(os.path.abspath(output))
    require(path.suffix == ".skill", "output must use .skill extension")
    require(not path.is_relative_to(directory), "package output must be outside authoring directory")
    for component in [*reversed(path.parent.parents), path.parent]:
        require(stat.S_ISDIR(component.lstat().st_mode), "output parent must be a real directory")
    if path.exists() or path.is_symlink():
        require(stat.S_ISREG(path.lstat().st_mode), "output must be a regular file")
    return path


def _members(snapshot, validation):
    prefix = validation["name"] + "/"
    members = {prefix + name: data for name, data in snapshot.members.items()}
    manifest = {"schema_version": 1, "candidate_revision_sha256": validation["candidate_revision_sha256"],
                "portable_revalidation": False, "execution_observed": False, "factual_success": False,
                "validation_scope": validation["validation_scope"],
                "members": [{"path": name, "sha256": sha(data), "bytes": len(data)}
                            for name, data in sorted(members.items())],
                "omitted_provenance": {name: snapshot.bindings[name]
                                       for name in validation["omitted_provenance"]}}
    members[prefix + "package-manifest.json"] = canonical(manifest)
    require(len(members) <= MAX_FILES and sum(map(len, members.values())) <= MAX_BYTES,
            "package exceeds 64 members or 8 MiB")
    return members


def _write_zip(path, members):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(path, "r") as archive:
        require(archive.namelist() == sorted(members), "ZIP member readback mismatch")
        for name, expected in members.items():
            require(archive.read(name) == expected, "ZIP bytes readback mismatch")


def package_skill(directory, output):
    """Preserve old output on failure; freeze, read back and rehash before atomic replacement."""
    result, temporary = facts(), None
    try:
        snapshot = _validate(Path(directory), result)
        output = _output_path(snapshot.root, output)
        members = _members(snapshot, result)
        descriptor, name = tempfile.mkstemp(prefix=".video-skill-", suffix=".tmp", dir=output.parent)
        temporary = Path(name)
        os.fchmod(descriptor, 0o600)
        os.close(descriptor)
        _write_zip(temporary, members)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
            data = stream.read(MAX_BYTES + 65537)
        require(len(data) <= MAX_BYTES + 65536, "archive size exceeds bound")
        snapshot.recheck()
        _output_path(snapshot.root, output)
        os.replace(temporary, output)
        temporary = None
        result.update(output=str(output), package_sha256=sha(data), package_bytes=len(data),
                      zip_members=sorted(members))
    except (InvalidSkill, OSError, ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError, zipfile.BadZipFile) as exc:
        result.update(status="fail", error=str(exc))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return result


def main():
    """Print JSON and return a nonzero status on a validation or packaging failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = package_skill(args.directory, args.output)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
