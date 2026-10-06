'use strict';

const assert = require('node:assert/strict');
const { test, before, after } = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { hashFile, readManifest } = require('../bin/lib/manifest');

const SOURCE = path.resolve(__dirname, '..');
const ADDED_SKILLS = ['av-events', 'educational-explainer', 'footage-edit',
  'research-visualization-blender', 'research-visualization-freecad', 'spatial-video-analysis',
  'video-translation', 'movie-commentary'];
const LEGACY_SKILLS = ['ffmpeg-production', 'gemini-visualize', 'gr-advisor',
  'hardware-evidence-capture', 'image-generation', 'mlflow-traces', 'plugin-maintenance',
  'research-brief-builder', 'reverse-search-video-frame', 'tts-production',
  'video-explainer', 'video-generation', 'video-production', 'video-research',
  'video-to-skill', 'weaviate-setup'];
const SUPPORT = 'skills/video-research-resources';
const RESOURCE_PATHS = [
  'THIRD_PARTY_NOTICES.md', 'LICENSE', 'licenses/fpdf2/GPL-3.0.txt', 'licenses/fpdf2/LGPL-3.0.txt',
  'docs/integrations/AV_EVENTS.md', 'docs/integrations/FOOTAGE_EDIT.md',
  'docs/integrations/qwen-education.md', 'docs/integrations/qwen-blender.md',
  'docs/integrations/qwen-freecad.md', 'docs/integrations/qwen-spatial.md',
  'integrations/qwen/av-events.json', 'integrations/qwen/footage-edit.json',
  'integrations/qwen/education.json', 'integrations/qwen/blender.json',
  'integrations/qwen/freecad.json', 'integrations/qwen/video-spatio.json',
  'scripts/blender_session.py', 'scripts/blender_startup.py', 'scripts/blender_stdio.py',
  'scripts/freecad_session.py', 'scripts/freecad_startup.py', 'scripts/freecad_jobs.py',
  'scripts/spatial_session.py', 'scripts/spatial_inputs.py',
  'scripts/spatial_launch.py', 'scripts/spatial_runtime.py', 'scripts/spatial_fonts.py',
  'scripts/spatial_dispatch.py', 'scripts/spatial_motion.py',
  'scripts/local_asr_service.py', 'scripts/local_asr_launch.py', 'scripts/local_asr_worker.py',
  'docs/integrations/local-asr.md', 'docs/integrations/qwen-dubbing.md',
  'docs/integrations/movie-commentary.md',
];
const EXPECTED_ADDITIONS = Object.fromEntries([
  ...ADDED_SKILLS.map(name => [`skills/${name}/SKILL.md`, `skills/${name}/SKILL.md`]),
  ['skills/educational-explainer/scripts/lesson.py', 'skills/educational-explainer/scripts/lesson.py'],
  ...RESOURCE_PATHS.map(relative => [relative, `${SUPPORT}/${relative}`]),
]);

let work, packedRoot, packedMap;

/** Run only installed tools, with child-local home/cache and no inherited credentials. */
function run(command, args, cwd, home = cwd) {
  return spawnSync(command, args, { cwd, encoding: 'utf8', timeout: 30000,
    env: { PATH: process.env.PATH, HOME: home, USERPROFILE: home,
      SystemRoot: process.env.SystemRoot, TMPDIR: work,
      npm_config_cache: path.join(work, 'npm-cache'), npm_config_offline: 'true',
      npm_config_userconfig: path.join(work, 'empty-npmrc'), npm_config_ignore_scripts: 'true' },
  });
}

before(() => {
  work = fs.mkdtempSync(path.join(os.tmpdir(), 'vr-claude-packaged-'));
  fs.writeFileSync(path.join(work, 'empty-npmrc'), '');
  const home = path.join(work, 'pack-home'); fs.mkdirSync(home);
  const result = run('npm', ['pack', '--offline', '--ignore-scripts', '--json',
    '--pack-destination', work], SOURCE, home);
  assert.equal(result.status, 0, result.stderr);
  const [packed] = JSON.parse(result.stdout);
  const unpack = run('tar', ['-xzf', path.join(work, packed.filename), '-C', work], work);
  assert.equal(unpack.status, 0, unpack.stderr);
  packedRoot = path.join(work, 'package');
  packedMap = require(path.join(packedRoot, 'bin/lib/copy')).FILE_MAP;
});

after(() => { if (work) fs.rmSync(work, { recursive: true, force: true }); });

function fixture(t) {
  const directory = fs.mkdtempSync(path.join(work, 'journey-'));
  const home = path.join(directory, 'home'), project = path.join(directory, 'project');
  fs.mkdirSync(home); fs.mkdirSync(project);
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  return { home, project, target: path.join(project, '.claude') };
}

function installAt(source, context, scope, ...args) {
  const result = run(process.execPath, [path.join(source, 'bin/install.js'), `--${scope}`,
    ...args], context.project, context.home);
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

function installedSkills(target) {
  return fs.readdirSync(path.join(target, 'skills')).filter(name =>
    fs.existsSync(path.join(target, 'skills', name, 'SKILL.md'))).sort();
}

for (const scope of ['local', 'global']) {
  test(`fresh packed ${scope} install delivers exactly ${LEGACY_SKILLS.length + ADDED_SKILLS.length} skills and the required resources`, (t) => {
    const context = fixture(t);
    const target = scope === 'global' ? path.join(context.home, '.claude') : context.target;
    installAt(packedRoot, context, scope);
    assert.deepEqual(installedSkills(target), [...LEGACY_SKILLS, ...ADDED_SKILLS].sort());
    const packedSkills = fs.readdirSync(path.join(packedRoot, 'skills'))
      .filter(name => fs.existsSync(path.join(packedRoot, 'skills', name, 'SKILL.md'))).sort();
    assert.deepEqual(installedSkills(target), packedSkills);
    const manifest = readManifest(target);
    for (const [source, destination] of Object.entries(EXPECTED_ADDITIONS)) {
      assert.equal(packedMap[source], destination, source);
    }
    for (const [source, destination] of Object.entries(packedMap)) {
      const sourceHash = hashFile(path.join(SOURCE, source));
      assert.ok(sourceHash, `missing source: ${source}`);
      assert.equal(hashFile(path.join(packedRoot, source)), sourceHash, `pack: ${source}`);
      assert.equal(hashFile(path.join(target, destination)), sourceHash, `install: ${destination}`);
      assert.equal(manifest.files[destination].hash, sourceHash, `ownership: ${destination}`);
    }
  });

  test(`${scope} check is read-only and reinstall writes no unchanged workflow/config/credential bytes`, (t) => {
    const context = fixture(t);
    const target = scope === 'global' ? path.join(context.home, '.claude') : context.target;
    const first = installAt(packedRoot, context, scope);
    const manifest = readManifest(target);
    const names = Object.keys(manifest.files).map(relative => path.join(target, relative));
    names.push(path.join(target, 'gr-file-manifest.json'),
      scope === 'global' ? path.join(context.home, '.claude.json') : path.join(context.project, '.mcp.json'),
      path.join(scope === 'global' ? context.home : context.project, '.config/video-research-mcp/.env'));
    const before = names.map(file => [file, hashFile(file), fs.statSync(file).mtimeMs]);
    const status = installAt(packedRoot, context, scope, '--check')[0];
    assert.equal(status.checkpoints.length, 1);
    assert.equal(status.checkpoints[0].id, first.checkpoint_id);
    assert.equal(status.configuration_sha256, first.configuration_sha256);
    for (const [file, hash, mtime] of before) {
      assert.equal(hashFile(file), hash); assert.equal(fs.statSync(file).mtimeMs, mtime);
    }
    const reinstalled = installAt(packedRoot, context, scope);
    // Existing installer records a fresh metadata checkpoint even for an unchanged asset plan.
    assert.deepEqual(Object.keys(reinstalled.files), ['@manifest']);
    for (const [file, hash, mtime] of before.filter(([file]) => !file.endsWith('gr-file-manifest.json'))) {
      assert.equal(hashFile(file), hash); assert.equal(fs.statSync(file).mtimeMs, mtime);
    }
    const report = installAt(packedRoot, context, scope, '--doctor');
    assert.equal(report.optional_qwen.state, 'external-disabled');
    assert.equal(report.python_server.started, false);
    assert.equal(report.run_authority, 'not-granted');
    assert.equal(report.network_requests + report.subprocesses + report.inference_calls + report.installs, 0);
  });
}

test('required resources are installed even independently of the skill-count assertion', (t) => {
  const context = fixture(t);
  installAt(packedRoot, context, 'local');
  const missing = Object.values(EXPECTED_ADDITIONS).filter(relative =>
    !fs.existsSync(path.join(context.target, relative)));
  assert.deepEqual(missing, []);
  installAt(packedRoot, context, 'local', '--uninstall');
  assert.equal(fs.existsSync(path.join(context.target, SUPPORT)), false);
  for (const name of ADDED_SKILLS) assert.equal(fs.existsSync(path.join(context.target, 'skills', name)), false);
});

test('added workflows name contracts, descriptors and helpers that resolve in their selected layout', (t) => {
  const context = fixture(t);
  installAt(packedRoot, context, 'local');
  const contracts = ['AV_EVENTS.md', 'qwen-education.md', 'FOOTAGE_EDIT.md',
    'qwen-blender.md', 'qwen-freecad.md', 'qwen-spatial.md', 'qwen-dubbing.md', 'movie-commentary.md'];
  const descriptors = ['av-events.json', 'education.json', 'footage-edit.json',
    'blender.json', 'freecad.json', 'video-spatio.json'];
  for (const root of [packedRoot, context.target]) {
    for (const [index, name] of ADDED_SKILLS.entries()) {
      const directory = path.join(root, 'skills', name);
      const text = fs.readFileSync(path.join(directory, 'SKILL.md'), 'utf8');
      const references = [...text.matchAll(/(?:\]\(|`)((?:\.\.\/)*(?:video-research-resources\/)?(?:docs|integrations|scripts)\/[^)`\s]+)[)`]/g)]
        .map(match => path.resolve(match[1].startsWith('../') ? directory : root, match[1]));
      assert.ok(references.some(file => path.basename(file) === contracts[index] && fs.existsSync(file)), `${root}: ${name} contract`);
      // Translation and commentary have contracts without a Qwen descriptor or helper.
      if (index >= descriptors.length) continue;
      const supportRoot = root === packedRoot ? root : path.join(root, SUPPORT);
      assert.equal(hashFile(path.join(supportRoot, 'integrations/qwen', descriptors[index])),
        hashFile(path.join(packedRoot, 'integrations/qwen', descriptors[index])));
      if (index >= 3) {
        const helper = ['blender_session.py', 'freecad_session.py', 'spatial_session.py'][index - 3];
        // Source/package references may be plain code paths, while Claude paths are skill-relative.
        assert.ok(text.includes(`scripts/${helper}`), `${name} helper selection`);
        assert.ok(fs.existsSync(path.join(supportRoot, 'scripts', helper)));
      }
    }
  }
  for (const relative of [...contracts.map(name => `docs/integrations/${name}`), 'THIRD_PARTY_NOTICES.md']) {
    const document = path.join(context.target, SUPPORT, relative);
    for (const [, reference] of fs.readFileSync(document, 'utf8').matchAll(/\]\(([^)\s#]+)[^)]*\)/g)) {
      if (/^[a-z][a-z0-9+.-]*:/i.test(reference)) continue;
      assert.ok(fs.existsSync(path.resolve(path.dirname(document), reference)), `${relative} -> ${reference}`);
    }
  }
});

test('managed 16-skill upgrade preserves modified/unmanaged assets, configuration and checkpoints', (t) => {
  const context = fixture(t), legacy = path.join(work, 'legacy-package');
  fs.cpSync(packedRoot, legacy, { recursive: true });
  const legacyMap = Object.fromEntries(Object.entries(packedMap)
    .filter(([source]) => !Object.hasOwn(EXPECTED_ADDITIONS, source)));
  const copyModule = path.join(legacy, 'bin/lib/copy.js');
  fs.writeFileSync(copyModule, fs.readFileSync(copyModule, 'utf8').replace(
    /const FILE_MAP = \{[\s\S]*?\n\};/, `const FILE_MAP = ${JSON.stringify(legacyMap, null, 2)};`));
  installAt(legacy, context, 'local');
  assert.deepEqual(installedSkills(context.target), LEGACY_SKILLS.toSorted());
  const oldManifest = readManifest(context.target);
  const checkpointDir = path.join(context.target, 'gr-install-backups');
  const previousCheckpoints = fs.readdirSync(checkpointDir).map(name =>
    [name, hashFile(path.join(checkpointDir, name))]);
  const edited = path.join(context.target, 'skills/video-research/SKILL.md');
  fs.appendFileSync(edited, '\nUser workflow customization\n');
  const userFile = path.join(context.target, SUPPORT, 'scripts/user-note.txt');
  fs.mkdirSync(path.dirname(userFile), { recursive: true });
  fs.writeFileSync(userFile, 'Unmanaged user note');
  const identical = path.join(context.target, SUPPORT, 'scripts/blender_stdio.py');
  fs.copyFileSync(path.join(packedRoot, 'scripts/blender_stdio.py'), identical);
  const custom = path.join(context.target, SUPPORT, 'docs/integrations/AV_EVENTS.md');
  fs.mkdirSync(path.dirname(custom), { recursive: true });
  fs.writeFileSync(custom, 'Unmanaged custom AV notes');
  const config = path.join(context.project, '.mcp.json');
  fs.writeFileSync(config, JSON.stringify({ customSetting: true,
    mcpServers: { 'video-research': { command: 'operator-choice' }, personal: { command: 'personal' } } }));
  const credentials = path.join(context.project, '.config/video-research-mcp/.env');
  fs.appendFileSync(credentials, '# User credential preference\n');
  const preserved = [edited, userFile, identical, custom, config, credentials]
    .map(file => [file, hashFile(file)]);
  const upgraded = installAt(packedRoot, context, 'local');
  assert.equal(upgraded.preserved_workflow_files, 2);
  assert.equal(upgraded.configured_entry_preserved, true);
  assert.deepEqual(installedSkills(context.target), [...LEGACY_SKILLS, ...ADDED_SKILLS].sort());
  for (const [file, hash] of preserved) assert.equal(hashFile(file), hash, file);
  for (const [relative, entry] of Object.entries(oldManifest.files)) {
    if (relative !== 'skills/video-research/SKILL.md') assert.equal(hashFile(path.join(context.target, relative)), entry.hash);
  }
  for (const [name, hash] of previousCheckpoints) assert.equal(hashFile(path.join(checkpointDir, name)), hash);
  const manifest = readManifest(context.target);
  assert.equal(manifest.files[`${SUPPORT}/scripts/blender_stdio.py`], undefined);
  assert.equal(manifest.files[`${SUPPORT}/docs/integrations/AV_EVENTS.md`], undefined);
  for (const [source, destination] of Object.entries(EXPECTED_ADDITIONS)) {
    if ([identical, custom].includes(path.join(context.target, destination))) continue;
    assert.equal(hashFile(path.join(context.target, destination)), hashFile(path.join(packedRoot, source)));
  }
  installAt(packedRoot, context, 'local', '--restore', upgraded.checkpoint_id);
  for (const [file, hash] of preserved) assert.equal(hashFile(file), hash);
  for (const destination of Object.values(EXPECTED_ADDITIONS)) {
    if (![identical, custom].includes(path.join(context.target, destination))) {
      assert.equal(fs.existsSync(path.join(context.target, destination)), false, destination);
    }
  }
});

const MODIFIED_ADDITIONS = ['skills/av-events/SKILL.md',
  'skills/educational-explainer/scripts/lesson.py',
  `${SUPPORT}/docs/integrations/qwen-freecad.md`, `${SUPPORT}/integrations/qwen/video-spatio.json`,
  `${SUPPORT}/scripts/freecad_jobs.py`];

for (const operation of ['--rollback', '--uninstall']) {
  test(`${operation} protects modified new skills, helpers, docs and descriptors`, (t) => {
    const context = fixture(t);
    installAt(packedRoot, context, 'local');
    const before = readManifest(context.target);
    const edits = MODIFIED_ADDITIONS.map(relative => {
      const file = path.join(context.target, relative);
      fs.appendFileSync(file, '\nUser-owned later edit\n');
      return [file, hashFile(file)];
    });
    const envFile = path.join(context.project, '.config/video-research-mcp/.env');
    fs.appendFileSync(envFile, '# Later credential choice\n');
    const envHash = hashFile(envFile);
    const result = installAt(packedRoot, context, 'local', operation);
    for (const [file, hash] of edits) assert.equal(hashFile(file), hash);
    assert.equal(hashFile(envFile), envHash);
    for (const relative of Object.keys(before.files)) {
      if (!MODIFIED_ADDITIONS.includes(relative)) assert.equal(fs.existsSync(path.join(context.target, relative)), false, relative);
    }
    if (operation === '--uninstall') {
      assert.equal(result.preserved_workflow_files, MODIFIED_ADDITIONS.length);
      assert.deepEqual(Object.keys(readManifest(context.target).files).sort(), MODIFIED_ADDITIONS.toSorted());
      const changedAfterRemoval = path.join(context.target, SUPPORT, 'scripts/spatial_inputs.py');
      fs.mkdirSync(path.dirname(changedAfterRemoval), { recursive: true });
      fs.writeFileSync(changedAfterRemoval, 'Later unmanaged replacement');
      const restored = installAt(packedRoot, context, 'local', '--restore', result.checkpoint_id);
      assert.ok(restored.retained.includes(`${SUPPORT}/scripts/spatial_inputs.py`));
      assert.equal(fs.readFileSync(changedAfterRemoval, 'utf8'), 'Later unmanaged replacement');
      for (const [relative, entry] of Object.entries(before.files)) {
        if (!MODIFIED_ADDITIONS.includes(relative) && relative !== `${SUPPORT}/scripts/spatial_inputs.py`) {
          assert.equal(hashFile(path.join(context.target, relative)), entry.hash);
        }
      }
      for (const [file, hash] of edits) assert.equal(hashFile(file), hash);
    } else {
      assert.ok(MODIFIED_ADDITIONS.every(relative => result.retained.includes(relative)));
    }
  });
}

test('packaged and installed optional helper imports/help preserve explicit runtime refusals', (t) => {
  const context = fixture(t);
  installAt(packedRoot, context, 'local');
  const selected = run('python3', ['-I', '-B', '-c', 'import sys; print(sys.executable)'], context.project, context.home);
  if (selected.error?.code === 'ENOENT') { t.skip('No installed Python interpreter; no dependency resolution allowed'); return; }
  assert.equal(selected.status, 0, selected.stderr);
  const python = selected.stdout.trim();
  assert.ok(path.isAbsolute(python));
  for (const directory of [path.join(packedRoot, 'scripts'), path.join(context.target, SUPPORT, 'scripts')]) {
    for (const script of ['blender_session.py', 'freecad_session.py', 'spatial_session.py']) {
      const result = run(python, ['-I', '-B', path.join(directory, script), '--help'], context.project, context.home);
      assert.equal(result.status, 0, result.stderr);
      assert.match(result.stdout, /--manifest-sha256/); assert.match(result.stdout, /--check/);
      const descriptor = { 'blender_session.py': 'blender.json', 'freecad_session.py': 'freecad.json',
        'spatial_session.py': 'video-spatio.json' }[script];
      const manifest = path.join(path.dirname(directory), 'integrations/qwen', descriptor);
      const output = path.join(context.project, `absent-${script}`);
      const args = ['-I', '-B', path.join(directory, script), '--source-root', path.join(context.project, 'absent-source'),
        '--manifest', manifest, '--manifest-sha256', hashFile(manifest), '--output', output, '--check'];
      if (script === 'spatial_session.py') args.push('--inputs', path.join(context.project, 'absent-inputs'), '--inputs-sha256', '0'.repeat(64));
      else args.push(script === 'blender_session.py' ? '--blender' : '--freecad', path.join(context.project, 'absent-native'),
        script === 'blender_session.py' ? '--blender-sha256' : '--freecad-sha256', '0'.repeat(64));
      const refused = run(python, args, context.project, context.home);
      assert.equal(refused.status, 2, refused.stderr); assert.match(refused.stderr, /session refused/);
      assert.equal(fs.existsSync(output), false);
    }
    const report = run(python, ['-I', '-B', '-c',
      'import json, sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import spatial_session; print(json.dumps(spatial_session.runtime_report(json.loads(Path(sys.argv[2]).read_text()))))',
      directory, path.join(path.dirname(directory), 'integrations/qwen/video-spatio.json')], context.project, context.home);
    assert.equal(report.status, 0, report.stderr);
    assert.deepEqual(JSON.parse(report.stdout), { ready: false, state: 'source-only-runtime-blocked',
      runtime_clearance: 'blocked-missing-font-grant', foreign_imports: 0,
      hint: 'Do not serve until the selected complete runtime grants are verified' });
  }
});
