"""Tests for tools/scenes.py — agent_generate_scenes + agent_generate_single_scene."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from video_agent_mcp.prompts.scene import (
    extract_code,
    title_to_component_name,
    title_to_scene_key,
)
from video_agent_mcp.prompts.scene_templates import generate_index_content
from video_agent_mcp.tools.scenes import (
    _build_scene_prompt,
    _collect_generated_scenes,
    _process_scene_result,
    _read_script,
    _read_voiceover_manifest,
    _write_infrastructure,
    agent_generate_scenes,
    agent_generate_single_scene,
)
from video_agent_mcp.types import AgentResult

# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestTitleConversions:
    """Tests for title_to_component_name and title_to_scene_key."""

    def test_title_to_component_name_basic(self):
        assert title_to_component_name("The Hook") == "TheHookScene"

    def test_title_to_component_name_special_chars(self):
        assert title_to_component_name("What's the Big Deal?") == "WhatsTheBigDealScene"

    def test_title_to_component_name_numbers(self):
        assert title_to_component_name("Step 1 Setup") == "Step1SetupScene"

    def test_title_to_component_name_leading_number(self):
        assert title_to_component_name("3D Overview") == "Scene3DOverviewScene"

    def test_title_to_scene_key_strips_article(self):
        assert title_to_scene_key("The Big Problem") == "big_problem"

    def test_title_to_scene_key_no_article(self):
        assert title_to_scene_key("Cutting Images") == "cutting_images"

    def test_title_to_scene_key_special_chars(self):
        assert title_to_scene_key("What's Next?") == "whats_next"


class TestIndexTemplate:
    """Tests for index.ts generation helpers."""

    def test_generate_index_quotes_registry_keys(self):
        content = generate_index_content(
            scenes=[
                {
                    "component_name": "Scene2025OutlookScene",
                    "filename": "Scene2025OutlookScene.tsx",
                    "scene_key": "2025_outlook",
                }
            ],
            project_title="Demo",
        )
        assert '"2025_outlook": Scene2025OutlookScene,' in content


class TestExtractCode:
    """Tests for TSX code extraction from agent responses."""

    def test_extract_fenced_typescript(self):
        response = '```typescript\nconst x = 1;\nexport const Foo = () => {};\n```'
        assert extract_code(response) == 'const x = 1;\nexport const Foo = () => {};'

    def test_extract_fenced_tsx(self):
        response = '```tsx\nimport React from "react";\nexport const Bar = () => null;\n```'
        code = extract_code(response)
        assert 'import React' in code
        assert 'export const Bar' in code

    def test_extract_plain_code(self):
        """GIVEN response without fences but with import/export WHEN extracting THEN returns it."""
        response = 'import React from "react";\nexport const Baz = () => null;'
        assert extract_code(response) is not None

    def test_extract_no_code(self):
        """GIVEN a response with no code WHEN extracting THEN returns None."""
        assert extract_code("I don't know how to do that.") is None


# ---------------------------------------------------------------------------
# Infrastructure writing
# ---------------------------------------------------------------------------


class TestWriteInfrastructure:
    """Tests for styles.ts and Reference.tsx generation."""

    def test_writes_styles_and_reference(self, tmp_path):
        scenes_dir = tmp_path / "scenes"
        _write_infrastructure(scenes_dir, "Test Project")

        assert (scenes_dir / "styles.ts").exists()
        styles = (scenes_dir / "styles.ts").read_text()
        assert "Test Project" in styles
        assert "COLORS" in styles

        assert (scenes_dir / "components" / "Reference.tsx").exists()
        ref = (scenes_dir / "components" / "Reference.tsx").read_text()
        assert "Reference" in ref


# ---------------------------------------------------------------------------
# Script reading
# ---------------------------------------------------------------------------


class TestReadScript:
    """Tests for _read_script."""

    def test_reads_script(self, project_dir, sample_script):
        script = _read_script(project_dir)
        assert script["title"] == "Test Video"
        assert len(script["scenes"]) == 3

    def test_missing_script_raises(self, tmp_path):
        empty_project = tmp_path / "empty"
        empty_project.mkdir()
        with pytest.raises(FileNotFoundError, match="Script not found"):
            _read_script(empty_project)


class TestReadVoiceoverManifest:
    """Tests for _read_voiceover_manifest."""

    def test_reads_manifest(self, project_dir):
        timestamps = _read_voiceover_manifest(project_dir)
        assert "scene1_hook" in timestamps
        assert len(timestamps["scene1_hook"]) == 4

    def test_missing_manifest_returns_empty(self, tmp_path):
        empty_project = tmp_path / "no-manifest"
        empty_project.mkdir()
        assert _read_voiceover_manifest(empty_project) == {}


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestBuildScenePrompt:
    """Tests for _build_scene_prompt."""

    def test_builds_prompt_with_all_fields(self, sample_script, tmp_path):
        scene = sample_script["scenes"][0]
        scenes_dir = tmp_path / "scenes"
        info = _build_scene_prompt(scene, 1, scenes_dir, [])

        assert info["scene_number"] == 1
        assert info["component_name"] == "TheHookScene"
        assert info["scene_key"] == "hook"
        assert info["filename"] == "TheHookScene.tsx"
        assert "Welcome to our video" in info["prompt"]

    def test_builds_prompt_with_visual_cue_format(self, tmp_path):
        """GIVEN a scene with visual_cue (old format) WHEN building THEN extracts correctly."""
        scene = {
            "title": "Old Format Scene",
            "scene_type": "explanation",
            "duration_seconds": 20,
            "voiceover": "Test narration",
            "visual_cue": {
                "description": "A diagram showing...",
                "elements": ["box", "arrow"],
            },
        }
        info = _build_scene_prompt(scene, 1, tmp_path / "scenes", [])
        assert "A diagram showing" in info["prompt"]


class TestCollectGeneratedScenes:
    """Tests for rebuilding index metadata from existing scene files."""

    def test_collects_only_existing_scene_files(self, sample_script, tmp_path):
        scenes_dir = tmp_path / "scenes"
        scenes_dir.mkdir()
        (scenes_dir / "TheHookScene.tsx").write_text("export const TheHookScene = () => null;")
        (scenes_dir / "ANewSolutionScene.tsx").write_text(
            "export const ANewSolutionScene = () => null;"
        )

        generated = _collect_generated_scenes(sample_script, scenes_dir)

        assert [entry["scene_number"] for entry in generated] == [1, 3]
        assert [entry["scene_key"] for entry in generated] == ["hook", "new_solution"]


# ---------------------------------------------------------------------------
# Result processing
# ---------------------------------------------------------------------------


class TestProcessSceneResult:
    """Tests for _process_scene_result."""

    def test_success_writes_file(self, tmp_path):
        scenes_dir = tmp_path / "scenes"
        scenes_dir.mkdir()

        info = {
            "scene_number": 1,
            "title": "Hook",
            "component_name": "HookScene",
            "filename": "HookScene.tsx",
            "scene_key": "hook",
        }
        agent_result = AgentResult(
            text='```tsx\nimport React from "react";\nexport const HookScene = () => null;\n```',
            success=True,
            duration_seconds=5.0,
        )
        result = _process_scene_result(info, agent_result, scenes_dir)

        assert result.success is True
        assert (scenes_dir / "HookScene.tsx").exists()

    def test_failed_agent_returns_error(self, tmp_path):
        info = {
            "scene_number": 1,
            "title": "Hook",
            "component_name": "HookScene",
            "filename": "HookScene.tsx",
            "scene_key": "hook",
        }
        agent_result = AgentResult(
            text="",
            success=False,
            duration_seconds=60.0,
            error="Timed out",
        )
        result = _process_scene_result(info, agent_result, tmp_path)
        assert result.success is False
        assert "Timed out" in result.error

    def test_no_code_extraction_returns_error(self, tmp_path):
        info = {
            "scene_number": 1,
            "title": "Hook",
            "component_name": "HookScene",
            "filename": "HookScene.tsx",
            "scene_key": "hook",
        }
        agent_result = AgentResult(
            text="Sorry, I can't generate that.",
            success=True,
            duration_seconds=3.0,
        )
        result = _process_scene_result(info, agent_result, tmp_path)
        assert result.success is False
        assert "extract TSX" in result.error


# ---------------------------------------------------------------------------
# Tool-level integration tests
# ---------------------------------------------------------------------------


class TestAgentGenerateScenes:
    """Integration tests for the agent_generate_scenes tool."""

    @pytest.mark.asyncio
    async def test_happy_path(self, project_dir, monkeypatch):
        """GIVEN a valid project WHEN generating scenes THEN writes all files."""
        monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(project_dir.parent))

        from video_agent_mcp.config import reset_config
        reset_config()

        tsx_code = 'import React from "react";\nexport const Scene = () => null;'

        async def mock_parallel(queries, *, concurrency=5):
            return [
                AgentResult(text=f"```tsx\n{tsx_code}\n```", success=True, duration_seconds=5.0)
                for _ in queries
            ]

        with patch("video_agent_mcp.tools.scenes.run_parallel_queries", side_effect=mock_parallel):
            result = await agent_generate_scenes(
                project_id=project_dir.name,
                concurrency=3,
                force=True,
            )

        assert len(result["scenes"]) == 3
        assert len(result["errors"]) == 0
        assert result["wall_clock_seconds"] >= 0

        scenes_dir = project_dir / "scenes"
        assert (scenes_dir / "styles.ts").exists()
        assert (scenes_dir / "index.ts").exists()
        assert (scenes_dir / "components" / "Reference.tsx").exists()

    @pytest.mark.asyncio
    async def test_partial_failure(self, project_dir, monkeypatch):
        """GIVEN some scenes fail WHEN generating THEN reports both successes and errors."""
        monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(project_dir.parent))

        from video_agent_mcp.config import reset_config
        reset_config()

        tsx_code = 'import React from "react";\nexport const Scene = () => null;'
        call_count = {"n": 0}

        async def mock_parallel(queries, *, concurrency=5):
            results = []
            for _ in queries:
                call_count["n"] += 1
                if call_count["n"] == 2:
                    results.append(AgentResult(
                        text="", success=False, duration_seconds=60.0, error="Timed out"
                    ))
                else:
                    results.append(AgentResult(
                        text=f"```tsx\n{tsx_code}\n```", success=True, duration_seconds=5.0
                    ))
            return results

        with patch("video_agent_mcp.tools.scenes.run_parallel_queries", side_effect=mock_parallel):
            result = await agent_generate_scenes(
                project_id=project_dir.name,
                force=True,
            )

        assert len(result["scenes"]) == 2
        assert len(result["errors"]) == 1
        assert result["errors"][0]["error"] == "Timed out"

    @pytest.mark.asyncio
    async def test_existing_scenes_without_force(self, project_dir, monkeypatch):
        """GIVEN existing scenes WHEN force=False THEN returns error."""
        monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(project_dir.parent))

        from video_agent_mcp.config import reset_config
        reset_config()

        scenes_dir = project_dir / "scenes"
        scenes_dir.mkdir()
        (scenes_dir / "SomeScene.tsx").write_text("// existing")

        result = await agent_generate_scenes(project_id=project_dir.name, force=False)

        assert "error" in result
        assert "SCENES_EXIST" in result["category"]

    @pytest.mark.asyncio
    async def test_missing_project(self, monkeypatch):
        """GIVEN a nonexistent project WHEN generating THEN returns error."""
        monkeypatch.setenv("EXPLAINER_PATH", "/tmp/test-explainer")

        from video_agent_mcp.config import reset_config
        reset_config()

        result = await agent_generate_scenes(project_id="nonexistent-project")

        assert "error" in result
        assert "PROJECT_NOT_FOUND" in result["category"]


class TestAgentGenerateSingleScene:
    """Tests for agent_generate_single_scene tool."""

    @pytest.mark.asyncio
    async def test_single_scene_success(self, project_dir, monkeypatch):
        """GIVEN a valid project WHEN generating scene 1 THEN writes the file."""
        monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(project_dir.parent))

        from video_agent_mcp.config import reset_config
        reset_config()

        tsx_code = 'import React from "react";\nexport const TheHookScene = () => null;'

        async def mock_query(prompt, *, system_prompt=None, **kwargs):
            return AgentResult(
                text=f"```tsx\n{tsx_code}\n```",
                success=True,
                duration_seconds=5.0,
            )

        with patch("video_agent_mcp.tools.scenes.run_agent_query", side_effect=mock_query):
            result = await agent_generate_single_scene(
                project_id=project_dir.name,
                scene_number=1,
            )

        assert result["success"] is True
        assert result["component_name"] == "TheHookScene"

    @pytest.mark.asyncio
    async def test_single_scene_retry_rebuilds_index(self, project_dir, monkeypatch):
        """GIVEN a partial run WHEN retrying one scene THEN index.ts includes retried scene."""
        monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(project_dir.parent))

        from video_agent_mcp.config import reset_config
        reset_config()

        async def mock_parallel(queries, *, concurrency=5):
            return [
                AgentResult(
                    text='```tsx\nexport const TheHookScene = () => null;\n```',
                    success=True,
                    duration_seconds=1.0,
                ),
                AgentResult(text="", success=False, error="Timed out", duration_seconds=60.0),
                AgentResult(text="", success=False, error="Timed out", duration_seconds=60.0),
            ]

        with patch("video_agent_mcp.tools.scenes.run_parallel_queries", side_effect=mock_parallel):
            first_result = await agent_generate_scenes(project_id=project_dir.name, force=True)

        assert len(first_result["scenes"]) == 1
        index_path = project_dir / "scenes" / "index.ts"
        before_retry = index_path.read_text()
        assert '"big_problem": TheBigProblemScene,' not in before_retry

        async def mock_query(prompt, *, system_prompt=None, **kwargs):
            return AgentResult(
                text='```tsx\nexport const TheBigProblemScene = () => null;\n```',
                success=True,
                duration_seconds=1.0,
            )

        with patch("video_agent_mcp.tools.scenes.run_agent_query", side_effect=mock_query):
            retry_result = await agent_generate_single_scene(
                project_id=project_dir.name,
                scene_number=2,
            )

        assert retry_result["success"] is True
        after_retry = index_path.read_text()
        assert '"big_problem": TheBigProblemScene,' in after_retry

    @pytest.mark.asyncio
    async def test_single_scene_out_of_range(self, project_dir, monkeypatch):
        """GIVEN scene_number > total scenes WHEN generating THEN returns error."""
        monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(project_dir.parent))

        from video_agent_mcp.config import reset_config
        reset_config()

        result = await agent_generate_single_scene(
            project_id=project_dir.name,
            scene_number=99,
        )

        assert "error" in result


async def test_duplicate_scene_names_fail_before_queries(project_dir, monkeypatch):
    """Title collisions are rejected before paid work or silent file overwrites."""
    import json

    from video_agent_mcp.config import reset_config
    script_file = project_dir / "script" / "script.json"
    script = json.loads(script_file.read_text())
    script["scenes"][1]["title"] = script["scenes"][0]["title"]
    script_file.write_text(json.dumps(script))
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(project_dir.parent))
    reset_config()
    with patch("video_agent_mcp.tools.scenes.run_parallel_queries") as query:
        result = await agent_generate_scenes(project_dir.name)
    query.assert_not_called()
    assert "unique component filenames and keys" in result["error"]
    assert not (project_dir / "scenes").exists()
