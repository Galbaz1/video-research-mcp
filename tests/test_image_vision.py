"""Portable protocol/cache controls for the optional local native backend; no native inference."""

import asyncio
import errno
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from video_research_mcp import image_vision


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))


def protocol(**changes):
    return json.dumps({"protocol": 1, "width": 20, "height": 10,
                       "coordinate_space": "normalized_bottom_left", "observations": [], **changes}).encode()


async def test_non_macos_runtime_is_explicitly_missing_without_compiler(monkeypatch):
    monkeypatch.setattr(image_vision.platform, "system", lambda: "Linux")
    with patch.object(image_vision, "run_media_process", new_callable=AsyncMock) as process:
        with pytest.raises(ImportError, match="requires macOS"):
            await image_vision._binding(time.monotonic() + 10)
    process.assert_not_awaited()


async def test_changed_bundled_source_blocks_all_execution(monkeypatch):
    monkeypatch.setattr(image_vision.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(Path, "is_file", lambda path: True)
    monkeypatch.setattr(image_vision, "SOURCE_SHA256", "0" * 64)
    with patch.object(image_vision, "run_media_process", new_callable=AsyncMock) as process:
        with pytest.raises(ValueError, match="source commitment"):
            await image_vision._binding(time.monotonic() + 10)
    process.assert_not_awaited()


async def test_binding_contains_selected_toolchain_sdk_and_unknown_transitives(monkeypatch):
    source = b"independently authored fixture source"
    monkeypatch.setattr(image_vision.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(Path, "is_file", lambda path: True)
    monkeypatch.setattr(image_vision, "SOURCE_SHA256", hashlib.sha256(source).hexdigest())
    monkeypatch.setattr(image_vision, "_read", lambda path, limit: source if path.suffix == ".swift" else b"system-shim")
    with patch.object(image_vision, "run_media_process", new=AsyncMock(side_effect=[
        (b"Swift fixture version", b""), (b"/fixture/toolchain/swiftc", b""),
        (b"/fixture/SDK", b""), (b"fixtureSDKVersion", b""),
    ])) as process:
        _, binding = await image_vision._binding(time.monotonic() + 10)
    assert process.await_count == 4 and binding["selected_compiler"] == "/fixture/toolchain/swiftc"
    assert binding["sdk_path"] == "/fixture/SDK" and binding["sdk_version"] == "fixtureSDKVersion"
    assert binding["transitive_sdk_framework_bytes"] == "unverified"


@pytest.fixture
def fake_compiler(monkeypatch):
    binding = {"source_sha256": "fixture-source", "selected_compiler": "fixture-compiler",
               "sdk_path": "fixture-sdk", "sdk_version": "first"}
    compiler_calls = []
    monkeypatch.setattr(image_vision, "_binding", AsyncMock(return_value=(b"owned source", binding)))

    async def compile_owned(command, timeout, **kwargs):
        compiler_calls.append(command)
        Path(command[command.index("-o") + 1]).write_bytes(b"owned fake binary, never executed")
        return b"", b""

    monkeypatch.setattr(image_vision, "run_media_process", compile_owned)
    return binding, compiler_calls


async def test_binary_cache_reuses_only_exact_complete_binding(fake_compiler):
    binding, calls = fake_compiler
    first, runtime = await image_vision._binary(time.monotonic() + 10)
    second, reused = await image_vision._binary(time.monotonic() + 10)
    assert first == second and runtime["compiled_this_call"] and not reused["compiled_this_call"]
    assert len(calls) == 1
    binding["sdk_version"] = "changed"
    _, changed = await image_vision._binary(time.monotonic() + 10)
    assert changed["cache_key"] != reused["cache_key"] and len(calls) == 2


@pytest.mark.parametrize("kind", ["binary", "receipt", "parent_symlink"])
async def test_corrupt_or_symlink_cache_never_executes(tmp_path, fake_compiler, kind):
    _, calls = fake_compiler
    _, runtime = await image_vision._binary(time.monotonic() + 10)
    cache = tmp_path / "cache" / "native-vision" / runtime["cache_key"]
    if kind == "binary":
        (cache / "vision-image").write_bytes(b"changed")
    elif kind == "receipt":
        (cache / "receipt.json").write_text("{}")
    else:
        moved = cache.with_name("owned-alternate")
        cache.rename(moved)
        cache.symlink_to(moved, target_is_directory=True)
    with pytest.raises((ValueError, PermissionError)):
        await image_vision._binary(time.monotonic() + 10)
    assert len(calls) == 1


async def test_failed_compile_removes_its_owned_staging(monkeypatch, fake_compiler, tmp_path):
    monkeypatch.setattr(image_vision, "run_media_process", AsyncMock(side_effect=TimeoutError("controlled compile timeout")))
    with pytest.raises(TimeoutError):
        await image_vision._binary(time.monotonic() + 10)
    assert not list((tmp_path / "cache" / "native-vision").iterdir())


async def test_concurrent_first_publication_attests_one_winner(
    monkeypatch, fake_compiler, tmp_path
):
    """Two actual nonempty directory renames share the valid winning cache."""
    arrived, ready = 0, asyncio.Event()
    binary = b"owned concurrent fixture binary, never executed"

    async def compile_together(command, timeout, **kwargs):
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            ready.set()
        await ready.wait()
        Path(command[command.index("-o") + 1]).write_bytes(binary)
        return b"", b""

    monkeypatch.setattr(image_vision, "run_media_process", compile_together)
    results = await asyncio.wait_for(asyncio.gather(
        image_vision._binary(time.monotonic() + 5),
        image_vision._binary(time.monotonic() + 5),
    ), 5)
    assert arrived == 2 and all(value[0] == binary for value in results)
    root = tmp_path / "cache" / "native-vision"
    assert len(list(root.iterdir())) == 1 and not list(root.glob("build-*"))


async def test_collision_attests_winner_and_propagates_unrelated_error(
    monkeypatch, fake_compiler, tmp_path
):
    """A lost publish race accepts no corrupted winner or unrelated rename error."""
    rename = Path.rename

    def corrupt_winner(path, target):
        target.mkdir()
        (target / "vision-image").write_bytes(b"corrupt winner")
        (target / "receipt.json").write_text("{}")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", corrupt_winner)
    with pytest.raises(ValueError, match="attestation"):
        await image_vision._binary(time.monotonic() + 5)
    assert not list((tmp_path / "cache" / "native-vision").glob("build-*"))

    def unrelated_failure(path, target):
        raise OSError(errno.EACCES, "controlled cache permission failure")

    binding, _ = fake_compiler
    binding["sdk_version"] = "separate-permission-case"
    monkeypatch.setattr(Path, "rename", unrelated_failure)
    with pytest.raises(OSError) as raised:
        await image_vision._binary(time.monotonic() + 5)
    assert raised.value.errno == errno.EACCES
    assert not list((tmp_path / "cache" / "native-vision").glob("build-*"))


@pytest.mark.parametrize("raw", [
    b"invalid JSON", protocol(protocol=True), protocol(width=True), protocol(width=0),
    protocol(width=1_000_001), protocol(coordinate_space="unknown"), protocol(observations=[{}] * 129),
    protocol(extra="unsupported"), b"x" * (256 * 1024 + 1),
])
async def test_unknown_malformed_or_oversized_native_protocol_rejects(tmp_path, raw):
    with patch.object(image_vision, "_binary", new=AsyncMock(return_value=(b"own fixture binary", {}))), patch.object(
        image_vision, "run_media_process", new=AsyncMock(return_value=(raw, b""))
    ):
        with pytest.raises(ValueError):
            await image_vision.run_vision(tmp_path / "prepared.png", {
                "languages": [], "barcodes": False, "documents": False
            }, tmp_path, time.monotonic() + 10)
    assert not (tmp_path / "vision-exec").exists()


async def test_raw_native_payload_is_exact_and_executable_snapshot_cleaned(tmp_path):
    raw = protocol()
    with patch.object(image_vision, "_binary", new=AsyncMock(return_value=(b"own fixture binary", {}))), patch.object(
        image_vision, "run_media_process", new=AsyncMock(return_value=(raw, b""))
    ) as process:
        retained, payload, runtime = await image_vision.run_vision(tmp_path / "prepared.png", {
            "languages": ["en-US"], "barcodes": True, "documents": False
        }, tmp_path, time.monotonic() + 10)
    assert retained == raw and payload["observations"] == []
    command = process.await_args.args[0]
    assert command[0] == str(tmp_path / "vision-exec")
    assert json.loads(command[2])["barcodes"] is True
    assert runtime["binary_sha256"] == hashlib.sha256(b"own fixture binary").hexdigest()
    assert not (tmp_path / "vision-exec").exists()
