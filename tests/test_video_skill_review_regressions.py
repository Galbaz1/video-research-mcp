"""Original review failures must refuse redistribution and bound changed file types."""

import json
import os

import pytest

from scripts import package_video_skill as pack
from scripts import validate_video_skill as validator
from tests.test_video_skill import candidate as candidate


def invoke(entry, root, output):
    """Exercise the selected public function with an existing package destination."""
    return validator.validate_skill(root) if entry == "validate" else pack.package_skill(root, output)


@pytest.mark.parametrize("entry", ["validate", "package"])
def test_regular_input_replaced_with_fifo_refuses_without_wait(candidate, tmp_path, monkeypatch, entry):
    """GIVEN a substitution after stat, WHEN opened, THEN refuse before any FIFO read."""
    root, _ = candidate
    output = tmp_path / "previous.skill"
    output.write_bytes(b"owned previous package")
    previous = output.read_bytes()
    source = root / ".build/source.bin"
    real_open = os.open
    substituted = []

    def replace_after_stat(path, flags, *args, **kwargs):
        if path == "source.bin":
            # Fail the original implementation before a potentially blocking FIFO open.
            assert flags & os.O_NONBLOCK, "Final retained input open must be nonblocking"
            source.unlink()
            os.mkfifo(source, 0o600)
            substituted.append(True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace_after_stat)
    result = invoke(entry, root, output)
    assert substituted == [True]
    assert result["status"] == "fail" and result["error"] == "file size/type bound"
    assert output.read_bytes() == previous
    assert not list(tmp_path.glob(".video-skill-*.tmp"))


@pytest.mark.parametrize("entry", ["validate", "package"])
@pytest.mark.parametrize("key", ["api_key", "api-key", "access_token", "secret"])
def test_quoted_json_credential_resource_is_refused_and_redacted(candidate, tmp_path, entry, key):
    """GIVEN a linked JSON credential, WHEN checked, THEN preserve output and hide its value."""
    root, _ = candidate
    output = tmp_path / "previous.skill"
    output.write_bytes(b"owned previous package")
    previous = output.read_bytes()
    fake = "synthetic_only_secret_1234567890"
    (root / "references/settings.json").write_text(json.dumps({key: fake}))
    with (root / "SKILL.md").open("a") as stream:
        stream.write("\n[settings](references/settings.json)\n")
    result = invoke(entry, root, output)
    assert result["status"] == "fail", result
    assert "unsafe embedded instruction or task pattern" in result["error"]
    assert fake not in json.dumps(result)
    assert output.read_bytes() == previous
    assert not list(tmp_path.glob(".video-skill-*.tmp"))
