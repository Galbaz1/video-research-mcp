"""SOURCE_ONLY authored PCM/timestamp fixtures; no speech, provider or render proof."""

import asyncio
import hashlib
import json
import struct
from copy import deepcopy

import pytest
from pydantic import ValidationError

from video_explainer_mcp import config
from video_explainer_mcp import storyboard_timing as timing
from video_explainer_mcp import render_worker
from video_explainer_mcp.models.planning import PlanRequest
from video_explainer_mcp.models.timing import TimingRequest
from video_explainer_mcp.narration_pcm import artifact, wav
from video_explainer_mcp.plan_artifacts import bind_script, bind_storyboard, require_binding
from video_explainer_mcp.planning import apply_plan, plan_transaction, save_plan
from video_explainer_mcp.planning_production import freeze_render_source
from video_explainer_mcp.planning_sources import canonical, digest
from video_explainer_mcp.render_storyboard import _timeline
from video_explainer_mcp.tools.timing import explainer_timing


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical(value))


def receipt(project, state, script, *, missing=False, changed=False, custom=False, spans=None):
    """Author known sample events into a real bound dummy receipt, without a provider."""
    rate, spans = 24000, spans or [8400, 6000, 9720]
    blocks = [struct.pack('<h', (2000 + i * 300 + (100 if changed and i == 0 else 0))) * span
              for i, span in enumerate(spans)]
    audio = wav(b''.join(blocks), rate)
    path = project / 'fixture/narration.wav'
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(audio)
    rows, words, cursor, offset = [], [], 0, 0
    for scene, span in zip(script['scenes'], spans, strict=True):
        text = scene['voiceover']
        rows.append({'scene_id': scene['scene_id'], 'text': text, 'status': 'accepted',
                     'start_frame': cursor, 'end_frame': cursor + span})
        words.append({'word': text, 'text_begin': offset, 'text_end': offset + len(text),
                      'start_frame': cursor, 'end_frame': cursor + span - 1200,
                      'alignment': 'synthetic_event'})
        cursor, offset = cursor + span, offset + len(text)
    body = {'status': 'accepted', 'action': 'custom' if custom else 'generate',
            'script_transcript': [{'scene_id': s['scene_id'], 'text': s['voiceover']} for s in script['scenes']],
            'transcript': ''.join(s['voiceover'] for s in script['scenes']),
            'artifact': artifact(path, project, audio), 'sentences': rows, 'words': None if missing else words,
            'word_alignment': 'absent' if missing else 'synthetic_event; authored fixture, not speech',
            'video_research_plan': {k: script['video_research_plan'][k] for k in
                                    ('revision', 'plan_sha256', 'source_commitment_sha256',
                                     'approval_role', 'factual_success', 'visual_audio_semantics')}}
    if custom:
        body['sentences'] = [{'scene_id': None, 'text': body['transcript'], 'status': 'accepted',
                             'start_frame': 0, 'end_frame': cursor}]
    target = project / 'fixture/narration.json'
    write(target, body)
    state['bindings']['narration'] = {
        'path': str(target.relative_to(project)), 'sha256': digest(body),
        'plan_revision': state['revision'], 'parent_script_sha256': state['bindings']['script']['sha256'],
        'audio_path': body['artifact']['path'], 'audio_sha256': body['artifact']['sha256']}
    return body


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Real source approval, SQLite CAS and source-bound storyboard; tiny dummy audio only."""
    root = tmp_path / 'projects' / 'timed'
    inputs = root / 'input'
    inputs.mkdir(parents=True)
    monkeypatch.setattr(config, '_config', config.ServerConfig(projects_path=str(root.parent)))
    packet = {'schema_version': 1, 'packet_id': 'timing-fixture', 'sources': [], 'claims': [], 'lineage': []}
    texts = ['One.', 'Two.', 'Three.']
    for index, text in enumerate(texts):
        key, sha = str(index), hashlib.sha256(text.encode()).hexdigest()
        (inputs / f'{key}.txt').write_text(text)
        packet['sources'].append({'id': key, 'revision': 'r1', 'sha256': sha, 'path': f'{key}.txt',
            'modality': 'text', 'asset_kind': 'original', 'snapshot': {'text': text, 'sha256': sha},
            'passages': [{'id': 'p', 'quote': text}]})
        packet['claims'].append({'id': key, 'text': text, 'editorial_approved': True,
                                'support': [{'source_id': key, 'passage_id': 'p'}]})
    write(inputs / 'evidence-packet.json', packet)
    plan = {'title': 'Authored timing fixture', 'audience': 'Unit test', 'thesis': 'Known samples only.',
            'concept_order': ['events'], 'duration_budget_seconds': 6.0,
            'scenes': [{'title': str(i), 'concept': 'events', 'purpose': 'Show authored event.',
                        'claim_ids': [str(i)], 'duration_seconds': 2.0} for i in range(3)],
            'sources': [{'source_id': str(i), 'disposition': 'included', 'reason': 'Exact fixture.'} for i in range(3)]}
    apply_plan(root.name, PlanRequest(action='create', expected_revision=0, plan=plan))
    apply_plan(root.name, PlanRequest(action='approve', expected_revision=1))
    script = {'title': plan['title'], 'total_duration_seconds': 6.0,
              'scenes': [{'scene_id': str(i), 'title': str(i), 'voiceover': text,
                         'duration_seconds': 2.0, 'visual_cue': {'description': 'Show authored event.'}}
                        for i, text in enumerate(texts)]}
    write(root / 'script/script.json', script)
    write(root / 'config.json', {'paths': {'storyboard': 'storyboard/storyboard.json'}})
    board = {'video': {'fps': 30}, 'total_duration_seconds': 6.0,
             'scenes': [{'id': str(i), 'type': 'CallerScene', 'title': str(i), 'audio_file': 'fixture/narration.wav',
                         'audio_duration_seconds': 2.0, 'props': {'visual': str(i)}} for i in range(3)]}
    write(root / 'storyboard/storyboard.json', board)
    with plan_transaction(root) as (connection, state):
        bind_script(root, state, packet)
        script = require_binding(root, state, 'script')
        receipt(root, state, script)
        bind_storyboard(root, state, root / 'storyboard/storyboard.json')
        save_plan(connection, state)
    return root


def call(project, action='inspect', revision=None):
    return asyncio.run(explainer_timing(project.name, TimingRequest(action=action, expected_revision=revision)))


def test_known_clock_public_repair_restart_and_visual_preservation(project):
    assert call(project)['status'] == 'stale'
    result = call(project, 'repair', 0)
    assert result['current'] and result['revision'] == 1 and result['affected_scenes'] == ['0', '1', '2']
    assert result['manifest']['render_verification'] == 'UNRUN'
    scenes = result['manifest']['scenes']
    assert [(s['start_sample'], s['end_sample']) for s in scenes] == [(0, 8400), (8400, 14400), (14400, 24120)]
    assert [(s['from_video_frame'], s['video_frames']) for s in scenes] == [(0, 11), (11, 7), (18, 13)]
    board = json.loads((project / 'storyboard/storyboard.json').read_text())
    _, frames = _timeline(board, project)
    assert frames == 31 and abs(frames / 30 - 24120 / 24000) <= 1 / 30
    for entry in board['scenes']:
        assert entry['type'] == 'CallerScene' and entry['props']['visual'] == entry['id']
        animations = entry['props']['timing']['animations']
        assert all(0 <= w['from'] < w['to'] <= scenes[int(entry['id'])]['video_frames'] for w in animations)
        assert 'authored fixture' in entry['props']['timing']['timestamp_method']
    restarted = call(project)
    assert restarted['current'] and restarted['revision'] == 1 and restarted['reused_scenes'] == ['0', '1', '2']


def test_changed_audio_selective_repair_and_revision_cas(project):
    first = call(project, 'repair', 0)
    old_board = json.loads((project / 'storyboard/storyboard.json').read_text())
    clips = {s['scene_id']: (project / s['audio_path']).stat().st_mtime_ns for s in first['manifest']['scenes']}
    with plan_transaction(project) as (connection, state):
        script = require_binding(project, state, 'script')
        receipt(project, state, script, changed=True)
        save_plan(connection, state)
    stale = call(project)
    assert stale['status'] == 'stale' and stale['affected_scenes'] == ['0']
    with plan_transaction(project) as (_, state), pytest.raises(ValueError, match='stale'):
        timing.require_current_timing(project, state)
    assert 'error' in call(project, 'repair', 0)
    result = call(project, 'repair', 1)
    assert result['current'] and result['revision'] == 2 and result['reused_scenes'] == ['1', '2']
    new_board = json.loads((project / 'storyboard/storyboard.json').read_text())
    assert new_board['scenes'][1:] == old_board['scenes'][1:]
    for row in result['manifest']['scenes'][1:]:
        assert (project / row['audio_path']).stat().st_mtime_ns == clips[row['scene_id']]


def test_changed_narration_requires_new_exact_source_script_then_repairs(project):
    call(project, 'repair', 0)
    packet = json.loads((project / 'input/evidence-packet.json').read_text())
    packet['claims'][0]['text'] = 'Four.'
    text, sha = 'Four.', hashlib.sha256(b'Four.').hexdigest()
    packet['sources'][0].update(sha256=sha, snapshot={'text': text, 'sha256': sha}, passages=[{'id': 'p', 'quote': text}])
    (project / 'input/0.txt').write_text(text)
    write(project / 'input/evidence-packet.json', packet)
    assert not call(project)['current']
    with plan_transaction(project) as (_, state):
        plan = state['plan']
    apply_plan(project.name, PlanRequest(action='revise', expected_revision=1, plan=plan))
    apply_plan(project.name, PlanRequest(action='approve', expected_revision=2))
    script = json.loads((project / 'script/script.json').read_text())
    script['scenes'][0]['voiceover'] = text
    write(project / 'script/script.json', script)
    with plan_transaction(project) as (connection, state):
        bind_script(project, state, packet)
        script = require_binding(project, state, 'script')
        receipt(project, state, script)
        save_plan(connection, state)
    result = call(project, 'repair', 1)
    assert result['current'] and result['affected_scenes'] == ['0'] and result['reused_scenes'] == ['1', '2']
    assert result['manifest']['plan_revision'] == 2


def test_earlier_length_change_shifts_global_clock_without_rewriting_unaffected_clips(project):
    first = call(project, 'repair', 0)
    old_paths = [project / s['audio_path'] for s in first['manifest']['scenes'][1:]]
    old_identity = [(p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in old_paths]
    with plan_transaction(project) as (connection, state):
        receipt(project, state, require_binding(project, state, 'script'), spans=[9200, 6000, 9720])
        save_plan(connection, state)
    result = call(project, 'repair', 1)
    assert result['affected_scenes'] == ['0'] and result['reused_scenes'] == ['1', '2']
    assert result['shifted_scenes'] == ['1', '2']
    assert [s['start_sample'] for s in result['manifest']['scenes']] == [0, 9200, 15200]
    assert result['manifest']['video_frames'] == 32
    assert [(p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in old_paths] == old_identity


def test_missing_alignment_never_creates_word_precision(project):
    with plan_transaction(project) as (connection, state):
        receipt(project, state, require_binding(project, state, 'script'), missing=True)
        save_plan(connection, state)
    result = call(project, 'repair', 0)
    assert result['status'] == 'missing_alignment' and result['current']
    board = json.loads((project / 'storyboard/storyboard.json').read_text())
    assert all(s['props']['timing']['words'] == s['props']['timing']['animations'] == [] for s in board['scenes'])
    assert result['manifest']['timestamp_method'] == 'absent'


def test_late_subframe_word_keeps_samples_and_has_nonempty_bounded_animation(project):
    with plan_transaction(project) as (connection, state):
        body = require_binding(project, state, 'narration')
        body['words'][1].update(start_frame=14360, end_frame=14390)
        write(project / 'fixture/narration.json', body)
        state['bindings']['narration']['sha256'] = digest(body)
        save_plan(connection, state)
    result = call(project, 'repair', 0)
    assert result['current']
    row = result['manifest']['scenes'][1]
    assert row['words'][0]['start_sample'] == 5960 and row['words'][0]['end_sample'] == 5990
    board = json.loads((project / 'storyboard/storyboard.json').read_text())
    event = board['scenes'][1]['props']['timing']['animations'][0]
    assert 0 <= event['from'] < event['to'] <= row['video_frames']


def test_custom_audio_without_scene_spans_refuses_and_invalidates_binding(project):
    old = call(project, 'repair', 0)
    with plan_transaction(project) as (connection, state):
        receipt(project, state, require_binding(project, state, 'script'), missing=True, custom=True)
        save_plan(connection, state)
    result = call(project, 'repair', 1)
    assert result['status'] == 'missing_scene_timing' and not result['current']
    assert result['revision'] == old['revision'] and result['issues']
    with pytest.raises(ValueError):
        freeze_render_source(project)


@pytest.mark.parametrize('target', ['input/0.txt', 'script/script.json', 'fixture/narration.wav',
                                    'fixture/narration.json', 'storyboard/storyboard.json', '.timing/manifest.json'])
def test_source_and_artifact_tampering_fail_closed(project, target):
    call(project, 'repair', 0)
    path = project / target
    path.write_bytes(path.read_bytes() + b'X')
    with plan_transaction(project) as (_, state), pytest.raises((ValueError, OSError)):
        timing.require_current_timing(project, state)


@pytest.mark.parametrize('fault', ['reversed_words', 'overlap_sentences', 'outside_scene', 'oversized_words',
                                  'cross_scene_text', 'extra_sentence'])
def test_bad_external_receipt_timing_is_refused_before_storyboard_write(project, fault):
    before = (project / 'storyboard/storyboard.json').read_bytes()
    with plan_transaction(project) as (connection, state):
        body = require_binding(project, state, 'narration')
        if fault == 'reversed_words':
            body['words'] = body['words'][::-1]
        elif fault == 'overlap_sentences':
            body['sentences'][1]['start_frame'] = 0
        elif fault == 'outside_scene':
            body['words'][0]['end_frame'] = 9000
        elif fault == 'oversized_words':
            body['words'] *= 1400
        elif fault == 'cross_scene_text':
            body['words'] = [{'word': body['transcript'], 'text_begin': 0, 'text_end': len(body['transcript']),
                              'start_frame': 0, 'end_frame': body['artifact']['frames'], 'alignment': 'synthetic_event'}]
        else:
            body['sentences'].append({**body['sentences'][0], 'scene_id': 'unreferenced'})
        write(project / 'fixture/narration.json', body)
        state['bindings']['narration']['sha256'] = digest(body)
        save_plan(connection, state)
    result = call(project, 'repair', 0)
    assert not result['current'] and result['issues']
    assert (project / 'storyboard/storyboard.json').read_bytes() == before
    assert not (project / '.timing/manifest.json').exists()


def test_interrupted_manifest_publication_retains_old_revision_and_refuses_render(project, monkeypatch):
    call(project, 'repair', 0)
    old = (project / '.timing/manifest.json').read_bytes()
    with plan_transaction(project) as (connection, state):
        receipt(project, state, require_binding(project, state, 'script'), changed=True)
        save_plan(connection, state)
    original = timing.atomic_write
    def interrupted(path, body):
        if path.name == 'manifest.json':
            raise OSError('controlled publication interruption')
        original(path, body)
    monkeypatch.setattr(timing, 'atomic_write', interrupted)
    result = call(project, 'repair', 1)
    assert 'error' in result
    assert (project / '.timing/manifest.json').read_bytes() == old
    with pytest.raises(ValueError):
        freeze_render_source(project)
    with plan_transaction(project) as (_, state), pytest.raises(ValueError):
        timing.require_current_timing(project, state)


def test_manifest_symlink_and_sparse_oversize_refused_without_following(project, tmp_path):
    call(project, 'repair', 0)
    path = project / '.timing/manifest.json'
    path.unlink()
    outside = tmp_path / 'outside.json'
    outside.write_text('{}')
    path.symlink_to(outside)
    assert 'error' in call(project)
    path.unlink()
    with path.open('wb') as stream:
        stream.truncate(1024 * 1024 + 1)
    assert 'error' in call(project)


def test_retained_clip_tamper_is_refused(project):
    result = call(project, 'repair', 0)
    path = project / result['manifest']['scenes'][1]['audio_path']
    body = path.read_bytes()
    path.write_bytes(body[:-2] + b'XX')
    with plan_transaction(project) as (_, state), pytest.raises(ValueError, match='audio changed'):
        timing.require_current_timing(project, state)


def test_rebound_board_cannot_forge_sample_animation_props(project):
    call(project, 'repair', 0)
    board = json.loads((project / 'storyboard/storyboard.json').read_text())
    board['scenes'][0]['props']['timing']['animations'][0]['to'] = 1
    write(project / 'storyboard/storyboard.json', board)
    with plan_transaction(project) as (connection, state):
        bind_storyboard(project, state, project / 'storyboard/storyboard.json')
        save_plan(connection, state)
    manifest = json.loads((project / '.timing/manifest.json').read_text())
    manifest['storyboard'] = timing.project_object(project, 'storyboard/storyboard.json')[1]
    write(project / '.timing/manifest.json', manifest)
    with plan_transaction(project) as (_, state), pytest.raises(ValueError, match='props differ'):
        timing.require_current_timing(project, state)


def test_render_qualification_existing_tolerance_and_request_source_binding(project):
    result = call(project, 'repair', 0)
    manifest = result['manifest']
    request = {'render_contract': {'input_props': {'fps': 30, 'durationInFrames': 31}},
               'renderer': {'project_sha256': {'storyboard/storyboard.json': manifest['storyboard']['sha256']}}}
    with plan_transaction(project) as (_, state):
        accepted = timing.verify_render_timing(project, state, request, {'media': {'duration_seconds': 31 / 30}})
        assert accepted['timing'] == 'verified_existing_qualification'
        for duration in (2.0, float('nan')):
            with pytest.raises(ValueError, match='duration'):
                timing.verify_render_timing(project, state, request, {'media': {'duration_seconds': duration}})
        bad = deepcopy(request)
        bad['renderer']['project_sha256']['storyboard/storyboard.json'] = 'wrong'
        with pytest.raises(ValueError, match='request'):
            timing.verify_render_timing(project, state, bad, {'media': {'duration_seconds': 31 / 30}})


def test_typed_tool_requires_exact_write_revision_and_no_speculative_flags(project):
    for payload in ({'action': 'repair'}, {'action': 'inspect', 'expected_revision': 0},
                    {'action': 'repair', 'expected_revision': True}, {'action': 'inspect', 'force': True}):
        with pytest.raises(ValidationError):
            TimingRequest.model_validate(payload)
    assert 'error' in call(project, 'repair', 9)
    assert not (project / '.timing').exists()


@pytest.mark.parametrize('duration', [31 / 30, 2.0, float('nan')])
def test_worker_qualification_enforces_accepted_narration_duration(project, monkeypatch, duration):
    manifest = call(project, 'repair', 0)['manifest']
    request = {'project_dir': str(project), 'resolution': '720p',
               'render_contract': {'input_props': {'fps': 30, 'durationInFrames': 31}},
               'renderer': {'route': 'authored_storyboard', 'project_sha256': {
                   'storyboard/storyboard.json': manifest['storyboard']['sha256']}}}

    async def qualified(*args):
        return {'media': {'duration_seconds': duration}}

    monkeypatch.setattr(render_worker, 'qualify_render', qualified)
    monkeypatch.setattr(render_worker, 'qualify_production', qualified)
    if duration == 31 / 30:
        result = asyncio.run(render_worker._qualify_output({'size_bytes': 1}, request))
        assert result['narration_timing']['timing'] == 'verified_existing_qualification'
    else:
        with pytest.raises(ValueError, match='duration'):
            asyncio.run(render_worker._qualify_output({'size_bytes': 1}, request))


def test_render_freeze_rejects_changed_accepted_audio(project):
    call(project, 'repair', 0)
    path = project / 'fixture/narration.wav'
    path.write_bytes(path.read_bytes() + b'changed')
    with pytest.raises(ValueError):
        freeze_render_source(project)
