"""Deterministic keyword, phonetic-name and fused ranking without models or I/O.

Adapted from QwenLM/Qwen-MM-Plugins@07736672525443c7f8a3f6405eed37d2236f023f
``src/capabilities/omni-memory/qwen_mm_plugins_omni_memory/text_match.py`` (tokens,
BM25 constants, soundex, phonetic_name_match, cosine, rrf) and ``mem_core.py``
(``MemoryStore._sparse_rank``), Apache-2.0. Changed: fixed constants instead of
environment overrides, a NumPy-free float64 cosine, deterministic tie order, and a
separate boost query so person IDs never dilute the main text field.
"""

import difflib
import math
import re

BM25_K1 = 1.5
BM25_B = 0.75
BM25_BOOST = 2.0
RRF_K = 60
_TOKEN = re.compile(r"[a-z0-9']+|[一-鿿]")
_STOP = frozenset(
    "the a an is are was were of to in on at and or do does did you i he she it they we this"
    " that what who which how when where why please hmm um uh".split()
)
_SOUNDEX = {
    **dict.fromkeys("BFPV", "1"),
    **dict.fromkeys("CGJKQSXZ", "2"),
    **dict.fromkeys("DT", "3"),
    "L": "4",
    **dict.fromkeys("MN", "5"),
    "R": "6",
}


def tokens(text: str) -> list[str]:
    """Lowercase word/CJK tokens with repeats, minus function words."""
    return [t for t in _TOKEN.findall(str(text).lower()) if t not in _STOP]


def soundex(text: str) -> str:
    """Four-character phonetic code for matching misheard stored names."""
    letters = "".join(c for c in text.upper() if "A" <= c <= "Z")
    if not letters:
        return ""
    out, previous = letters[0], _SOUNDEX.get(letters[0], "")
    for char in letters[1:]:
        code = _SOUNDEX.get(char, "")
        if code and code != previous:
            out += code
        if char not in "HW":
            previous = code
    return (out + "000")[:4]


def phonetic_match(a: str, b: str) -> bool:
    """True when two names match exactly, by soundex, or by edit similarity >= 0.72."""
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return False
    return a == b or soundex(a) == soundex(b) or difflib.SequenceMatcher(None, a, b).ratio() >= 0.72


def _bm25(texts: list[str], terms: set[str], weight: float) -> list[float]:
    """Okapi BM25 per document against the collection actually passed in."""
    counts = [tokens(text) for text in texts]
    n = len(counts)
    average = (sum(map(len, counts)) / n if n else 0.0) or 1.0
    frequency = {t: sum(1 for doc in counts if t in doc) for t in terms}
    idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in frequency.items() if c}
    scores = []
    for doc in counts:
        score = 0.0
        for term, weight_idf in idf.items():
            f = doc.count(term)
            if f:
                norm = BM25_K1 * (1 - BM25_B + BM25_B * len(doc) / average)
                score += weight_idf * f * (BM25_K1 + 1) / (f + norm)
        scores.append(score * weight)
    return scores


def bm25_rank(texts: list[str], query: str, boosts: list[str] | None = None,
              boost_query: str = "") -> list[int]:
    """Indices best-first; documents matching neither field are omitted."""
    terms = set(tokens(query))
    if not texts or not (terms or boost_query):
        return []
    scores = _bm25(texts, terms, 1.0)
    if boosts and boost_query:
        for i, extra in enumerate(_bm25(boosts, set(tokens(boost_query)), BM25_BOOST)):
            scores[i] += extra
    ranked = [(i, s) for i, s in enumerate(scores) if s > 0]
    return [i for i, _ in sorted(ranked, key=lambda pair: (-pair[1], pair[0]))]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in float64; zero for mismatched or zero vectors."""
    if len(a) != len(b):
        return 0.0
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def rrf(rank_lists: list[list[int]]) -> dict[int, float]:
    """Reciprocal-rank fusion score per index (k=60)."""
    score: dict[int, float] = {}
    for ranked in rank_lists:
        for rank, index in enumerate(ranked):
            score[index] = score.get(index, 0.0) + 1.0 / (RRF_K + rank + 1)
    return score
