"""Stub-only font fences; no Matplotlib, glyph engine or host font enumeration."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from tests.test_spatial_runtime import row

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import spatial_fonts as sf  # noqa: E402


@pytest.fixture
def fonts(tmp_path):
    """Generate 38 inert TTF sentinels in the sole accepted directory."""
    site = tmp_path / "site-packages"
    directory = site / "matplotlib/mpl-data/fonts/ttf"
    directory.mkdir(parents=True)
    rows = []
    for index in range(38):
        path = directory / f"font-{index}.ttf"
        path.write_text("FONT BYTES MUST NOT REACH NATIVE CODE IN UNITS")
        rows.append(row(path))
    return {"runtime_fields": {"site_packages": str(site), "installed_sources": rows}}


def manager_stub(cache):
    """Emulate the inspected v390 decoder and font loader without executing foreign code."""
    calls = []

    class FontManager:
        __version__ = 390

        def __init__(self):
            pytest.fail("host font scan")

        def addfont(self, path):
            calls.append(("initialize", path))
            self.ttflist.append(SimpleNamespace(fname=path))

    data = json.loads(cache.read_text())
    assert data.pop("__class__") == "FontManager"
    manager = FontManager.__new__(FontManager)
    vars(manager).update(data)

    def get_font(paths, hinting_factor):
        calls.append(("get_font", tuple(paths), hinting_factor))
        return SimpleNamespace(fname=paths[0])

    return SimpleNamespace(FontManager=FontManager, fontManager=manager, get_font=get_font,
                           findSystemFonts=lambda *a, **k: pytest.fail("host font scan")), calls


def test_seed_cache_initializes_only_selected_fonts_and_records_real_requests(fonts, tmp_path):
    cache = sf.seed_cache(tmp_path)
    manager, calls = manager_stub(cache)
    boundary = sf.FontBoundary(sf.selected_fonts(fonts))
    boundary.install(manager)
    assert len(calls) == 38 and all(call[0] == "initialize" for call in calls)
    assert boundary.readback()["successful_font_requests"] == []
    selected = sorted(boundary.fonts)
    # Agg and mathtext bind this function after boundary installation.
    agg_get_font, mathtext_get_font = manager.get_font, manager.get_font
    assert agg_get_font(selected[0]).fname == selected[0]
    mathtext_get_font([selected[1], selected[2]], hinting_factor=8)
    assert {r["path"] for r in boundary.readback()["successful_font_requests"]} == set(selected[:3])
    assert {r["path"] for r in boundary.readback()["returned_primary_fonts"]} == set(selected[:2])
    assert not boundary.readback()["glyph_or_pixel_acceptance"]
    assert manager.findSystemFonts() == selected
    assert manager.findSystemFonts(["/host/fonts"], "afm") == []
    # Missing-font rebuild uses only the fenced discovery and addfont methods.
    rebuilt = manager.FontManager.__new__(manager.FontManager)
    rebuilt.ttflist = []
    for path in manager.findSystemFonts(["/host/fonts"]):
        rebuilt.addfont(path)
    assert {entry.fname for entry in rebuilt.ttflist} == set(selected)


@pytest.mark.parametrize("operation", ["get", "add", "fallback"])
def test_host_font_path_refuses_before_loader(fonts, tmp_path, operation):
    manager, calls = manager_stub(sf.seed_cache(tmp_path))
    boundary = sf.FontBoundary(sf.selected_fonts(fonts))
    boundary.install(manager)
    initial = list(calls)
    host = tmp_path / "host.ttf"
    host.write_text("HOST FONT MUST NOT LOAD")
    with pytest.raises(ValueError, match="outside"):
        if operation == "get":
            manager.get_font(str(host))
        elif operation == "fallback":
            manager.get_font([next(iter(boundary.fonts)), host])
        else:
            manager.fontManager.addfont(host)
    assert calls == initial and not boundary.used


@pytest.mark.parametrize("change", ["missing", "extra_afm", "extra_ttf", "wrong_directory", "altered", "symlink"])
def test_font_inventory_refuses_before_import(fonts, tmp_path, monkeypatch, change):
    rows = fonts["runtime_fields"]["installed_sources"]
    path = Path(rows[0]["path"])
    if change == "missing":
        rows.pop()
    elif change in {"extra_afm", "extra_ttf"}:
        extra = path.parent / ("extra.afm" if change == "extra_afm" else "extra.ttf")
        extra.write_text("unselected")
        rows.append(row(extra))
    elif change == "wrong_directory":
        other = tmp_path / "other.ttf"
        other.write_bytes(path.read_bytes())
        rows[0] = row(other)
    elif change == "altered":
        path.write_text("changed")
    else:
        other = tmp_path / "linked.ttf"
        other.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(other)
    monkeypatch.setattr(sf.importlib, "import_module", lambda *a: pytest.fail("foreign import"))
    with pytest.raises(ValueError):
        sf.initialize(fonts, tmp_path)
    assert not (tmp_path / "fontlist-v390.json").exists()


def test_readback_refuses_changed_previously_used_font(fonts, tmp_path):
    boundary = sf.FontBoundary(sf.selected_fonts(fonts))
    manager, _ = manager_stub(sf.seed_cache(tmp_path))
    boundary.install(manager)
    path = next(iter(boundary.fonts))
    manager.get_font(path)
    Path(path).write_text("changed after request")
    with pytest.raises(ValueError, match="differs"):
        boundary.readback()


def test_returned_font_identity_must_match_request(fonts, tmp_path):
    manager, _ = manager_stub(sf.seed_cache(tmp_path))
    boundary = sf.FontBoundary(sf.selected_fonts(fonts))
    selected = sorted(boundary.fonts)
    manager.get_font = lambda *a: SimpleNamespace(fname=selected[1])
    boundary.install(manager)
    with pytest.raises(ValueError, match="Returned native font"):
        manager.get_font(selected[0])
    assert not boundary.used and not boundary.returned


def test_seed_failure_or_unexpected_loaded_manager_is_a_real_gap(fonts, tmp_path):
    cache = sf.seed_cache(tmp_path)
    with pytest.raises(FileExistsError):
        sf.seed_cache(tmp_path)
    manager, calls = manager_stub(cache)
    manager.fontManager.ttflist = [SimpleNamespace(fname="/host/font.ttf")]
    with pytest.raises(ValueError, match="empty font cache"):
        sf.FontBoundary(sf.selected_fonts(fonts)).install(manager)
    assert calls == []
