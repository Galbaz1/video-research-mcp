"""Admit the optional ASR interpreter before exec, using trusted stdlib only.

Owned launcher/bootstrap bytes, the caller's trusted Python and an independently
pinned descriptor are the trust boundary. This is admission, not an OS sandbox.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import types

PROTOCOL = "faster_whisper_v1"
MODEL_FILES = {"config.json", "model.bin", "tokenizer.json", "vocabulary.txt"}
TRUSTED_PYTHON = sys.executable


def file_digest(path):
    """Hash complete bytes without importing or loading a model."""
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_pinned(path, expected):
    """Read the same regular bytes whose separately supplied hash is checked."""
    path = Path(path)
    if not path.is_absolute() or path != path.resolve() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Pinned path must be absolute, regular and without links")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Pinned bytes changed: " + str(path))
    return raw


def link_lineage(path):
    """Record each selected executable link, including links in ancestor paths."""
    path, rows = Path(path), []
    for _ in range(40):
        for index in range(1, len(path.parts) + 1):
            part = Path(*path.parts[:index])
            if part.is_symlink():
                target = os.readlink(part)
                rows.append({"path": str(part), "target": target})
                path = Path(os.path.normpath(part.parent / target / Path(*path.parts[index:])))
                break
        else:
            return {"realpath": str(path), "links": rows}
    raise ValueError("Interpreter link cycle")


def population(root, allowed):
    """Inventory all files, directories and links; reject specials and escaping links."""
    root = Path(root)
    if not root.is_absolute() or root != root.resolve() or not root.is_dir():
        raise ValueError("Inventory root must be a real absolute directory")
    rows, pending = [], [root]
    while pending:
        for path in sorted(pending.pop().iterdir()):
            mode = path.lstat().st_mode
            row = {"path": str(path.relative_to(root))}
            if stat.S_ISLNK(mode):
                real = path.resolve(strict=True)
                if not any(real.is_relative_to(Path(directory)) for directory in allowed):
                    raise ValueError("Inventory link escapes admitted roots")
                row.update(kind="link", target=os.readlink(path), realpath=str(real))
            elif stat.S_ISDIR(mode):
                row.update(kind="directory")
                pending.append(path)
            elif stat.S_ISREG(mode):
                row.update(kind="file", bytes=path.stat().st_size, sha256=file_digest(path))
            else:
                raise ValueError("Nonregular inventory path")
            rows.append(row)
    return sorted(rows, key=lambda row: row["path"])


def check_population(root, inventory, digest, allowed):
    """Compare the full live population to the exact private inventory."""
    records = json.loads(read_pinned(inventory, digest))
    if population(root, allowed) != records:
        raise ValueError("Complete inventory changed: " + str(root))
    return records


def source_bytes(row):
    """Admit source bytes for compilation, never an adjacent module's bytecode."""
    raw = read_pinned(row["path"], row["sha256"])
    if len(raw) != row["bytes"]:
        raise ValueError("Source extent changed")
    return raw


def admit_interpreter(runtime):
    """Bind executable lineage, base/library, pyvenv and cold bootstrap paths."""
    selected = Path(runtime["python"])
    base = Path(runtime["base_directory"])
    version = ".".join(runtime["versions"]["python"].split(".")[:2])
    if (not selected.is_absolute() or selected.parent != Path(runtime["directory"]) / "bin"
            or link_lineage(selected) != runtime["lineage"]
            or Path(runtime["lineage"]["realpath"]).parent.parent != base
            or file_digest(selected) != runtime["python_sha256"] or not os.access(selected, os.X_OK)):
        raise ValueError("Selected interpreter changed")
    library = runtime["libpython"]
    if Path(library["path"]) != base / f"lib/libpython{version}.dylib":
        raise ValueError("libpython selection changed")
    source_bytes(library)
    stdlib = base / f"lib/python{version}"
    paths = [str(base / f"lib/python{version.replace('.', '')}.zip"), str(stdlib), str(stdlib / "lib-dynload")]
    if runtime["stdlib_paths"] != paths or runtime["site_packages"] != str(Path(runtime["directory"]) / f"lib/python{version}/site-packages"):
        raise ValueError("Bootstrap import path changed")
    absent = [paths[0], str(base / "pyvenv.cfg"), str(base / "bin/pyvenv.cfg"), str(selected.parent / "pyvenv.cfg")]
    if runtime["absent_paths"] != absent or any(os.path.lexists(path) for path in absent):
        raise ValueError("Cold bootstrap population changed")
    cfg = Path(runtime["directory"]) / "pyvenv.cfg"
    if Path(runtime["pyvenv"]["path"]) != cfg:
        raise ValueError("pyvenv selection changed")
    settings = dict(line.split("=", 1) for line in source_bytes(runtime["pyvenv"]).decode().splitlines() if "=" in line)
    settings = {key.strip(): value.strip() for key, value in settings.items()}
    if Path(settings["home"]).resolve() != base / "bin" or settings["include-system-site-packages"] != "false":
        raise ValueError("Unsupported pyvenv bootstrap")


def admit(descriptor_path, expected_digest):
    """Readmit source, complete runtime/base populations and both complete models."""
    data = json.loads(read_pinned(descriptor_path, expected_digest))
    if type(data["schema_version"]) is not int or data["schema_version"] != 2 or data["protocol"] != PROTOCOL:
        raise ValueError("Unsupported admission descriptor")
    if set(data["sources"]) != {"launch", "service", "worker"}:
        raise ValueError("All three exact sources required")
    for name, row in data["sources"].items():
        if Path(row["path"]) != Path(__file__).with_name(f"local_asr_{name}.py"):
            raise ValueError("Owned source selection changed")
        source_bytes(row)
    if data["script_sha256"] != data["sources"]["service"]["sha256"] or data["worker_sha256"] != data["sources"]["worker"]["sha256"]:
        raise ValueError("Source receipt differs")
    runtime = data["runtime"]
    admit_interpreter(runtime)
    roots = [runtime["directory"], runtime["base_directory"]]
    base = check_population(runtime["base_directory"], runtime["base_inventory"], runtime["base_inventory_sha256"], roots)
    installed = check_population(runtime["directory"], runtime["inventory"], runtime["inventory_sha256"], roots)
    for row in installed + base:
        path = Path(row["path"])
        if any(part.split(".")[0] in {"sitecustomize", "usercustomize"} for part in path.parts):
            raise ValueError("Startup customization refused")
        if path.suffix.lower() == ".pth":
            exact = "lib/python3.12/site-packages/_virtualenv.pth"
            if row not in installed or str(path) != exact or row.get("sha256") != "69ac3d8f27e679c81b94ab30b3b56e9cd138219b1ba94a1fa3606d5a76a1433d":
                raise ValueError("Unqualified startup hook")
    if runtime["bytecode_policy"] != "complete-inventory" or runtime["pth_policy"] != "inactive-exact-virtualenv-only":
        raise ValueError("Unsupported import policy")
    if set(data["models"]) != {"en", "multilingual"}:
        raise ValueError("Both exact model populations required")
    for model in data["models"].values():
        actual = population(model["directory"], [model["directory"]])
        records = sorted([dict(kind="file", **row) for row in model["files"]], key=lambda row: row["path"])
        if {row["path"] for row in records} != MODEL_FILES or actual != records:
            raise ValueError("Complete model population changed")
    return data


def load_source(name, row):
    """Compile admitted bytes into a named module without consulting import finders."""
    module = types.ModuleType(name)
    module.__file__ = row["path"]
    sys.modules[name] = module
    exec(compile(source_bytes(row), row["path"], "exec"), module.__dict__)
    return module


def selected_bootstrap(argv, trusted_python):
    """Check the actual isolated bootstrap, then supply only the verified package path."""
    global TRUSTED_PYTHON
    TRUSTED_PYTHON = trusted_python
    args = arguments(argv)
    data = admit(args.descriptor, args.expected_descriptor_sha256)
    runtime = data["runtime"]
    if (not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode
            or sys.pycache_prefix is not None or sys.path != runtime["stdlib_paths"]
            or Path(sys.executable).resolve() != Path(runtime["lineage"]["realpath"])
            or sys.prefix != runtime["base_directory"] or sys.base_prefix != runtime["base_directory"]
            or sys.version.split()[0] != runtime["versions"]["python"]):
        raise ValueError("Effective optional bootstrap differs")
    sys.path.append(runtime["site_packages"])
    import importlib.metadata
    for name in ("faster-whisper", "ctranslate2", "numpy"):
        if importlib.metadata.version(name) != runtime["versions"][name]:
            raise ValueError("Installed package version differs")
    worker = load_source("local_asr_worker", data["sources"]["worker"])
    entry = worker if args.entry == "worker" else load_source("local_asr_service", data["sources"]["service"])
    if args.check:
        print(json.dumps({"entry": args.entry, "pid": os.getpid(), "descriptor_sha256": args.expected_descriptor_sha256,
                          "executable": sys.executable, "prefix": sys.prefix, "path": sys.path,
                          "isolated": sys.flags.isolated, "no_site": sys.flags.no_site,
                          "bytecode_policy": runtime["bytecode_policy"], "pth_active": False,
                          "model_libraries_imported": any(name in sys.modules for name in ("numpy", "ctranslate2", "faster_whisper")),
                          "inference": False, "listening": False}))
        return
    sys.argv = [entry.__file__, "--descriptor", args.descriptor, "--expected-descriptor-sha256", args.expected_descriptor_sha256]
    if args.entry == "service":
        sys.argv.extend(["--host", args.host, "--port", str(args.port)])
    entry.main()


def arguments(argv):
    """Parse the two current entries and the inert readiness command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", required=True)
    parser.add_argument("--expected-descriptor-sha256", required=True)
    parser.add_argument("--entry", choices=("service", "worker"), default="service")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--host", choices=("127.0.0.1", "::1"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    return parser.parse_args(argv)


def main(argv=None):
    """Refuse before optional startup, or exec-replace with the verified bootstrap."""
    args = arguments(argv)
    try:
        if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or sys.pycache_prefix is not None:
            raise ValueError("Trusted launcher requires -I -S -B without a cache prefix")
        data = admit(args.descriptor, args.expected_descriptor_sha256)
        source = source_bytes(data["sources"]["launch"])
        bootstrap = ("import sys,types; m=types.ModuleType('local_asr_launch'); "
                     f"m.__file__={__file__!r}; sys.modules[m.__name__]=m; "
                     f"exec(compile({source!r},m.__file__,'exec'),m.__dict__); "
                     f"m.selected_bootstrap({list(argv if argv is not None else sys.argv[1:])!r},{sys.executable!r})")
        command = [data["runtime"]["python"], "-I", "-S", "-B", "-c", bootstrap]
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
               "HF_HUB_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false"}
        os.chdir("/")
        os.execve(command[0], command, env)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(f"ASR launch refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
