"""Exact-byte catalog lifecycle, restart, corruption and owned-file boundaries."""

import hashlib
import json
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from video_research_mcp.media_assets import AssetCatalog
from video_research_mcp.media_local_io import _copy_hash


@pytest.fixture(autouse=True)
def isolated_catalog(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))


def adopt(catalog, source):
    return catalog.adopt(source, alias=str(source), provenance={"method": "owned_fixture"})


def test_exact_dedup_and_restart_preserve_originals_aliases_and_permissions(tmp_path):
    """GIVEN identical originals WHEN adopted and reopened THEN one fresh identity retains both aliases."""
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    for path in (a, b):
        path.write_bytes(b"original owned fixture")
    first = adopt(AssetCatalog(), a)
    second = adopt(AssetCatalog(), b)
    restarted = AssetCatalog().get(first["asset_id"])
    assert first["asset_id"] == second["asset_id"] == hashlib.sha256(a.read_bytes()).hexdigest()
    assert first["reused"] is False and second["reused"] is True
    assert restarted["aliases"] == [str(a), str(b)]
    assert Path(restarted["path"]).read_bytes() == a.read_bytes() == b.read_bytes()
    assert stat.S_IMODE(Path(restarted["path"]).stat().st_mode) == 0o600
    assert stat.S_IMODE(AssetCatalog().root.stat().st_mode) == 0o700
    assert stat.S_IMODE(AssetCatalog().database.stat().st_mode) == 0o600


def test_concurrent_catalogs_deduplicate_exact_bytes(tmp_path):
    source = tmp_path / "owned.mp4"
    source.write_bytes(b"owned parallel fixture")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: adopt(AssetCatalog(), source), range(2)))
    assert len({r["asset_id"] for r in results}) == 1
    assert sorted(r["reused"] for r in results) == [False, True]
    assert AssetCatalog().list()["total"] == 1


def test_removal_invalidates_only_digest_and_never_originals(tmp_path):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"owned fixture")
    record = adopt(AssetCatalog(), source)
    with patch("video_research_mcp.media_assets.invalidate_source", return_value=2) as invalidate:
        result = AssetCatalog().remove(record["asset_id"])
    invalidate.assert_called_once_with(record["asset_id"])
    assert result["removed"] is True and result["originals_removed"] is False
    assert result["invalidated_cache_entries"] == 2
    assert source.read_bytes() == b"owned fixture"
    assert not Path(record["path"]).exists() and AssetCatalog().list()["total"] == 0


@pytest.mark.parametrize("identity", ["/tmp/original.mp4", "../outside.mp4", "a" * 63, "A" * 64])
def test_paths_and_invalid_ids_cannot_authorize_deletion(identity):
    with pytest.raises(ValueError, match="paths cannot be removed"):
        AssetCatalog().remove(identity)


@pytest.mark.parametrize("state", ["corrupt", "deleted", "symlink"])
def test_unhealthy_owned_asset_never_reuses_or_deletes_substitute(tmp_path, state):
    """GIVEN a mutated catalog destination WHEN reused or removed THEN original/substitute survive."""
    source = tmp_path / "original.mp4"
    source.write_bytes(b"owned unchanged")
    record = adopt(AssetCatalog(), source)
    owned = Path(record["path"])
    if state == "corrupt":
        owned.write_bytes(b"later user bytes")
    else:
        owned.unlink()
        if state == "symlink":
            owned.symlink_to(source)
    for operation in (
        lambda: AssetCatalog().get(record["asset_id"]),
        lambda: adopt(AssetCatalog(), source),
        lambda: AssetCatalog().remove(record["asset_id"]),
    ):
        with pytest.raises((OSError, ValueError)):
            operation()
    assert source.read_bytes() == b"owned unchanged"
    if state != "symlink":
        assert AssetCatalog().list()["assets"][0]["state"] == state


def test_catalog_suffix_injection_cannot_escape_owned_root(tmp_path):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"owned fixture")
    catalog = AssetCatalog()
    record = adopt(catalog, source)
    with catalog._connection() as db:
        db.execute("UPDATE assets SET suffix=?", ("/../../original.mp4",))
    with pytest.raises(ValueError, match="suffix"):
        catalog.remove(record["asset_id"])
    assert source.read_bytes() == b"owned fixture"


@pytest.mark.parametrize("slot", ["media", "objects", "catalog.sqlite3"])
def test_symlinked_catalog_or_storage_is_rejected(tmp_path, slot):
    catalog = AssetCatalog()
    target = tmp_path / "outside"
    if slot == "catalog.sqlite3":
        target.write_bytes(b"private original")
        catalog.database.unlink()
        catalog.database.symlink_to(target)
    else:
        path = catalog.root if slot == "media" else catalog.objects
        if slot == "media":
            catalog.database.unlink()
            catalog.objects.rmdir()
            catalog.staging.rmdir()
        path.rmdir()
        target.mkdir()
        path.symlink_to(target, target_is_directory=True)
    with pytest.raises(PermissionError):
        AssetCatalog()
    assert (
        list(target.iterdir()) == []
        if target.is_dir()
        else target.read_bytes() == b"private original"
    )


def test_empty_and_oversized_inputs_leave_no_partial_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_MAX_INPUT_BYTES", "4")
    for data in (b"", b"12345"):
        source = tmp_path / "source.mp4"
        source.write_bytes(data)
        with pytest.raises(ValueError):
            adopt(AssetCatalog(), source)
    catalog = AssetCatalog()
    assert catalog.list()["total"] == 0
    assert not list(catalog.objects.iterdir()) and not list(catalog.staging.iterdir())


def test_copy_hash_commits_the_same_retained_buffer(tmp_path):
    source, target = tmp_path / "source.mp4", tmp_path / "copy.mp4"
    source.write_bytes(b"original committed bytes")
    digest, count = _copy_hash(source, target)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    assert count == len(target.read_bytes())


def test_expected_transport_digest_is_checked_on_the_actual_copied_bytes(tmp_path):
    """GIVEN changed helper output WHEN adopted THEN stale transport provenance cannot bless new bytes."""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"later substitute bytes")
    with pytest.raises(ValueError, match="transport receipt"):
        AssetCatalog().adopt(
            source,
            alias="original",
            provenance={},
            expected_digest=hashlib.sha256(b"original").hexdigest(),
            expected_bytes=8,
        )
    assert AssetCatalog().list()["total"] == 0
    assert list(AssetCatalog().objects.iterdir()) == []


def test_cancel_before_commit_rolls_back_only_the_new_owned_file(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"owned")
    catalog, canceled = AssetCatalog(), threading.Event()
    original_record = catalog._record

    def cancel_after_readback(row, **kwargs):
        result = original_record(row, **kwargs)
        canceled.set()
        return result

    with patch.object(catalog, "_record", side_effect=cancel_after_readback):
        with pytest.raises(TimeoutError, match="before transaction commit"):
            catalog.adopt(source, alias=str(source), provenance={}, cancelled=canceled)
    assert source.read_bytes() == b"owned"
    assert catalog.list()["total"] == 0 and list(catalog.objects.iterdir()) == []
    assert list(catalog.staging.iterdir()) == []


def test_listing_bounds_total_hash_bytes_and_retains_unverified_denominator(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_MAX_INPUT_BYTES", "6")
    for index in range(3):
        source = tmp_path / f"owned-{index}.mp4"
        source.write_bytes(bytes([index]) * 4)
        adopt(AssetCatalog(), source)
    result = AssetCatalog().list()
    assert result["total"] == len(result["assets"]) == 3
    assert [record["state"] for record in result["assets"]] == ["verified", "unknown", "unknown"]
    assert all(
        record["verification_reason"] == "aggregate_byte_budget_exhausted"
        for record in result["assets"][1:]
    )
    assert result["verification_byte_budget"] == 6
    assert AssetCatalog().list(3)["assets"] == []


def test_user_edit_between_removal_hash_and_unlink_is_preserved(tmp_path):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"original owned")
    catalog = AssetCatalog()
    record = adopt(catalog, source)
    original_record = catalog._record

    def change_after_verified(row, **kwargs):
        result = original_record(row, **kwargs)
        Path(result["path"]).write_bytes(b"later owned slot edit")
        return result

    with patch.object(catalog, "_record", side_effect=change_after_verified):
        with pytest.raises(ValueError, match="before removal"):
            catalog.remove(record["asset_id"])
    assert Path(record["path"]).read_bytes() == b"later owned slot edit"
    assert source.read_bytes() == b"original owned"


def test_receipts_are_redacted_without_losing_alias_identity(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"owned")
    record = AssetCatalog().adopt(
        source,
        alias="https://cdn.example.invalid/owned.mp4?token=opaque-fixture-token",
        provenance={"method": "checked_fixture"},
    )
    assert "opaque-fixture-token" not in json.dumps(record)
    assert (
        record["provenance"][0]["alias_sha256"]
        == hashlib.sha256(
            b"https://cdn.example.invalid/owned.mp4?token=opaque-fixture-token"
        ).hexdigest()
    )


@pytest.mark.parametrize("offset,limit", [(True, 1), (0, True), (-1, 1), (0, 0), (0, 101)])
def test_invalid_page_coordinates_are_rejected(offset, limit):
    with pytest.raises(ValueError):
        AssetCatalog().list(offset, limit)


def test_oversized_historical_receipts_are_never_materialized_or_parsed(tmp_path):
    """GIVEN an oversized old row WHEN read THEN SQL hides its blob and history remains intact."""
    source = tmp_path / "original.mp4"
    source.write_bytes(b"original")
    catalog = AssetCatalog()
    record = adopt(catalog, source)
    oversized = json.dumps(
        [
            {
                "alias_sha256": "a" * 64,
                "source": "original",
                "acquisition": {"detail": "x" * (70 * 1024)},
            }
        ]
    )
    with catalog._connection() as db:
        db.execute("UPDATE assets SET receipts=?", (oversized,))
    original_record, observed = catalog._record, []

    def guard(row, **kwargs):
        observed.append(row["receipts"])
        assert row["receipts"] is None, "Oversized receipt blob was materialized in Python"
        return original_record(row, **kwargs)

    with patch.object(catalog, "_record", side_effect=guard):
        with pytest.raises(ValueError, match="receipt"):
            catalog.get(record["asset_id"])
    assert observed == [None]
    listed = catalog.list()
    assert listed["total"] == len(listed["assets"]) == 1
    assert listed["assets"][0]["state"] == "unknown"
    assert listed["assets"][0]["metadata_reason"] == "asset_receipt_byte_limit"
    assert listed["assets"][0]["metadata_included"] is False
    with catalog._connection() as db:
        assert db.execute("SELECT receipts FROM assets").fetchone()[0] == oversized
    assert source.read_bytes() == b"original"


def test_sql_receipt_limit_counts_utf8_bytes_not_characters(tmp_path):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"original")
    catalog = AssetCatalog()
    record = adopt(catalog, source)
    text = json.dumps(
        [{"alias_sha256": "a" * 64, "source": "original", "acquisition": {"detail": "😀" * 17000}}],
        ensure_ascii=False,
    )
    assert len(text) < 64 * 1024 < len(text.encode())
    with catalog._connection() as db:
        db.execute("UPDATE assets SET receipts=?", (text,))
    with patch.object(
        catalog, "_record", side_effect=AssertionError("No large row may be decoded")
    ):
        result = catalog.list()
    assert result["assets"][0]["metadata_included"] is False
    assert result["assets"][0]["metadata_reason"] == "asset_receipt_byte_limit"
    assert result["total"] == 1 and record["asset_id"] == result["assets"][0]["asset_id"]


def test_asset_receipt_capacity_rejects_new_alias_without_discard_or_commit(tmp_path):
    """GIVEN full valid source history WHEN a new alias arrives THEN bytes/history stay exact."""
    source = tmp_path / "original.mp4"
    source.write_bytes(b"original")
    catalog = AssetCatalog()
    first = catalog.adopt(source, alias="original-one", provenance={"detail": "x" * (60 * 1024)})
    with catalog._connection() as db:
        before = db.execute("SELECT receipts FROM assets").fetchone()[0]
    with pytest.raises(ValueError, match="receipt"):
        catalog.adopt(source, alias="original-two", provenance={"detail": "y" * (60 * 1024)})
    with catalog._connection() as db:
        assert db.execute("SELECT receipts FROM assets").fetchone()[0] == before
    assert catalog.get(first["asset_id"])["aliases"] == ["original-one"]
    assert Path(first["path"]).read_bytes() == source.read_bytes() == b"original"
    assert not list(catalog.staging.iterdir()) and len(list(catalog.objects.iterdir())) == 1


def test_post_redaction_receipt_expansion_is_rejected_before_adoption(tmp_path):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"original")
    catalog = AssetCatalog()
    with pytest.raises(ValueError, match="receipt"):
        catalog.adopt(source, alias="original", provenance={"detail": "token=x;" * 5000})
    assert catalog.list()["total"] == 0 and not list(catalog.objects.iterdir())
    assert not list(catalog.staging.iterdir()) and source.read_bytes() == b"original"


def test_cancelled_admission_skips_large_metadata_and_preserves_catalog(tmp_path):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"original")
    catalog, canceled = AssetCatalog(), threading.Event()
    canceled.set()
    with (
        patch("json.dumps", side_effect=AssertionError("No canceled metadata encoding")),
        patch(
            "video_research_mcp.redaction.redact_text",
            side_effect=AssertionError("No canceled redaction"),
        ),
    ):
        with pytest.raises(TimeoutError, match="cancel"):
            catalog.adopt(
                source,
                alias="original",
                provenance={"detail": "x" * (60 * 1024)},
                cancelled=canceled,
            )
    assert catalog.list()["total"] == 0 and source.read_bytes() == b"original"
    assert not list(catalog.objects.iterdir()) and not list(catalog.staging.iterdir())


def test_page_metadata_and_output_are_bounded_without_losing_rows(tmp_path):
    """GIVEN a large valid page WHEN listed THEN reads/output are bounded and all identities remain."""
    catalog = AssetCatalog()
    identities = set()
    for index in range(24):
        source = tmp_path / f"original-{index}.mp4"
        source.write_bytes(bytes([index + 1]))
        record = catalog.adopt(
            source, alias=f"original-{index}", provenance={"detail": "x" * (60 * 1024)}
        )
        identities.add(record["asset_id"])
    original_loads, parsed_sizes = json.loads, []

    def bounded_loads(value, **kwargs):
        size = len(value.encode())
        parsed_sizes.append(size)
        assert size <= 64 * 1024
        return original_loads(value, **kwargs)

    with patch("json.loads", side_effect=bounded_loads):
        result = catalog.list(limit=100)
    assert result["total"] == len(result["assets"]) == 24
    assert {record["asset_id"] for record in result["assets"]} == identities
    assert sum(parsed_sizes) <= result["metadata_read_byte_budget"] == 1024 * 1024
    assert result["metadata_read_bytes"] <= 1024 * 1024
    assert (
        len(json.dumps(result).encode()) <= result["serialized_output_byte_budget"] == 1024 * 1024
    )
    assert 0 < result["metadata_omitted_rows"] < 24 and not result["has_more"]
    assert all(
        record["state"] == "unknown" and record["metadata_reason"].startswith("page_")
        for record in result["assets"]
        if not record["metadata_included"]
    )


def test_listing_keeps_symlink_fifo_deleted_and_bad_metadata_denominator(tmp_path):
    """GIVEN unhealthy owned slots WHEN listed THEN each remains an explicit row without following it."""
    catalog, records, sources = AssetCatalog(), {}, {}
    for index, kind in enumerate(("healthy", "symlink", "fifo", "deleted", "metadata")):
        source = tmp_path / f"original-{kind}.mp4"
        source.write_bytes(bytes([index + 1]))
        records[kind] = adopt(catalog, source)
        sources[kind] = source
    for kind in ("symlink", "fifo", "deleted"):
        path = Path(records[kind]["path"])
        path.unlink()
        if kind == "symlink":
            path.symlink_to(sources[kind])
        elif kind == "fifo":
            os.mkfifo(path)
    with catalog._connection() as db:
        db.execute(
            "UPDATE assets SET receipts=? WHERE digest=?",
            ('[{"malformed":true}]', records["metadata"]["asset_id"]),
        )
    result = catalog.list()
    assert result["total"] == len(result["assets"]) == 5
    states = {record["asset_id"]: record["state"] for record in result["assets"]}
    assert states == {
        records[kind]["asset_id"]: state
        for kind, state in {
            "healthy": "verified",
            "symlink": "corrupt",
            "fifo": "corrupt",
            "deleted": "deleted",
            "metadata": "corrupt",
        }.items()
    }
    assert all(
        source.read_bytes() == bytes([index + 1]) for index, source in enumerate(sources.values())
    )


def test_page_output_budget_omits_whole_histories_without_shortening_aliases(tmp_path):
    """GIVEN repeated long aliases WHEN output fills THEN full histories stay stored for later pages."""
    catalog, aliases = AssetCatalog(), {}
    for index in range(13):
        source = tmp_path / f"original-{index}.mp4"
        source.write_bytes(bytes([index + 1]))
        alias = f"owned-{index}-" + "x" * (48 * 1024)
        record = catalog.adopt(source, alias=alias, provenance={})
        aliases[record["asset_id"]] = alias
    result = catalog.list(limit=100)
    omitted = [r for r in result["assets"] if not r["metadata_included"]]
    assert result["total"] == len(result["assets"]) == 13
    assert omitted and all(
        r["metadata_reason"] == "page_output_byte_budget_exhausted" for r in omitted
    )
    assert result["metadata_read_bytes"] < result["metadata_read_byte_budget"]
    assert result["serialized_output_bytes"] == len(json.dumps(result).encode())
    assert result["serialized_output_bytes"] <= result["serialized_output_byte_budget"]
    for row in result["assets"]:
        if row["metadata_included"]:
            assert row["aliases"] == [aliases[row["asset_id"]]]
        else:
            assert "aliases" not in row and "provenance" not in row and row["state"] == "unknown"
    assert all(
        catalog.get(row["asset_id"])["aliases"] == [aliases[row["asset_id"]]] for row in omitted
    )


def test_unreadable_row_is_unknown_without_hiding_other_assets(tmp_path):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"original")
    catalog = AssetCatalog()
    record = adopt(catalog, source)
    original_open = os.open

    def permission(path, *args, **kwargs):
        if Path(path) == Path(record["path"]):
            raise PermissionError("controlled unreadable owned file")
        return original_open(path, *args, **kwargs)

    with patch("os.open", side_effect=permission):
        result = catalog.list()
    assert result["total"] == len(result["assets"]) == 1
    assert result["assets"][0]["state"] == "unknown"
    assert result["assets"][0]["verification_reason"] == "owned_file_unreadable"
    assert source.read_bytes() == b"original"
