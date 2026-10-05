// Independently authored production route; the fixed fixture remains separate.
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {performance} from 'node:perf_hooks';
import {parseObject, regular, revision, confined, productionProject, probeAudio} from './production_project.mjs';

const entryDir = path.dirname(fileURLToPath(import.meta.url));
const sourceFiles = ['production_entry.mjs', 'production_project.mjs', 'src/production-index.ts', 'src/ProductionRoot.tsx',
  'src/Production.tsx', 'src/production-types.ts', 'package.json', 'package-lock.json'];
const packages = {remotion: '4.0.532', '@remotion/renderer': '4.0.532', '@remotion/bundler': '4.0.532',
  '@remotion/compositor-darwin-arm64': '4.0.532', react: '19.0.0', 'react-dom': '19.0.0'};
const chromiumOptions = {disableWebSecurity: false, ignoreCertificateErrors: false};
const sha = (body) => createHash('sha256').update(body).digest('hex');
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const sameKeys = (value, keys) => object(value) && Object.keys(value).sort().join('\0') === [...keys].sort().join('\0');
const same = (a, b) => object(a) && object(b) && sameKeys(a, Object.keys(b))
  && Object.keys(b).every((key) => a[key] === b[key]);
let ownedBrowser, closingBrowser;
let cancelRender = () => {};

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}

async function treeRevision(directory) {
  requireValue((await fs.lstat(directory)).isDirectory(), 'Runtime tree must be a regular directory');
  const files = {};
  let count = 0;
  const pending = [directory];
  while (pending.length) {
    for (const entry of await fs.readdir(pending.pop(), {withFileTypes: true})) {
      requireValue(count < 50000, 'Runtime exceeds 50000 files');
      const file = path.join(entry.parentPath, entry.name);
      const name = path.relative(directory, file).split(path.sep).join('/');
      if (entry.isSymbolicLink()) {
        requireValue((await fs.realpath(file)).startsWith(directory + path.sep), 'Runtime symlink escapes frozen tree');
        files[name] = {symlink: await fs.readlink(file)}; count++;
      } else if (entry.isDirectory()) pending.push(file);
      else { requireValue(entry.isFile(), 'Nonregular runtime entry'); files[name] = await revision(file); count++; }
    }
  }
  const ordered = Object.fromEntries(Object.keys(files).sort().map((name) => [name, files[name]]));
  return sha(JSON.stringify(ordered));
}

export async function executable(binary) {
  requireValue(object(binary) && path.isAbsolute(binary.path) && /^[0-9a-f]{64}$/.test(binary.sha256),
    'Absolute externally frozen executable required');
  await fs.access(binary.path, fsSync.constants.X_OK);
  const observed = await revision(binary.path);
  requireValue(observed.sha256 === binary.sha256, `Executable changed: ${binary.path}`);
  return {path: binary.path, ...observed};
}

async function frozen(specFile, specSha) {
  requireValue(path.isAbsolute(specFile) && /^[0-9a-f]{64}$/.test(specSha), 'Absolute spec and external SHA required');
  const body = await regular(specFile, 1024 * 1024);
  requireValue(sha(body) === specSha, 'Root spec hash changed');
  const spec = parseObject(body);
  requireValue(spec.schema === 'vrm-authored-storyboard/r1', 'Unsupported production spec');
  requireValue(sameKeys(spec.entry_sha256, sourceFiles), 'Freeze must bind production source and existing package files');
  for (const name of sourceFiles) requireValue(sha(await regular(path.join(entryDir, name), 1024 * 1024))
    === spec.entry_sha256[name], `Authored source changed: ${name}`);
  requireValue(same(spec.package_versions, packages), 'Unsupported package versions');
  for (const [name, version] of Object.entries(packages)) {
    const installed = parseObject(await regular(path.join(entryDir, 'node_modules', name, 'package.json'), 1024 * 1024));
    requireValue(installed.name === name && installed.version === version, `Package changed: ${name}`);
  }
  requireValue(await treeRevision(path.join(entryDir, 'node_modules')) === spec.node_modules_sha256, 'Installed runtime bytes changed');
  for (const name of ['node', 'browser', 'ffprobe']) {
    const observed = await executable(spec[name]);
    if (name === 'ffprobe') spec.ffprobe = observed;
  }
  requireValue(await fs.realpath(process.execPath) === await fs.realpath(spec.node.path), 'Wrong Node executable');
  requireValue(path.isAbsolute(spec.browser.directory) && spec.browser.path.startsWith(spec.browser.directory + path.sep),
    'Browser resources require an absolute containing directory');
  requireValue(await treeRevision(spec.browser.directory) === spec.browser.tree_sha256, 'Browser resources changed');
  requireValue(object(spec.project_sha256), 'Exact project SHA256 projection required');
  return spec;
}

function custody(file, state, token, pid) {
  const record = {schema: 'vrm-browser-custody/r1', execution_token: token, state};
  if (pid) Object.assign(record, {browser_pid: pid, browser_pgid: pid});
  const fd = fsSync.openSync(file, fsSync.constants.O_WRONLY | fsSync.constants.O_APPEND | fsSync.constants.O_NOFOLLOW);
  try {
    requireValue(fsSync.fstatSync(fd).isFile(), 'Private regular custody file required');
    fsSync.writeSync(fd, JSON.stringify(record) + '\n'); fsSync.fsyncSync(fd);
  } finally { fsSync.closeSync(fd); }
}

async function openOwnedBrowser(openBrowser, spec, token, custodyFile) {
  const spawn = childProcess.spawn;
  let captured = false;
  childProcess.spawn = function(executable, args, options) {
    if (executable !== spec.browser.path) return spawn.call(this, executable, args, options);
    requireValue(!captured && options?.detached === true, 'Expected one detached frozen browser');
    captured = true; custody(custodyFile, 'launching', token);
    const proc = spawn.call(this, executable, args, options);
    requireValue(Number.isSafeInteger(proc.pid) && proc.pid > 1, 'Browser PID unavailable; custody unknown');
    custody(custodyFile, 'registered', token, proc.pid);
    return proc;
  };
  try {
    syncBuiltinESMExports();
    ownedBrowser = await openBrowser('chrome', {browserExecutable: spec.browser.path, chromiumOptions, logLevel: 'info'});
    requireValue(captured, 'Frozen browser spawn was not captured');
    return ownedBrowser;
  } finally { childProcess.spawn = spawn; syncBuiltinESMExports(); }
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

export async function cleanup(primary, actions) {
  const failures = [];
  for (const [stage, action] of actions) {
    try { await action(); } catch (error) { failures.push({stage, error}); }
  }
  if (!failures.length) return;
  const inherited = primary instanceof AggregateError && Array.isArray(primary.cleanup_failures);
  const original = inherited ? primary.cause : primary;
  const combined = [...(inherited ? primary.cleanup_failures : []), ...failures];
  const errors = [...(original === undefined ? [] : [original]), ...combined.map(({error}) => error)];
  const message = [original === undefined ? 'Cleanup failed' : `Primary failure: ${String(original)}`,
    ...combined.map(({stage, error}) => `${stage}: ${String(error)}`)].join('; ');
  const error = new AggregateError(errors, message, {cause: original});
  error.cleanup_failures = combined;
  throw error;
}

export function webpackOverride(project, inputs) {
  const admitted = new Set(sourceFiles.map((name) => path.join(entryDir, name)));
  const modules = path.join(entryDir, 'node_modules');
  const plugin = {apply(compiler) {
    compiler.hooks.normalModuleFactory.tap('ProductionClosure', (factory) => {
      factory.hooks.afterResolve.tapPromise('ProductionClosure', async (data) => {
        const resource = data.createData.resource?.split('?')[0];
        requireValue(data.createData.loaders.every(({loader}) => loader.startsWith(modules + path.sep)), 'Unfrozen module loader');
        requireValue(resource, 'Unresolved scene module is unsupported');
        if (resource.startsWith(modules + path.sep) || admitted.has(resource)) return;
        const name = path.relative(project, resource).split(path.sep).join('/');
        requireValue(name.startsWith('scenes/') && Object.hasOwn(inputs, name)
          && sha(await regular(await confined(project, name), 1024 * 1024)) === inputs[name], `Undeclared scene module: ${resource}`);
      });
    });
  }};
  return (config) => ({...config, resolve: {...config.resolve, modules: [modules],
    alias: {...config.resolve?.alias, '@project-scenes$': path.join(project, 'scenes/index.ts')}},
  plugins: [...(config.plugins ?? []), plugin]});
}

export function localAudioDownload(src, scenes) {
  const url = new URL(src);
  const name = decodeURIComponent(url.pathname);
  requireValue(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
    && !url.username && !url.password && !url.search && !url.hash
    && scenes.some((scene) => name === '/public/' + scene.audio_src), 'Only admitted local audio may be transferred');
}

async function render(project, spec, state, staging, token, custodyFile, encoding) {
  const publicDir = path.join(staging, 'public');
  await fs.mkdir(publicDir);
  for (const name of new Set(state.inputProps.scenes.map((scene) => scene.audio_src))) {
    const target = path.join(publicDir, name); await fs.mkdir(path.dirname(target), {recursive: true});
    await fs.writeFile(target, await regular(await confined(project, name), 64 * 1024 * 1024), {flag: 'wx'});
    requireValue((await revision(target)).sha256 === state.inputs[name], 'Audio changed before staging');
  }
  // No SDK import or TSX evaluation precedes the source/runtime/audio preflight.
  const {bundle} = await import('@remotion/bundler');
  const {openBrowser, selectComposition, renderMedia, makeCancelSignal} = await import('@remotion/renderer');
  let serveUrl, primary;
  try {
    serveUrl = await bundle({entryPoint: path.join(entryDir, 'src/production-index.ts'), rootDir: entryDir,
      publicDir, enableCaching: false, webpackOverride: webpackOverride(project, state.inputs),
      onSymlinkDetected: () => {throw new Error('Public symlinks are forbidden');}});
    const html = path.join(serveUrl, 'index.html');
    const body = (await regular(html, 1024 * 1024)).toString('utf8');
    requireValue(body.includes('<head>'), 'Bundle HTML head is unavailable');
    const csp = "default-src 'self' data: blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-src 'none'";
    await fs.writeFile(html, body.replace('<head>', `<head><meta http-equiv="Content-Security-Policy" content="${csp}">`));
    const browser = {puppeteerInstance: await openOwnedBrowser(openBrowser, spec, token, custodyFile),
      browserExecutable: spec.browser.path, chromiumOptions, timeoutInMilliseconds: 30000,
      onBrowserDownload: () => {throw new Error('Browser downloads are forbidden');}};
    const composition = await selectComposition({serveUrl, id: 'Production', inputProps: state.inputProps, ...browser});
    const actual = Object.fromEntries(['id', 'width', 'height', 'fps', 'durationInFrames'].map((key) => [key, composition[key]]));
    const expected = {id: 'Production', ...Object.fromEntries(['width', 'height', 'fps', 'durationInFrames'].map((key) => [key, state.inputProps[key]]))};
    requireValue(same(actual, expected), 'Actual production composition differs from admitted clock');
    const {cancelSignal, cancel} = makeCancelSignal(); cancelRender = cancel;
    const timer = setTimeout(cancel, 120000);
    try {
      await renderMedia({composition, serveUrl, inputProps: state.inputProps, outputLocation: path.join(staging, 'final.mp4'), ...browser,
        codec: 'h264', audioCodec: 'aac', sampleRate: 48000, pixelFormat: 'yuv420p', colorSpace: 'bt709', concurrency: 1, muted: false, ...encoding,
        enforceAudioTrack: true, disallowParallelEncoding: true, overwrite: false, logLevel: 'info', cancelSignal,
        onDownload: (src) => localAudioDownload(src, state.inputProps.scenes)});
    } finally { clearTimeout(timer); cancelRender = () => {}; }
    return {composition: actual, bundle_sha256: await treeRevision(serveUrl)};
  } catch (error) { primary = error; throw error; }
  finally {
    await cleanup(primary, [['browser_close', closeOwnedBrowser],
      ['bundle_remove', () => serveUrl ? fs.rm(serveUrl, {recursive: true, force: true}) : undefined]]);
  }
}

export function parseArguments(argv) {
  const keys = ['project', 'resolution', 'spec', 'spec-sha256', 'output-relative', 'execution-token'];
  requireValue(argv.at(-2) === '--execution-token', 'Execution token value must remain last');
  const values = {fast: false};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--fast') {requireValue(!values.fast, 'Duplicate --fast'); values.fast = true; continue;}
    const key = argv[i].slice(2);
    requireValue(argv[i].startsWith('--') && keys.includes(key) && !Object.hasOwn(values, key), 'Unknown or duplicate argument');
    requireValue(i + 1 < argv.length && !argv[i + 1].startsWith('--'), 'Missing argument value');
    values[key] = argv[++i];
  }
  requireValue(keys.every((key) => Object.hasOwn(values, key)), 'Expected Root production argv');
  requireValue(/^[0-9a-f]{32}$/.test(values['execution-token']), 'Execution token must be a persisted request identity');
  return values;
}
async function fresh(file) {
  await fs.lstat(file).then(() => {throw new Error(`Fresh output required: ${file}`);}, (error) => {
    if (error.code !== 'ENOENT') throw error;
  });
}

async function main() {
  const args = parseArguments(process.argv.slice(2)), started = performance.now();
  const spec = await frozen(args.spec, args['spec-sha256']);
  const state = await productionProject(args.project, args.resolution, spec.project_sha256, args['output-relative']);
  await fresh(state.output); await fresh(state.output + '.receipt.json');
  const custodyFile = process.env.VRM_RENDER_CUSTODY_FILE;
  requireValue(path.isAbsolute(custodyFile ?? '') && (await fs.lstat(custodyFile)).isFile()
    && await fs.realpath(custodyFile) === custodyFile, 'Current runner-created regular custody file required');
  const observed = await probeAudio(args.project, state.board, spec);
  await productionProject(args.project, args.resolution, spec.project_sha256, args['output-relative']);
  await fs.mkdir(path.join(args.project, 'output'), {recursive: true});
  const staging = await fs.mkdtemp(path.join(args.project, 'output', `.production-${args['execution-token']}-`));
  let primary, receipt;
  try {
    const encoding = args.fast ? {crf: 28, x264Preset: 'veryfast'} : {crf: 18, x264Preset: 'medium'};
    const rendered = await render(args.project, spec, state, staging, args['execution-token'], custodyFile, encoding);
    const outputRevision = await revision(path.join(staging, 'final.mp4'), 512 * 1024 * 1024);
    requireValue(outputRevision.size_bytes > 0, 'Output must be nonempty');
    await frozen(args.spec, args['spec-sha256']);
    await productionProject(args.project, args.resolution, spec.project_sha256, args['output-relative']);
    receipt = {schema: 'vrm-authored-storyboard-receipt/r1', execution_token: args['execution-token'],
      spec_sha256: args['spec-sha256'], project_sha256: state.inputs, entry_sha256: spec.entry_sha256,
      input_props: state.inputProps, audio_observations: observed, ...rendered,
      output: {path: state.output, ...outputRevision}, node_version: process.version, package_versions: packages,
      node_modules_sha256: spec.node_modules_sha256, browser_sha256: spec.browser.sha256, ffprobe: spec.ffprobe,
      fast_requested: args.fast, fast_applied: args.fast, quality: encoding,
      options: {...encoding, codec: 'h264', audioCodec: 'aac', sampleRate: 48000, pixelFormat: 'yuv420p', colorSpace: 'bt709', concurrency: 1,
        enforceAudioTrack: true, disallowParallelEncoding: true, overwrite: false, chromiumOptions},
      started_monotonic_ms: started, ended_monotonic_ms: performance.now(), playback_verified: false};
    const receiptFile = path.join(staging, 'receipt.json');
    await fs.writeFile(receiptFile, JSON.stringify(receipt, null, 2) + '\n', {flag: 'wx'});
    await fs.link(path.join(staging, 'final.mp4'), state.output);
    await fs.link(receiptFile, state.output + '.receipt.json');
  } catch (error) { primary = error; throw error; }
  finally { await cleanup(primary, [['staging_remove', () => fs.rm(staging, {recursive: true, force: true})]]); }
  console.log(JSON.stringify({output: receipt.output, spec_sha256: receipt.spec_sha256, execution_token: receipt.execution_token}));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const deadline = setTimeout(() => {console.error('Production entry exceeded its 180-second hard deadline'); process.exit(3);}, 180000);
  const stop = () => {cancelRender(); closeOwnedBrowser().catch((error) => console.error(String(error))).finally(() => process.exit(3));};
  const closingDeadline = setTimeout(stop, 179000);
  process.on('SIGTERM', stop);
  try { await main(); } catch (error) {console.error(String(error)); process.exitCode = 3;}
  finally { clearTimeout(deadline); clearTimeout(closingDeadline); process.off('SIGTERM', stop); }
}
