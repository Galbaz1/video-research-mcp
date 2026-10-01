"""Verify public simulator selection, authority isolation and worker boundaries."""

import pytest

from video_research_mcp.config import ServerConfig, get_config
from video_research_mcp.tools.hardware import (
    mhs_discover, mhs_health_check, mhs_meta_info, mhs_read, mhs_reset, mhs_write,
)
from video_research_mcp.tools.infra import infra_configure


@pytest.fixture(autouse=True)
def isolated(clean_config, monkeypatch, tmp_path):
    """Keep all operator settings and simulator artifacts inside the control."""
    monkeypatch.setenv("MHS_MODE", "disabled")
    monkeypatch.setenv("MHS_AUTHORITY_FILE", "")
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))


@pytest.mark.parametrize("tool,args", [
    (mhs_discover, ()), (mhs_health_check, ()),
    (mhs_meta_info, ("simulator/lamp",)),
    (mhs_read, ("simulator/camera", "image", {})),
    (mhs_write, ("simulator/lamp", "brightness", {"brightness": 20}, "command-1")),
    (mhs_reset, ("simulator/lamp", "estop", "command-1")),
])
async def test_all_six_tools_disabled_without_state_or_action(tool, args, tmp_path):
    """GIVEN default selection THEN every operation fails before creating state."""
    result = await tool(*args)
    assert result["category"] == "PERMISSION_DENIED"
    assert "MHS_MODE=simulator" in result["error"]
    assert not (tmp_path / "cache" / "hardware").exists()


@pytest.mark.parametrize("mode", ["physical", "qwen", "true", "Simulator"])
def test_unsupported_mode_cannot_activate_an_external_device(mode):
    """GIVEN an unsupported selection THEN configuration fails explicitly."""
    with pytest.raises(ValueError, match="mhs_mode"):
        ServerConfig(mhs_mode=mode)


async def test_runtime_config_omits_host_authority_path(monkeypatch):
    """GIVEN private host authority THEN read-only configuration does not expose its path."""
    monkeypatch.setenv("MHS_AUTHORITY_FILE", "/private/operator/never-opened.json")
    result = await infra_configure()
    assert get_config().mhs_authority_file == "/private/operator/never-opened.json"
    assert "mhs_authority_file" not in result["current_config"]
    assert result["current_config"]["mhs_mode"] == "disabled"


async def test_nonfinite_arguments_rejected_before_simulator_mutation(monkeypatch, tmp_path):
    """GIVEN caller nonfinite data THEN dispatch refuses it before simulator creation."""
    monkeypatch.setenv("MHS_MODE", "simulator")
    result = await mhs_write("simulator/lamp", "brightness", {"brightness": float("nan")}, "bad")
    assert "error" in result
    assert not (tmp_path / "cache" / "hardware").exists()


async def test_argument_byte_ceiling_precedes_core_dispatch(monkeypatch, tmp_path):
    """GIVEN oversized arguments THEN no device receipt or values are created."""
    monkeypatch.setenv("MHS_MODE", "simulator")
    result = await mhs_read("simulator/camera", "image", {"unknown": "x" * 8192})
    assert "8192-byte" in result["error"]
    assert not (tmp_path / "cache" / "hardware").exists()
