"""Honest renderer diagnostics and confined public-route controls without vendor execution."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from video_explainer_mcp.prereqs import check_prereqs, doctor, require_render_ready
from video_explainer_mcp.render_contract import MAPPED_SOURCE_SHA256, project_contract, source_contract
from video_explainer_mcp.tools.doctor import explainer_doctor


class NativeReply:
    """An owned subprocess-edge response with real bounded asyncio pipe readers."""

    def __init__(self, stdout=b"", stderr=b"", code=0):
        self.pid = 1_000_000_000
        self.returncode = code
        self.stdout, self.stderr = asyncio.StreamReader(), asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stderr.feed_data(stderr)
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.waits = 0

    async def wait(self):
        self.waits += 1
        return self.returncode


@pytest.fixture
def environment(tmp_path, monkeypatch):
    """Create only owned availability markers, never fake matching pinned-source hashes."""
    root = tmp_path / "configured"
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ("node", "ffprobe", "ffmpeg"):
        path = binaries / name
        path.write_text(f"Owned nonexecuted {name} fixture")
        path.chmod(0o700)
    console = root / ".venv/bin/video-explainer"
    console.parent.mkdir(parents=True)
    console.write_text("Owned nonexecuted console marker")
    console.chmod(0o700)
    for package in ("remotion", "@remotion/renderer", "@remotion/bundler"):
        path = root / "remotion/node_modules" / package / "package.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"version":"4.0.242"}')
    for target in ("mac-arm64", "mac-x64", "linux64", "win64"):
        path = root / "remotion/node_modules/.remotion/chrome-headless-shell" / target
        path /= f"chrome-headless-shell-{target}"
        path /= "chrome-headless-shell.exe" if target == "win64" else "chrome-headless-shell"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Owned nonexecuted browser marker")
        path.chmod(0o700)
    project = root / "projects/test"
    (project / "storyboard").mkdir(parents=True)
    (project / "storyboard/storyboard.json").write_text('{"scenes":[]}')
    (project / "config.json").write_text(json.dumps({"paths": {
        "storyboard": "storyboard/storyboard.json", "final_video": "output/final.mp4",
    }}))
    monkeypatch.setenv("EXPLAINER_PATH", str(root))
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(project.parent))
    monkeypatch.setenv("PATH", str(binaries))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    return root, binaries, project


def _versions(monkeypatch, *, node=b"v22.1.0\n", failure=None):
    calls, replies = [], []

    async def spawn(*command, **kwargs):
        name = Path(command[0]).name
        calls.append((command, kwargs))
        body = node if name == "node" else f"{name} version owned-fixture\n".encode()
        reply = NativeReply(body, b"version failure" if name == failure else b"", int(name == failure))
        replies.append(reply)
        return reply

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return calls, replies


def _checks(report):
    value = report.model_dump() if hasattr(report, "model_dump") else report
    return {check["name"]: check for check in value["checks"]}


def test_missing_and_changed_mapped_source_are_retained_honestly(environment):
    root, _, _ = environment
    absent = source_contract(root)
    assert absent["mapped_source_verified"] is False
    assert len(absent["errors"]) == len(MAPPED_SOURCE_SHA256) == 5
    name = next(iter(MAPPED_SOURCE_SHA256))
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Owned changed body; this is not the audited external source")
    changed = source_contract(root)
    assert changed["file_sha256"][name] != MAPPED_SOURCE_SHA256[name]
    assert any(f"source changed: {name}" in error for error in changed["errors"])
    assert changed["mapped_source_verified"] is False
    assert changed["foreign_runtime_executed"] is False
    assert "unresolved" in changed["source_grant"]


def test_source_size_bound_rejects_sparse_oversize_without_execution(environment):
    root, _, _ = environment
    name = next(iter(MAPPED_SOURCE_SHA256))
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    report = source_contract(root)
    assert report["mapped_source_verified"] is False
    assert name not in report["file_sha256"]
    assert any("8MiB" in error for error in report["errors"])


async def test_local_versions_modules_and_browser_do_not_claim_provider_or_render_success(environment, monkeypatch):
    calls, replies = _versions(monkeypatch)
    report = await explainer_doctor("test")
    checks = _checks(report)
    assert all(checks[name]["available"] for name in ("node", "ffmpeg", "ffprobe", "renderer", "bundler", "remotion", "browser", "console_script"))
    assert checks["claude"]["available"] is False
    assert checks["node"]["version"] == "v22.1.0"
    assert report["all_ok"] is False and report["source"]["mapped_source_verified"] is False
    assert report["provider_calls"] == 0
    assert report["capabilities"]["real_render"]["execution_verified"] is False
    assert report["capabilities"]["generation"]["provider_access"] == "not checked"
    assert report["capabilities"]["tts"]["actual_audio_provenance"] == "unknown"
    assert [Path(call[0][0]).name for call in calls] == ["node", "ffmpeg", "ffprobe"]
    assert all(reply.waits == 1 for reply in replies)
    assert all(call[1]["stdin"] == asyncio.subprocess.DEVNULL for call in calls)


@pytest.mark.parametrize("version", [b"v18.20.0\n", b"node unknown\n"])
async def test_unsupported_or_malformed_node_version_is_unavailable(environment, monkeypatch, version):
    _versions(monkeypatch, node=version)
    report = await doctor("test")
    node = _checks(report)["node"]
    assert node["available"] is False
    assert "Node 20 or newer" in node["message"] and report.all_ok is False


async def test_native_version_failure_is_diagnostic_and_owned_work_is_joined(environment, monkeypatch):
    _, replies = _versions(monkeypatch, failure="ffprobe")
    report = await doctor("test")
    check = _checks(report)["ffprobe"]
    assert check["available"] is False and "status 1" in check["message"]
    assert report.provider_calls == 0
    assert next(reply for reply in replies if reply.returncode == 1).waits >= 2


@pytest.mark.parametrize("damage", ["missing", "version", "malformed", "wrong_type"])
def test_modules_report_missing_changed_major_or_malformed_json(environment, damage):
    root, _, _ = environment
    target = root / "remotion/node_modules/@remotion/renderer/package.json"
    if damage == "missing":
        target.unlink()
    else:
        target.write_text({"version": '{"version":"5.0.0"}',
                           "malformed": "{malformed", "wrong_type": '{"version":[]}' }[damage])
    report = check_prereqs("test")
    assert _checks(report)["renderer"]["available"] is False
    assert _checks(report)["bundler"]["available"] is True
    assert report.all_ok is False


def test_missing_browser_and_node_are_named_without_download_or_launch(environment):
    root, binaries, _ = environment
    for path in (root / "remotion/node_modules/.remotion").rglob("chrome-headless-shell*"):
        if path.is_file():
            path.unlink()
    (binaries / "node").unlink()
    report = check_prereqs("test")
    checks = _checks(report)
    assert checks["browser"]["available"] is checks["node"]["available"] is False
    assert "does not download or launch" in checks["browser"]["message"]


def test_provider_credential_presence_is_separate_and_secret_is_not_returned(environment, monkeypatch):
    monkeypatch.setenv("EXPLAINER_TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "owned-credential-placeholder")
    report = check_prereqs("test").model_dump()
    assert report["capabilities"]["tts"]["credential_present"] is True
    assert report["capabilities"]["tts"]["provider_access"] == "not checked"
    assert report["provider_calls"] == 0
    assert "owned-credential-placeholder" not in json.dumps(report)


@pytest.mark.parametrize("resolution,filename", [("720p", "final-720p.mp4"), ("1080p", "final.mp4"), ("4k", "final-4k.mp4")])
def test_public_render_contract_names_exact_current_request_output(environment, resolution, filename):
    _, _, project = environment
    contract = project_contract(project, resolution)
    assert Path(contract["expected_output"]) == project / "output" / filename
    assert Path(contract["storyboard_path"]) == project / "storyboard/storyboard.json"


async def test_confined_alternate_storyboard_is_rejected_before_any_production(environment, monkeypatch):
    _, _, project = environment
    alternative = project / "custom/board.json"
    alternative.parent.mkdir()
    alternative.write_text('{"scenes":[]}')
    (project / "config.json").write_text(json.dumps({"paths": {"storyboard": "custom/board.json"}}))
    calls, _ = _versions(monkeypatch)
    report = await doctor("test")
    assert report.project["supported"] is False
    assert "Node entry ignores" in report.project["error"]
    with pytest.raises(RuntimeError, match="prerequisites unavailable"):
        await require_render_ready("test")
    assert all(Path(command[0]).name in {"node", "ffmpeg", "ffprobe"} for command, _ in calls)
    assert not (project / "output").exists()


@pytest.mark.parametrize("output", ["../outside.mp4", "input/source.mp4", "output/wrong.webm", "/outside.mp4", "output/nested/final.mp4"])
def test_output_contract_rejects_unconfined_non_mp4_routes(environment, output):
    _, _, project = environment
    (project / "config.json").write_text(json.dumps({"paths": {
        "storyboard": "storyboard/storyboard.json", "final_video": output,
    }}))
    with pytest.raises(ValueError):
        project_contract(project, "1080p")


async def test_empty_native_version_output_is_an_unavailable_diagnostic(environment, monkeypatch):
    _versions(monkeypatch, node=b"")
    report = await doctor("test")
    node = _checks(report)["node"]
    assert node["available"] is False and node["message"]
    assert report.all_ok is False and report.provider_calls == 0


def test_output_directory_symlink_is_rejected_by_actual_project_inspection(environment, tmp_path):
    _, _, project = environment
    outside = tmp_path / "outside-output"
    outside.mkdir()
    (project / "output").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        project_contract(project, "720p")
