'use strict';

const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const config = require('../bin/lib/config');
const { readManifest, computeActions, hashFile } = require('../bin/lib/manifest');

function fixture(t) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'gr-installer-'));
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  return home;
}

function runInstaller(home, ...args) {
  return spawnSync(process.execPath, [path.resolve(__dirname, '../bin/install.js'), ...args], {
    cwd: home,
    env: { ...process.env, HOME: home, USERPROFILE: home },
    encoding: 'utf8',
  });
}

test('global registration uses Claude user scope and preserves user configuration', (t) => {
  const home = fixture(t);
  const configPath = path.join(home, '.claude.json');
  fs.writeFileSync(configPath, JSON.stringify({
    projects: { '/other/project': { hasTrustDialogAccepted: true } },
    mcpServers: {
      personal: { command: 'my-server' },
      'video-research': { command: 'uvx', args: ['old'], env: { GEMINI_MODEL: 'custom' } },
      'video-agent': { command: 'uv', args: ['run', 'video-agent-mcp'] },
    },
  }));
  const result = runInstaller(home, '--global');
  assert.equal(result.status, 0, result.stderr);
  const installed = JSON.parse(fs.readFileSync(configPath));
  assert.equal(installed.projects['/other/project'].hasTrustDialogAccepted, true);
  assert.deepEqual(installed.mcpServers.personal, { command: 'my-server' });
  assert.equal(installed.mcpServers['video-research'].env.GEMINI_MODEL, 'custom');
  assert.deepEqual(installed.mcpServers['video-research'].args, config.MCP_SERVERS['video-research'].args);
  assert.equal(installed.mcpServers['video-agent'].command, 'uv');
  assert.equal(fs.existsSync(path.join(home, '.claude/.mcp.json')), false);
});

test('local install registers at the project root and creates private credential template', (t) => {
  const home = fixture(t);
  const result = runInstaller(home, '--local');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.existsSync(path.join(home, '.mcp.json')), true);
  const envPath = path.join(home, '.config/video-research-mcp/.env');
  assert.match(fs.readFileSync(envPath, 'utf8'), /GEMINI_MODEL=gemini-3\.8-flash/);
  if (process.platform !== 'win32') assert.equal(fs.statSync(envPath).mode & 0o777, 0o600);
});

test('upgrade and uninstall retain modified files and their ownership evidence', (t) => {
  const home = fixture(t);
  assert.equal(runInstaller(home, '--global').status, 0);
  const target = path.join(home, '.claude');
  const modified = path.join(target, 'commands/gr/video.md');
  fs.appendFileSync(modified, '\nUser addition\n');
  const before = readManifest(target).files['commands/gr/video.md'].hash;
  assert.equal(runInstaller(home, '--global').status, 0);
  assert.equal(readManifest(target).files['commands/gr/video.md'].hash, before);
  assert.equal(runInstaller(home, '--global', '--uninstall').status, 0);
  assert.match(fs.readFileSync(modified, 'utf8'), /User addition/);
  assert.equal(readManifest(target).files['commands/gr/video.md'].hash, before);
});

test('a missing manifest cannot authorize overwriting or adopting an existing file', (t) => {
  const home = fixture(t);
  const userFile = path.join(home, '.claude/commands/gr/video.md');
  fs.mkdirSync(path.dirname(userFile), { recursive: true });
  fs.writeFileSync(userFile, 'Existing user command');
  assert.equal(runInstaller(home, '--global').status, 0);
  assert.equal(fs.readFileSync(userFile, 'utf8'), 'Existing user command');
  assert.equal(readManifest(path.join(home, '.claude')).files['commands/gr/video.md'], undefined);
  assert.equal(runInstaller(home, '--global', '--uninstall').status, 0);
  assert.equal(fs.readFileSync(userFile, 'utf8'), 'Existing user command');
});

test('force explicitly replaces a protected user edit', (t) => {
  const home = fixture(t);
  assert.equal(runInstaller(home, '--local').status, 0);
  const userFile = path.join(home, '.claude/commands/gr/video.md');
  fs.writeFileSync(userFile, 'User customization');
  assert.equal(runInstaller(home, '--local', '--force').status, 0);
  assert.notEqual(fs.readFileSync(userFile, 'utf8'), 'User customization');
});

test('malformed manifests fail before changing files', (t) => {
  const home = fixture(t);
  const target = path.join(home, '.claude');
  fs.mkdirSync(target);
  fs.writeFileSync(path.join(target, 'gr-file-manifest.json'), '{broken');
  const result = runInstaller(home, '--global');
  assert.notEqual(result.status, 0);
  assert.equal(fs.existsSync(path.join(target, 'commands')), false);
});

test('manifest traversal fails before uninstall can delete outside the install tree', (t) => {
  const home = fixture(t);
  const outside = path.join(home, 'keep.txt');
  fs.writeFileSync(outside, 'Keep');
  const target = path.join(home, '.claude');
  fs.mkdirSync(target);
  fs.writeFileSync(path.join(target, 'gr-file-manifest.json'), JSON.stringify({
    installedAt: 'test', files: { '../keep.txt': { hash: hashFile(outside) } },
  }));
  const result = runInstaller(home, '--global', '--uninstall');
  assert.notEqual(result.status, 0);
  assert.equal(fs.readFileSync(outside, 'utf8'), 'Keep');
});

test('a namespace prefix cannot authorize deleting unrelated Claude settings', (t) => {
  const home = fixture(t);
  const target = path.join(home, '.claude');
  fs.mkdirSync(target);
  const settings = path.join(target, 'settings.json');
  fs.writeFileSync(settings, 'User settings');
  fs.writeFileSync(path.join(target, 'gr-file-manifest.json'), JSON.stringify({
    installedAt: 'test', files: { 'commands/../settings.json': { hash: hashFile(settings) } },
  }));
  assert.notEqual(runInstaller(home, '--global', '--uninstall').status, 0);
  assert.equal(fs.readFileSync(settings, 'utf8'), 'User settings');
});

test('symlinked managed directories cannot redirect install or uninstall writes', (t) => {
  const home = fixture(t);
  const target = path.join(home, '.claude');
  const outside = path.join(home, 'outside');
  fs.mkdirSync(target);
  fs.mkdirSync(outside);
  fs.symlinkSync(outside, path.join(target, 'commands'), 'dir');
  const keep = path.join(outside, 'keep.md');
  fs.writeFileSync(keep, 'Keep');
  assert.notEqual(runInstaller(home, '--global').status, 0);
  fs.writeFileSync(path.join(target, 'gr-file-manifest.json'), JSON.stringify({
    installedAt: 'test', files: { 'commands/keep.md': { hash: hashFile(keep) } },
  }));
  assert.notEqual(runInstaller(home, '--global', '--uninstall').status, 0);
  assert.equal(fs.readFileSync(keep, 'utf8'), 'Keep');
});

test('a manifest entry without ownership hash cannot authorize removal', (t) => {
  const home = fixture(t);
  assert.throws(() => computeActions(home, home, {}, { files: { 'commands/user.md': {} } }, false),
    /Invalid install manifest hash/);
});

test('modified obsolete files remain protected across upgrades', (t) => {
  const home = fixture(t);
  assert.equal(runInstaller(home, '--global').status, 0);
  const target = path.join(home, '.claude');
  const obsolete = path.join(target, 'commands/gr/old.md');
  fs.writeFileSync(obsolete, 'Old command');
  const manifestPath = path.join(target, 'gr-file-manifest.json');
  const manifest = readManifest(target);
  manifest.files['commands/gr/old.md'] = { hash: hashFile(obsolete) };
  fs.writeFileSync(manifestPath, JSON.stringify(manifest));
  fs.appendFileSync(obsolete, ' user edit');
  assert.equal(runInstaller(home, '--global').status, 0);
  assert.equal(readManifest(target).files['commands/gr/old.md'].hash,
    manifest.files['commands/gr/old.md'].hash);
  assert.equal(runInstaller(home, '--global', '--uninstall').status, 0);
  assert.equal(fs.readFileSync(obsolete, 'utf8'), 'Old command user edit');
});

test('uninstall preserves a customized MCP server', (t) => {
  const home = fixture(t);
  const configPath = path.join(home, '.claude.json');
  fs.writeFileSync(configPath, JSON.stringify({ mcpServers: {
    'video-research': { ...config.MCP_SERVERS['video-research'], env: { GEMINI_MODEL: 'custom' } },
  } }));
  assert.equal(config.removeFromConfig(configPath), false);
  assert.equal(JSON.parse(fs.readFileSync(configPath)).mcpServers['video-research'].env.GEMINI_MODEL, 'custom');
});

test('action planning rejects unsafe paths even without reading a manifest file', (t) => {
  const home = fixture(t);
  assert.throws(() => computeActions(home, home, {}, { files: { '/outside': {} } }, false),
    /Unsafe install manifest path/);
});
