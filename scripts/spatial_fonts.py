"""Fence the pinned Matplotlib 3.10.9 Agg font caller to admitted bundled TTFs."""

from __future__ import annotations

from functools import wraps
import importlib
import json
from pathlib import Path

from spatial_inputs import admit_file


def selected_fonts(data: dict) -> dict[str, dict]:
    """Select exactly the 38 qualified bundled TTFs and reject every AFM/font addition."""
    site = Path(data["runtime_fields"]["site_packages"])
    directory = site / "matplotlib/mpl-data/fonts/ttf"
    fonts = {}
    for row in data["runtime_fields"]["installed_sources"]:
        path = Path(row["path"])
        if path.suffix.lower() in {".ttf", ".otf", ".ttc", ".afm"}:
            if path.parent != directory or path.suffix != ".ttf" or str(path) in fonts:
                raise ValueError("Font inventory exceeds the selected bundled TTF set")
            admit_file(row)
            fonts[str(path)] = row
    if len(fonts) != 38:
        raise ValueError("Selected PNG font inventory requires 38 TTFs and zero AFMs")
    return fonts


def seed_cache(directory: Path) -> Path:
    """Seed the pinned decoder's empty manager before it can fall back to host discovery."""
    cache = directory / "fontlist-v390.json"
    data = {"__class__": "FontManager", "_version": 390,
            "_FontManager__default_weight": "normal", "default_size": None,
            "defaultFamily": {"ttf": "DejaVu Sans", "afm": "Helvetica"},
            "afmlist": [], "ttflist": []}
    with cache.open("x") as stream:
        json.dump(data, stream)
    return cache


class FontBoundary:
    """Retain separately initialized fonts and successful Agg/mathtext font requests."""

    def __init__(self, fonts: dict[str, dict]):
        self.fonts = fonts
        self.initialized = {}
        self.used = {}
        self.returned = {}

    def paths(self, paths) -> list[str]:
        """Reject unknown files before the pinned loader receives any font path."""
        values = [paths] if isinstance(paths, (str, bytes, Path)) else list(paths)
        result = []
        for value in values:
            path = str(Path(value.decode() if isinstance(value, bytes) else value).absolute())
            if path not in self.fonts:
                raise ValueError("Font path is outside the selected 38 TTFs")
            admit_file(self.fonts[path])
            result.append(path)
        return result

    def discovery(self, fontpaths=None, fontext="ttf") -> list[str]:
        """Return only admitted TTFs even during the pinned missing-font rebuild path."""
        return self.paths(sorted(self.fonts)) if fontext == "ttf" else []

    def install(self, manager) -> None:
        """Fence discovery, addfont and actual get_font requests before foreign callers import."""
        if (manager.FontManager.__version__ != 390 or manager.fontManager._version != 390
                or manager.fontManager.ttflist or manager.fontManager.afmlist):
            raise ValueError("Pinned empty font cache was not loaded")
        manager.findSystemFonts = self.discovery
        original_add = manager.FontManager.addfont
        original_get = manager.get_font

        @wraps(original_add)
        def addfont(instance, path):
            admitted = self.paths(path)
            result = original_add(instance, admitted[0])
            self.initialized.update({p: self.fonts[p] for p in admitted})
            return result

        @wraps(original_get)
        def get_font(paths, hinting_factor=None):
            admitted = self.paths(paths)
            result = original_get(admitted, hinting_factor)
            returned = self.paths(result.fname)[0]
            if returned != admitted[0]:
                raise ValueError("Returned native font differs from the admitted primary font")
            self.used.update({p: self.fonts[p] for p in admitted})
            self.returned[returned] = self.fonts[returned]
            return result

        manager.FontManager.addfont = addfont
        manager.get_font = get_font
        for path in sorted(self.fonts):
            manager.fontManager.addfont(path)
        if {entry.fname for entry in manager.fontManager.ttflist} != set(self.fonts) or manager.fontManager.afmlist:
            raise ValueError("Initialized font manager differs from the selected font inventory")

    def readback(self) -> dict:
        """Rehash actual font requests without claiming which fallback supplied a glyph."""
        for row in self.fonts.values():
            admit_file(row)
        return {"selected_ttf_count": 38, "selected_afm_count": 0,
                "initialized_fonts": list(self.initialized.values()),
                "successful_font_requests": list(self.used.values()),
                "returned_primary_fonts": list(self.returned.values()),
                "glyph_or_pixel_acceptance": False}


def initialize(data: dict, directory: Path) -> FontBoundary:
    """Populate the empty session cache from only the admitted 38 bundled fonts."""
    boundary = FontBoundary(selected_fonts(data))
    seed_cache(directory)
    boundary.install(importlib.import_module("matplotlib.font_manager"))
    return boundary
