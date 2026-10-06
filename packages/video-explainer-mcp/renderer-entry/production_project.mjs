import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import childProcess from 'node:child_process';
import path from 'node:path';
import {createHash} from 'node:crypto';

const resolutions = {'720p': [1280, 720], '1080p': [1920, 1080], '4k': [3840, 2160]};
const sha = (body) => createHash('sha256').update(body).digest('hex');
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const sameKeys = (value, keys) => object(value) && Object.keys(value).sort().join('\0') === [...keys].sort().join('\0');
const same = (a, b) => object(a) && object(b) && sameKeys(a, Object.keys(b))
  && Object.keys(b).every((key) => a[key] === b[key]);
function requireValue(condition, message) { if (!condition) throw new Error(message); }
const numberTokens = new WeakMap();

export function parseObject(body) {
  const text = new TextDecoder('utf-8', {fatal: true}).decode(body);
  const value = JSON.parse(text);
  requireValue(object(value), 'JSON input must be an object');
  const stack = [];
  for (const token of text.match(/"(?:\\.|[^"\\])*"|[{}\[\],:]|true|false|null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g)) {
    const top = stack.at(-1);
    if (token === '{' || token === '[') {
      const container = top ? top.container[top.keys ? top.name : top.index] : value;
      stack.push({container, keys: token === '{' ? new Set() : null, key: true, index: 0});
    }
    else if (token === '}' || token === ']') stack.pop();
    else if (token === ',') {top.key = true; top.index++;}
    else if (token.startsWith('"') && top?.keys && top.key) {
      const key = JSON.parse(token);
      requireValue(!top.keys.has(key), `Duplicate JSON key: ${key}`);
      top.keys.add(key); top.key = false; top.name = key;
    } else if (/^-?\d/.test(token)) {
      requireValue(Number.isFinite(Number(token)), 'Nonfinite JSON number');
      if (!numberTokens.has(top.container)) numberTokens.set(top.container, {});
      numberTokens.get(top.container)[top.keys ? top.name : top.index] = token;
    }
  }
  return value;
}


export async function regular(file, limit) {
  const handle = await fs.open(file, fsSync.constants.O_RDONLY | fsSync.constants.O_NOFOLLOW | fsSync.constants.O_NONBLOCK);
  try {
    const before = await handle.stat();
    requireValue(before.isFile() && before.size <= limit, `Not a bounded regular file: ${file}`);
    const buffer = Buffer.alloc(before.size + 1);
    let total = 0;
    while (total < buffer.length) {
      const {bytesRead} = await handle.read(buffer, total, Math.min(1024 * 1024, buffer.length - total), null);
      if (!bytesRead) break;
      total += bytesRead;
    }
    const body = buffer.subarray(0, total);
    const after = await handle.stat();
    requireValue(before.size === after.size && before.mtimeMs === after.mtimeMs
      && before.ctimeMs === after.ctimeMs && body.length === before.size && body.length <= limit, `File changed: ${file}`);
    return body;
  } finally { await handle.close(); }
}


export async function revision(file, limit = 512 * 1024 * 1024) {
  const body = await regular(file, limit);
  return {sha256: sha(body), size_bytes: body.length};
}


export async function confined(project, relative) {
  requireValue(typeof relative === 'string' && relative.length > 0 && !/[\\:\x00]/.test(relative)
    && !path.isAbsolute(relative) && relative.split('/').every((part) => part && part !== '.' && part !== '..'),
  `Confined project-relative path required: ${relative}`);
  let current = project;
  const parts = relative.split('/');
  for (let i = 0; i < parts.length; i++) {
    current = path.join(current, parts[i]);
    const stat = await fs.lstat(current);
    requireValue(!stat.isSymbolicLink() && (i === parts.length - 1 ? stat.isFile() : stat.isDirectory()),
      `Nonregular project path: ${relative}`);
  }
  return current;
}


export async function sceneSources(project) {
  const root = path.join(project, 'scenes');
  const sources = {};
  const pending = [root];
  let bytes = 0;
  while (pending.length) {
    const directory = pending.pop(), stat = await fs.lstat(directory);
    requireValue(stat.isDirectory() && (stat.mode & 0o444) && (stat.mode & 0o111), 'Scene directory must be regular and readable');
    for (const entry of await fs.readdir(directory, {withFileTypes: true})) {
      const file = path.join(entry.parentPath, entry.name);
      requireValue(!entry.isSymbolicLink(), 'Project scenes cannot contain symlinks');
      if (entry.isDirectory()) pending.push(file);
      else {
        requireValue(entry.isFile() && /\.tsx?$/.test(entry.name), 'Only declared TypeScript scene source is supported');
        const rev = await revision(file, 1024 * 1024); bytes += rev.size_bytes;
        requireValue(bytes <= 16 * 1024 * 1024, 'Project source closure exceeds bound');
        sources[path.relative(project, file).split(path.sep).join('/')] = rev.sha256;
      }
    }
  }
  requireValue(Object.hasOwn(sources, 'scenes/index.ts'), 'Project must declare scenes/index.ts');
  return sources;
}

function safeSceneProps(props) {
  const pending = [props];
  while (pending.length) {
    const value = pending.pop();
    if (typeof value === 'number') requireValue(!Number.isInteger(value) || Number.isSafeInteger(value),
      'Scene props contain an unsafe integer');
    else if (value !== null && typeof value === 'object') {
      for (const child of Object.values(value)) pending.push(child);
    }
  }
}


export function normalizeBoard(board, resolution) {
  requireValue(Object.hasOwn(resolutions, resolution), 'Unsupported resolution');
  const fields = ['title', 'description', 'version', 'project', 'video', 'style', 'audio', 'scenes', 'total_duration_seconds', 'video_research_plan'];
  requireValue(object(board) && Object.keys(board).every((key) => fields.includes(key)), 'Unsupported storyboard fields');
  requireValue(Array.isArray(board.scenes) && board.scenes.length > 0 && board.scenes.length <= 64, 'Requires 1 to 64 scenes');
  boardControls(board);
  const ids = new Set();
  let from = 0, total = [0n, 1n];
  const scenes = board.scenes.map((scene) => {
    const allowed = ['id', 'type', 'title', 'audio_file', 'audio_duration_seconds', 'scene_buffer_seconds', 'visual_padding_seconds', 'sfx_cues', 'props'];
    requireValue(object(scene) && Object.keys(scene).every((k) => allowed.includes(k)), 'Unsupported scene fields');
    requireValue(typeof scene.id === 'string' && scene.id.trim() && !ids.has(scene.id)
      && typeof scene.type === 'string' && scene.type.trim() && typeof scene.title === 'string', 'Invalid scene identity/type/title');
    ids.add(scene.id);
    const audio = scene.audio_duration_seconds, padding = scene.visual_padding_seconds === undefined ? 0 : scene.visual_padding_seconds;
    requireValue(typeof audio === 'number' && Number.isFinite(audio) && audio > 0 && audio <= 1800
      && typeof padding === 'number' && Number.isFinite(padding) && padding >= 0 && padding <= 1800, 'Invalid audio duration/padding');
    requireValue(scene.scene_buffer_seconds === undefined || scene.scene_buffer_seconds === 0, 'Scene buffer is unsupported');
    requireValue(scene.sfx_cues === undefined || (Array.isArray(scene.sfx_cues) && scene.sfx_cues.length === 0), 'SFX is unsupported');
    const audioSeconds = decimal(audio), paddingSeconds = decimal(padding), span = add(audioSeconds, paddingSeconds);
    total = add(total, span);
    const durationInFrames = frames(span);
    const normalized = {id: scene.id, type: scene.type, title: scene.title, from, durationInFrames,
      audio_src: scene.audio_file, audioDurationInFrames: frames(audioSeconds), visualPaddingInFrames: frames(paddingSeconds)};
    if (scene.props !== undefined) {
      requireValue(object(scene.props), 'Scene props must be an object');
      safeSceneProps(scene.props);
      normalized.props = scene.props;
    }
    from += durationInFrames;
    requireValue(Number.isSafeInteger(from) && from <= 1800 * 30 && total[0] <= 1800n * total[1], 'Total scene clock exceeds 1800 seconds');
    return normalized;
  });
  if (board.total_duration_seconds !== undefined) requireValue(typeof board.total_duration_seconds === 'number'
    && Number.isFinite(board.total_duration_seconds) && board.total_duration_seconds > 0 && board.total_duration_seconds <= 1800
    && decimal(board.total_duration_seconds)[0] * total[1] === total[0] * decimal(board.total_duration_seconds)[1],
  'Declared total duration disagrees with scene clock');
  const [width, height] = resolutions[resolution];
  return {width, height, fps: 30, durationInFrames: from, scenes};
}

function boardControls(board) {
  for (const key of ['title', 'description', 'version', 'project']) {
    requireValue(board[key] === undefined || typeof board[key] === 'string', `Storyboard ${key} must be a string`);
  }
  const video = board.video === undefined ? {} : board.video;
  requireValue(object(video) && Object.keys(video).every((k) => ['width', 'height', 'fps'].includes(k)), 'Unsupported video controls');
  requireValue(video.fps === undefined || (integerField(video, 'fps') && video.fps === 30), 'Unsupported video clock');
  if (video.width !== undefined || video.height !== undefined) requireValue(integerField(video, 'width') && integerField(video, 'height')
    && Object.values(resolutions).some(([w, h]) => video.width === w && video.height === h), 'Unsupported video dimensions');
  if (board.style !== undefined) requireValue(object(board.style) && Object.keys(board.style).length === 0, 'Unsupported global style controls');
  if (board.audio !== undefined) requireValue(object(board.audio) && Object.keys(board.audio).every((k) => ['background_music', 'music_volume'].includes(k))
    && (board.audio.background_music == null || board.audio.background_music === '') && (board.audio.music_volume === undefined
      || (typeof board.audio.music_volume === 'number' && Number.isFinite(board.audio.music_volume)
        && board.audio.music_volume >= 0 && board.audio.music_volume <= 1)), 'Music is unsupported');
  requireValue(board.video_research_plan === undefined || object(board.video_research_plan), 'Storyboard plan lineage must be an object');
}

function integerField(value, key) {
  const token = numberTokens.get(value)?.[key];
  return Number.isInteger(value[key]) && (token === undefined || !/[.eE]/.test(token));
}

function decimal(value) {
  const [mantissa, exponent = '0'] = String(value).toLowerCase().split('e');
  const [whole, fractional = ''] = mantissa.split('.');
  const scale = fractional.length - Number(exponent), numerator = BigInt(whole + fractional);
  return scale >= 0 ? [numerator, 10n ** BigInt(scale)] : [numerator * 10n ** BigInt(-scale), 1n];
}

const add = ([a, b], [c, d]) => [a * d + c * b, b * d];
const frames = ([a, b]) => Number((a * 30n + b - 1n) / b);


export async function productionProject(project, resolution, projectSha, outputRelative) {
  requireValue(path.isAbsolute(project) && (await fs.lstat(project)).isDirectory()
    && await fs.realpath(project) === project, 'Absolute regular project required');
  requireValue(outputRelative === `output/final-${resolution}.mp4`, 'Unsupported output route');
  await fs.lstat(path.join(project, 'output')).then((stat) => {
    requireValue(stat.isDirectory(), 'Output must be a regular directory');
  }, (error) => {if (error.code !== 'ENOENT') throw error;});
  const inputs = {}, bodies = {};
  let jsonBytes = 0;
  for (const name of ['config.json', 'storyboard/storyboard.json']) {
    const body = await regular(await confined(project, name), 1024 * 1024);
    jsonBytes += body.length;
    requireValue(jsonBytes <= 1024 * 1024, 'Project JSON exceeds 1 MiB total');
    inputs[name] = sha(body); bodies[name] = parseObject(body);
  }
  const routes = bodies['config.json'].paths === undefined ? {} : bodies['config.json'].paths;
  requireValue(object(routes) && (routes.storyboard === undefined ? 'storyboard/storyboard.json' : routes.storyboard) === 'storyboard/storyboard.json', 'Unsupported storyboard route');
  requireValue(routes.final_video === undefined || routes.final_video === outputRelative, 'Configured final_video differs from selected output');
  const inputProps = normalizeBoard(bodies['storyboard/storyboard.json'], resolution);
  Object.assign(inputs, await sceneSources(project));
  for (const scene of inputProps.scenes) {
    requireValue(typeof scene.audio_src === 'string' && /\.(wav|mp3|m4a|aac|ogg|flac|opus)$/i.test(scene.audio_src), 'Unsupported local audio extension');
    const file = await confined(project, scene.audio_src);
    const rev = await revision(file, 64 * 1024 * 1024);
    requireValue(rev.size_bytes > 0, 'Selected audio asset cannot be empty'); inputs[scene.audio_src] = rev.sha256;
  }
  requireValue(same(inputs, projectSha), 'Current project source/audio differs from exact project SHA256 projection');
  return {inputProps, inputs, board: bodies['storyboard/storyboard.json'], output: path.join(project, outputRelative)};
}


export function audioExtent(probe, declared) {
  requireValue(object(probe) && Array.isArray(probe.streams) && probe.streams.length === 1
    && probe.streams[0].codec_type === 'audio', 'Audio requires exactly one audio stream');
  const raw = probe.streams[0].duration;
  const duration = typeof raw === 'string' && raw.trim() ? Number(raw) : NaN;
  requireValue(Number.isFinite(duration) && duration > 0 && Math.abs(duration - declared) <= 1 / 30
    && Math.abs(duration - frames(decimal(declared)) / 30) <= 1 / 30, 'Observed audio extent differs by more than one frame');
  requireValue(probe.streams[0].start_time === undefined || Math.abs(Number(probe.streams[0].start_time)) <= 1 / 30,
    'Audio must begin at the local zero clock');
  return duration;
}


export async function probeAudio(project, board, spec) {
  const observed = new Map();
  for (const scene of board.scenes) {
    if (observed.has(scene.audio_file)) {
      audioExtent({streams: [{codec_type: 'audio', duration: String(observed.get(scene.audio_file).duration_seconds)}]},
        scene.audio_duration_seconds);
      continue;
    }
    const file = await confined(project, scene.audio_file);
    const args = ['-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_entries',
      'stream=codec_type,duration,start_time', '-of', 'json', file];
    const stdout = await new Promise((resolve, reject) => {
      childProcess.execFile(spec.ffprobe.path, args, {timeout: 10000, maxBuffer: 16384, encoding: 'utf8'}, (error, out, err) => {
        if (error || err) reject(error ?? new Error('Audio probe emitted errors')); else resolve(out);
      });
    });
    observed.set(scene.audio_file, {path: scene.audio_file,
      duration_seconds: audioExtent(parseObject(Buffer.from(stdout)), scene.audio_duration_seconds)});
  }
  requireValue((await revision(spec.ffprobe.path)).sha256 === spec.ffprobe.sha256, 'ffprobe changed during audio preflight');
  return [...observed.values()];
}
