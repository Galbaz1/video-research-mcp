"""Escaped standalone HTML and Markdown; no scripts, external resources or embeds."""

from html import escape
import re


def bounded(parts, limit: int) -> bytes:
    """Charge UTF-8 fragments before retaining them, including repeated inline images."""
    chunks, size = [], 0
    for part in parts:
        raw = part.encode("utf-8")
        size += len(raw)
        if size > limit:
            raise ValueError("Export exceeds max_export_bytes")
        chunks.append(raw)
    return b"".join(chunks)


def moment(record) -> str:
    """Display supplied source endpoints; a linked frame has no invented capture clock."""
    span = "timing not recorded" if record["start_seconds"] is None else f'{record["start_seconds"]}–{record["end_seconds"]} seconds'
    return f'{record["video_id"]}@{record["source_revision"]}: {span}'


def html_parts(report, inline):
    """Yield only escaped data, internal citation anchors and admitted data images."""
    yield '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
    yield '<meta http-equiv="Content-Security-Policy" content="default-src &apos;none&apos;; img-src data:; style-src &apos;unsafe-inline&apos;; base-uri &apos;none&apos;; form-action &apos;none&apos;"><title>' + escape(report["title"]) + '</title>'
    yield '<style>body{max-width:70rem;margin:auto;padding:2rem;font:16px system-ui}img{max-width:100%}pre{white-space:pre-wrap}article{border-top:1px solid #aaa;padding:1rem 0}.issue{color:#912}</style></head><body>'
    yield '<h1>' + escape(report["title"]) + '</h1><p>Offline export. Byte integrity does not establish semantic truth. No source media is requested.</p><nav>'
    for number, record in enumerate(report["records"]):
        yield f'<p><a href="#record-{number}">' + escape(record["citation_id"]) + ' — ' + escape(moment(record)) + '</a></p>'
    yield '</nav>'
    for number, record in enumerate(report["records"]):
        yield f'<article id="record-{number}"><h2>' + escape(record["title"] or record["kind"]) + '</h2><p>' + escape(moment(record)) + '</p>'
        yield '<p>' + escape(f'Citation: {record["citation_id"]}; basis: {record["basis"]}; origin: {record["origin"]}; model: {record["model"] or "not_recorded"}; method: {record["method"]}; source SHA256: {record["media_digest"]}') + '</p>'
        yield '<pre>' + escape(record["text"]) + '</pre>'
        if record["attribution"]:
            yield '<p>' + escape(f'Attribution: {record["attribution"]}; stance: {record["stance"]}; source state: {record["source_state"]}') + '</p>'
        if record["claim"]:
            yield '<p>Attributed claim: ' + escape(record["claim"]) + '</p>'
        for frame in record["frames"]:
            caption = moment(record) + ' — linked frame ' + frame["artifact_id"] + '; capture time not recorded'
            if frame["state"] == "inline_verified":
                yield '<figure><img alt="Linked evidence frame" src="' + inline[frame["key"]] + '"><figcaption>' + escape(caption) + '</figcaption></figure>'
            else:
                yield '<p class="issue">' + escape(f'Frame {frame["artifact_id"]}: {frame["state"]} — {frame["reason"]}') + '</p>'
        yield '</article>'
    yield '</body></html>'


def md(value) -> str:
    """Escape raw HTML and Markdown control syntax in every untrusted value."""
    return re.sub(r'([\\`*_{}\[\]()#+.!|~\-])', r'\\\1', escape(str(value)))


def markdown_parts(report):
    """Retain exact identities, methods and labels without external image requests."""
    yield '# ' + md(report["title"]) + '\n\nOffline evidence; semantic claims remain unqualified.\n'
    for record in report["records"]:
        yield '\n## ' + md(record["title"] or record["kind"]) + '\n\n' + md(moment(record)) + '\n\n'
        for key in ("citation_id", "source_id", "video_id", "source_revision", "media_digest", "observation_id", "start_seconds", "end_seconds", "basis", "origin", "model", "method", "attribution", "claim", "stance", "page_revision", "page_sha256", "source_state"):
            yield '- ' + key + ': ' + md(record[key]) + '\n'
        yield '\n' + md(record["text"]) + '\n'
        for ref in record["artifact_refs"]:
            yield '\n- Artifact: ' + md(ref["artifact_id"]) + '; ' + md(ref["kind"]) + '; path: ' + md(ref["path"]) + '; SHA256: ' + md(ref["sha256"]) + '\n'
        for frame in record["frames"]:
            yield '\n- Frame: ' + md(frame["artifact_id"]) + '; state: ' + md(frame["state"]) + '; SHA256: ' + md(frame["sha256"]) + '; ' + md(frame.get("reason", "verified local bytes; capture time not recorded")) + '\n'
