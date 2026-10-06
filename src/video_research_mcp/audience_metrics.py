"""Disclosed lexical counts and fixed-cohort audience summaries; no inference runtime."""

from collections import Counter, defaultdict
from datetime import datetime
import re
from statistics import median
from zoneinfo import ZoneInfo

from .audience_store import identity
from .corpus_index import canonical

POSITIVE = ("good", "great", "helpful", "love", "thanks")
NEGATIVE = ("awful", "bad", "boring", "confusing", "hate")
THEMES = {"tutorial_requests": ("tutorial", "please", "more"),
          "clarity": ("clear", "confusing", "explain"),
          "production_quality": ("audio", "quality", "sound")}
UNCERTAINTY = "Unvalidated English lexical/checklist heuristics; negation, sarcasm, context and sampling bias are not resolved. No calibrated accuracy or causal growth claim."


def tokens(text: str) -> list[str]:
    """Use Unicode word tokens and casefold without changing the stored quote."""
    return re.findall(r"\w+", text.casefold())


def ratio(numerator, denominator) -> dict:
    """Expose numerator and denominator; distinguish missing data and division by zero."""
    state = "missing_data" if numerator is None or denominator is None else "zero_denominator" if denominator == 0 else "defined"
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if state == "defined" else None, "state": state}


def sentiment(comment) -> dict:
    """Count disclosed positive/negative hits; a tie or no hits is explicitly ambiguous."""
    words = tokens(comment.quoted_text)
    positive = [word for word in words if word in POSITIVE]
    negative = [word for word in words if word in NEGATIVE]
    balance = len(positive) - len(negative)
    label = "positive_hits" if balance > 0 else "negative_hits" if balance < 0 else "mixed_hits" if positive else "unmatched"
    return {"label": label, "positive_matches": positive, "negative_matches": negative,
            "hit_balance": ratio(balance, len(positive) + len(negative)), "token_count": len(words)}


def hook(video) -> dict:
    """Score a supplied opening's literal four-rule checklist, never inferred audiovisual content."""
    if video.opening_text is None:
        return {"state": "missing_opening_text", "score": ratio(None, 4), "matches": [], "opening_quote": None}
    words = tokens(video.opening_text)[:12]
    checks = {"question_mark": "?" in video.opening_text, "number_token": any(w.isdecimal() for w in words),
              "how_or_why_token": any(w in ("how", "why") for w in words), "imagine_token": "imagine" in words}
    hits = [name for name, matched in checks.items() if matched]
    return {"state": "supplied_opening_checklist", "score": ratio(len(hits), 4),
            "matches": hits, "opening_quote": video.opening_text}


def video_metrics(video) -> dict:
    """Normalize supplied metadata counts without replacing unknown counts with zero."""
    engagement = None if video.like_count is None or video.comment_count is None else video.like_count + video.comment_count
    return {"video_id": video.video_id, "format": video.format,
            "likes_per_view": ratio(video.like_count, video.view_count),
            "comments_per_view": ratio(video.comment_count, video.view_count),
            "engagement_per_view": ratio(engagement, video.view_count), "hook": hook(video)}


def lexical_comparison(videos) -> dict:
    """Count per-video title tokens and exact casefolded tags with evidence identities."""
    result = {}
    for name, extract in (("title_tokens", lambda v: set(tokens(v.title))), ("tags", lambda v: set(t.casefold() for t in v.tags))):
        members = defaultdict(list)
        for video in videos:
            for term in extract(video):
                members[term].append(video.video_id)
        ordered = sorted(members, key=lambda term: (-len(members[term]), term))[:10]
        result[name] = [{"term": term, "video_ids": members[term], "fraction": ratio(len(members[term]), len(videos))} for term in ordered]
    return result


def formats(videos) -> dict:
    """Compare caller-declared formats on exactly the same frozen metadata cohort."""
    result = {}
    for name in ("short", "long"):
        cohort = [v for v in videos if v.format == name]
        known = [v.view_count for v in cohort if v.view_count is not None]
        result[name] = {"video_ids": [v.video_id for v in cohort], "sample_size": len(cohort),
                        "mean_views": ratio(sum(known), len(known)), "missing_view_count": len(cohort) - len(known),
                        "median_duration_seconds": median(v.duration_seconds for v in cohort) if cohort else None,
                        **lexical_comparison(cohort)}
    return result


def uploads(videos, timezone: str) -> dict:
    """Report observed local upload windows and within-channel cadence, including DST offsets."""
    zone = ZoneInfo(timezone)
    windows, channels = defaultdict(list), defaultdict(list)
    evidence = []
    for video in videos:
        instant = datetime.fromisoformat(video.published_at.replace("Z", "+00:00"))
        local = instant.astimezone(zone)
        windows[(local.weekday(), local.hour)].append(video.video_id)
        channels[video.channel_id].append(instant)
        evidence.append({"video_id": video.video_id, "published_at": video.published_at, "local_time": local.isoformat()})
    cadence = []
    for channel, instants in sorted(channels.items()):
        ordered = sorted(instants)
        gaps = [(right - left).total_seconds() for left, right in zip(ordered, ordered[1:])]
        cadence.append({"channel_id": channel, "upload_count": len(ordered), "gap_count": len(gaps),
                        "median_gap_seconds": median(gaps) if gaps else None})
    top = sorted(windows, key=lambda key: (-len(windows[key]), key))[:3]
    return {"timezone": timezone, "algorithm": "observed_local_weekday_hour_counts_v1",
            "sample_size": len(videos), "windows": [{"weekday_monday_zero": day, "hour": hour,
            "video_ids": windows[(day, hour)], "fraction": ratio(len(windows[(day, hour)]), len(videos))} for day, hour in top],
            "cadence": cadence, "timestamp_evidence": evidence,
            "interpretation": "Observed sample frequency, not an optimal posting time or performance effect"}


def comment_evidence(comments, sample, digest, limit: int) -> list:
    """Keep exact evidence strings and identities for a bounded deterministic prefix."""
    return [{**comment.model_dump(mode="json"), "sample_id": sample.sample_id, "sample_sha256": digest,
             "sentiment": sentiment(comment)} for comment in comments[:limit]]


def niche_candidates(comments, videos, evidence) -> dict:
    """Contrast sampled theme mentions with sampled title/tag coverage, without market inference."""
    available = {(row["video_id"], row["comment_id"]) for row in evidence}
    candidates, omitted, counts = [], [], {}
    for theme, terms in THEMES.items():
        demand = [c for c in comments if set(tokens(c.quoted_text)).intersection(terms)]
        coverage = [v.video_id for v in videos if set(tokens(v.title + " " + " ".join(v.tags))).intersection(terms)]
        counts[theme] = {"comment_mentions": ratio(len(demand), len(comments)),
                         "cohort_title_tag_coverage": ratio(len(coverage), len(videos))}
        if not demand or len(coverage) == len(videos):
            continue
        refs = [{"video_id": c.video_id, "comment_id": c.comment_id} for c in demand if (c.video_id, c.comment_id) in available]
        if not refs:
            omitted.append(theme)
            continue
        candidates.append({"theme": theme, "classification": "sampled_topic_gap_candidate",
                           "comment_mentions": ratio(len(demand), len(comments)),
                           "cohort_title_tag_coverage": ratio(len(coverage), len(videos)),
                           "comment_evidence": refs, "covered_video_ids": coverage})
    return {"algorithm": "english_theme_mentions_minus_sampled_title_tag_coverage_v1", "theme_counts": counts, "candidates": candidates,
            "omitted_for_evidence_limit": omitted, "market_saturation": "UNKNOWN",
            "interpretation": "Sampled visibility only; no discovery completeness or opportunity prediction"}


def analyze(sample, digest: str, request) -> dict:
    """Return a reproducible source-linked cohort with explicit denominators and uncertainty."""
    lookup = {v.video_id: v for v in sample.videos}
    if any(key not in lookup for key in request.video_ids):
        raise ValueError("Cohort video metadata missing from the immutable sample")
    videos = [lookup[key] for key in sorted(request.video_ids)]
    comments = sorted((c for c in sample.comments if c.video_id in request.video_ids), key=lambda c: (c.video_id, c.comment_id))
    labels = Counter(sentiment(c)["label"] for c in comments)
    evidence = comment_evidence(comments, sample, digest, request.evidence_limit)
    cohort = {"sample_sha256": digest, "video_ids": sorted(request.video_ids), "timezone": request.timezone}
    return {"cohort": {**cohort, "sha256": identity(canonical(cohort)), "format_basis": "caller_declared_short_or_long"},
            "denominators": {"video_count": len(videos), "cohort_comment_count": len(comments),
                             "imported_comment_count": sample.sample_size, "reply_count": sum(c.reply_id is not None for c in comments)},
            "methods": {"sentiment": "english_term_hit_balance_v1", "lexicon": {"positive": POSITIVE, "negative": NEGATIVE},
                        "themes": THEMES, "hook": "supplied_opening_first12_word_four_rule_checklist_v1",
                        "hook_rules": ["question_mark", "number_token", "how_or_why_token", "imagine_token"],
                        "ratios": "supplied_count_division_v1", "title_tags": "per_video_literal_presence_v1"},
            "uncertainty": UNCERTAINTY, "calibrated_accuracy": None, "model_generated": False,
            "videos": [video_metrics(v) for v in videos], "formats": formats(videos), "uploads": uploads(videos, request.timezone),
            "sentiment": {label: ratio(labels[label], len(comments)) for label in ("positive_hits", "negative_hits", "mixed_hits", "unmatched")},
            "evidence": evidence, "evidence_omitted_count": len(comments) - len(evidence),
            "niches": niche_candidates(comments, videos, evidence)}
