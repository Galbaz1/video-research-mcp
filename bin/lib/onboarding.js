'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { hashFile, MANIFEST_FILE } = require('./manifest');
const { atomicWrite, assertRegularDestination, getConfigPath, entryHash, MCP_SERVERS } = require('./config');
const VERSION = require('../../package.json').version;
const CHECKPOINT_DIR = 'gr-install-backups';
const ID = /^[a-f0-9-]{36}$/;

/** Map owned slots to the selected installation, never caller-supplied absolute paths. */
function slotPath(mode, target, slot) {
  const home = process.env.HOME || process.env.USERPROFILE;
  const fixed = { '@config': getConfigPath(mode), '@manifest': path.join(target, MANIFEST_FILE),
    '@env': path.join(home, '.config/video-research-mcp/.env') };
  if (fixed[slot]) { guard(fixed[slot], slot === '@env' ? home : path.dirname(fixed[slot])); return fixed[slot]; }
  if (!/^(commands|skills|agents)\//.test(slot) || slot.includes('\\') ||
      slot.split('/').some((part) => !part || part === '.' || part === '..')) {
    throw new Error('Invalid checkpoint ownership path');
  }
  const result = path.join(target, slot);
  guard(result, target);
  return result;
}

/** Refuse symlink ancestors within the installation's trusted home/project fence. */
function guard(filePath, anchor) {
  let current = path.resolve(anchor);
  const relative = path.relative(current, path.resolve(filePath));
  if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Installer path escapes fence');
  for (const component of ['', ...relative.split(path.sep)]) {
    current = path.join(current, component);
    try { if (fs.lstatSync(current).isSymbolicLink()) throw new Error('Symlinked installer destination'); }
    catch (err) { if (err.code === 'ENOENT') break; throw err; }
  }
}

/** Capture exact private bytes and mode; receipts expose hashes rather than content. */
function capture(filePath) {
  assertRegularDestination(filePath);
  try {
    if (fs.statSync(filePath).size > 16 * 1024 * 1024) throw new Error('Installer snapshot exceeds 16 MiB');
    const bytes = fs.readFileSync(filePath);
    if (bytes.length > 16 * 1024 * 1024) throw new Error('Installer snapshot exceeds 16 MiB');
    return { bytes: bytes.toString('base64'), hash: crypto.createHash('sha256').update(bytes).digest('hex'), mode: fs.statSync(filePath).mode & 0o777 };
  } catch (err) { if (err.code === 'ENOENT') return { bytes: null, hash: null, mode: 0o600 }; throw err; }
}

/** Validate and read an exact checkpoint; contents never become diagnostic text. */
function checkpoint(mode, target, id) {
  if (!ID.test(id || '')) throw new Error('Invalid checkpoint identifier');
  const file = path.join(target, CHECKPOINT_DIR, `${id}.json`);
  guard(file, target);
  if (fs.statSync(file).size > 32 * 1024 * 1024) throw new Error('Checkpoint exceeds size bound');
  const result = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (result.id !== id || result.mode !== mode || result.schema_version !== 1) throw new Error('Invalid checkpoint');
  for (const slot of Object.keys(result.before)) {
    slotPath(mode, target, slot);
    if (!(slot in result.expected)) throw new Error('Corrupted checkpoint');
    for (const value of [result.before[slot], result.expected[slot]]) {
      const hash = value.bytes === null ? null : crypto.createHash('sha256').update(Buffer.from(value.bytes, 'base64')).digest('hex');
      if (value.hash !== hash) throw new Error('Corrupted checkpoint');
    }
  }
  return { file, result };
}

/** Restore an unchanged owned entry while retaining later unrelated client edits. */
function restoreConfig(filePath, before, expected) {
  let current;
  try { current = JSON.parse(fs.readFileSync(filePath, 'utf8')); } catch { return false; }
  if (!current || typeof current !== 'object' || Array.isArray(current) ||
      (Object.hasOwn(current, 'mcpServers') && (!current.mcpServers ||
        typeof current.mcpServers !== 'object' || Array.isArray(current.mcpServers)))) return false;
  const original = before.bytes === null ? {} : JSON.parse(Buffer.from(before.bytes, 'base64'));
  const after = expected.bytes === null ? {} : JSON.parse(Buffer.from(expected.bytes, 'base64'));
  for (const name of Object.keys(MCP_SERVERS)) {
    if (entryHash(current.mcpServers?.[name]) === entryHash(after.mcpServers?.[name])) {
      current.mcpServers ||= {};
      if (original.mcpServers?.[name] === undefined) delete current.mcpServers[name];
      else current.mcpServers[name] = original.mcpServers[name];
    }
  }
  atomicWrite(filePath, JSON.stringify(current, null, 2) + '\n');
  return true;
}

/** Undo only bytes proved to be this operation's output; keep later user modifications. */
function restore(mode, target, id) {
  const { file, result } = checkpoint(mode, target, id);
  const retained = [], restored = [];
  for (const [slot, before] of Object.entries(result.before).reverse()) {
    const destination = slotPath(mode, target, slot);
    let current;
    try { current = hashFile(destination); } catch { retained.push(slot); continue; }
    const expected = result.expected[slot];
    if (current === before.hash) continue;
    if (current !== expected.hash) {
      if (slot === '@config' && current) restoreConfig(destination, before, expected);
      retained.push(slot);
      continue;
    }
    if (before.bytes === null) { if (fs.existsSync(destination)) fs.unlinkSync(destination); }
    else { atomicWrite(destination, Buffer.from(before.bytes, 'base64')); fs.chmodSync(destination, before.mode); }
    restored.push(slot);
  }
  result.state = 'restored';
  atomicWrite(file, JSON.stringify(result, null, 2) + '\n');
  return { checkpoint_id: id, restored, retained, state: 'restored', no_external_operations: true };
}

/** List checkpoint metadata without emitting private backup bytes or config paths. */
function history(target) {
  const directory = path.join(target, CHECKPOINT_DIR);
  guard(path.join(directory, 'placeholder'), target);
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory).filter((name) => ID.test(name.slice(0, -5)) && name.endsWith('.json'))
    .map((name) => {
      const file = path.join(directory, name); assertRegularDestination(file);
      if (fs.statSync(file).size > 32 * 1024 * 1024) throw new Error('Checkpoint exceeds size bound');
      const record = JSON.parse(fs.readFileSync(file, 'utf8'));
      return { id: name.slice(0, -5), state: ['prepared', 'complete', 'restored'].includes(record.state) ? record.state : 'invalid',
        created_at: /^\d{4}-\d\d-\d\dT[\d:.Z+-]+$/.test(record.created_at || '') ? record.created_at : '' };
    }).sort((a, b) => a.created_at.localeCompare(b.created_at));
}

/** Apply a finite atomic write plan with durable recovery before its first mutation. */
function runTransaction(mode, target, operation, operations, expectedBefore = null) {
  if (history(target).some((item) => item.state === 'prepared')) throw new Error('Interrupted install; restore its checkpoint first');
  const id = crypto.randomUUID(), before = {}, expected = {};
  let total = 0;
  for (const [slot, content] of Object.entries(operations)) {
    before[slot] = capture(slotPath(mode, target, slot));
    if (expectedBefore && (!Object.hasOwn(expectedBefore, slot) || before[slot].hash !== expectedBefore[slot])) {
      throw new Error('Destination changed during planning; user edit retained');
    }
    const bytes = content === null ? null : Buffer.from(content);
    total += (bytes?.length || 0) + (before[slot].bytes ? Buffer.byteLength(before[slot].bytes, 'base64') : 0);
    expected[slot] = { bytes: bytes?.toString('base64') ?? null,
      hash: bytes === null ? null : crypto.createHash('sha256').update(bytes).digest('hex') };
  }
  if (total > 16 * 1024 * 1024) throw new Error('Install plan exceeds 16 MiB');
  const record = { schema_version: 1, id, mode, operation, package_version: VERSION,
    created_at: new Date().toISOString(), state: 'prepared', before, expected };
  const file = path.join(target, CHECKPOINT_DIR, `${id}.json`);
  guard(file, target); fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  atomicWrite(file, JSON.stringify(record, null, 2) + '\n');
  try {
    for (const [slot, content] of Object.entries(operations)) {
      const destination = slotPath(mode, target, slot);
      if (hashFile(destination) !== before[slot].hash) throw new Error('Destination changed after checkpoint; user edit retained');
      if (content === null) { if (fs.existsSync(destination)) fs.unlinkSync(destination); }
      else atomicWrite(destination, content);
      if (hashFile(destination) !== expected[slot].hash) throw new Error('Install output identity differs');
    }
    record.state = 'complete'; atomicWrite(file, JSON.stringify(record, null, 2) + '\n');
  } catch (err) { restore(mode, target, id); throw err; }
  return { checkpoint_id: id, operation, mode, package_version: VERSION, state: 'complete',
    files: Object.fromEntries(Object.entries(expected).map(([slot, value]) => [slot, value.hash])),
    no_external_operations: true };
}

/** Observe executable presence without executing it, downloading it, or echoing its path. */
function binaryPresent(name) {
  const suffixes = process.platform === 'win32' ? (process.env.PATHEXT || '.EXE;.CMD;.BAT').split(';') : [''];
  return (process.env.PATH || '').split(path.delimiter).some((directory) => suffixes.some((suffix) => {
    try { fs.accessSync(path.join(directory, name + suffix), fs.constants.X_OK); return fs.statSync(path.join(directory, name + suffix)).isFile(); }
    catch { return false; }
  }));
}

/** Report only key presence, matching process precedence without outputting local values. */
function credentials(home) {
  const names = ['GEMINI_API_KEY', 'YOUTUBE_API_KEY', 'S2_API_KEY', 'SEMANTIC_SCHOLAR_API_KEY',
    'WEAVIATE_URL', 'COHERE_API_KEY', 'ELEVENLABS_API_KEY', 'ANTHROPIC_API_KEY'];
  let content = '';
  try {
    const envPath = path.join(home, '.config/video-research-mcp/.env'); guard(envPath, home);
    if (fs.statSync(envPath).size <= 1024 * 1024) content = fs.readFileSync(envPath, 'utf8');
  } catch { /* absent, oversized, linked or unreadable */ }
  const observed = {};
  for (const line of content.split(/\r?\n/)) {
    const match = line.match(/^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (match && names.includes(match[1])) observed[match[1]] = match[2].replace(/(^|\s+)#.*$/, '').replace(/^(['"])(.*)\1$/, '$2').trim();
  }
  const present = (value) => Boolean(value?.trim()) && !/^\$\{?\w+\}?$/.test(value.trim());
  return Object.fromEntries(names.map((name) => [name, present(process.env[name]) ||
    (!present(process.env[name]) && present(observed[name]))]));
}

/** Validate the metadata-only Qwen route without adopting or launching a foreign runtime. */
function qwenReadiness(source) {
  const file = path.join(source, 'integrations/qwen/manifest.json');
  if (!fs.existsSync(file)) return { manifest_available: false, state: 'missing', reason: 'Optional manifest is not bundled' };
  const names = ['api', 'blender', 'core', 'edu-agent', 'freecad', 'mhs', 'omni-chatcut', 'omni-memory',
    'omni-skill-creator', 'omni-video2note', 'search', 'video-edit', 'video-memory', 'video-spatio'];
  let manifest;
  try {
    if (fs.statSync(file).size > 128 * 1024) throw new Error('Oversized metadata');
    manifest = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (manifest.source_revision !== '07736672525443c7f8a3f6405eed37d2236f023f' || manifest.capabilities.length !== 14 ||
        ['copied_paths', 'imported_packages', 'managed_binaries', 'bundled_fonts', 'bundled_media', 'bundled_weights']
          .some((key) => !Array.isArray(manifest[key]) || manifest[key].length)) throw new Error('Uncleared metadata');
    for (const name of names) {
      const row = manifest.capabilities.find((item) => item.id === name);
      if (!row || !/^\d+\.\d+\.\d+$/.test(row.declared_version) || row.declared_tag !== `qwen-mm-plugins-${name}-v${row.declared_version}` ||
          row.state !== 'external-disabled' || row.copied_paths.length || row.imported_packages.length) throw new Error('Invalid metadata');
    }
  } catch { return { manifest_available: true, state: 'invalid', reason: 'Restore reviewed metadata; no activation is allowed' }; }
  return { manifest_available: true, state: 'external-disabled', capabilities: names.map((id) => ({ id,
    state: 'unavailable-no-selected-backend', actual_probe: 'none',
    reason: 'No rights-cleared isolated runtime/dependency lock or operation authority selected' })),
    local_cloud_boundary: 'Local host payloads and selected cloud uploads are separate; no external runtime is installed or invoked.' };
}

/** Portable read-only doctor: npm assets cannot prove a Python server or native client acceptance. */
function doctor(mode, target, source) {
  const home = process.env.HOME || process.env.USERPROFILE;
  const binaries = Object.fromEntries(['uv', 'uvx', 'python3', 'ffmpeg', 'ffprobe', 'yt-dlp', 'blender', 'FreeCAD']
    .map((name) => [name, binaryPresent(name)]));
  const checker = fs.existsSync(path.join(source, 'scripts/inspect_provider_readiness.py'));
  return { schema_version: 1, package_version: VERSION, mode, inspection: 'read-only-local-presence',
    binaries_present: binaries, credential_presence: credentials(home), checkpoints: history(target),
    prerequisites: Object.entries(binaries).filter(([, found]) => !found).map(([name]) => ({ name,
      verification_command: [name, ['ffmpeg', 'ffprobe'].includes(name) ? '-version' : '--version'],
      required_action: `Install or select ${name} separately, then rerun --doctor; no repair is performed.` })),
    python_server: { installed: 'unverified', started: false, discovery: 'not-probed',
      required_command: 'Use an already-installed pinned Python environment to inspect MCP discovery; uvx startup may download packages.' },
    detailed_readiness: { checker_available_in_this_package: checker, executed: false,
      required_command: checker ? 'uv run python scripts/inspect_provider_readiness.py' :
        'Select a source checkout containing scripts/inspect_provider_readiness.py and its locked Python environment.' },
    optional_qwen: qwenReadiness(source),
    client_transport: { candidate_image_tool_source_present: fs.existsSync(path.join(source, 'src/video_research_mcp/tools/media.py')),
      native_image: 'not-probed-by-doctor; candidate-source-and-published-package-are-separate',
      text_only: 'examples-only; verify-current-server-discovery-schema-and-transport' },
    network_requests: 0, subprocesses: 0, inference_calls: 0, installs: 0,
    run_authority: 'not-granted' };
}

/** Print reviewed stdio examples without modifying a client or resolving remote packages. */
function clientConfig(client) {
  if (!['claude', 'cursor', 'codex'].includes(client)) throw new Error('Supported clients: claude, cursor, codex');
  const entry = MCP_SERVERS['video-research'];
  if (client === 'codex') return `[mcp_servers.video-research]\ncommand = "${entry.command}"\nargs = ${JSON.stringify(entry.args)}\n`;
  return JSON.stringify({ mcpServers: MCP_SERVERS }, null, 2) + '\n';
}

module.exports = { CHECKPOINT_DIR, guard, capture, runTransaction, restore, history, doctor, clientConfig };
