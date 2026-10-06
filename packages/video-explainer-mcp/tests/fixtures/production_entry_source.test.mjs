import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import os from 'node:os';
import {parseObject, normalizeBoard, audioExtent, sceneSources, confined, regular} from
  '../../renderer-entry/production_project.mjs';
import {parseArguments, webpackOverride, localAudioDownload, executable, cleanup} from
  '../../renderer-entry/production_entry.mjs';

const first = {id: 'a', type: 'diagram', title: 'Diagram', audio_file: 'voiceover/a.wav',
  audio_duration_seconds: 0.2, visual_padding_seconds: 0.1, props: {label: 'Caller content', nodes: [1, 2]}};
const second = {id: 'b', type: 'explanation', title: 'Explanation', audio_file: 'voiceover/b.mp3',
  audio_duration_seconds: 1.05, visual_padding_seconds: 0.25};
const board = () => ({video: {fps: 30, width: 1920, height: 1080}, scenes: [structuredClone(first), {...second}],
  total_duration_seconds: 1.6, audio: {background_music: null, music_volume: 0.1}, style: {}});

test('two actual registry types retain scene props and exact decimal audio/padding clocks', () => {
  const source = board();
  const actual = normalizeBoard(source, '720p');
  assert.deepEqual([actual.width, actual.height, actual.fps, actual.durationInFrames], [1280, 720, 30, 48]);
  assert.deepEqual(actual.scenes.map((s) => [s.type, s.from, s.durationInFrames, s.audioDurationInFrames, s.visualPaddingInFrames]),
    [['diagram', 0, 9, 6, 3], ['explanation', 9, 39, 32, 8]]);
  assert.equal(actual.scenes[0].props, source.scenes[0].props);
  assert.deepEqual(actual.scenes.map((s) => s.audio_src), ['voiceover/a.wav', 'voiceover/b.mp3']);
});

test('each scene rounds once; separate padding/audio ceilings do not extend its clock', () => {
  const actual = normalizeBoard({scenes: [{...first, audio_duration_seconds: 0.01, visual_padding_seconds: 0.01}],
    total_duration_seconds: 0.02}, '4k');
  assert.equal(actual.durationInFrames, 1);
  assert.equal(actual.scenes[0].audioDurationInFrames, 1);
  assert.equal(actual.scenes[0].visualPaddingInFrames, 1);
  assert.deepEqual([actual.width, actual.height], [3840, 2160]);
});

test('64-scene and 1800-second boundaries retain exact frame denominators', () => {
  const maximum = {scenes: [{...first, audio_duration_seconds: 1800, visual_padding_seconds: 0}], total_duration_seconds: 1800};
  assert.equal(normalizeBoard(maximum, '1080p').durationInFrames, 54000);
  assert.throws(() => normalizeBoard({scenes: [{...first, audio_duration_seconds: 1800, visual_padding_seconds: 0.01}]}, '720p'));
  const scenes = Array.from({length: 64}, (_, i) => ({...first, id: String(i), audio_duration_seconds: 0.01, visual_padding_seconds: 0.01}));
  assert.equal(normalizeBoard({scenes}, '720p').durationInFrames, 64);
  assert.throws(() => normalizeBoard({scenes: [...scenes, {...first, id: '65'}]}, '720p'));
});

const damages = {
  duplicate_id: (b) => {b.scenes[1].id = 'a';},
  blank_type: (b) => {b.scenes[0].type = ' ';},
  negative_audio: (b) => {b.scenes[0].audio_duration_seconds = -1;},
  bool_audio: (b) => {b.scenes[0].audio_duration_seconds = true;},
  nonfinite_audio: (b) => {b.scenes[0].audio_duration_seconds = Infinity;},
  negative_padding: (b) => {b.scenes[0].visual_padding_seconds = -0.1;},
  null_padding: (b) => {b.scenes[0].visual_padding_seconds = null;},
  bool_buffer: (b) => {b.scenes[0].scene_buffer_seconds = false;},
  nonzero_buffer: (b) => {b.scenes[0].scene_buffer_seconds = 0.1;},
  active_sfx: (b) => {b.scenes[0].sfx_cues = ['bell'];},
  active_music: (b) => {b.audio.background_music = 'music.wav';},
  malformed_sfx: (b) => {b.scenes[0].sfx_cues = null;},
  active_style: (b) => {b.style.color = 'red';},
  unknown_scene: (b) => {b.scenes[0].camera = 'ignored';},
  unknown_board: (b) => {b.transition = 'ignored';},
  malformed_props: (b) => {b.scenes[0].props = [];},
  changed_total: (b) => {b.total_duration_seconds = 1.61;},
  bad_fps: (b) => {b.video.fps = 60;},
  null_video: (b) => {b.video = null;},
  unpaired_dimensions: (b) => {delete b.video.height;},
  malformed_lineage: (b) => {b.video_research_plan = 'claim';},
};
for (const [name, damage] of Object.entries(damages)) {
  test(`refuses ${name}`, () => {const value = board(); damage(value); assert.throws(() => normalizeBoard(value, '720p'));});
}

test('retains raw JSON integer typing for Python parity and rejects nested duplicates/nonfinite/invalid UTF8', () => {
  for (const raw of ['30.0', '3e1']) {
    const value = parseObject(Buffer.from(`{"video":{"fps":${raw}},"scenes":[${JSON.stringify(first)}]}`));
    assert.throws(() => normalizeBoard(value, '720p'), /clock/);
  }
  for (const raw of ['{"nested":{"x":1,"x":2}}', '{"x":1e999}', '{"x":NaN}']) {
    assert.throws(() => parseObject(Buffer.from(raw)));
  }
  assert.throws(() => parseObject(Buffer.from([123, 34, 120, 34, 58, 34, 0xff, 34, 125])));
  assert.deepEqual(parseObject(Buffer.from('{"array":[{"x":1}, {"x":2}],"text":"{\\"x\\":1}"}')),
    {array: [{x: 1}, {x: 2}], text: '{"x":1}'});
  const nested = JSON.stringify({scenes: [{...first, props: {nested: [{edge: 'EDGE'}]}}]});
  for (const raw of ['9007199254740991', '-9007199254740991', '1.25', '-1.25', 'null', 'true', '"label"']) {
    const value = parseObject(Buffer.from(nested.replace('"EDGE"', raw)));
    assert.equal(normalizeBoard(value, '720p').scenes[0].props, value.scenes[0].props);
  }
  for (const raw of ['9007199254740992', '-9007199254740992', '9007199254740993', '-9007199254740993']) {
    const value = parseObject(Buffer.from(nested.replace('"EDGE"', raw)));
    assert.throws(() => normalizeBoard(value, '720p'), /Scene props contain an unsafe integer/);
  }
  const lineage = board(); lineage.video_research_plan = {outside_props: 9007199254740992};
  assert.equal(normalizeBoard(lineage, '720p').durationInFrames, 48);
});

test('accepts one bounded audio extent and refuses inaccurate or additional streams', () => {
  const probe = {streams: [{codec_type: 'audio', duration: '1.01', start_time: '0.0'}]};
  assert.equal(audioExtent(probe, 1), 1.01);
  assert.throws(() => audioExtent(probe, 1.1), /extent/);
  assert.throws(() => audioExtent({streams: [{codec_type: 'audio', duration: '0.97'}]}, 1.001), /extent/);
  assert.throws(() => audioExtent({streams: [...probe.streams, {codec_type: 'video'}]}, 1), /one audio/);
  assert.throws(() => audioExtent({streams: [{codec_type: 'audio', duration: 'N/A'}]}, 1));
  assert.throws(() => audioExtent({streams: [{codec_type: 'audio', duration: '1', start_time: '0.2'}]}, 1));
});

test('Root base argv preserves token last, ENV custody and explicit fast selection; cleanup retains primary', async () => {
  const base = ['--project', '/project', '--resolution', '1080p', '--spec', '/spec', '--spec-sha256', 'a'.repeat(64),
    '--output-relative', 'output/final-1080p.mp4'];
  const token = ['--execution-token', 'b'.repeat(32)];
  assert.equal(parseArguments([...base, ...token]).fast, false);
  assert.equal(parseArguments([...base, '--fast', ...token]).fast, true);
  assert.throws(() => parseArguments([...base, ...token, '--fast']), /remain last/);
  assert.throws(() => parseArguments([...base, '--fast', '--fast', ...token]), /Duplicate/);
  assert.throws(() => parseArguments([...base, '--browser-custody', '/custody', ...token]), /Unknown/);
  const primary = new Error('PRIMARY_RENDER_REFUSAL'), close = new Error('BROWSER_CLOSE_FAILED');
  const remove = new Error('BUNDLE_REMOVE_FAILED'), staging = new Error('STAGING_REMOVE_FAILED');
  const attempted = [];
  let combined;
  await assert.rejects(cleanup(primary, [
    ['browser_close', async () => {attempted.push('close'); throw close;}],
    ['bundle_remove', async () => {attempted.push('remove'); throw remove;}],
  ]), (error) => {combined = error; return error instanceof AggregateError;});
  assert.deepEqual(attempted, ['close', 'remove']);
  assert.equal(combined.cause, primary);
  assert.deepEqual(combined.errors, [primary, close, remove]);
  assert.deepEqual(combined.cleanup_failures, [{stage: 'browser_close', error: close}, {stage: 'bundle_remove', error: remove}]);
  await assert.rejects(cleanup(combined, [['staging_remove', async () => {throw staging;}]]), (error) => {
    assert.equal(error.cause, primary); assert.equal(error.errors[0], primary);
    assert.deepEqual(error.errors, [primary, close, remove, staging]);
    assert.deepEqual(error.cleanup_failures.map(({stage}) => stage), ['browser_close', 'bundle_remove', 'staging_remove']);
    for (const original of error.errors) assert.ok(String(error).includes(String(original)));
    return true;
  });
  assert.equal(String(primary), 'Error: PRIMARY_RENDER_REFUSAL');
  await assert.rejects((async () => {
    try {throw primary;} finally {await cleanup(primary, [['successful_cleanup', async () => {}]]);}
  })(), (error) => error === primary);
  await cleanup(undefined, [['successful_cleanup', async () => {}]]);
  await assert.rejects(cleanup(undefined, [['browser_close', async () => {throw close;}]]), (error) => {
    assert.equal(error.cause, undefined); assert.deepEqual(error.errors, [close]);
    return String(error).includes(String(close));
  });
});

test('admitted local audio transfer permits no remote origin, other asset, or query', () => {
  const scenes = [{audio_src: 'voiceover/a.wav'}];
  localAudioDownload('http://localhost:3000/public/voiceover/a.wav', scenes);
  for (const src of ['https://remote.example/public/voiceover/a.wav', 'http://localhost:3000/public/font.woff',
    'http://localhost:3000/public/voiceover/a.wav?other=1', 'file:///public/voiceover/a.wav']) {
    assert.throws(() => localAudioDownload(src, scenes));
  }
});

test('source closure pins actual regular TSX bytes and refuses symlink/escape/unreadable paths', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'vrm-production-source-unit-'));
  try {
    await fs.mkdir(path.join(root, 'scenes'));
    await fs.writeFile(path.join(root, 'scenes/index.ts'), 'export const sceneRegistry = {};\n');
    await fs.writeFile(path.join(root, 'scenes/Diagram.tsx'), 'export const value = 1;\n');
    const before = await sceneSources(root);
    assert.equal((await regular(path.join(root, 'scenes/index.ts'), 1024)).toString(), 'export const sceneRegistry = {};\n');
    await assert.rejects(regular(path.join(root, 'scenes/index.ts'), 1), /bounded regular/);
    assert.deepEqual(Object.keys(before).sort(), ['scenes/Diagram.tsx', 'scenes/index.ts']);
    const binary = path.join(root, 'scenes/index.ts');
    await fs.chmod(binary, 0o700);
    const minimal = {path: binary, sha256: before['scenes/index.ts']};
    const normalized = {...minimal, size_bytes: Buffer.byteLength('export const sceneRegistry = {};\n')};
    assert.deepEqual(await executable(minimal), normalized);
    assert.deepEqual(await executable({...minimal, size_bytes: 0, extra: 'accepted input'}), normalized);
    assert.deepEqual(Object.keys(minimal).sort(), ['path', 'sha256']);
    await assert.rejects(executable({...minimal, sha256: '0'.repeat(64)}), /Executable changed/);
    await fs.writeFile(path.join(root, 'scenes/Diagram.tsx'), 'export const value = 2;\n');
    assert.notEqual((await sceneSources(root))['scenes/Diagram.tsx'], before['scenes/Diagram.tsx']);
    for (const name of ['../outside', '/absolute', 'scenes/../index.ts', 'scenes//index.ts', 'http://remote.example/a.wav']) {
      await assert.rejects(confined(root, name));
    }
    await fs.symlink('index.ts', path.join(root, 'scenes/alias.ts'));
    await assert.rejects(sceneSources(root), /symlink/);
    await assert.rejects(confined(root, 'scenes/alias.ts'), /Nonregular/);
    await fs.unlink(path.join(root, 'scenes/alias.ts'));
    await fs.chmod(path.join(root, 'scenes'), 0o000);
    await assert.rejects(sceneSources(root), /readable/);
    await fs.chmod(path.join(root, 'scenes'), 0o700);
    await fs.writeFile(path.join(root, 'scenes/extra.js'), 'export const extra = true;\n');
    await assert.rejects(sceneSources(root), /TypeScript/);
  } finally {await fs.chmod(path.join(root, 'scenes'), 0o700); await fs.rm(root, {recursive: true, force: true});}
});

test('webpack closure guard checks resolved source bytes and forbids foreign modules/loaders before build', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'vrm-production-closure-unit-'));
  try {
    await fs.mkdir(path.join(root, 'scenes'));
    const source = path.join(root, 'scenes/index.ts'), bytes = 'export const sceneRegistry = {};\n';
    await fs.writeFile(source, bytes);
    const inputs = {'scenes/index.ts': createHash('sha256').update(bytes).digest('hex')};
    const config = webpackOverride(root, inputs)({resolve: {}, plugins: []});
    assert.equal(config.resolve.alias['@project-scenes$'], source);
    let guard;
    const compiler = {hooks: {normalModuleFactory: {tap: (_, callback) => callback({hooks: {
      afterResolve: {tapPromise: (_, callback) => {guard = callback;}},
    }})}}};
    config.plugins[0].apply(compiler);
    await guard({createData: {resource: source, loaders: []}});
    await assert.rejects(guard({createData: {resource: path.join(root, 'foreign.ts'), loaders: []}}), /Undeclared/);
    await assert.rejects(guard({createData: {resource: source, loaders: [{loader: '/foreign/loader.js'}]}}), /Unfrozen/);
    await fs.writeFile(source, 'export const sceneRegistry = {changed: true};\n');
    await assert.rejects(guard({createData: {resource: source, loaders: []}}), /Undeclared/);
  } finally {await fs.rm(root, {recursive: true, force: true});}
});
