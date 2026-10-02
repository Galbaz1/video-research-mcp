"""Report concrete configured routes without equating incompatible provider operations."""

import os

from .config import get_config
from .models.text_provider import TEXT_CAPABILITIES
from .provider_readiness import present
from .text_provider import _secret_data


def capability_matrix():
    """Describe available entry points and declared profile support without probing."""
    cfg = get_config()
    rows = [{"backend": "gemini", "entry_points": ["content_analyze", "content_extract", "video_analyze", "research_execute", "web_search"],
             "capabilities": ["text", "structured_json", "images", "video", "audio", "files", "grounding"],
             "configured": bool(cfg.gemini_api_key), "authority": "existing distinct tool contracts; live acceptance unverified"}]
    for name, profile in cfg.text_backends.items():
        credential = os.environ.get(profile.api_key_env, "") if profile.api_key_env else ""
        if _secret_data({"name": name, **profile.model_dump(mode="json")}, credential):
            raise PermissionError("Selected text credential occurs in profile metadata; capability inspection blocked")
        rows.append({"backend": "text:" + name, "entry_points": ["text_generate"],
                     "capabilities": sorted(TEXT_CAPABILITIES), "provider": profile.provider,
                     "configured": not profile.api_key_env or present(os.environ, profile.api_key_env),
                     "authority": "operator profile; text protocol fixtures, live model support unverified"})
    for name, profile in cfg.vision_backends.items():
        rows.append({"backend": "vision:" + name, "entry_points": ["vision_chat", "vision_ocr", "vision_grounding"],
                     "capabilities": profile.capabilities,
                     "configured": not profile.api_key_env or bool(os.environ.get(profile.api_key_env)),
                     "authority": "operator vision profile; grounding uses inferred geometry, no GoogleSearch/FileAPI"})
    rows.append({"backend": "weaviate", "entry_points": ["knowledge_search"],
                 "capabilities": ["embeddings"] + (["rerank"] if cfg.reranker_enabled else []),
                 "configured": cfg.weaviate_enabled, "embedding_provider": cfg.weaviate_vectorizer,
                 "rerank_provider": cfg.reranker_provider if cfg.reranker_enabled else None,
                 "authority": "existing selected vectorizer and Cohere collection contracts; no local probe"})
    return rows


def inspect_capabilities(backend, required):
    """Refuse unsupported requests before any inference, upload or search call."""
    rows = capability_matrix()
    if backend is not None:
        rows = [row for row in rows if row["backend"] == backend]
        if not rows:
            raise ValueError("Unknown capability route; use configured text:/vision: profile name, gemini or weaviate")
        missing = set(required) - set(rows[0]["capabilities"])
        if missing:
            raise ValueError("Selected route does not support " + ", ".join(sorted(missing)))
    elif required:
        raise ValueError("Required capabilities need an explicitly selected backend")
    return {"backends": rows, "provider_calls": 0, "live_verified": False}
