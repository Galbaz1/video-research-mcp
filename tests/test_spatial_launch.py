"""Pre-launch refusal tests with a concrete executable sentinel and no selected runtime."""

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.test_spatial_runtime import row, runtime as runtime
from tests.test_spatial_session import selection as selection

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import spatial_launch as sl  # noqa: E402
from spatial_inputs import digest  # noqa: E402


@pytest.fixture
def launch(selection, runtime, monkeypatch):
    """Bind the source/input fixture to the synthetic runtime and independent descriptor hash."""
    selection.data.update(runtime.data)
    selection.manifest.write_text(json.dumps(selection.data))
    selection.argv[selection.argv.index("--manifest-sha256") + 1] = digest(selection.manifest)
    monkeypatch.setattr(sl, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=True, no_site=True), stderr=sys.stderr))
    return selection, runtime


def test_probe_control_is_executable(runtime):
    """The inert process-boundary probe demonstrably writes a marker when executed."""
    result = subprocess.run([str(runtime.executable)], check=False)
    assert result.returncode == 37 and runtime.marker.is_file()


@pytest.mark.parametrize("change", ["descriptor", "binary", "library", "link", "config", "package", "missing", "extra", "symlink", "fifo", "source", "frame", "startup", "pth"])
def test_prelaunch_refusals_never_start_probe_or_write_session(launch, monkeypatch, change):
    """GIVEN an executable sentinel WHEN admission fails THEN even process creation never occurs."""
    selection, runtime = launch
    starts = []

    def start(command, **options):
        starts.append(command)
        return SimpleNamespace(returncode=37)

    monkeypatch.setattr(sl.subprocess, "run", start)
    if change == "descriptor":
        selection.manifest.write_text("{}")
    elif change in {"binary", "library", "config", "package"}:
        path = {"binary": runtime.real, "library": runtime.library, "config": runtime.cfg,
                "package": runtime.package}[change]
        path.write_text("altered")
    elif change == "link":
        other = runtime.real.with_name("other")
        other.write_bytes(runtime.real.read_bytes())
        runtime.executable.unlink()
        runtime.executable.symlink_to(other)
    elif change == "missing":
        runtime.package.unlink()
    elif change == "extra":
        (runtime.site / "unadmitted").write_bytes(b"extra")
    elif change == "symlink":
        (runtime.site / "unadmitted").symlink_to(runtime.real)
    elif change == "fifo":
        import os
        os.mkfifo(runtime.site / "pipe")
    elif change == "source":
        (selection.root / sorted(sl.session.SOURCES)[0]).write_text("changed")
    elif change == "frame":
        Path(next(iter(selection.inputs.frames))).write_bytes(b"changed")
    else:
        path = runtime.site / ("_virtualenv.pth" if change == "pth" else "sitecustomize.py")
        path.write_text("unqualified")
        runtime.fields["installed_sources"].append(row(path))
        selection.manifest.write_text(json.dumps(selection.data))
        selection.argv[selection.argv.index("--manifest-sha256") + 1] = digest(selection.manifest)
    assert sl.main(selection.argv) == 2
    assert starts == []
    assert not runtime.marker.exists() and not selection.output.exists()


def test_admitted_launch_flags_arguments_environment_and_exit(launch, monkeypatch):
    selection, runtime = launch
    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-inherit")
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/untrusted")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=17)

    monkeypatch.setattr(sl.subprocess, "run", run)
    assert sl.main(selection.argv + ["--check"]) == 17
    command, options = calls[0]
    assert command[:4] == [str(runtime.executable), "-I", "-S", "-B"]
    assert command[-1] == "--check" and command[4] == sl.session.__file__
    assert options["cwd"] == "/" and not options["check"]
    assert not {"OPENAI_API_KEY", "PYTHONPATH", "DYLD_LIBRARY_PATH"} & options["env"].keys()
    assert not runtime.marker.exists() and not selection.output.exists()


def test_blocked_check_never_selects_executable(selection, monkeypatch, capsys):
    monkeypatch.setattr(sl, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=True, no_site=True), stderr=sys.stderr))
    monkeypatch.setattr(sl.subprocess, "run", lambda *a, **k: pytest.fail("selected process"))
    assert sl.main(selection.argv + ["--check"]) == 2
    assert json.loads(capsys.readouterr().out)["foreign_imports"] == 0
    assert not selection.output.exists()


def test_launcher_itself_requires_no_site(selection, monkeypatch):
    monkeypatch.setattr(sl, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=True, no_site=False), stderr=sys.stderr))
    monkeypatch.setattr(sl.subprocess, "run", lambda *a, **k: pytest.fail("selected process"))
    assert sl.main(selection.argv + ["--check"]) == 2
