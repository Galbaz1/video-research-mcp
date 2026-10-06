"""Source boundaries for titles in generated scene infrastructure."""

import importlib.util
from pathlib import Path


_SOURCE = Path(__file__).parents[1] / "src/video_agent_mcp/prompts/scene_templates.py"
_SPEC = importlib.util.spec_from_file_location("scene_templates_under_test", _SOURCE)
_TEMPLATES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_TEMPLATES)

_SCENES = [{"component_name": "HookScene", "filename": "HookScene.tsx", "scene_key": "hook"}]


def test_comment_terminator_title_cannot_enter_source():
    """A caller title containing a comment terminator stays outside both sources."""
    title = '*/console.log("TITLE_CODE");/*'
    for source in (
        _TEMPLATES.generate_styles_content(title),
        _TEMPLATES.generate_index_content(_SCENES, title),
    ):
        assert title not in source
        assert "TITLE_CODE" not in source


def test_ordinary_title_callers_keep_styles_and_registry():
    """Existing title arguments still produce sidebar styles and scene exports."""
    styles = _TEMPLATES.generate_styles_content("Ordinary project", sidebar_width=120)
    index = _TEMPLATES.generate_index_content(_SCENES, "Ordinary project")
    assert "Shared Style Constants" in styles
    assert "const SIDEBAR_WIDTH = 120;" in styles
    assert 'import { HookScene } from "./HookScene";' in index
    assert '"hook": HookScene,' in index
    assert 'export { HookScene } from "./HookScene";' in index
    assert styles == _TEMPLATES.generate_styles_content("Another title", sidebar_width=120)
    assert index == _TEMPLATES.generate_index_content(_SCENES, "Another title")
