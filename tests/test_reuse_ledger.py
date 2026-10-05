"""Check that the reuse gate rejects uncleared routes and archive payloads."""

import io
import json
from pathlib import Path
import shutil
import tarfile
import zipfile

import pytest

from scripts.check_reuse_ledger import LEDGER, ROOT, check_archive, sha256, validate_ledger


@pytest.fixture
def receipt_root(tmp_path):
    """Copy only source authority and receipt inputs into an isolated workspace."""
    paths = [
        LEDGER,
        "THIRD_PARTY_NOTICES.md",
        "LICENSE",
        "licenses/fpdf2/GPL-3.0.txt",
        "licenses/fpdf2/LGPL-3.0.txt",
        "docs/research/2026-09-30-capability-transfer.json",
        "uv.lock",
        "packages/video-agent-mcp/uv.lock",
        "packages/video-explainer-mcp/uv.lock",
    ]
    data = json.loads((ROOT / LEDGER).read_text())
    paths += [
        receipt["target_path"] for unit in data["units"] for receipt in unit["implementations"]
    ]
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    return tmp_path


@pytest.fixture
def ledger(receipt_root):
    """Read independent editable receipt input for each negative case."""
    return json.loads((receipt_root / LEDGER).read_text())


def wheel(root: Path, path: Path, extra=None, package="video-research-mcp", omit=()):
    """Build a tiny archive fixture with the real notice and ledger bytes."""
    members = {
        "test.dist-info/METADATA": f"Name: {package}\nVersion: 1.0\n".encode(),
        "test.dist-info/licenses/LICENSE": (root / "LICENSE").read_bytes(),
        "THIRD_PARTY_NOTICES.md": (root / "THIRD_PARTY_NOTICES.md").read_bytes(),
        "reuse-ledger.json": (root / LEDGER).read_bytes(),
        "example.py": b'"""Own fixture source."""\n',
        "licenses/fpdf2/GPL-3.0.txt": (root / "licenses/fpdf2/GPL-3.0.txt").read_bytes(),
        "licenses/fpdf2/LGPL-3.0.txt": (root / "licenses/fpdf2/LGPL-3.0.txt").read_bytes(),
    }
    members.update(extra or {})
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            if name not in omit:
                archive.writestr(name, data)
    return path


def test_current_source_and_lock_population_is_accounted_for(receipt_root):
    """GIVEN current receipts WHEN checked THEN plans remain distinct from adoption."""
    data = validate_ledger(receipt_root)
    assert len(data["units"]) == 85
    assert len(data["dependency_locks"]) == 3
    assert len(data["dependency_packages"]) == 120
    assert {u["unit_key"] for u in data["units"] if u["adoption"] == "adopted"} == {
        "qwen_reverse_image",
        "qwen_segmentation",
        "qwen_footage_edit",
        "qwen_av_events",
        "qwen_educational",
        "qwen_file_visualization",
        "qwen_speech",
        "direct.speech",
        "direct.twelvelabs",
        "direct.audio_qa",
        "adj_research_eval",
        "adj_video_eval",
        "direct.security",
        "own.strict-evidence-semantics",
        "adj_evidence_packet",
        "qwen_reuse_manifest",
        "direct.providers",
        "own.analysis-cache-contract",
        "direct.identity",
        "direct.budgets",
        "own.interactions-compatibility",
        "adj_durable_jobs",
        "direct.batch_jobs",
        "direct.acquisition",
        "qwen_native_media",
        "direct.frames",
        "own.local-windowing-upload-recovery",
        "direct.long_video",
        "qwen_media_assets",
        "direct.image_ops",
        "qwen_vision_api",
        "direct.image_vision",
        "direct.ocr_timeline",
        "qwen_scene_assets",
        "qwen_av_perception",
        "own.grounded-research-routing",
        "adj_research_workflow",
        "qwen_search_backends",
        "adj_provider_adapters",
        "adj_external_harness",
        "adj_context_compaction",
        "adj_video_planning",
        "adj_render_pipeline",
        "adj_ingestion",
        "qwen_hardware",
        "qwen_video_to_skill",
        "qwen_tutorial_note",
        "qwen_blender",
        "qwen_freecad",
        "qwen_spatial",
        "qwen_tts",
        "adj_tts_audio",
    }
    assert all(not u["imports"] for u in data["units"])
    transfers = [(u, receipt) for u in data["units"] for receipt in u["transfers"]]
    assert len(transfers) == 3
    assert all(
        u["unit_key"] == "own.interactions-compatibility"
        and receipt["scope"] == "Test-only exact bodies; production transfers empty"
        for u, receipt in transfers
    )
    assert data["bundled_assets"] == []
    assert data["optional_runtime_receipts"] == []


@pytest.mark.parametrize("mutation", ["remove", "duplicate", "revision", "paths"])
def test_pinned_unit_cannot_disappear_or_change(receipt_root, ledger, mutation):
    """GIVEN a source population change WHEN checked THEN the gate rejects it."""
    if mutation == "remove":
        ledger["units"].pop()
    elif mutation == "duplicate":
        ledger["units"].append(ledger["units"][0])
    elif mutation == "revision":
        ledger["units"][0]["source_revision"] = "0" * 40
    else:
        ledger["units"][0]["source_paths"] = []
    with pytest.raises(ValueError, match="coverage|Duplicate|Source contract"):
        validate_ledger(receipt_root, ledger)


def test_adoption_requires_actual_file_or_import_receipt(receipt_root, ledger):
    """GIVEN an implementation claim without outputs THEN it cannot pass."""
    unit = next(u for u in ledger["units"] if u["adoption"] == "not-adopted")
    unit["adoption"] = "adopted"
    with pytest.raises(ValueError, match="adoption receipt"):
        validate_ledger(receipt_root, ledger)


def test_missing_grant_cannot_be_relabelled_permissive(receipt_root, ledger):
    """GIVEN renderer metadata relabelled MIT THEN the pinned copy block persists."""
    unit = next(u for u in ledger["units"] if u["source_repo"] == "prajwal-y/video_explainer")
    component = next(c for c in ledger["components"] if c["repo"] == unit["source_repo"])
    component["clearance"] = "verified-code-grant"
    component["commercial_code_use"] = True
    unit.update(permitted_route="copy", adoption="adopted")
    unit["implementations"] = [
        {"target_path": "LICENSE", "target_sha256": sha256((receipt_root / "LICENSE").read_bytes())}
    ]
    with pytest.raises(ValueError, match="Per-file grant not cleared"):
        validate_ledger(receipt_root, ledger)


def test_transfers_cannot_hide_under_independent_implementation(receipt_root, ledger):
    """GIVEN a transfer described as own code THEN a route contradiction fails."""
    unit = ledger["units"][0]
    unit.update(adoption="adopted", transfers=[{}])
    with pytest.raises(ValueError, match="Transfer contradicts route"):
        validate_ledger(receipt_root, ledger)


def test_foreign_source_cannot_use_the_own_source_route(receipt_root, ledger):
    """GIVEN an uncleared foreign source THEN calling it own source cannot clear it."""
    ledger["units"][0]["permitted_route"] = "own-source"
    with pytest.raises(ValueError, match="Foreign source labelled own"):
        validate_ledger(receipt_root, ledger)


def test_dependency_lock_mutation_requires_a_new_receipt(receipt_root, ledger):
    """GIVEN changed dependency bytes THEN the old lock receipt fails."""
    with (receipt_root / "uv.lock").open("a") as stream:
        stream.write("\n# changed dependency selection\n")
    with pytest.raises(ValueError, match="lock hash drift"):
        validate_ledger(receipt_root, ledger)


def test_unobserved_dependency_artifact_is_rejected(receipt_root, ledger):
    """GIVEN a package with no registry artifact proof THEN imports are uncleared."""
    ledger["dependency_packages"][0]["registry_artifact_hashes"] = []
    with pytest.raises(ValueError, match="Unreceipted dependency artifact"):
        validate_ledger(receipt_root, ledger)


def test_operational_block_cannot_be_omitted(receipt_root, ledger):
    """GIVEN missing noncommercial disposition THEN the gate fails."""
    ledger["blocks"] = [b for b in ledger["blocks"] if b["id"] != "imagebind-commercial"]
    with pytest.raises(ValueError, match="Missing operational disposition"):
        validate_ledger(receipt_root, ledger)


def test_verified_dependency_grant_must_be_distributed_in_full(receipt_root, ledger):
    """GIVEN a BSD title/copyright without its terms THEN the notice is incomplete."""
    path = receipt_root / "THIRD_PARTY_NOTICES.md"
    grant = next(
        item for item in ledger["dependency_packages"] if item["name"] == "weaviate-agents"
    )["source_grant"]["text"].strip()
    notices = path.read_text()
    assert grant in notices
    path.write_text(notices.replace(grant, "Copyright (c) 2025, Weaviate\nBSD 3-Clause License"))
    with pytest.raises(ValueError, match="Missing full verified dependency grant"):
        validate_ledger(receipt_root, ledger)


def test_own_source_wheel_passes_with_exact_receipts(receipt_root, tmp_path):
    """GIVEN clear source and actual notice bytes THEN the archive passes."""
    path = wheel(receipt_root, tmp_path / "fixture.whl")
    result = check_archive(path, receipt_root)
    assert result["files"] == 7
    assert result["sha256"] == sha256(path.read_bytes())


@pytest.mark.parametrize(
    "name,data",
    [
        ("assets/uncleared.ttf", b"font bytes"),
        ("models/checkpoint.safetensors", b"model bytes"),
        ("assets/logo.svg", b"<svg></svg>"),
        ("assets/disguised.json", b"\x00\xffbinary"),
    ],
)
def test_unreceipted_archive_asset_fails_even_with_forged_extension(
    receipt_root, tmp_path, name, data
):
    """GIVEN a bundled asset without rights evidence THEN bytes cannot ship."""
    path = wheel(receipt_root, tmp_path / "asset.whl", {name: data})
    with pytest.raises(ValueError, match="Unreceipted archive asset"):
        check_archive(path, receipt_root)


def test_archive_asset_requires_commercial_permission_and_matching_hash(
    receipt_root, ledger, tmp_path
):
    """GIVEN a receipted asset THEN permission and actual bytes both remain gates."""
    name = "assets/own.svg"
    data = b"<svg>own fixture</svg>"
    target = receipt_root / name
    target.parent.mkdir()
    target.write_bytes(data)
    grant = (receipt_root / "LICENSE").read_text()
    notices = receipt_root / "THIRD_PARTY_NOTICES.md"
    notices.write_text(notices.read_text() + "\n" + grant + "\nChanged: own fixture.\n")
    receipt = {
        "target_path": name,
        "target_sha256": sha256(data),
        "commercial_redistribution": False,
        "license": "MIT",
        "license_source": "LICENSE",
        "license_text": grant,
        "copyright": "Copyright (c) 2026 Fausto Albers",
        "change_notice": "Changed: own fixture.",
    }
    ledger["bundled_assets"] = [receipt]
    with pytest.raises(ValueError, match="Uncleared commercial asset"):
        validate_ledger(receipt_root, ledger)
    receipt["commercial_redistribution"] = True
    receipt["license"] = "CC-BY-NC-4.0"
    with pytest.raises(ValueError, match="Restricted asset license"):
        validate_ledger(receipt_root, ledger)
    receipt["license"] = "MIT"
    (receipt_root / LEDGER).write_text(json.dumps(ledger))
    clear = wheel(receipt_root, tmp_path / "clear.whl", {name: data})
    assert check_archive(clear, receipt_root)["assets"] == 1
    changed = wheel(receipt_root, tmp_path / "changed.whl", {name: b"<svg>different</svg>"})
    with pytest.raises(ValueError, match="Archive asset hash drift"):
        check_archive(changed, receipt_root)


@pytest.mark.parametrize("missing", [
    "THIRD_PARTY_NOTICES.md", "reuse-ledger.json",
    "licenses/fpdf2/GPL-3.0.txt", "licenses/fpdf2/LGPL-3.0.txt",
])
def test_archive_requires_current_notices_and_ledger(receipt_root, tmp_path, missing):
    """GIVEN a distribution missing an audit receipt THEN it cannot pass."""
    path = wheel(receipt_root, tmp_path / "missing.whl", omit=[missing])
    with pytest.raises(ValueError, match="Missing or stale archive receipt"):
        check_archive(path, receipt_root)


@pytest.mark.parametrize("license_name", ["GPL-3.0.txt", "LGPL-3.0.txt"])
def test_pdf_writer_application_license_cannot_be_shortened(receipt_root, ledger, license_name):
    """GIVEN only a license label THEN full required application terms are missing."""
    (receipt_root / "licenses/fpdf2" / license_name).write_text(license_name)
    with pytest.raises(ValueError, match="PDF writer application license"):
        validate_ledger(receipt_root, ledger)


def test_fake_companion_source_does_not_bypass_root_notice_gate(receipt_root, tmp_path):
    """GIVEN a root wheel with a companion-looking file THEN actual metadata wins."""
    path = wheel(
        receipt_root,
        tmp_path / "fake.whl",
        {"video_agent_mcp/fake.py": b"pass"},
        omit=["THIRD_PARTY_NOTICES.md"],
    )
    with pytest.raises(ValueError, match="Missing or stale archive receipt"):
        check_archive(path, receipt_root)


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "..\\escape.txt"])
def test_archive_rejects_unsafe_paths(receipt_root, tmp_path, name):
    """GIVEN an unsafe member THEN validation rejects it without extraction."""
    path = wheel(receipt_root, tmp_path / "unsafe.whl", {name: b"text"})
    with pytest.raises(ValueError, match="unsafe path"):
        check_archive(path, receipt_root)


def test_tar_symlink_is_rejected_without_extraction(receipt_root, tmp_path):
    """GIVEN a tar symlink THEN no linked external content is inspected."""
    path = tmp_path / "linked.tgz"
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo("package/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "../../outside"
        archive.addfile(member)
    with pytest.raises(ValueError, match="link or special member"):
        check_archive(path, receipt_root)


def test_actual_npm_tar_bytes_pass(receipt_root, tmp_path):
    """GIVEN the npm archive format THEN the same notice and asset gate applies."""
    members = {
        "package/package.json": b'{"name":"video-research-mcp"}',
        "package/LICENSE": (receipt_root / "LICENSE").read_bytes(),
        "package/THIRD_PARTY_NOTICES.md": (receipt_root / "THIRD_PARTY_NOTICES.md").read_bytes(),
        "package/" + LEDGER: (receipt_root / LEDGER).read_bytes(),
        "package/licenses/fpdf2/GPL-3.0.txt": (receipt_root / "licenses/fpdf2/GPL-3.0.txt").read_bytes(),
        "package/licenses/fpdf2/LGPL-3.0.txt": (receipt_root / "licenses/fpdf2/LGPL-3.0.txt").read_bytes(),
    }
    path = tmp_path / "fixture.tgz"
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    assert check_archive(path, receipt_root)["files"] == 6


@pytest.mark.parametrize("name", ["generate_video.py", "README.md", ".dockerignore"])
def test_archive_rejects_uncleared_renderer_text(receipt_root, tmp_path, name):
    """A root MIT grant cannot authorize the blocked renderer subtree's text."""
    path = wheel(
        receipt_root, tmp_path / "fixture.whl",
        {f"packages/video-explainer/{name}": b"foreign renderer text"},
    )
    with pytest.raises(ValueError, match="Uncleared renderer submodule"):
        check_archive(path, receipt_root)


def test_archive_allows_own_renderer_adapter_path(receipt_root, tmp_path):
    """The own companion wrapper remains distinct from the uncleared renderer."""
    path = wheel(
        receipt_root, tmp_path / "fixture.whl",
        {"packages/video-explainer-mcp/README.md": b"own wrapper"},
    )
    assert check_archive(path, receipt_root)["files"] == 8


def test_archive_rejects_renderer_dot_path_alias(receipt_root, tmp_path):
    """Equivalent safe tar paths must enforce the same renderer subtree boundary."""
    members = {
        "fixture/PKG-INFO": b"Name: video-explainer-mcp\nVersion: 1.0\n",
        "fixture/LICENSE": (receipt_root / "LICENSE").read_bytes(),
        "fixture/packages/./video-explainer/README.md": b"synthetic renderer text",
    }
    path = tmp_path / "fixture.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    with pytest.raises(ValueError, match="Uncleared renderer submodule"):
        check_archive(path, receipt_root)
