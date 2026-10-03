"""Byte-inventory tests using synthetic runtime files; no selected code executes."""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import spatial_runtime as sr  # noqa: E402
from spatial_inputs import digest  # noqa: E402


def row(path):
    """Describe exact synthetic regular-file bytes."""
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """Use a shell probe in place of CPython and the concrete zero-hook stdlib venv."""
    base = tmp_path / "cpython-3.12.13"
    prefix = tmp_path / "venv"
    real = base / "bin/python3.12"
    library = base / "lib/libpython3.12.dylib"
    site = prefix / "lib/python3.12/site-packages"
    for directory in (real.parent, library.parent, prefix / "bin", site):
        directory.mkdir(parents=True, exist_ok=True)
    marker = tmp_path / "probe-started"
    real.write_text(f"#!/bin/sh\n: > '{marker}'\nexit 37\n")
    real.chmod(0o700)
    library.write_bytes(b"synthetic libpython")
    executable = prefix / "bin/python"
    executable.symlink_to(real)
    cfg = prefix / "pyvenv.cfg"
    cfg.write_text(f"home = {real.parent}\nexecutable = {real}\nversion = 3.12.13\n"
                   "include-system-site-packages = false\n")
    package = site / "synthetic/package.py"
    package.parent.mkdir()
    package.write_text("raise RuntimeError('SELECTED PACKAGE MUST NOT EXECUTE')\n")
    fields = {"python_executable": str(executable), "python_realpath": str(real),
              "python_sha256": digest(real), "python_bytes": real.stat().st_size,
              "libpython": row(library), "site_packages": str(site),
              "bootstrap_sources": [row(cfg)], "installed_sources": [row(package)]}
    data = {"runtime_clearance": sr.CLEARANCE, "selected_python": "3.12.13",
            "selected_direct_packages": sr.DIRECT_PACKAGES.copy(), "runtime_fields": fields}
    return SimpleNamespace(data=data, fields=fields, real=real, prefix=prefix, site=site,
                           executable=executable, library=library, cfg=cfg,
                           package=package, marker=marker)


def test_exact_inventory_is_read_only(runtime):
    result = sr.admit_runtime(runtime.data)
    assert result["installed_files"] == 1
    assert result["prefix"] == str(runtime.prefix)
    assert not runtime.marker.exists()


@pytest.mark.parametrize("change", ["altered", "missing", "extra", "file_link", "dir_link", "fifo", "duplicate", "escape"])
def test_complete_installed_bytes_refuse(runtime, change):
    """GIVEN a frozen inventory WHEN any installed file deviates THEN admission refuses."""
    if change == "altered":
        runtime.package.write_text("different")
    elif change == "missing":
        runtime.package.unlink()
    elif change == "extra":
        (runtime.site / "extra.py").write_text("unlisted")
    elif change == "file_link":
        runtime.package.unlink()
        runtime.package.symlink_to(runtime.real)
    elif change == "dir_link":
        (runtime.site / "external").symlink_to(runtime.real.parent, target_is_directory=True)
    elif change == "fifo":
        import os
        os.mkfifo(runtime.site / "pipe")
    elif change == "duplicate":
        runtime.fields["installed_sources"].append(runtime.fields["installed_sources"][0])
    else:
        runtime.fields["installed_sources"].append(row(runtime.library))
    with pytest.raises((ValueError, OSError)):
        sr.admit_runtime(runtime.data)
    assert not runtime.marker.exists()


@pytest.mark.parametrize("name", ["injected.pth", "sitecustomize.py", "usercustomize/__init__.py", "sub/nested.pth"])
def test_even_descriptor_listed_startup_hook_refuses(runtime, name):
    path = runtime.site / name
    path.parent.mkdir(exist_ok=True)
    path.write_text("import synthetic.package")
    runtime.fields["installed_sources"].append(row(path))
    with pytest.raises(ValueError, match="startup hook"):
        sr.admit_runtime(runtime.data)


@pytest.mark.parametrize("change", ["home", "version", "system_site", "duplicate", "executable"])
def test_bootstrap_semantics_cannot_be_changed_by_rehashing(runtime, change):
    text = runtime.cfg.read_text()
    text = {"home": text.replace(str(runtime.real.parent), "/another/bin"),
            "version": text.replace("3.12.13", "3.12.12"),
            "system_site": text.replace("false", "true"),
            "duplicate": text + "home = /other\n",
            "executable": text.replace(f"executable = {runtime.real}", "executable = /other")}[change]
    runtime.cfg.write_text(text)
    runtime.fields["bootstrap_sources"] = [row(runtime.cfg)]
    with pytest.raises(ValueError):
        sr.admit_runtime(runtime.data)


@pytest.mark.parametrize("change", ["binary", "library", "retarget", "alias", "regular", "prefix", "bootstrap_missing"])
def test_interpreter_and_prefix_bindings_refuse(runtime, change):
    if change == "binary":
        runtime.real.write_text("changed")
    elif change == "library":
        runtime.library.write_text("changed")
    elif change in {"retarget", "alias", "regular"}:
        runtime.executable.unlink()
        if change == "regular":
            runtime.executable.write_bytes(runtime.real.read_bytes())
        elif change == "retarget":
            other = runtime.real.with_name("another-python")
            other.write_bytes(runtime.real.read_bytes())
            runtime.executable.symlink_to(other)
        else:
            alias = runtime.real.with_name("python3")
            alias.symlink_to(runtime.real)
            runtime.executable.symlink_to(alias)
    elif change == "prefix":
        runtime.fields["site_packages"] = str(runtime.real.parent)
    else:
        runtime.fields["bootstrap_sources"].pop()
    with pytest.raises(ValueError):
        sr.admit_runtime(runtime.data)


def test_descriptor_hash_and_regular_path_are_independent(tmp_path):
    descriptor = tmp_path / "selection.json"
    descriptor.write_text('{"selected":true}')
    expected = digest(descriptor)
    assert sr.read_descriptor(descriptor, expected) == {"selected": True}
    descriptor.write_text('{"selected":false}')
    with pytest.raises(ValueError, match="independently trusted"):
        sr.read_descriptor(descriptor, expected)
    linked = tmp_path / "linked.json"
    linked.symlink_to(descriptor)
    with pytest.raises(ValueError, match="regular"):
        sr.read_descriptor(linked, digest(descriptor))


@pytest.mark.parametrize("change", ["altered", "missing", "symlink"])
def test_unused_console_wrapper_bytes_are_still_bound(runtime, change):
    wrapper = runtime.prefix / "bin/unused-wrapper"
    wrapper.write_text("#!/old/qualified/prefix/bin/python\nunused\n")
    runtime.fields["bootstrap_sources"].append(row(wrapper))
    assert sr.admit_runtime(runtime.data)["installed_files"] == 1
    if change == "altered":
        wrapper.write_text("changed unused wrapper")
    else:
        wrapper.unlink()
        if change == "symlink":
            wrapper.symlink_to(runtime.real)
    with pytest.raises((ValueError, OSError)):
        sr.admit_runtime(runtime.data)
    assert not runtime.marker.exists()
