'use strict';

const assert = require('node:assert/strict');
const { test, before, after } = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const config = require('../bin/lib/config');
const pkg = require('../package.json');

const SOURCE = path.resolve(__dirname, '..');
// Agent Plugins 1.0.0 plugin.schema.json forbids other top-level keys.
const PLUGIN_KEYS = ['$schema', 'name', 'version', 'description', 'author', 'homepage',
  'repository', 'license', 'keywords', 'extensions'];

let work;
let root;

before(() => {
  work = fs.mkdtempSync(path.join(os.tmpdir(), 'vr-codex-plugin-'));
  // Codex fetches npm plugin sources without lifecycle scripts; pack the same way.
  const [packed] = JSON.parse(execFileSync('npm',
    ['pack', '--ignore-scripts', '--json', '--pack-destination', work],
    { cwd: SOURCE, encoding: 'utf8' }));
  execFileSync('tar', ['-xzf', path.join(work, packed.filename), '-C', work]);
  root = path.join(work, 'package');
});

after(() => fs.rmSync(work, { recursive: true, force: true }));

function readJson(relative) {
  return JSON.parse(fs.readFileSync(path.join(root, relative), 'utf8'));
}

function frontmatter(text) {
  const block = text.match(/^---\n([\s\S]*?)\n---\n/)?.[1] ?? '';
  const field = (key) => block.match(new RegExp(`^${key}:\\s*"?(.*?)"?\\s*$`, 'm'))?.[1];
  return { name: field('name'), description: field('description') };
}

test('packed payload is a portable Agent Plugins root with a stable identity', () => {
  const manifest = readJson('plugin.json');
  assert.equal(manifest.$schema, 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json');
  assert.deepEqual(Object.keys(manifest).filter((key) => !PLUGIN_KEYS.includes(key)), []);
  assert.equal(manifest.name, 'video-research');
  assert.equal(manifest.version, pkg.version);
  assert.equal(manifest.extensions['com.openai'].interface.displayName, 'Video Research');
  // Codex discovers hooks/hooks.json by default; this plugin must execute nothing on load.
  assert.equal(fs.existsSync(path.join(root, 'hooks')), false);
  assert.deepEqual(Object.keys(pkg.scripts).filter((name) => /^(pre|post)?install$|^prepare$/.test(name)), []);
});

test('packed mcp.json launches the version-matched runtime the Claude installer registers', () => {
  const declaration = readJson('mcp.json');
  assert.deepEqual(Object.keys(declaration), ['$schema', 'mcpServers']);
  assert.equal(declaration.$schema, 'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json');
  assert.deepEqual(declaration.mcpServers, {
    'video-research': { type: 'stdio', ...config.MCP_SERVERS['video-research'] },
  });
  assert.deepEqual(declaration.mcpServers['video-research'].args, [`video-research-mcp==${pkg.version}`]);
  // Codex silently drops Agent Plugins stdio servers whose command is an absolute or uncontained path.
  for (const server of Object.values(declaration.mcpServers)) {
    assert.match(server.command, /^(?:[^/\\]+|\.\/(?!.*\.\.)[^\\]+)$/, server.command);
  }
});

test('video-to-skill names helper paths that resolve in native and Claude layouts', (t) => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'vr-claude-layout-'));
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  execFileSync(process.execPath, [path.join(SOURCE, 'bin/install.js'), '--local'],
    { cwd: home, env: { ...process.env, HOME: home, USERPROFILE: home }, stdio: 'ignore' });
  const layouts = {
    native: path.join(root, 'skills/video-to-skill'),
    claude: path.join(home, '.claude/skills/video-to-skill'),
  };
  for (const [layout, directory] of Object.entries(layouts)) {
    const named = fs.readFileSync(path.join(directory, 'SKILL.md'), 'utf8').match(/(?:\.\.\/)*scripts\/\w+\.py/g) ?? [];
    for (const helper of ['validate_video_skill.py', 'package_video_skill.py']) {
      const found = named.map((relative) => path.resolve(directory, relative))
        .find((candidate) => path.basename(candidate) === helper && fs.existsSync(candidate));
      assert.ok(found, `${layout} layout cannot resolve ${helper}`);
      assert.ok(fs.existsSync(path.join(path.dirname(found), 'video_skill_contract.py')), `${layout} ${helper} contract`);
    }
  }
});

test('packed payload carries every tracked skill with valid metadata and resolvable links', () => {
  const tracked = execFileSync('git', ['ls-files', 'skills'], { cwd: SOURCE, encoding: 'utf8' })
    .split('\n').filter(Boolean);
  for (const file of tracked) {
    assert.deepEqual(fs.readFileSync(path.join(root, file)), fs.readFileSync(path.join(SOURCE, file)), file);
  }
  for (const skill of fs.readdirSync(path.join(root, 'skills'))) {
    const { name, description } = frontmatter(
      fs.readFileSync(path.join(root, 'skills', skill, 'SKILL.md'), 'utf8'));
    assert.equal(name, skill);
    assert.ok(description && description.length <= 1024, `${skill} description`);
  }
  for (const file of tracked.filter((name) => name.endsWith('.md'))) {
    const text = fs.readFileSync(path.join(root, file), 'utf8');
    for (const [, target] of text.matchAll(/\]\(([^)\s#]+)[^)]*\)/g)) {
      if (/^[a-z][a-z0-9+.-]*:/i.test(target)) continue;
      const resolved = path.resolve(root, path.dirname(file), target);
      assert.ok(resolved.startsWith(root + path.sep) && fs.existsSync(resolved), `${file} -> ${target}`);
    }
  }
});

test('creative brief and production routes resolve in packed native and Claude layouts', (t) => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'vr-creative-layout-'));
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  execFileSync(process.execPath, [path.join(root, 'bin/install.js'), '--local'],
    { cwd: home, env: { PATH: process.env.PATH, HOME: home, USERPROFILE: home }, stdio: 'ignore' });
  for (const layout of [root, path.join(home, '.claude')]) {
    const skill = path.join(layout, 'skills/creative-concept-design/SKILL.md');
    const brief = path.join(path.dirname(skill), 'templates/production-brief.md');
    const creativeFiles = ['skills/creative-concept-design/SKILL.md',
      'skills/creative-concept-design/templates/production-brief.md',
      ...['art-direction.md', 'motion-and-rhythm.md', 'narration-audition.md', 'current-media-routes.md'].map(name =>
        `skills/creative-concept-design/references/${name}`)];
    for (const relative of creativeFiles) {
      assert.deepEqual(fs.readFileSync(path.join(layout, relative)),
        fs.readFileSync(path.join(SOURCE, relative)), relative);
      const document = path.join(layout, relative);
      for (const [, target] of fs.readFileSync(document, 'utf8').matchAll(/\]\(([^)\s#]+)[^)]*\)/g)) {
        if (/^[a-z][a-z0-9+.-]*:/i.test(target)) continue;
        assert.ok(fs.existsSync(path.resolve(path.dirname(document), target)), `${relative} -> ${target}`);
      }
    }
    assert.ok(fs.existsSync(brief));
    const routes = [...fs.readFileSync(skill, 'utf8').matchAll(/\]\(([^)\s#]+)[^)]*\)/g)]
      .map(([, target]) => path.resolve(path.dirname(skill), target));
    for (const name of ['image-generation', 'video-generation', 'tts-production',
      'ffmpeg-production', 'video-production', 'video-explainer']) {
      assert.ok(routes.includes(path.join(layout, 'skills', name, 'SKILL.md')), name);
    }
    assert.ok(routes.includes(brief));
    for (const route of routes) assert.ok(fs.existsSync(route), route);
    const production = path.join(layout, 'skills/video-production/SKILL.md');
    const links = [...fs.readFileSync(production, 'utf8').matchAll(/\]\(([^)\s#]+)[^)]*\)/g)]
      .map(([, target]) => path.resolve(path.dirname(production), target));
    assert.ok(links.includes(skill));
  }
});
