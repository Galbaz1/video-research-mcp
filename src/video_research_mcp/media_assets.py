"""Private, persistent exact-byte media assets; originals are never adopted in place."""

from __future__ import annotations

import os
import sqlite3
import stat
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .cache import invalidate_source
from .config import get_config
from .media_asset_receipts import (
    MAX_ASSET_RECEIPTS_BYTES,
    MAX_PAGE_METADATA_BYTES,
    MAX_PAGE_OUTPUT_BYTES,
    decode_receipts,
    encode_receipts,
    make_receipt,
    metadata_stub,
    page_receipt,
    serialized_bytes,
)
from .media_identity import valid_digest
from .media_local_io import _copy_hash
from .media_sources import VIDEO_TYPES


def _private_directory(path: Path) -> None:
    """Reject redirected storage and keep catalog-owned directories private."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not stat.S_ISDIR(path.lstat().st_mode):
        raise PermissionError("Media storage must be an owned directory, not a symlink")
    path.chmod(0o700)


_ROW_HEADERS = "CASE WHEN typeof(digest)='text' AND length(digest)=64 THEN digest END AS digest, CASE WHEN typeof(suffix)='text' AND length(suffix)<=8 THEN suffix END AS suffix, CASE WHEN typeof(size)='integer' THEN size END AS size, length(CAST(receipts AS BLOB)) AS receipt_bytes, typeof(receipts) AS receipt_type"


def _select_row(
    db: sqlite3.Connection, digest: str, metadata_budget: int = MAX_ASSET_RECEIPTS_BYTES
):
    """Have SQLite exclude oversized receipt blobs before Python materializes them."""
    return db.execute(
        f"SELECT {_ROW_HEADERS}, CASE WHEN typeof(receipts)='text' AND length(CAST(receipts AS BLOB))<=? THEN receipts END AS receipts FROM assets WHERE digest=?",
        (min(metadata_budget, MAX_ASSET_RECEIPTS_BYTES), digest),
    ).fetchone()


class AssetCatalog:
    """Manage immutable byte identities and source aliases under cache/media.

    SQLite serializes adoption and removal across processes. Each reuse, listing
    and removal checks the owned file again; a catalog row is never byte proof.
    """

    def __init__(self) -> None:
        """Initialize the private catalog using the current configured cache root."""
        self.root = Path(get_config().cache_dir).expanduser().absolute() / "media"
        self.objects = self.root / "objects"
        self.staging = self.root / "staging"
        self.database = self.root / "catalog.sqlite3"
        self._directories()
        with self._connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS assets (digest TEXT PRIMARY KEY, suffix TEXT NOT NULL, size INTEGER NOT NULL, receipts TEXT NOT NULL)"
            )

    def _directories(self) -> None:
        for path in (self.root, self.objects, self.staging):
            _private_directory(path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Use private database files; errors and unreadable state fail closed."""
        self._directories()
        for path in (self.database, Path(str(self.database) + "-journal")):
            if path.is_symlink() or (path.exists() and not stat.S_ISREG(path.lstat().st_mode)):
                raise PermissionError("Media catalog must be a regular owned file")
        fd = os.open(self.database, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.fchmod(fd, 0o600)
        os.close(fd)
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _path(self, row: sqlite3.Row) -> Path:
        if not valid_digest(row["digest"]) or row["suffix"] not in VIDEO_TYPES:
            raise ValueError("Media catalog identity or suffix is invalid")
        return self.objects / (row["digest"] + row["suffix"])

    def _record(
        self, row: sqlite3.Row, *, verify: bool = True, max_bytes: int | None = None
    ) -> dict:
        """Return only catalog-derived paths and retained bounded source receipts."""
        path = self._path(row)
        receipts = decode_receipts(row["receipts"])
        if type(row["size"]) is not int or row["size"] <= 0:
            raise ValueError("Media catalog byte count is invalid")
        if verify:
            digest, size = _copy_hash(path, max_bytes=max_bytes)
            if digest != row["digest"] or size != row["size"]:
                invalidate_source(row["digest"])
                raise ValueError("Owned media bytes are corrupt; remove the cause before reuse")
        return {
            "asset_id": row["digest"],
            "source_revision": "sha256:" + row["digest"],
            "path": str(path),
            "bytes": row["size"],
            "mime_type": VIDEO_TYPES[row["suffix"]],
            "aliases": [receipt["source"] for receipt in receipts],
            "provenance": receipts,
            "state": "verified",
            "identity_method": "full_sha256",
        }

    def adopt(
        self,
        source: Path,
        *,
        alias: str,
        provenance: dict,
        expected_digest: str | None = None,
        expected_bytes: int | None = None,
        cancelled: threading.Event | None = None,
    ) -> dict:
        """Copy bounded input into owned storage and reuse only fresh exact matches.

        Args:
            source: Regular local or privately staged video, never adopted in place.
            alias: Original source locator; public receipts redact URL credentials.
            provenance: Acquisition route receipt, not a claim of media quality.
            expected_digest: Checked transport commitment, when available.
            expected_bytes: Checked transport byte count, when available.
            cancelled: Acquisition cancellation signal for the bounded copying worker.

        Returns:
            Verified catalog asset and whether exact owned bytes were reused.
        """
        if cancelled and cancelled.is_set():
            raise TimeoutError("Media adoption canceled before metadata processing")
        suffix = source.suffix.lower()
        if suffix not in VIDEO_TYPES:
            raise ValueError("Unsupported media extension for asset adoption")
        receipt = make_receipt(alias, provenance)
        self._directories()
        with tempfile.TemporaryDirectory(prefix="adopt-", dir=self.staging) as directory:
            staged = Path(directory) / ("media" + suffix)
            digest, size = _copy_hash(source, staged, cancelled=cancelled)
            if (expected_digest is not None and digest != expected_digest) or (
                expected_bytes is not None and size != expected_bytes
            ):
                raise ValueError("Acquired bytes differ from the checked transport receipt")
            return self._publish(staged, digest, size, suffix, receipt, cancelled)

    def _publish(
        self,
        staged: Path,
        digest: str,
        size: int,
        suffix: str,
        receipt: dict,
        cancelled: threading.Event | None,
    ) -> dict:
        """Publish without replacing an untracked file; rollback only our exact bytes."""
        published = None
        try:
            with self._connection() as db:
                if cancelled and cancelled.is_set():
                    raise TimeoutError("Media adoption canceled before catalog write")
                row = _select_row(db, digest)
                reused = row is not None
                if row:
                    receipts = self._record(row)["provenance"]
                else:
                    receipts = []
                receipts = [r for r in receipts if r["alias_sha256"] != receipt["alias_sha256"]] + [
                    receipt
                ]
                encoded = encode_receipts(receipts)
                if not row:
                    target = self.objects / (digest + suffix)
                    if target.exists() or target.is_symlink():
                        raise ValueError(
                            "Uncatalogued media file blocks adoption; inspect owned storage"
                        )
                    os.link(staged, target)
                    published = target
                db.execute(
                    "INSERT INTO assets VALUES (?, ?, ?, ?) ON CONFLICT(digest) DO UPDATE SET receipts=excluded.receipts",
                    (digest, suffix, size, encoded),
                )
                row = _select_row(db, digest)
                result = {**self._record(row), "reused": reused}
                if cancelled and cancelled.is_set():
                    raise TimeoutError("Media adoption canceled before transaction commit")
            return result
        except BaseException:
            if published and _copy_hash(published) == (digest, size):
                published.unlink()
            raise

    def get(self, asset_id: str) -> dict:
        """Read back exact owned bytes.

        Args:
            asset_id: Full SHA-256 identity; paths are forbidden.

        Returns:
            Freshly verified catalog asset and retained source receipts.
        """
        if not valid_digest(asset_id):
            raise ValueError("asset_id must be a full lowercase SHA-256; paths cannot be removed")
        with self._connection() as db:
            row = _select_row(db, asset_id)
            if not row:
                raise FileNotFoundError("Media asset not found in the owned catalog")
            return self._record(row)

    def list(self, offset: int = 0, limit: int = 50) -> dict:
        """List a bounded identity-ordered page, retaining unhealthy or unverified rows.

        Args:
            offset: Nonnegative ordered row offset.
            limit: At most 100 rows, sharing one configured verification byte budget.

        Returns:
            Complete page denominator, states and continuation metadata.
        """
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Asset offset must be nonnegative and limit an integer from 1 to 100")
        with self._connection() as db:
            total = db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
            rows = db.execute(
                f"SELECT {_ROW_HEADERS} FROM assets ORDER BY digest LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            records = [metadata_stub(row) for row in rows]
            metadata_left, verification_left = (
                MAX_PAGE_METADATA_BYTES,
                get_config().media_max_input_bytes,
            )
            # Reserve every denominator row and the envelope before expanding metadata.
            output_left = MAX_PAGE_OUTPUT_BYTES - 1024 - serialized_bytes(records)
            for index, row in enumerate(rows):
                record, read_bytes = self._listed_metadata(db, row, metadata_left)
                metadata_left -= read_bytes
                if record["metadata_included"]:
                    verification_left = self._verify_listed(record, verification_left)
                    extra = serialized_bytes(record) - serialized_bytes(records[index])
                    if extra > output_left:
                        record = records[index]
                        record["metadata_reason"] = "page_output_byte_budget_exhausted"
                    else:
                        output_left -= extra
                records[index] = record
            return page_receipt(
                records,
                total,
                offset,
                limit,
                MAX_PAGE_METADATA_BYTES - metadata_left,
                get_config().media_max_input_bytes,
            )

    def _listed_metadata(
        self, db: sqlite3.Connection, header: sqlite3.Row, remaining: int
    ) -> tuple[dict, int]:
        """Keep a row visible when its metadata cannot be safely fetched or decoded."""
        record = metadata_stub(header)
        count = header["receipt_bytes"]
        if (
            not valid_digest(header["digest"])
            or header["suffix"] not in VIDEO_TYPES
            or header["receipt_type"] != "text"
            or type(header["size"]) is not int
            or header["size"] <= 0
        ):
            return {**record, "state": "corrupt", "metadata_reason": "invalid_catalog_metadata"}, 0
        if count > MAX_ASSET_RECEIPTS_BYTES:
            return {**record, "metadata_reason": "asset_receipt_byte_limit"}, 0
        if count > remaining:
            return record, 0
        row = _select_row(db, header["digest"], remaining)
        try:
            record = self._record(row, verify=False)
        except ValueError:
            return {
                **record,
                "state": "corrupt",
                "metadata_reason": "invalid_catalog_metadata",
            }, count
        return {**record, "metadata_included": True, "metadata_bytes": count}, count

    def _verify_listed(self, record: dict, remaining: int) -> int:
        """Observe each owned slot without allowing unhealthy files to abort the page."""
        path = Path(record["path"])
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                record.update(state="corrupt", verification_reason="owned_file_not_regular")
                invalidate_source(record["asset_id"])
            elif record["bytes"] > remaining:
                record.update(
                    state="unknown", verification_reason="aggregate_byte_budget_exhausted"
                )
            else:
                digest, size = _copy_hash(path, max_bytes=remaining)
                remaining -= size
                if (digest, size) != (record["asset_id"], record["bytes"]):
                    record.update(state="corrupt", verification_reason="owned_bytes_mismatch")
                    invalidate_source(record["asset_id"])
        except FileNotFoundError:
            record.update(state="deleted", verification_reason="owned_file_missing")
            invalidate_source(record["asset_id"])
        except OSError:
            record.update(state="unknown", verification_reason="owned_file_unreadable")
            remaining = 0
        except ValueError:
            record.update(state="corrupt", verification_reason="owned_bytes_unstable_or_invalid")
            invalidate_source(record["asset_id"])
            remaining = 0
        return remaining

    def remove(self, asset_id: str) -> dict:
        """Delete one verified owned file and invalidate source caches.

        Args:
            asset_id: Full catalog identity, never an original file path.

        Returns:
            Owned deletion and cache invalidation receipt; originals are retained.
        """
        if not valid_digest(asset_id):
            raise ValueError("asset_id must be a full lowercase SHA-256; paths cannot be removed")
        with self._connection() as db:
            row = _select_row(db, asset_id)
            if not row:
                raise FileNotFoundError("Media asset not found in the owned catalog")
            path = self._path(row)
            before = path.lstat()
            record = self._record(row)
            after = path.lstat()
            if (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ):
                raise ValueError("Owned media changed before removal; retain the current file")
            path.unlink()
            db.execute("DELETE FROM assets WHERE digest=?", (asset_id,))
            invalidated = invalidate_source(asset_id)
            return {
                "asset_id": asset_id,
                "removed": True,
                "bytes": record["bytes"],
                "invalidated_cache_entries": invalidated,
                "originals_removed": False,
            }
