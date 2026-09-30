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
  assert.deepEqual(installed.mcpServers['video-research'].args, ['old']);
  assert.equal(installed.mcpServers.playwright, undefined);
  assert.equal(installed.mcpServers['mlflow-mcp'], undefined);
  assert.equal(installed.mcpServers['video-agent'].command, 'uv');
  assert.equal(fs.existsSync(path.join(home, '.claude/.mcp.json')), false);
});

test('local install registers at the project root and creates private credential template', (t) => {
  const home = fixture(t);
  const result = runInstaller(home, '--local');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.existsSync(path.join(home, '.mcp.json')), true);
  const envPath = path.join(home, '.config/video-research-mcp/.env');
  assert.match(fs.readFileSync(envPath, 'utf8'), /# GEMINI_MODEL=\n/);
  assert.doesNotMatch(fs.readFileSync(envPath, 'utf8'), /gemini-\d/);
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

const onboarding = require('../bin/lib/onboarding');
const { FILE_MAP } = require('../bin/lib/copy');

function originalPackage(t, version) {
  const directory = fixture(t);
  fs.cpSync(path.resolve(__dirname, '../bin'), path.join(directory, 'bin'), { recursive: true });
  fs.writeFileSync(path.join(directory, 'package.json'), JSON.stringify({ version }));
  for (const source of Object.keys(FILE_MAP)) {
    const file = path.join(directory, source);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, `Original installer fixture ${version}: ${source}\n`);
  }
  return directory;
}

function runPackage(source, home, ...args) {
  return spawnSync(process.execPath, [path.join(source, 'bin/install.js'), ...args], {
    cwd: home, env: { ...process.env, HOME: home, USERPROFILE: home }, encoding: 'utf8',
  });
}

function isolatedEnvironment(home, operation) {
  const beforeHome = process.env.HOME, beforeProfile = process.env.USERPROFILE;
  process.env.HOME = home; process.env.USERPROFILE = home;
  try { return operation(); }
  finally {
    if (beforeHome === undefined) delete process.env.HOME; else process.env.HOME = beforeHome;
    if (beforeProfile === undefined) delete process.env.USERPROFILE; else process.env.USERPROFILE = beforeProfile;
  }
}

test('original two-version install/update/rollback preserves modifications and exact owned hashes', (t) => {
  const home = fixture(t), first = originalPackage(t, '9.0.1'), second = originalPackage(t, '9.0.2');
  const fresh = runPackage(first, home, '--global');
  assert.equal(fresh.status, 0, fresh.stderr);
  const firstReceipt = JSON.parse(fresh.stdout);
  assert.equal(firstReceipt.package_version, '9.0.1');
  const modified = path.join(home, '.claude/commands/gr/video.md');
  const unchanged = path.join(home, '.claude/commands/gr/search.md');
  fs.appendFileSync(modified, 'User addition');
  const modifiedHash = hashFile(modified), oldUnchangedHash = hashFile(unchanged);
  const upgraded = runPackage(second, home, '--global');
  assert.equal(upgraded.status, 0, upgraded.stderr);
  const receipt = JSON.parse(upgraded.stdout);
  assert.equal(receipt.preserved_workflow_files, 1);
  assert.equal(hashFile(modified), modifiedHash);
  assert.notEqual(hashFile(unchanged), oldUnchangedHash);
  assert.equal(JSON.parse(fs.readFileSync(path.join(home, '.claude.json'))).mcpServers['video-research'].args[0],
    'video-research-mcp==9.0.2');
  const rollback = runPackage(second, home, '--global', '--rollback');
  assert.equal(rollback.status, 0, rollback.stderr);
  assert.equal(JSON.parse(rollback.stdout).checkpoint_id, receipt.checkpoint_id);
  assert.equal(hashFile(modified), modifiedHash);
  assert.equal(hashFile(unchanged), oldUnchangedHash);
  assert.equal(JSON.parse(fs.readFileSync(path.join(home, '.claude.json'))).mcpServers['video-research'].args[0],
    'video-research-mcp==9.0.1');
});

test('forced update keeps exact private recovery bytes and later edits survive restoration', (t) => {
  const home = fixture(t), source = originalPackage(t, '9.0.1');
  assert.equal(runPackage(source, home, '--global').status, 0);
  const modified = path.join(home, '.claude/commands/gr/video.md');
  fs.writeFileSync(modified, 'Original user customization');
  const result = runPackage(source, home, '--global', '--force');
  assert.equal(result.status, 0, result.stderr);
  const receipt = JSON.parse(result.stdout);
  assert.equal(runPackage(source, home, '--global', '--restore', receipt.checkpoint_id).status, 0);
  assert.equal(fs.readFileSync(modified, 'utf8'), 'Original user customization');
  const forced = JSON.parse(runPackage(source, home, '--global', '--force').stdout);
  fs.writeFileSync(modified, 'Later user customization');
  const recovered = runPackage(source, home, '--global', '--restore', forced.checkpoint_id);
  assert.equal(recovered.status, 0, recovered.stderr);
  assert.ok(JSON.parse(recovered.stdout).retained.includes('commands/gr/video.md'));
  assert.equal(fs.readFileSync(modified, 'utf8'), 'Later user customization');
});

test('uninstall and exact restore retain credentials and unrelated configuration changes', (t) => {
  const home = fixture(t), source = originalPackage(t, '9.0.1');
  assert.equal(runPackage(source, home, '--global').status, 0);
  const configPath = path.join(home, '.claude.json'), envPath = path.join(home, '.config/video-research-mcp/.env');
  fs.appendFileSync(envPath, 'GEMINI_API_KEY=ORIGINAL-PRIVATE-KEY\n');
  const envHash = hashFile(envPath), workflow = path.join(home, '.claude/commands/gr/video.md');
  const workflowHash = hashFile(workflow);
  const removed = runPackage(source, home, '--global', '--uninstall');
  assert.equal(removed.status, 0, removed.stderr);
  const receipt = JSON.parse(removed.stdout);
  assert.equal(fs.existsSync(workflow), false);
  const current = JSON.parse(fs.readFileSync(configPath));
  current.mcpServers.personal = { command: 'my-local-server' };
  current.projects = { original: true };
  fs.writeFileSync(configPath, JSON.stringify(current));
  assert.equal(runPackage(source, home, '--global', '--restore', receipt.checkpoint_id).status, 0);
  const restored = JSON.parse(fs.readFileSync(configPath));
  assert.deepEqual(restored.mcpServers.personal, { command: 'my-local-server' });
  assert.deepEqual(restored.projects, { original: true });
  assert.equal(restored.mcpServers['video-research'].args[0], 'video-research-mcp==9.0.1');
  assert.equal(hashFile(workflow), workflowHash);
  assert.equal(hashFile(envPath), envHash);
  assert.doesNotMatch(removed.stdout + removed.stderr, /ORIGINAL-PRIVATE-KEY/);
});

test('customized and preexisting identical MCP entries are not adopted or removed', (t) => {
  const home = fixture(t), configPath = path.join(home, '.claude.json');
  const original = { mcpServers: { ...config.MCP_SERVERS, custom: { command: 'other' } } };
  fs.writeFileSync(configPath, JSON.stringify(original));
  assert.equal(runInstaller(home, '--global').status, 0);
  assert.deepEqual(readManifest(path.join(home, '.claude')).config_entries, {});
  assert.equal(runInstaller(home, '--global', '--uninstall').status, 0);
  assert.deepEqual(JSON.parse(fs.readFileSync(configPath)), original);
});

test('a preexisting identical workflow has no deletion ownership without a manifest', (t) => {
  const home = fixture(t), source = originalPackage(t, '9.0.1');
  const userFile = path.join(home, '.claude/commands/gr/video.md');
  fs.mkdirSync(path.dirname(userFile), { recursive: true });
  fs.copyFileSync(path.join(source, 'commands/video.md'), userFile);
  assert.equal(runPackage(source, home, '--global').status, 0);
  assert.equal(readManifest(path.join(home, '.claude')).files['commands/gr/video.md'], undefined);
  assert.equal(runPackage(source, home, '--global', '--uninstall').status, 0);
  assert.equal(fs.existsSync(userFile), true);
});

test('atomic promotion failure after a managed write restores exact prior bytes', (t) => {
  const home = fixture(t), target = path.join(home, '.claude');
  const file = path.join(target, 'commands/gr/original.md');
  fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, 'Original bytes');
  const originalHash = hashFile(file), rename = fs.renameSync;
  isolatedEnvironment(home, () => {
    let failed = false;
    fs.renameSync = (from, to) => {
      if (!failed && to === path.join(home, '.claude.json')) { failed = true; throw new Error('Original injected promotion failure'); }
      return rename(from, to);
    };
    try {
      assert.throws(() => onboarding.runTransaction('global', target, 'original-failure-fixture', {
        'commands/gr/original.md': 'Changed bytes', '@config': JSON.stringify({ mcpServers: config.MCP_SERVERS }),
      }), /Original injected promotion failure/);
    } finally { fs.renameSync = rename; }
    assert.equal(hashFile(file), originalHash);
    assert.equal(fs.existsSync(path.join(home, '.claude.json')), false);
    assert.equal(onboarding.history(target).at(-1).state, 'restored');
  });
});

test('abrupt process interruption leaves a recoverable prepared checkpoint and blocks further writes', (t) => {
  const home = fixture(t), target = path.join(home, '.claude');
  const file = path.join(target, 'commands/gr/original.md');
  fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, 'Before interruption');
  const helper = path.resolve(__dirname, '../bin/lib/onboarding.js');
  const script = `const fs=require('fs');const rename=fs.renameSync;fs.renameSync=(a,b)=>{if(b===process.argv[1])process.exit(77);return rename(a,b);};require(process.argv[2]).runTransaction('global',process.argv[3],'original-interruption',{'commands/gr/original.md':'After first write','@config':'{"mcpServers":{}}'});`;
  const interrupted = spawnSync(process.execPath, ['-e', script, path.join(home, '.claude.json'), helper, target], {
    env: { ...process.env, HOME: home, USERPROFILE: home }, encoding: 'utf8',
  });
  assert.equal(interrupted.status, 77);
  assert.equal(fs.readFileSync(file, 'utf8'), 'After first write');
  const report = JSON.parse(runInstaller(home, '--global', '--doctor').stdout);
  const prepared = report.checkpoints.find((record) => record.state === 'prepared');
  assert.ok(prepared);
  assert.notEqual(runInstaller(home, '--global').status, 0);
  assert.equal(runInstaller(home, '--global', '--restore', prepared.id).status, 0);
  assert.equal(fs.readFileSync(file, 'utf8'), 'Before interruption');
});

test('doctor is read-only, redacted and truthful about unbundled Python readiness and missing binaries', (t) => {
  const home = fixture(t), source = originalPackage(t, '9.0.1');
  const envPath = path.join(home, '.config/video-research-mcp/.env');
  fs.mkdirSync(path.dirname(envPath), { recursive: true });
  fs.writeFileSync(envPath, 'GEMINI_API_KEY=DOCTOR-PRIVATE-TOKEN\nWEAVIATE_URL=https://private.invalid/?token=DOCTOR-PRIVATE-TOKEN\n');
  const before = hashFile(envPath);
  const result = spawnSync(process.execPath, [path.join(source, 'bin/install.js'), '--global', '--doctor'], {
    cwd: home, env: { HOME: home, USERPROFILE: home, PATH: '', GEMINI_MODEL: 'DOCTOR-PRIVATE-TOKEN' }, encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stderr);
  const report = JSON.parse(result.stdout);
  assert.equal(report.credential_presence.GEMINI_API_KEY, true);
  assert.equal(report.credential_presence.WEAVIATE_URL, true);
  assert.equal(report.detailed_readiness.checker_available_in_this_package, false);
  assert.equal(report.python_server.installed, 'unverified');
  assert.equal(report.binaries_present.uv, false);
  assert.equal(report.network_requests + report.subprocesses + report.inference_calls + report.installs, 0);
  assert.match(report.prerequisites.find((item) => item.name === 'ffmpeg').required_action, /separately/);
  assert.doesNotMatch(result.stdout + result.stderr, /DOCTOR-PRIVATE-TOKEN|private.invalid/);
  assert.equal(hashFile(envPath), before);
  assert.equal(fs.existsSync(path.join(home, '.claude')), false);
});

test('portable client examples are parseable and contain only a current version-pinned core declaration', (t) => {
  const home = fixture(t);
  for (const client of ['claude', 'cursor']) {
    const result = runInstaller(home, '--client-config', client);
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout), { mcpServers: config.MCP_SERVERS });
  }
  const codex = runInstaller(home, '--client-config', 'codex');
  assert.equal(codex.status, 0);
  assert.match(codex.stdout, /^\[mcp_servers.video-research\]/);
  assert.match(codex.stdout, /video-research-mcp==/);
  assert.doesNotMatch(codex.stdout, /tracing|playwright|GEMINI_API_KEY/);
  assert.equal(fs.existsSync(path.join(home, '.codex')), false);
  assert.equal(fs.existsSync(path.join(home, '.cursor')), false);
  assert.equal(fs.existsSync(path.join(home, '.claude')), false);
});

test('manifest accounts for exact capability tags and excludes unresolved redistributed assets', () => {
  const manifest = require('../integrations/qwen/manifest.json');
  assert.equal(manifest.source_revision, '07736672525443c7f8a3f6405eed37d2236f023f');
  assert.equal(manifest.capabilities.length, 14);
  for (const capability of manifest.capabilities) {
    assert.equal(capability.declared_tag, `qwen-mm-plugins-${capability.id}-v${capability.declared_version}`);
    assert.equal(capability.tag_commit_verified, false);
    assert.equal(capability.state, 'external-disabled');
    assert.deepEqual(capability.copied_paths, []);
    assert.deepEqual(capability.imported_packages, []);
    assert.ok(capability.applicable_notice_receipts.length);
  }
  for (const key of ['copied_paths', 'imported_packages', 'managed_binaries', 'bundled_fonts', 'bundled_media', 'bundled_weights']) {
    assert.deepEqual(manifest[key], []);
  }
  assert.equal(manifest.runtime_isolation.core_lock_changes, false);
});

test('root/config/env symlinks cannot redirect an installer transaction', (t) => {
  for (const kind of ['root', 'config', 'env-parent']) {
    const home = fixture(t), outside = fixture(t);
    const sentinel = path.join(outside, 'keep.txt'); fs.writeFileSync(sentinel, 'Original outside bytes');
    if (kind === 'root') fs.symlinkSync(outside, path.join(home, '.claude'), 'dir');
    if (kind === 'config') fs.symlinkSync(sentinel, path.join(home, '.claude.json'));
    if (kind === 'env-parent') fs.symlinkSync(outside, path.join(home, '.config'), 'dir');
    assert.notEqual(runInstaller(home, '--global').status, 0);
    assert.equal(fs.readFileSync(sentinel, 'utf8'), 'Original outside bytes');
    assert.equal(fs.existsSync(path.join(outside, 'video-research-mcp')), false);
  }
});

test('later malformed private config is retained while other owned files restore', (t) => {
  for (const edited of ['{original-private-value:DO-NOT-PRINT', 'null', '[]', '"DO-NOT-PRINT"', '42', '{"mcpServers":null}']) {
    const home = fixture(t), source = originalPackage(t, '9.0.1');
    const installed = runPackage(source, home, '--global');
    assert.equal(installed.status, 0);
    const id = JSON.parse(installed.stdout).checkpoint_id, configPath = path.join(home, '.claude.json');
    fs.writeFileSync(configPath, edited);
    const recovered = runPackage(source, home, '--global', '--restore', id);
    assert.equal(recovered.status, 0, recovered.stderr);
    assert.ok(JSON.parse(recovered.stdout).retained.includes('@config'));
    assert.equal(fs.readFileSync(configPath, 'utf8'), edited);
    assert.equal(fs.existsSync(path.join(home, '.claude/commands/gr/video.md')), false);
    assert.doesNotMatch(recovered.stdout + recovered.stderr, /DO-NOT-PRINT/);
  }
});

test('corrupted checkpoint hashes fail before any restore mutation', (t) => {
  const home = fixture(t), source = originalPackage(t, '9.0.1');
  const installed = runPackage(source, home, '--global');
  assert.equal(installed.status, 0);
  const id = JSON.parse(installed.stdout).checkpoint_id;
  const checkpoint = path.join(home, '.claude', onboarding.CHECKPOINT_DIR, id + '.json');
  const record = JSON.parse(fs.readFileSync(checkpoint));
  record.before[Object.keys(record.before)[0]].hash = '0'.repeat(64);
  fs.writeFileSync(checkpoint, JSON.stringify(record));
  const before = hashFile(path.join(home, '.claude/gr-file-manifest.json'));
  assert.notEqual(runPackage(source, home, '--global', '--restore', id).status, 0);
  assert.equal(hashFile(path.join(home, '.claude/gr-file-manifest.json')), before);
});

test('oversized user workflow is rejected before content hashing or writes', (t) => {
  const home = fixture(t), file = path.join(home, '.claude/commands/gr/video.md');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const fd = fs.openSync(file, 'w'); fs.ftruncateSync(fd, 16 * 1024 * 1024 + 1); fs.closeSync(fd);
  assert.notEqual(runInstaller(home, '--global').status, 0);
  assert.equal(fs.statSync(file).size, 16 * 1024 * 1024 + 1);
  assert.equal(fs.existsSync(path.join(home, '.claude.json')), false);
  assert.equal(fs.existsSync(path.join(home, '.claude', onboarding.CHECKPOINT_DIR)), false);
});

test('destination changed after checkpoint is retained before transaction promotion', (t) => {
  const home = fixture(t), target = path.join(home, '.claude');
  const file = path.join(target, 'commands/gr/original.md');
  const later = path.join(target, 'commands/gr/later.md');
  fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, 'Original bytes');
  fs.writeFileSync(later, 'Original later bytes');
  const rename = fs.renameSync;
  isolatedEnvironment(home, () => {
    let changed = false;
    fs.renameSync = (from, to) => {
      const result = rename(from, to);
      if (!changed && to === file) {
        changed = true; fs.writeFileSync(later, 'Later user edit');
      }
      return result;
    };
    try { assert.throws(() => onboarding.runTransaction('global', target, 'original-concurrent-edit',
      { 'commands/gr/original.md': 'Planned promotion', 'commands/gr/later.md': 'Planned later promotion' }), /Destination changed/); }
    finally { fs.renameSync = rename; }
    assert.equal(fs.readFileSync(file, 'utf8'), 'Original bytes');
    assert.equal(fs.readFileSync(later, 'utf8'), 'Later user edit');
    assert.equal(onboarding.history(target).at(-1).state, 'restored');
  });
});

test('install refuses stale planned config before checkpoint capture or any write', (t) => {
  const home = fixture(t), file = path.join(home, '.claude.json');
  fs.writeFileSync(file, JSON.stringify({ mcpServers: { personal: { command: 'original' } } }));
  const installer = require('../bin/install'), read = fs.readFileSync;
  isolatedEnvironment(home, () => {
    let reads = 0, changed = false;
    fs.readFileSync = (name, ...args) => {
      if (name === file) reads++;
      if (!changed && reads >= 2 && name === path.resolve(__dirname, '../commands/video.md')) {
        changed = true; fs.writeFileSync(file, JSON.stringify({ mcpServers: { personal: { command: 'original' } }, later_setting: 'USER_EDIT' }));
      }
      return read(name, ...args);
    };
    try { assert.throws(() => installer.install('global'), /Destination changed during planning/); }
    finally { fs.readFileSync = read; }
    assert.equal(changed, true);
    assert.equal(JSON.parse(fs.readFileSync(file)).later_setting, 'USER_EDIT');
    assert.equal(fs.existsSync(path.join(home, '.claude', onboarding.CHECKPOINT_DIR)), false);
  });
});

test('capture hashes its retained bounded bytes with one content read', (t) => {
  const home = fixture(t), file = path.join(home, 'original.txt');
  fs.writeFileSync(file, 'Original bytes');
  const read = fs.readFileSync; let reads = 0;
  fs.readFileSync = (name, ...args) => name === file ? Buffer.from(++reads === 1 ? 'Original bytes' : 'Later user edit') : read(name, ...args);
  let captured;
  try { captured = onboarding.capture(file); } finally { fs.readFileSync = read; }
  assert.equal(reads, 1);
  assert.equal(Buffer.from(captured.bytes, 'base64').toString(), 'Original bytes');
  assert.equal(captured.hash, require('node:crypto').createHash('sha256').update('Original bytes').digest('hex'));
});

test('unreadable later destination cannot be treated as absence during recovery', (t) => {
  const home = fixture(t), target = path.join(home, '.claude'), slot = 'commands/gr/original.md';
  const file = path.join(target, slot), read = fs.readFileSync;
  fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, 'Original owned bytes');
  isolatedEnvironment(home, () => {
    const removed = onboarding.runTransaction('global', target, 'original-uninstall', { [slot]: null });
    fs.writeFileSync(file, 'Later unreadable user edit');
    fs.readFileSync = (name, ...args) => {
      if (name === file) throw Object.assign(new Error('Original private EACCES detail'), { code: 'EACCES' });
      return read(name, ...args);
    };
    let receipt;
    try {
      assert.throws(() => hashFile(file), /Installer file identity is unreadable/);
      receipt = onboarding.restore('global', target, removed.checkpoint_id);
    } finally { fs.readFileSync = read; }
    assert.deepEqual(receipt.retained, [slot]);
    assert.deepEqual(receipt.restored, []);
    assert.equal(fs.readFileSync(file, 'utf8'), 'Later unreadable user edit');
    assert.doesNotMatch(JSON.stringify(receipt), /private EACCES|unreadable user edit/);
  });
});
