"""Read-only optional profile classification without service clients or secret values."""

import json
import re

from .dotenv import _is_unset_or_placeholder


def present(env, key):
    """Recognize a selected non-placeholder credential without exposing its value."""
    value = env.get(key, "").strip()
    return bool(value) and not _is_unset_or_placeholder(key, value) and not value.startswith("${")


def optional_adapter_profiles(env: dict) -> dict:
    """Inspect explicit text/search selection without clients, endpoint probes or secret values."""
    from video_research_mcp.models.text_provider import TextBackend

    result = {"text": [], "search": [], "live_verified": False, "run_authority": "not-granted"}
    enabled = env.get("TWELVELABS_ENABLED", "").lower() in {"1", "true", "yes"}
    available = present(env, "TWELVELABS_API_KEY")
    result["twelvelabs"] = {"provider": "twelvelabs", "credential_present": available,
        "state": "disabled" if not enabled else "configured-but-unverified" if available else "missing",
        "external_mcp_discovery_verified": False}
    result["audio_dsp"] = []
    for backend in ("juzzy", "ferrous"):
        key = "AUDIO_DSP_" + backend.upper()
        path_present = bool(env.get(key + "_PATH", ""))
        hash_present = bool(re.fullmatch(r"[a-f0-9]{64}", env.get(key + "_SHA256", "")))
        result["audio_dsp"].append({"backend": backend,
            "state": "configured-but-unverified" if path_present and hash_present else "missing" if path_present or hash_present else "disabled",
            "path_configured": path_present, "binary_sha256_configured": hash_present,
            "binary_presence_or_native_discovery_verified": False})
    try:
        profiles = json.loads(env.get("TEXT_BACKENDS_JSON", "{}"))
        if not isinstance(profiles, dict) or len(profiles) > 32:
            raise ValueError("Invalid optional text profiles")
        for index, (name, raw) in enumerate(profiles.items()):
            row = {"index": index, "state": "missing", "credential_present": False}
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
                result["text"].append(row)
                continue
            try:
                profile = TextBackend.model_validate(raw)
                row["credential_present"] = not profile.api_key_env or present(env, profile.api_key_env)
                row["state"] = "configured-but-unverified" if row["credential_present"] else "missing"
                row["provider"] = profile.provider
            except ValueError:
                pass
            result["text"].append(row)
    except (TypeError, ValueError):
        result["text_config_invalid"] = True
    try:
        providers = json.loads(env.get("SEARCH_BACKENDS_JSON", "[]"))
        order = ["serper", "tavily", "exa", "serply"]
        if not isinstance(providers, list) or len(providers) != len(set(providers)) or not set(providers) <= set(order):
            raise ValueError("Invalid optional search allowlist")
        for name in order:
            available = present(env, name.upper() + "_API_KEY")
            state = "disabled" if name not in providers else "configured-but-unverified" if available else "missing"
            result["search"].append({"provider": name, "state": state, "credential_present": available})
    except (TypeError, ValueError):
        result["search_config_invalid"] = True
    return result
