"""Canonical record, identity and fact accumulation on one caller-declared timeline.

Independent lifecycle protocol implementation; reference QwenLM/Qwen-MM-Plugins
@07736672525443c7f8a3f6405eed37d2236f023f, Apache-2.0. Identity links are explicit
user assertions; captions never create speakers and suggestions never bind names.
"""

from ..models.video_memory_av import Fact, Person, WINDOW_SECONDS
from . import av_build, av_store


def _people(state, source, people) -> dict[str, str]:
    """Keep source-local transcript labels distinct unless the caller explicitly links them."""
    known = {p.person_id for p in state.persons}
    if set(source.identity_bindings.values()) - known:
        raise ValueError("Identity binding refers to a person not already stored")
    labels = {p.source_label: p for p in state.persons}
    mapping = {}
    for person in people:
        label = f"{source.segment_id}:{person.source_label}"
        if len(label) > 128:
            raise ValueError("Scoped transcript speaker label exceeds 128 characters")
        if person.source_label in source.identity_bindings:
            pid = source.identity_bindings[person.source_label]
        elif label in labels:
            pid = labels[label].person_id
        else:
            if len(state.persons) >= 999:
                raise ValueError("Canonical memory exceeds 999 persons")
            pid = f"P{max((int(p.person_id[1:]) for p in state.persons), default=0) + 1:03d}"
            stored = Person(person_id=pid, source_label=label, label_basis=person.label_basis)
            state.persons.append(stored)
            labels[label] = stored
        mapping[person.person_id] = pid
    return mapping


def _facts(state, source) -> None:
    """Accumulate only caller-authored facts whose canonical evidence has been admitted."""
    records = {r.record_id for r in state.records}
    people = {p.person_id for p in state.persons}
    for item in source.facts:
        if not set(item.evidence_ids) <= records:
            continue
        if item.subject_id.startswith("P") and item.subject_id not in people:
            raise ValueError("Fact cites an unknown global person")
        fact = Fact(fact_id=av_store.fact_id(item.subject_id, item.key, item.value), **item.model_dump(),
                    basis="asserted", created_revision=state.revision, updated_revision=state.revision)
        av_store.merge_fact(state.facts, fact, state.revision)


def accumulate(state, planned, window: int, admitted) -> None:
    """Add one source window without changing prior records, identities or fact provenance."""
    source = planned.source
    records, people = av_build.fold(source.expected_source_sha256, source.duration_seconds, admitted)
    chosen = [r for r in records if r.window == window]
    used = {r.person_id for r in chosen if r.person_id}
    mapping = _people(state, source, [p for p in people if p.person_id in used])
    known = {r.record_id for r in state.records}
    for record in chosen:
        if record.record_id in known:
            raise ValueError("Duplicate canonical record ID; no silent reuse")
        record.start_seconds += planned.offset_seconds
        record.end_seconds += planned.offset_seconds
        record.window = int(record.start_seconds // WINDOW_SECONDS)
        record.person_id = mapping.get(record.person_id)
        state.records.append(record)
        known.add(record.record_id)
    if len(state.records) > av_build.MAX_RECORDS:
        raise ValueError("Canonical memory exceeds 5000 records")
    state.records.sort(key=lambda r: (r.start_seconds, r.record_id))
    retained = {r.sha256 for r in state.artifacts}
    state.artifacts.extend(r for r, _ in admitted if r.sha256 not in retained)
    suggestions = {s.suggestion_id for s in state.suggestions}
    state.suggestions.extend(s for s in av_build.suggest_names(chosen) if s.suggestion_id not in suggestions)
    _facts(state, source)
    if window == planned.planned_windows - 1:
        missing = {e for f in source.facts for e in f.evidence_ids} - known
        if missing:
            raise ValueError("Caller-authored facts cite records absent from the completed source")
    state.windows = av_build.window_count(sum(s["source"]["duration_seconds"]
                                             for s in state.history[-1]["lifecycle"]["segments"]))
