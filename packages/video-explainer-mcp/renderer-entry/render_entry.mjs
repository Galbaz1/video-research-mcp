// Independently authored entry for the bounded single-card research fixture.
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {performance} from 'node:perf_hooks';

const entryDir = path.dirname(fileURLToPath(import.meta.url));
const files = ['package.json', 'src/index.ts', 'src/Root.tsx', 'src/Fixture.tsx',
  'render_entry.mjs', 'package-lock.json'];
const packages = {'remotion': '4.0.532', '@remotion/renderer': '4.0.532',
  '@remotion/bundler': '4.0.532', '@remotion/compositor-darwin-arm64': '4.0.532',
  'react': '19.0.0', 'react-dom': '19.0.0'};
const expectedComposition = {id: 'Fixture', fps: 30, width: 1280, height: 720, durationInFrames: 30};
const fixtureFiles = ['config.json', 'storyboard/storyboard.json', 'assets/fixture.wav'];
const chromiumOptions = {disableWebSecurity: false, ignoreCertificateErrors: false};
const sha = (body) => createHash('sha256').update(body).digest('hex');
const canonical = (value) => JSON.stringify(value, Object.keys(value).sort());
let ownedBrowser;
let closingBrowser;
let cancelRender = () => {};

function custody(state, token, pid) {
  const file = process.env.VRM_RENDER_CUSTODY_FILE;
  requireValue(path.isAbsolute(file ?? '') && fsSync.lstatSync(file).isFile(), 'Private custody file required');
  const record = {schema: 'vrm-browser-custody/r1', execution_token: token, state};
  if (pid) Object.assign(record, {browser_pid: pid, browser_pgid: pid});
  const fd = fsSync.openSync(file, 'a');
  try { fsSync.writeSync(fd, JSON.stringify(record) + '\n'); fsSync.fsyncSync(fd); }
  finally { fsSync.closeSync(fd); }
}

async function openOwnedBrowser(openBrowser, spec, token) {
  const spawn = childProcess.spawn;
  let captured = false;
  childProcess.spawn = function(executable, args, options) {
    if (executable !== spec.browser.path) return spawn.call(this, executable, args, options);
    requireValue(!captured && options?.detached === true, 'Expected one detached frozen browser');
    captured = true;
    custody('launching', token);
    const proc = spawn.call(this, executable, args, options);
    requireValue(Number.isSafeInteger(proc.pid) && proc.pid > 1, 'Browser PID unavailable; custody unknown');
    custody('registered', token, proc.pid);
    return proc;
  };
  try {
    syncBuiltinESMExports();
    ownedBrowser = await openBrowser('chrome', {browserExecutable: spec.browser.path, chromiumOptions, logLevel: 'info'});
    requireValue(captured, 'Frozen browser spawn was not captured');
    return ownedBrowser;
  } finally {
    childProcess.spawn = spawn;
    syncBuiltinESMExports();
  }
}

async function closeOwnedBrowser() {
  if (!ownedBrowser) return;
  closingBrowser ??= ownedBrowser.close({silent: true});
  let timer;
  try {
    await Promise.race([closingBrowser, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('Browser close exceeded 1 second; Python must sweep custody')), 1000);
    })]);
  } finally { clearTimeout(timer); }
}

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}

function sameKeys(value, keys) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join('\0') === [...keys].sort().join('\0');
}

async function regular(file, limit) {
  const before = await fs.lstat(file);
  requireValue(before.isFile() && before.size <= limit, `Not a bounded regular file: ${file}`);
  const body = await fs.readFile(file);
  const after = await fs.lstat(file);
  requireValue(before.size === after.size && before.mtimeMs === after.mtimeMs
    && before.ctimeMs === after.ctimeMs && body.length <= limit, `File changed: ${file}`);
  return body;
}

async function revision(file) {
  const body = await regular(file, 512 * 1024 * 1024);
  return {sha256: sha(body), size_bytes: body.length};
}

async function treeRevision(directory) {
  const result = {};
  let count = 0;
  const walk = async (current) => {
    const entries = await fs.readdir(current, {withFileTypes: true});
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name, 'en'))) {
      const file = path.join(current, entry.name);
      const name = path.relative(directory, file).split(path.sep).join('/');
      requireValue(count < 50000, 'Runtime exceeds 50000 files');
      if (entry.isSymbolicLink()) {
        const target = await fs.realpath(file);
        requireValue(target.startsWith(directory + path.sep), 'Runtime symlink escapes frozen tree');
        result[name] = {symlink: await fs.readlink(file)};
        count++;
      } else if (entry.isDirectory()) {
        await walk(file);
      } else {
        result[name] = await revision(file);
        count++;
      }
    }
  };
  requireValue((await fs.lstat(directory)).isDirectory(), 'Runtime tree must be a directory');
  await walk(directory);
  const ordered = Object.fromEntries(Object.keys(result).sort().map((name) => [name, result[name]]));
  return sha(JSON.stringify(ordered));
}

async function frozen(specFile, specSha) {
  requireValue(path.isAbsolute(specFile) && /^[0-9a-f]{64}$/.test(specSha), 'Absolute spec and external SHA required');
  const body = await regular(specFile, 1024 * 1024);
  requireValue(sha(body) === specSha, 'Root spec hash changed');
  const spec = JSON.parse(body);
  requireValue(spec.schema === 'vrm-authored-renderer/r1'
    && canonical(spec.composition) === canonical(expectedComposition), 'Unsupported freeze/composition');
  requireValue(sameKeys(spec.entry_sha256, files), 'Freeze must bind all six authored files');
  for (const name of files) {
    requireValue(sha(await regular(path.join(entryDir, name), 1024 * 1024)) === spec.entry_sha256[name],
      `Authored source changed: ${name}`);
  }
  requireValue(canonical(spec.package_versions) === canonical(packages), 'Unsupported package versions');
  for (const [name, version] of Object.entries(packages)) {
    const installed = JSON.parse(await regular(path.join(entryDir, 'node_modules', name, 'package.json'), 1024 * 1024));
    requireValue(installed.name === name && installed.version === version, `Package changed: ${name}`);
  }
  requireValue(await treeRevision(path.join(entryDir, 'node_modules')) === spec.node_modules_sha256,
    'Installed runtime bytes changed');
  for (const name of ['node', 'browser']) {
    const binary = spec[name];
    requireValue(path.isAbsolute(binary.path), 'Executable path must be absolute');
    await fs.access(binary.path, fs.constants.X_OK);
    requireValue((await revision(binary.path)).sha256 === binary.sha256, `Executable changed: ${name}`);
  }
  const browserDir = spec.browser.directory;
  requireValue(path.isAbsolute(browserDir) && spec.browser.path.startsWith(browserDir + path.sep),
    'Browser resources require an absolute containing directory');
  requireValue(await treeRevision(browserDir) === spec.browser.tree_sha256, 'Browser resources changed');
  requireValue(await fs.realpath(process.execPath) === await fs.realpath(spec.node.path), 'Wrong Node executable');
  requireValue(sameKeys(spec.fixture_sha256, fixtureFiles), 'Freeze must bind three fixture inputs');
  return spec;
}

async function fixture(project, resolution, spec, outputRelative) {
  requireValue(path.isAbsolute(project) && resolution === '720p', 'Only absolute project and 720p supported');
  requireValue(outputRelative === 'output/final-720p.mp4', 'Unsupported output route');
  requireValue((await fs.lstat(project)).isDirectory(), 'Project must be a regular directory');
  for (const name of ['assets', 'storyboard', 'output']) {
    requireValue((await fs.lstat(path.join(project, name))).isDirectory(), 'Project directory must not be a symlink');
  }
  for (const name of fixtureFiles) {
    requireValue(sha(await regular(path.join(project, name), 1024 * 1024)) === spec.fixture_sha256[name],
      `Frozen fixture changed: ${name}`);
  }
  const config = JSON.parse(await regular(path.join(project, 'config.json'), 1024 * 1024));
  const paths = config.paths ?? {};
  requireValue(paths && typeof paths === 'object' && !Array.isArray(paths)
    && (paths.storyboard ?? 'storyboard/storyboard.json') === 'storyboard/storyboard.json', 'Unsupported storyboard route');
  const board = JSON.parse(await regular(path.join(project, 'storyboard/storyboard.json'), 1024 * 1024));
  requireValue(sameKeys(board, ['scenes']) && Array.isArray(board.scenes) && board.scenes.length === 1,
    'Unsupported storyboard: exactly one scene required');
  const scene = board.scenes[0];
  requireValue(sameKeys(scene, ['id', 'title', 'audio_duration_seconds', 'scene_buffer_seconds',
    'visual_padding_seconds', 'audio_file', 'card_color']), 'Unsupported storyboard fields');
  requireValue(scene.id === 'fixture' && typeof scene.title === 'string'
    && scene.audio_duration_seconds === 1 && scene.scene_buffer_seconds === 0
    && scene.visual_padding_seconds === 0 && scene.audio_file === 'fixture.wav'
    && typeof scene.card_color === 'string' && /^#[0-9a-fA-F]{6}$/.test(scene.card_color), 'Unsupported fixture properties');
  const wav = await regular(path.join(project, 'assets/fixture.wav'), 96044);
  requireValue(wav.length === 96044 && wav.toString('ascii', 0, 4) === 'RIFF'
    && wav.readUInt32LE(4) === 96036 && wav.toString('ascii', 8, 16) === 'WAVEfmt '
    && wav.readUInt32LE(16) === 16 && wav.readUInt16LE(20) === 1 && wav.readUInt16LE(22) === 1
    && wav.readUInt32LE(24) === 48000 && wav.readUInt32LE(28) === 96000 && wav.readUInt16LE(32) === 2
    && wav.readUInt16LE(34) === 16 && wav.toString('ascii', 36, 40) === 'data'
    && wav.readUInt32LE(40) === 96000, 'Canonical 48kHz mono PCM16 one-second WAV required');
  const assets = await fs.readdir(path.join(project, 'assets'));
  requireValue(assets.length === 1 && assets[0] === 'fixture.wav', 'Unsupported extra fixture assets');
  const output = path.join(project, outputRelative);
  for (const file of [output, output + '.receipt.json']) {
    await fs.lstat(file).then(() => {throw new Error('Fresh output required');}, (err) => {
      if (err.code !== 'ENOENT') throw err;
    });
  }
  return {output, inputProps: {color: scene.card_color, audio_file: 'fixture.wav', audio_duration_seconds: 1}};
}

async function render(project, spec, inputProps, output, token) {
  // Runtime imports occur only after every root-frozen source/input/runtime check.
  const {bundle} = await import('@remotion/bundler');
  const {openBrowser, selectComposition, renderMedia, makeCancelSignal} = await import('@remotion/renderer');
  const serveUrl = await bundle({entryPoint: path.join(entryDir, 'src/index.ts'), rootDir: entryDir,
    publicDir: path.join(project, 'assets'), enableCaching: false});
  try {
    const browser = {puppeteerInstance: await openOwnedBrowser(openBrowser, spec, token),
      browserExecutable: spec.browser.path, chromiumOptions, timeoutInMilliseconds: 30000,
      onBrowserDownload: () => {throw new Error('Browser downloads are forbidden');}};
    const composition = await selectComposition({serveUrl, id: 'Fixture', inputProps, ...browser});
    for (const [key, value] of Object.entries(expectedComposition)) {
      requireValue(composition[key] === value, `Composition mismatch: ${key}`);
    }
    const {cancelSignal, cancel} = makeCancelSignal();
    const timer = setTimeout(cancel, 120000);
    cancelRender = cancel;
    try {
      await renderMedia({composition, serveUrl, inputProps, outputLocation: output, ...browser,
        codec: 'h264', audioCodec: 'aac', pixelFormat: 'yuv420p', colorSpace: 'bt709', concurrency: 1, muted: false,
        enforceAudioTrack: true, disallowParallelEncoding: true, overwrite: false,
        logLevel: 'info', cancelSignal});
    } finally {
      clearTimeout(timer);
      cancelRender = () => {};
    }
    return await treeRevision(serveUrl);
  } finally {
    try { await closeOwnedBrowser(); }
    finally { await fs.rm(serveUrl, {recursive: true, force: true}); }
  }
}

async function main() {
  requireValue(process.argv.length === 8, 'Expected project resolution spec spec-sha output execution-token');
  const [project, resolution, specFile, specSha, outputRelative, token] = process.argv.slice(2);
  requireValue(/^[0-9a-f]{32}$/.test(token), 'Execution token must be a persisted request identity');
  const started = performance.now();
  const spec = await frozen(specFile, specSha);
  const {output, inputProps} = await fixture(project, resolution, spec, outputRelative);
  const bundleSha = await render(project, spec, inputProps, output, token);
  const outputRevision = await revision(output);
  requireValue(outputRevision.size_bytes > 0 && outputRevision.size_bytes <= 16 * 1024 * 1024,
    'Output must be nonempty and at most 16 MiB');
  await frozen(specFile, specSha);
  const receipt = {schema: 'vrm-authored-render-receipt/r1', execution_token: token,
    capability: 'bounded solid-card fixture only; production storyboards unsupported',
    spec_sha256: specSha, fixture_sha256: spec.fixture_sha256, composition: expectedComposition,
    bundle_sha256: bundleSha, output: {path: output, ...outputRevision},
    node_version: process.version, package_versions: packages, browser_sha256: spec.browser.sha256,
    options: {codec: 'h264', audioCodec: 'aac', pixelFormat: 'yuv420p', colorSpace: 'bt709', concurrency: 1,
      enforceAudioTrack: true, disallowParallelEncoding: true, overwrite: false, chromiumOptions},
    started_monotonic_ms: started, ended_monotonic_ms: performance.now(), playback_verified: false};
  await fs.writeFile(output + '.receipt.json', JSON.stringify(receipt, null, 2) + '\n', {flag: 'wx'});
  console.log(JSON.stringify({output: receipt.output, spec_sha256: specSha, execution_token: token}));
}

const deadline = setTimeout(() => {
  console.error('Authored entry exceeded its 180-second hard deadline');
  process.exit(3);
}, 180000);
const closingDeadline = setTimeout(() => {
  cancelRender();
  closeOwnedBrowser().catch((error) => console.error(String(error))).finally(() => process.exit(3));
}, 179000);
process.on('SIGTERM', () => {
  cancelRender();
  closeOwnedBrowser().catch((error) => console.error(String(error))).finally(() => process.exit(3));
});
try {
  await main();
} catch (error) {
  console.error(String(error));
  process.exitCode = 3;
} finally {
  clearTimeout(deadline);
  clearTimeout(closingDeadline);
}
