"""Mocked native wire, original PNG custody and bounded exchange controls."""
import asyncio
import base64
import hashlib
import json
import struct
import zlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from video_research_mcp import config, media_local_io, media_snapshot
from video_research_mcp import vision_analysis as analysis, vision_provider as provider
from video_research_mcp.models.vision import VisionBackend, VisionRequest


def png_bytes():
    """Produce a small valid PNG fixture without a native encoder."""
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0')) + chunk(b'IEND', b''))


@pytest.fixture
def native(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    image = root / 'exact.png'
    data = png_bytes()
    image.write_bytes(data)
    profile = VisionBackend(base_url='http://127.0.0.1:19001', model='fixture:4b',
                            local=True, capabilities=['images'], protocol='ollama_plain')
    cfg = config.get_config().model_copy(update={'vision_backends': {'native': profile},
                                                 'cache_dir': str(root / 'cache')})
    for module in (analysis, provider, media_snapshot, media_local_io):
        monkeypatch.setattr(module, 'get_config', lambda: cfg)
    request = VisionRequest(sources=[{'file_path': str(image), 'expected_source_sha256': hashlib.sha256(data).hexdigest()}],
                            instruction='Only original instruction.', backend='native', dry_run=False,
                            authorize_submission=True, limits={'max_calls': 1, 'max_tokens': 1000, 'max_output_tokens': 128})
    response = {'model': 'fixture:4b', 'done': True, 'done_reason': 'stop',
                'message': {'role': 'assistant', 'content': 'red', 'thinking': ''},
                'eval_count': 1, 'total_duration': 100}
    exchange = AsyncMock(return_value=(200, json.dumps(response).encode()))
    monkeypatch.setattr('video_research_mcp.vision_http.exchange', exchange)
    monkeypatch.setattr(analysis, 'prepare_sources', AsyncMock(side_effect=AssertionError('native conversion')))
    return SimpleNamespace(request=request, profile=profile, image=image, data=data,
                           root=root, exchange=exchange, response=response)


async def test_exact_wire_and_dry_plan(native):
    plan = await analysis.analyze_vision(native.request.model_copy(update={'dry_run': True}), 'vision_chat')
    assert plan['status'] == 'planned' and plan['execution']['model_inference_attempts'] == 0
    native.exchange.assert_not_called()
    result = await analysis.analyze_vision(native.request, 'vision_chat')
    assert result['status'] == 'complete' and result['model_output'] == {'answer': 'red', 'regions': []}
    assert result['request_sha256'] == plan['request_sha256']
    assert native.exchange.call_count == 1
    args, kwargs = native.exchange.call_args
    body = json.loads(kwargs['content'])
    assert args == ('http://127.0.0.1:19001/api/chat',)
    assert body == {'model': 'fixture:4b', 'messages': [{'role': 'user', 'content': native.request.instruction,
                     'images': [base64.b64encode(native.data).decode()]}],
                    'options': {'num_predict': 128, 'num_ctx': 4096, 'temperature': 0},
                    'think': False, 'stream': False, 'keep_alive': 0}
    assert kwargs['local'] is True and kwargs['request_limit'] == 1048576 and kwargs['response_limit'] == 131072
    assert result['execution']['planned_calls'] == result['execution']['model_inference_attempts'] == 1
    call = result['execution']['calls'][0]
    assert call['wire_request_body_sha256'] == hashlib.sha256(kwargs['content']).hexdigest()
    assert call['wire_response_body_sha256'] == hashlib.sha256(json.dumps(native.response).encode()).hexdigest()
    assert call['native_metadata']['eval_count'] == 1
    assert 'thinking_level' not in result['backend']
    assert result['payload_receipt'][0]['sha256'] == hashlib.sha256(native.data).hexdigest()
    assert not list((native.root / 'cache').rglob('source.png'))


@pytest.mark.parametrize('change,operation', [({'output_schema': {}}, 'vision_chat'),
    ({'thinking_level': 'high'}, 'vision_chat'),
    ({'export_crops': True}, 'vision_chat'), ({}, 'ocr'), ({}, 'grounding'),
    ({'sources': 'resize'}, 'vision_chat'), ({'sources': 'fps'}, 'vision_chat'),
    ({'sources': 'two'}, 'vision_chat'), ({'sources': 'frame'}, 'vision_chat')])
async def test_unsupported_before_preparation(native, monkeypatch, change, operation):
    from video_research_mcp import vision_ollama
    prepare = AsyncMock(side_effect=AssertionError('unsupported preparation'))
    monkeypatch.setattr(vision_ollama, 'prepare_png', prepare)
    change = dict(change)
    if 'sources' in change:
        mode = change['sources']
        source = native.request.sources[0].model_copy()
        if mode == 'two':
            change['sources'] = [source, source]
        elif mode == 'frame':
            change['sources'] = [source.model_copy(update={'kind': 'frame', 'time_seconds': 0})]
        else:
            update = {'resize': {'width': 1, 'height': 1}} if mode == 'resize' else {'fps': 1}
            change['sources'] = [source.model_copy(update=update)]
    result = await analysis.analyze_vision(native.request.model_copy(update=change), operation)
    assert result['retryable'] is False and result['execution']['model_inference_attempts'] == 0
    prepare.assert_not_called()
    native.exchange.assert_not_called()


@pytest.mark.parametrize('update', [dict(local=False), dict(base_url='http://localhost:19001'),
    dict(base_url='http://127.0.0.1:19001/v1'), dict(api_key_env='OTHER_API_KEY'),
    dict(video_delivery='dashscope_temporary'), dict(capabilities=['images', 'video'])])
def test_native_profile_local_only(update):
    with pytest.raises(ValueError):
        VisionBackend.model_validate({**dict(base_url='http://127.0.0.1:19001', model='fixture:4b',
                                          local=True, capabilities=['images'], protocol='ollama_plain'), **update})


@pytest.mark.parametrize('field,value', [('model', 'foreign:4b'), ('done', False),
    ('done_reason', 'length'), ('thinking', 'hidden thinking'), ('content', 'x' * 32769), ('eval_count', 129)])
async def test_bad_native_result_no_retry_and_cleanup(native, field, value):
    if field in {'thinking', 'content'}:
        native.response['message'][field] = value
    else:
        native.response[field] = value
    native.exchange.return_value = 200, json.dumps(native.response).encode()
    result = await analysis.analyze_vision(native.request, 'vision_chat')
    assert result['retryable'] is False
    assert result['execution']['model_inference_attempts'] == native.exchange.call_count == 1
    assert result['execution']['calls'][0]['wire_response_body_sha256']
    if field == 'thinking':
        assert 'hidden thinking' not in json.dumps(result)
        assert result['execution']['calls'][0]['native_metadata']['thinking_present'] is True
    assert not list((native.root / 'cache').rglob('source.png'))


@pytest.mark.parametrize('mode', ['source', 'payload', 'cancel', 'transport'])
async def test_mutation_and_cancellation_cleanup(native, mode):
    async def exchange(*args, **kwargs):
        if mode == 'source':
            native.image.write_bytes(native.data + b'mutated')
        elif mode == 'payload':
            next((native.root / 'cache').rglob('source.png')).write_bytes(b'mutated')
        elif mode == 'cancel':
            raise asyncio.CancelledError()
        else:
            raise RuntimeError('transport')
        return 200, json.dumps(native.response).encode()
    native.exchange.side_effect = exchange
    if mode == 'cancel':
        with pytest.raises(asyncio.CancelledError):
            await analysis.analyze_vision(native.request, 'vision_chat')
    else:
        result = await analysis.analyze_vision(native.request, 'vision_chat')
        assert result['retryable'] is False and native.exchange.call_count == 1
    assert not list((native.root / 'cache').rglob('source.png'))


@pytest.mark.parametrize('data', [b'not png', b'\x89PNG\r\n\x1a\n', b'x' * 786433])
async def test_input_limits_before_submission(native, data):
    native.image.write_bytes(data)
    source = native.request.sources[0].model_copy(update={'expected_source_sha256': hashlib.sha256(data).hexdigest()})
    result = await analysis.analyze_vision(native.request.model_copy(update={'sources': [source]}), 'vision_chat')
    assert result['retryable'] is False
    native.exchange.assert_not_called()


async def test_header_and_body_bound_before_http_parser_allocation(monkeypatch):
    from video_research_mcp.vision_http import _LimitedStream
    class Stream:
        def __init__(self):
            self.requested = []
        async def read(self, max_bytes, timeout=None):
            self.requested.append(max_bytes)
            return b'h' * max_bytes
    raw = Stream()
    stream = _LimitedStream(raw, 131072)
    assert len(await stream.read(65536)) == 65536
    assert len(await stream.read(65536)) == 65536
    with pytest.raises(ValueError, match='byte limit'):
        await stream.read(65536)
    assert raw.requested == [65536, 65536, 1]


async def test_native_request_bound_before_destination(monkeypatch):
    from video_research_mcp import vision_http
    destination = AsyncMock(side_effect=AssertionError('destination lookup'))
    monkeypatch.setattr(vision_http, '_destination', destination)
    with pytest.raises(ValueError, match='byte limit'):
        await vision_http.exchange('http://127.0.0.1:19001/api/chat', headers={},
                                   content=b'x' * 1048576, method='POST', local=True,
                                   request_limit=1048576, response_limit=131072)
    destination.assert_not_called()
