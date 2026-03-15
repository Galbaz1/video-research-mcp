"""Document file helpers -- upload, download, and preparation for research_document."""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from pathlib import Path

from ..config import get_config
from ..local_path_policy import enforce_local_access_root, resolve_path
from ..url_policy import download_checked

from .video_file import _file_content_hash, _upload_large_file

logger = logging.getLogger(__name__)

SUPPORTED_DOC_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/plain",
    ".html": "text/html",
    ".xml": "text/xml",
}

DOC_MAX_SIZE = 50 * 1024 * 1024  # 50 MB Gemini limit


def _doc_mime_type(path: Path) -> str:
    """Return MIME type for a document file, or raise ValueError."""
    ext = path.suffix.lower()
    mime = SUPPORTED_DOC_EXTENSIONS.get(ext)
    if not mime:
        allowed = ", ".join(sorted(SUPPORTED_DOC_EXTENSIONS))
        raise ValueError(f"Unsupported document extension '{ext}'. Supported: {allowed}")
    return mime


_ARXIV_ABS_RE = re.compile(r"https?://arxiv\.org/abs/([\d.]+)(v\d+)?/?(?:\?.*)?$")
_ARXIV_PDF_RE = re.compile(r"https?://arxiv\.org/pdf/([\d.]+)(v\d+)?/?(?:\?.*)?$")


def _normalize_document_url(url: str) -> str:
    """Convert known academic URLs to direct PDF download URLs.

    Handles:
        - arxiv.org/abs/XXXX.XXXXX -> arxiv.org/pdf/XXXX.XXXXX.pdf
        - arxiv.org/pdf/XXXX.XXXXX -> arxiv.org/pdf/XXXX.XXXXX.pdf (ensure .pdf extension)
    """
    # arXiv abstract page -> PDF
    m = _ARXIV_ABS_RE.match(url)
    if m:
        paper_id = m.group(1)
        version = m.group(2) or ""
        return f"https://arxiv.org/pdf/{paper_id}{version}.pdf"

    # arXiv PDF without .pdf extension
    m = _ARXIV_PDF_RE.match(url)
    if m:
        paper_id = m.group(1)
        version = m.group(2) or ""
        return f"https://arxiv.org/pdf/{paper_id}{version}.pdf"

    return url


async def _prepare_document(path: Path) -> tuple[str, str]:
    """Upload document via File API, return (file_uri, content_id).

    Always uses File API (even for small files) because the multi-phase
    pipeline references documents across 3-4 Gemini calls.
    """
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")
    if path.stat().st_size > DOC_MAX_SIZE:
        raise ValueError(f"Document exceeds 50MB Gemini limit: {path.name}")
    mime = _doc_mime_type(path)
    content_id = _file_content_hash(path)
    uri = await _upload_large_file(path, mime, content_hash=content_id)
    return uri, content_id


async def _download_document(url: str, tmp_dir: Path) -> Path:
    """Download a URL to a temp file with SSRF protection."""
    url = _normalize_document_url(url)
    cfg = get_config()
    return await download_checked(url, tmp_dir, max_bytes=cfg.doc_max_download_bytes)


async def _prepare_all_documents(
    file_paths: list[str] | None,
    urls: list[str] | None,
) -> list[tuple[str, str, str]]:
    """Backward-compatible wrapper returning only prepared documents."""
    prepared, _issues = await _prepare_all_documents_with_issues(file_paths, urls)
    return prepared


async def _prepare_all_documents_with_issues(
    file_paths: list[str] | None,
    urls: list[str] | None,
) -> tuple[list[tuple[str, str, str]], list[dict[str, str]]]:
    """Prepare all documents for the research pipeline.

    Downloads URL documents to temp files, then uploads everything via File API.

    Returns:
        Tuple of:
        - prepared documents as (file_uri, content_id, original_path_or_url)
        - preparation issues with source, phase, error_type, and error message
    """
    prepared: list[tuple[str, str, str]] = []
    issues: list[dict[str, str]] = []

    # Download URL documents first
    downloaded: list[tuple[Path, str]] = []
    if urls:
        tmp_dir = Path(tempfile.mkdtemp(prefix="research_doc_"))
        download_tasks = [_download_document(u, tmp_dir) for u in urls]
        results = await asyncio.gather(*download_tasks, return_exceptions=True)
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                logger.warning("Failed to download %s (%s): %s", url, type(result).__name__, result)
                issues.append(
                    {
                        "source": url,
                        "phase": "download",
                        "error_type": type(result).__name__,
                        "error": str(result),
                    }
                )
            else:
                downloaded.append((result, url))

    # Collect all local paths
    all_paths: list[tuple[Path, str]] = []
    if file_paths:
        for fp in file_paths:
            p = enforce_local_access_root(resolve_path(fp))
            all_paths.append((p, fp))
    all_paths.extend(downloaded)

    # Upload all via File API (parallel)
    async def _upload(path: Path, original: str) -> tuple[str, str, str]:
        uri, cid = await _prepare_document(path)
        return uri, cid, original

    upload_tasks = [_upload(p, orig) for p, orig in all_paths]
    results = await asyncio.gather(*upload_tasks, return_exceptions=True)
    for (_path, original), result in zip(all_paths, results):
        if isinstance(result, Exception):
            logger.warning("Failed to upload document: %s", result)
            issues.append(
                {
                    "source": original,
                    "phase": "upload",
                    "error_type": type(result).__name__,
                    "error": str(result),
                }
            )
        else:
            prepared.append(result)

    return prepared, issues
