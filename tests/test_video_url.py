"""Tests for video URL helpers — VideoMetadata support on Parts."""

from __future__ import annotations

from video_research_mcp.tools.video_url import (
    _video_content,
    _video_content_with_metadata,
)


class TestVideoContentWithMetadata:
    def test_no_overrides_no_video_metadata(self):
        """Without any overrides, video_metadata is not set on the Part."""
        content = _video_content_with_metadata(
            "https://www.youtube.com/watch?v=abc123", "summarize"
        )
        assert content.parts[0].file_data.file_uri == "https://www.youtube.com/watch?v=abc123"
        assert content.parts[0].file_data.mime_type == "video/mp4"
        assert content.parts[0].video_metadata is None
        assert content.parts[1].text == "summarize"

    def test_fps_override_sets_video_metadata(self):
        """fps override creates VideoMetadata with fps populated."""
        content = _video_content_with_metadata(
            "https://www.youtube.com/watch?v=abc123", "analyze", fps=2.0
        )
        vm = content.parts[0].video_metadata
        assert vm is not None
        assert vm.fps == 2.0
        assert vm.start_offset is None
        assert vm.end_offset is None

    def test_all_overrides_fully_populated(self):
        """All overrides produce a fully populated VideoMetadata."""
        content = _video_content_with_metadata(
            "https://www.youtube.com/watch?v=abc123",
            "analyze",
            fps=1.0,
            start_offset="10s",
            end_offset="5m",
        )
        vm = content.parts[0].video_metadata
        assert vm is not None
        assert vm.fps == 1.0
        assert vm.start_offset == "10s"
        assert vm.end_offset == "5m"

    def test_matches_video_content_without_overrides(self):
        """Without overrides, output structure matches _video_content."""
        url = "https://www.youtube.com/watch?v=abc123"
        prompt = "test prompt"
        basic = _video_content(url, prompt)
        enhanced = _video_content_with_metadata(url, prompt)

        assert basic.parts[0].file_data.file_uri == enhanced.parts[0].file_data.file_uri
        assert basic.parts[0].file_data.mime_type == enhanced.parts[0].file_data.mime_type == "video/mp4"
        assert basic.parts[1].text == enhanced.parts[1].text
