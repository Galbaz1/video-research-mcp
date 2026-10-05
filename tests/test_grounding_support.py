"""Frozen development corpus for grounding tests; authored bytes, no real media or models."""

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from video_research_mcp.tools.corpus import corpus_retrieve

COLLECTION = "fixture"
OBSERVATIONS = [
    ("speech-1", "speech", 0.0, 1.0, "The operator says the copper circuit is open.", "transcript"),
    ("ocr-1", "OCR", 0.1, 0.9, "ERROR B overheating", "frame"),
    ("desc-1", "description", 1.0, 2.0, "Caller description: a red warning light", "description"),
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _artifact(directory: Path, oid: str, kind: str, text: str) -> tuple[Path, bytes]:
    if kind == "frame":
        path = directory / f"{oid}.png"
        Image.new("RGB", (8, 4), "#dddddd").save(path)
    else:
        path = directory / f"{oid}.json"
        path.write_text(json.dumps({"observation": oid, "text": text}))
    return path, path.read_bytes()


async def index_corpus(root: Path, digest: str) -> dict:
    """Index the frozen observations with real artifact files through the public tool."""
    directory = root / "artifacts"
    directory.mkdir(exist_ok=True)
    paths, records = {}, []
    for oid, kind, start, end, text, artifact_kind in OBSERVATIONS:
        path, data = _artifact(directory, oid, artifact_kind, text)
        paths[oid] = path
        records.append({"video_id": "lab", "observation_id": oid, "source_revision": "r1",
                        "media_digest": digest, "kind": kind, "start_seconds": start,
                        "end_seconds": end, "text": text, "entities": [],
                        "artifact_refs": [{"artifact_id": "artifact-" + oid, "kind": artifact_kind,
                                           "path": str(path), "sha256": sha(data)}]})
    index_path = str(root / "corpus.sqlite3")
    result = await corpus_retrieve(request={"action": "index", "collection": COLLECTION,
                                            "index_path": index_path, "expected_revision": 0,
                                            "observations": records})
    assert result["status"] == "indexed", result
    return {"index_path": index_path, "paths": paths, "digest": digest}


@pytest.fixture
async def grounding_corpus(tmp_path, monkeypatch, clean_config):
    """Fence the corpus and caches to this test's directory."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    return await index_corpus(tmp_path, "a" * 64)


def cite(oid, start, end, quote=None, revision="r1") -> dict:
    return {"observation_id": oid, "source_revision": revision, "start_seconds": start,
            "end_seconds": end, "quote": quote}


def claim(cid, text, *citations) -> dict:
    return {"claim_id": cid, "text": text, "citations": list(citations)}


def grounding_request(corpus, query, claims=(), **updates) -> dict:
    retrieval = {"action": "query", "index_path": corpus["index_path"], "collection": COLLECTION,
                 "query": query, "source_revisions": {"lab": "r1"}, "mode": "fts"}
    return {"retrieval": retrieval, "claims": list(claims), **updates}
