"""One exact original PNG and literal instruction for selected native Ollama chat."""
import base64
import hashlib
import json
import os
import struct
import zlib

from .image_manifest import json_digest
from .media_local_io import _open_regular
from .media_snapshot import checked_path, snapshot
from .models.vision import VisionAnswer
from .vision_preparation import read_payload

REQUEST_BYTES = 1048576
RESPONSE_BYTES = 131072
CONTROLS = {'num_ctx': 4096, 'temperature': 0, 'think': False, 'stream': False, 'keep_alive': 0}


def validate_request(request, operation):
    """Refuse unsupported routes and explicit transforms before snapshot acquisition."""
    if (operation != 'vision_chat' or request.output_schema is not None or request.export_crops
            or 'thinking_level' in request.model_fields_set):
        raise ValueError('Native Ollama supports only plain vision_chat without schemas or crop export')
    if len(request.sources) != 1:
        raise ValueError('Native Ollama requires exactly one original PNG image')
    source = request.sources[0]
    forbidden = {'crop', 'resize', 'time_seconds', 'start_seconds', 'end_seconds', 'fps', 'max_frames'}
    if source.kind != 'image' or forbidden.intersection(source.model_fields_set):
        raise ValueError('Native Ollama requires an image without transform or time fields')


async def prepare_png(request, stack):
    """Hold a bounded regular-file snapshot through inference without re-encoding it."""
    source = request.sources[0]
    path = checked_path(source.file_path)
    with _open_regular(path) as reader:
        if os.fstat(reader.fileno()).st_size > 3 * REQUEST_BYTES // 4:
            raise ValueError('Native PNG exceeds the request byte limit')
    owned = await stack.enter_async_context(snapshot(source.file_path, source.expected_source_sha256))
    if owned.size > 3 * REQUEST_BYTES // 4:
        raise ValueError('Native PNG exceeds the request byte limit')
    part = {'path': str(owned.path), 'sha256': owned.sha256, 'bytes': owned.size,
            'kind': 'image', 'mime': 'image/png', 'source_index': 0}
    data = read_payload(part)
    if len(data) < 33 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[8:16] != b'\0\0\0\rIHDR':
        raise ValueError('Native input requires a PNG signature and IHDR')
    width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', data[16:29])
    if not 0 < width <= 16384 or not 0 < height <= 16384 or width * height > 64000000:
        raise ValueError('Native PNG dimensions exceed the bounded image route')
    if (depth not in {1, 2, 4, 8, 16} or color not in {0, 2, 3, 4, 6}
            or compression or filtering or interlace not in {0, 1}
            or zlib.crc32(data[12:29]) != struct.unpack('>I', data[29:33])[0]):
        raise ValueError('Native PNG IHDR is invalid')
    prepared = {'source': {'path': str(owned.original), 'sha256': owned.sha256, 'bytes': owned.size,
                           'width': width, 'height': height}, 'preparation': 'exact_original_png_snapshot'}
    return [prepared], [part]


def wire_body(request, profile, parts):
    """Serialize only the frozen native controls, literal instruction and exact bytes."""
    payload = {'model': profile.model, 'messages': [{'role': 'user', 'content': request.instruction,
               'images': [base64.b64encode(read_payload(parts[0])).decode('ascii')]}],
               'options': {'num_predict': request.limits.max_output_tokens,
                           'num_ctx': CONTROLS['num_ctx'], 'temperature': CONTROLS['temperature']},
               'think': False, 'stream': False, 'keep_alive': 0}
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    if len(body) + 512 + len(profile.base_url.encode()) > REQUEST_BYTES:
        raise ValueError('Native request exceeds the byte limit')
    return body


def binding(request, profile, prepared, parts):
    """Commit the exact planned body and controls without legacy thinking claims."""
    body = wire_body(request, profile, parts)
    value = {'backend': request.backend, 'protocol': 'ollama_plain',
             'endpoint': profile.base_url.rstrip('/') + '/api/chat', 'model': profile.model,
             'instruction': request.instruction, 'effective_controls': {**CONTROLS, 'num_predict': request.limits.max_output_tokens},
             'wire_request_body_sha256': hashlib.sha256(body).hexdigest(), 'wire_request_body_bytes': len(body),
             'sources': [p['source']['sha256'] for p in prepared],
             'payloads': [{'sha256': p['sha256'], 'bytes': p['bytes']} for p in parts],
             'planned_inference_count': 1, 'request_limit': REQUEST_BYTES, 'response_limit': RESPONSE_BYTES}
    return value, json_digest(value)


def result_answer(body, model, maximum, call):
    """Retain observed native metadata and reject incomplete or unexpected generation."""
    if not isinstance(body, dict):
        raise ValueError('Native response must be an object')
    keys = ('total_duration', 'load_duration', 'prompt_eval_count', 'prompt_eval_duration', 'eval_count', 'eval_duration')
    message = body.get('message')
    metadata = {key: body.get(key) if type(body.get(key)) is int and body[key] >= 0 else None for key in keys}
    done, reason = body.get('done'), body.get('done_reason')
    metadata.update(done=done if type(done) is bool else None,
                    done_reason=reason if reason in ('stop', 'length', 'load', 'unload') else None,
                    thinking_present=isinstance(message, dict) and message.get('thinking') not in (None, ''))
    call['native_metadata'] = metadata
    if body.get('model') != model or body.get('done') is not True or body.get('done_reason') != 'stop':
        raise ValueError('Native model or generation termination differs from the selected request')
    if not isinstance(message, dict) or message.get('role') != 'assistant' or message.get('tool_calls'):
        raise ValueError('Native response has no plain assistant answer')
    if message.get('thinking') not in (None, ''):
        raise ValueError('Native response contains thinking despite think=false')
    text = message.get('content')
    if not isinstance(text, str) or not text or len(text.encode()) > 32768:
        raise ValueError('Native response has no bounded plain text')
    if metadata['eval_count'] is not None and metadata['eval_count'] > maximum:
        raise ValueError('Native observed output count exceeds the requested maximum')
    call['status'] = 'completed'
    return VisionAnswer(answer=text, regions=[]).model_dump(mode='json')


async def inference(request, profile, parts, calls):
    """Submit once through the existing fenced exchange and retain raw body identities."""
    from .vision_http import exchange
    content = wire_body(request, profile, parts)
    call = {'kind': 'ollama_chat', 'status': 'attempted_usage_unknown', 'usage': None,
            'endpoint': profile.base_url.rstrip('/') + '/api/chat', 'protocol': 'ollama_plain',
            'model': profile.model, 'effective_controls': {**CONTROLS, 'num_predict': request.limits.max_output_tokens},
            'wire_request_body_sha256': hashlib.sha256(content).hexdigest(), 'wire_request_body_bytes': len(content),
            'wire_response_body_sha256': None, 'wire_response_body_bytes': None}
    calls.append(call)
    status, data = await exchange(call['endpoint'], headers={'Content-Type': 'application/json'},
                                  content=content, method='POST', local=True,
                                  request_limit=REQUEST_BYTES, response_limit=RESPONSE_BYTES)
    call.update(http_status=status, wire_response_body_sha256=hashlib.sha256(data).hexdigest(),
                wire_response_body_bytes=len(data))
    if status != 200:
        raise RuntimeError('Native endpoint returned an unsuccessful HTTP status')
    return result_answer(json.loads(data), profile.model, request.limits.max_output_tokens, call)
