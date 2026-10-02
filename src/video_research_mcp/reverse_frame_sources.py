"""Verify one owned captured PNG and bounded untrusted Lens suggestions."""

from urllib.parse import urlsplit
import struct
import zlib

from .image_ops import MAX_INPUT_PIXELS
from .media_frame_views import _frame_path
from .media_local_io import _open_regular
from .media_snapshot import checked_path, copy_hash
from .models.reverse_search import FrameQuery, LensCandidate
from .models.search_provider import ProviderRejection, source_url
from .search_provider_results import ProviderFailure, digest, protect


async def frame_bytes(request):
    """Bind original and privately owned query bytes before any public disclosure."""
    source, frame = request.capture.source, request.capture.frames[0]
    original = checked_path(source.path)
    if await copy_hash(original) != (source.sha256, source.bytes):
        raise ValueError("Original source differs from capture metadata")
    path = _frame_path(frame.model_dump(mode="json"))
    with _open_regular(path) as stream:
        body = stream.read(request.max_query_bytes + 1)
    width, height = png_dimensions(body)
    if (len(body) > min(request.max_query_bytes, request.max_response_bytes)
            or (digest(body), len(body)) != (frame.sha256, frame.bytes)
            or (width, height) != (frame.width, frame.height)):
        raise ValueError("Query frame differs from its bounded captured bytes")
    query = FrameQuery(source_sha256=source.sha256, source_bytes=source.bytes,
        frame_sha256=frame.sha256, frame_bytes=frame.bytes, width=frame.width, height=frame.height,
        requested_seconds=frame.requested_seconds, actual_seconds=frame.actual_seconds,
        original_pts=frame.original_pts, time_base=frame.time_base, crop_box=frame.crop_box,
        source_reference=f"urn:sha256:{source.sha256}#t={frame.actual_seconds}")
    return body, query


def png_dimensions(body):
    """Validate geometry from the submitted bounded bytes, without a second path open."""
    if len(body) < 33 or body[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise ValueError("Expected a complete PNG header")
    if zlib.crc32(body[12:29]) != struct.unpack(">I", body[29:33])[0]:
        raise ValueError("PNG header checksum is invalid")
    width, height = struct.unpack(">II", body[16:24])
    if not width or not height or width * height > MAX_INPUT_PIXELS:
        raise ValueError("PNG exceeds the decoded input pixel ceiling")
    if body[24] != 8 or body[25] not in {2, 6} or body[26:29] != b"\x00\x00\x00":
        raise ValueError("Only standard noninterlaced 8-bit RGB/RGBA PNG is supported")
    return width, height


def publication_url(body, credential, image_bytes):
    """Accept one acknowledged Uguu URL, never a provider-selected arbitrary fetch target."""
    files = body.get("files")
    if body.get("success") is not True or not isinstance(files, list) or len(files) != 1:
        raise ProviderFailure("publication_response_invalid")
    size = files[0].get("size") if isinstance(files[0], dict) else None
    if type(size) is not int or size != image_bytes:
        raise ProviderFailure("publication_size_invalid")
    value = files[0].get("url") if isinstance(files[0], dict) else None
    if not isinstance(value, str) or len(value) > 2048 or protect(value, credential) != value:
        raise ProviderFailure("publication_url_invalid")
    source_url(value)
    host = urlsplit(value).hostname
    if not (host == "uguu.se" or host.endswith(".uguu.se")) or urlsplit(value).port not in {None, 443}:
        raise ProviderFailure("publication_host_refused")
    return value


def candidates(body, request, credential):
    """Validate every returned row; provider identity claims never become verified identities."""
    rows = body.get("organic")
    if not isinstance(rows, list) or len(rows) > 100:
        raise ProviderFailure("lens_population_invalid")
    results, rejections = [], []
    for index, row in enumerate(rows):
        try:
            if not isinstance(row, dict) or len(results) >= request.num_results:
                raise ValueError("row_or_result_limit")
            url = row.get("link")
            if not isinstance(url, str) or len(url) > 2048 or protect(url, credential) != url:
                raise ValueError("candidate_url_invalid")
            source_url(url)
            image = row.get("imageUrl")
            if image is not None:
                if not isinstance(image, str) or len(image) > 2048 or protect(image, credential) != image:
                    raise ValueError("candidate_image_invalid")
                source_url(image)
            fields = [row.get(name) for name in ("title", "source")]
            if any(value is not None and (not isinstance(value, str) or len(value.encode()) > 8192) for value in fields):
                raise ValueError("candidate_text_invalid")
            results.append(LensCandidate(url=url, title=protect(fields[0], credential),
                source=protect(fields[1], credential), image_url=image))
        except ValueError:
            rejections.append(ProviderRejection(index=index, code="invalid_or_limited_lens_candidate"))
    if sum(len((value or "").encode()) for hit in results for value in (hit.title, hit.source)) > request.max_text_bytes:
        raise ProviderFailure("lens_text_byte_limit")
    return results, rejections, len(rows)


async def verify_capture(request, query):
    """Refuse promotion if either selected local file changes during external execution."""
    source, frame = request.capture.source, request.capture.frames[0]
    if await copy_hash(checked_path(source.path)) != (query.source_sha256, query.source_bytes):
        raise ValueError("Original source changed during reverse search")
    if await copy_hash(_frame_path(frame.model_dump(mode="json"))) != (query.frame_sha256, query.frame_bytes):
        raise ValueError("Captured frame changed during reverse search")
