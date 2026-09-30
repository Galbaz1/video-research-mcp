#!/usr/bin/env node
'use strict';

const path = require('path');
const fs = require('fs');
const readline = require('readline');
const ui = require('./lib/ui');
const { FILE_MAP, cleanEmptyDirs } = require('./lib/copy');
const { hashFile, readManifest, computeActions } = require('./lib/manifest');
const { getConfigPath, readConfig, mergedConfig, MCP_SERVERS, entryHash, envTemplate } = require('./lib/config');
const { guard, capture, runTransaction, restore, history, doctor, clientConfig } = require('./lib/onboarding');
const VERSION = require('../package.json').version;

/** Parse bounded commands; read-only modes never prompt or mutate installation state. */
function parseArgs(argv) {
  const flags = {};
  const booleans = ['global', 'local', 'check', 'doctor', 'uninstall', 'force', 'rollback', 'help'];
  for (let i = 2; i < argv.length; i++) {
    const name = argv[i] === '-h' ? 'help' : argv[i].slice(2);
    if (!argv[i].startsWith('--') && argv[i] !== '-h') throw new Error('Unknown installer option');
    if (booleans.includes(name)) flags[name] = true;
    else if (['restore', 'client-config'].includes(name) && argv[i + 1] && !argv[i + 1].startsWith('--')) flags[name] = argv[++i];
    else throw new Error('Unknown or incomplete installer option');
  }
  if (flags.global && flags.local) throw new Error('Choose one installation scope');
  if (['check', 'doctor', 'uninstall', 'rollback', 'restore', 'client-config'].filter((key) => flags[key]).length > 1) {
    throw new Error('Choose one installer operation');
  }
  return flags;
}

function showHelp() {
  process.stderr.write(`video-research-mcp installer v${VERSION}\n\n` +
    'Usage: video-research-mcp [--global|--local] [operation]\n' +
    '  (default)           Install/update owned workflows and the pinned core MCP entry\n' +
    '  --doctor            Read-only runtime/key presence and recovery prerequisites\n' +
    '  --check             Read-only installation hashes/checkpoint status\n' +
    '  --client-config C   Print claude/cursor JSON or codex TOML; change no client\n' +
    '  --rollback          Restore the latest operation, preserving later edits\n' +
    '  --restore ID        Restore an exact private checkpoint, preserving later edits\n' +
    '  --uninstall         Remove unchanged owned files/config; retain edits/backups/env\n' +
    '  --force             Explicitly replace modified workflow assets during install\n' +
    '  --help, -h          Show help\n');
}

async function promptMode() {
  const rl = readline.createInterface({ input: process.stdin, output: process.stderr });
  return new Promise((resolve) => rl.question('Install globally [1] or in this project [2]? ', (answer) => {
    rl.close(); resolve(answer.trim() === '2' ? 'local' : 'global');
  }));
}

function homeDir() {
  const home = process.env.HOME || process.env.USERPROFILE;
  if (!home) throw new Error('Home directory is unavailable');
  return home;
}

function targetDir(mode) {
  return path.join(mode === 'global' ? homeDir() : process.cwd(), '.claude');
}

/** Bound package/user workflow files before the existing hash/action planner reads them. */
function preflightFiles(source, target, manifest) {
  const paths = [...Object.keys(FILE_MAP).map((rel) => path.join(source, rel)),
    ...new Set([...Object.values(FILE_MAP), ...Object.keys(manifest.files)])].map((value) =>
      path.isAbsolute(value) ? value : path.join(target, value));
  for (const file of paths) {
    try { if (fs.statSync(file).size > 16 * 1024 * 1024) throw new Error('Workflow exceeds installer size bound'); }
    catch (err) { if (err.code !== 'ENOENT') throw err; }
  }
}

/** Identify managed files without displaying local contents, endpoints or credentials. */
function status(mode) {
  const target = targetDir(mode); guard(path.join(target, 'gr-file-manifest.json'), target);
  capture(path.join(target, 'gr-file-manifest.json'));
  const manifest = readManifest(target);
  preflightFiles(path.resolve(__dirname, '..'), target, manifest);
  return { mode, installed: Boolean(manifest.installedAt), package_version: VERSION,
    files: Object.fromEntries(Object.entries(manifest.files).map(([rel, entry]) =>
      [rel, { installed_sha256: entry.hash, current_sha256: hashFile(path.join(target, rel)) }])),
    configuration_sha256: hashFile(getConfigPath(mode)), checkpoints: history(target) };
}

/** Plan assets/config/template before writing anything; ownership is never inferred from equal bytes. */
function install(mode, force = false) {
  const source = path.resolve(__dirname, '..'), target = targetDir(mode), configPath = getConfigPath(mode);
  guard(path.join(target, 'gr-file-manifest.json'), target);
  const manifestInput = capture(path.join(target, 'gr-file-manifest.json'));
  const manifest = readManifest(target);
  preflightFiles(source, target, manifest);
  const expectedBefore = Object.fromEntries([...new Set([...Object.values(FILE_MAP), ...Object.keys(manifest.files)])]
    .map((rel) => [rel, hashFile(path.join(target, rel))]));
  expectedBefore['@manifest'] = manifestInput.hash;
  expectedBefore['@config'] = capture(configPath).hash;
  const actions = computeActions(source, target, FILE_MAP, manifest, force);
  const beforeConfig = readConfig(configPath), afterConfig = mergedConfig(beforeConfig, manifest.config_entries || {});
  const operations = {}, files = {}, ownedEntries = {};
  for (const action of actions.toCopy) {
    const artifact = capture(path.join(source, action.src));
    operations[action.dest] = Buffer.from(artifact.bytes, 'base64');
    files[action.dest] = { hash: artifact.hash };
  }
  for (const action of actions.toSkip) {
    if (manifest.files[action.dest]) files[action.dest] = manifest.files[action.dest];
  }
  for (const action of actions.toRemove) operations[action.dest] = null;
  for (const name of Object.keys(MCP_SERVERS)) {
    const before = beforeConfig?.mcpServers?.[name];
    if (before === undefined || entryHash(before) === manifest.config_entries?.[name]) {
      ownedEntries[name] = entryHash(afterConfig.mcpServers[name]);
    }
  }
  if (JSON.stringify(beforeConfig) !== JSON.stringify(afterConfig)) operations['@config'] = JSON.stringify(afterConfig, null, 2) + '\n';
  const envPath = path.join(homeDir(), '.config/video-research-mcp/.env'); guard(envPath, homeDir());
  const env = capture(envPath), currentEnv = env.bytes === null ? '' : Buffer.from(env.bytes, 'base64').toString('utf8');
  expectedBefore['@env'] = env.hash;
  if (envTemplate(currentEnv) !== currentEnv) operations['@env'] = envTemplate(currentEnv);
  operations['@manifest'] = JSON.stringify({ version: VERSION, mode, installedAt: new Date().toISOString(),
    package_sha256: hashFile(path.join(source, 'package.json')), files, config_entries: ownedEntries }, null, 2) + '\n';
  const receipt = runTransaction(mode, target, 'install-or-update', operations, expectedBefore);
  receipt.preserved_workflow_files = actions.toSkip.filter((action) => action.reason.startsWith('user modified')).length;
  receipt.configuration_sha256 = hashFile(configPath);
  receipt.configured_entry_preserved = Boolean(beforeConfig?.mcpServers?.['video-research'] && !ownedEntries['video-research']);
  return receipt;
}

/** Uninstall only unchanged owned entries; shared credentials and recovery snapshots remain private. */
function uninstall(mode) {
  const target = targetDir(mode); guard(path.join(target, 'gr-file-manifest.json'), target);
  const manifestInput = capture(path.join(target, 'gr-file-manifest.json'));
  const manifest = readManifest(target);
  if (!manifest.installedAt) return { operation: 'uninstall', mode, state: 'no-installation' };
  preflightFiles(path.resolve(__dirname, '..'), target, manifest);
  const operations = {}, retained = {}, expectedBefore = { '@manifest': manifestInput.hash };
  for (const [rel, entry] of Object.entries(manifest.files)) {
    const current = hashFile(path.join(target, rel));
    expectedBefore[rel] = current;
    if (current && current === entry.hash) operations[rel] = null;
    else if (current) retained[rel] = entry;
  }
  const configPath = getConfigPath(mode);
  expectedBefore['@config'] = capture(configPath).hash;
  const existing = readConfig(configPath);
  if (existing?.mcpServers) {
    const cleaned = structuredClone(existing);
    for (const [name, hash] of Object.entries(manifest.config_entries || {})) {
      if (Object.hasOwn(MCP_SERVERS, name) && entryHash(cleaned.mcpServers[name]) === hash) delete cleaned.mcpServers[name];
    }
    if (JSON.stringify(cleaned) !== JSON.stringify(existing)) operations['@config'] = JSON.stringify(cleaned, null, 2) + '\n';
  }
  operations['@manifest'] = Object.keys(retained).length ? JSON.stringify({ ...manifest, files: retained,
    config_entries: {} }, null, 2) + '\n' : null;
  const receipt = runTransaction(mode, target, 'uninstall', operations, expectedBefore);
  cleanEmptyDirs(target, Object.keys(manifest.files).map((rel) => path.dirname(rel)));
  return { ...receipt, preserved_workflow_files: Object.keys(retained).length, shared_credentials_retained: true };
}

async function main() {
  const flags = parseArgs(process.argv);
  if (flags.help) { showHelp(); return; }
  if (flags['client-config']) { process.stdout.write(clientConfig(flags['client-config'])); return; }
  let mode = flags.local ? 'local' : 'global';
  if (flags.check) {
    const scopes = flags.global || flags.local ? [mode] : ['global', 'local'];
    process.stdout.write(JSON.stringify(scopes.map(status), null, 2) + '\n'); return;
  }
  if (flags.doctor) {
    process.stdout.write(JSON.stringify(doctor(mode, targetDir(mode), path.resolve(__dirname, '..')), null, 2) + '\n'); return;
  }
  if (!flags.global && !flags.local && !flags.uninstall && !flags.rollback && !flags.restore) mode = await promptMode();
  let receipt;
  if (flags.rollback || flags.restore) {
    const records = history(targetDir(mode));
    const id = flags.restore || records.at(-1)?.id;
    receipt = restore(mode, targetDir(mode), id);
  } else if (flags.uninstall) receipt = uninstall(mode);
  else receipt = install(mode, flags.force);
  process.stdout.write(JSON.stringify(receipt, null, 2) + '\n');
  ui.success(`${receipt.state}: local operation recorded; use --doctor to inspect prerequisites.`);
}

if (require.main === module) main().catch(() => {
  ui.error('Installer failed safely. Check configuration/ownership paths or restore an interrupted checkpoint; diagnostic values are withheld.');
  process.exitCode = 1;
});

module.exports = { parseArgs, install, uninstall, status, main };
