#!/usr/bin/env bash
set -euo pipefail

# High-signal security regression smoke suite consolidated in iteration 10.
export PYTHONPATH=src

uv run pytest -q \
  tests/test_content_tools.py::TestContentAnalyze::test_url_rejects_non_https_before_model_call \
  tests/test_infra_tools.py::TestInfraTools::test_infra_configure_requires_token_when_configured \
  tests/test_video_file.py::TestUploadCache::test_concurrent_same_hash_uploads_once \
  tests/test_video_file.py::TestValidateVideoPath::test_rejects_path_outside_local_access_root \
  tests/test_research_document_tools.py::TestResearchDocument::test_surfaces_preparation_issues \
  tests/test_research_document_tools.py::TestResearchDocument::test_rejects_too_many_sources \
  tests/test_url_policy.py::TestDownloadChecked::test_blocks_redirect_before_following_blocked_target \
  tests/test_content_batch_tools.py::TestContentBatchAnalyze::test_compare_mode
