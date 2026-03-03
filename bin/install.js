#!/usr/bin/env node
'use strict';

const path = require('path');
const fs = require('fs');
const readline = require('readline');
const { execSync } = require('child_process');

const ui = require('./lib/ui');
const { FILE_MAP, copyFiles, removeFiles, cleanEmptyDirs } = require('./lib/copy');
const {
  hashFile,
  readManifest,
  writeManifest,
  deleteManifest,
  computeActions,
} = require('./lib/manifest');
const { getConfigPath, mergeConfig, removeFromConfig, ensureEnvFile } = require('./lib/config');

const VERSION = require('../package.json').version;

// ---------------------------------------------------------------------------
// CLI parsing
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const args = argv.slice(2);
  return {
    global: args.includes('--global'),
    local: args.includes('--local'),
    check: args.includes('--check'),
    uninstall: args.includes('--uninstall'),
    force: args.includes('--force'),
    help: args.includes('--help') || args.includes('-h'),
  };
}

function showHelp() {
  process.stderr.write(`
video-research-mcp installer v${VERSION}

Usage: npx video-research-mcp@latest [options]

Options:
  --global      Install globally to ~/.claude/
  --local       Install locally to ./.claude/
  --check       Show current install status
  --uninstall   Remove installed files and config
  --force       Overwrite user-modified files
  --help, -h    Show this help

Without flags, prompts for global vs local install.
\n`);
}

// ---------------------------------------------------------------------------
// Prompts & checks
// ---------------------------------------------------------------------------

async function promptMode() {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stderr,
  });
  return new Promise((resolve) => {
    process.stderr.write('Install mode:\n');
    process.stderr.write('  1) Global (~/.claude/) \u2014 available in all projects\n');
    process.stderr.write('  2) Local  (./.claude/) \u2014 this project only\n\n');
    rl.question('Choice [1]: ', (answer) => {
      rl.close();
      resolve(answer.trim() === '2' ? 'local' : 'global');
    });
  });
}

/** Check for uv and python3 — warn if missing, never block. */
function checkPrereqs() {
  const checks = [];
  // Safe: hardcoded commands, no user input
  try {
    execSync('uv --version', { stdio: 'pipe' });
    checks.push({ name: 'uv', ok: true });
  } catch {
    checks.push({
      name: 'uv',
      ok: false,
      hint: 'Install from https://docs.astral.sh/uv/',
    });
  }
  try {
    execSync('python3 --version', { stdio: 'pipe' });
    checks.push({ name: 'python3', ok: true });
  } catch {
    checks.push({ name: 'python3', ok: false, hint: 'Python >= 3.11 required' });
  }
  return checks;
}

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

function getHomeDir() {
  const home = process.env.HOME || process.env.USERPROFILE;
  if (!home) {
    throw new Error(
      'Cannot determine home directory: HOME and USERPROFILE are both unset',
    );
  }
  return home;
}

function getTargetDir(mode) {
  if (mode === 'global') {
    return path.join(getHomeDir(), '.claude');
  }
  return path.join(process.cwd(), '.claude');
}

function getSourceDir() {
  return path.resolve(__dirname, '..');
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

function showStatus(mode) {
  const targetDir = getTargetDir(mode);
  const manifest = readManifest(targetDir);

  if (!manifest.installedAt) {
    ui.info(`No ${mode} installation found`);
    return;
  }

  ui.header(`${mode} installation`);
  ui.step(`Version:   ${manifest.version || 'unknown'}`);
  ui.step(`Installed: ${manifest.installedAt}`);
  ui.step(`Mode:      ${manifest.mode || mode}`);
  ui.step(`Files:     ${Object.keys(manifest.files).length}`);

  let modified = 0;
  for (const [rel, entry] of Object.entries(manifest.files)) {
    const currentHash = hashFile(path.join(targetDir, rel));
    if (currentHash && currentHash !== entry.hash) modified++;
  }
  if (modified > 0) ui.warn(`${modified} file(s) modified since install`);
}

// ---------------------------------------------------------------------------
// Install
// ---------------------------------------------------------------------------

async function install(mode, force) {
  const sourceDir = getSourceDir();
  const targetDir = getTargetDir(mode);
  const configPath = getConfigPath(mode);

  ui.header(`video-research-mcp v${VERSION}`);

  // Prerequisites
  const prereqs = checkPrereqs();
  for (const p of prereqs) {
    if (p.ok) {
      ui.success(`${p.name} found`);
    } else {
      ui.warn(`${p.name} not found \u2014 ${p.hint}`);
    }
  }
  ui.blank();

  // Compute actions
  const manifest = readManifest(targetDir);
  const actions = computeActions(sourceDir, targetDir, FILE_MAP, manifest, force);

  // Copy files
  if (actions.toCopy.length > 0) {
    copyFiles(sourceDir, targetDir, actions.toCopy);
    for (const a of actions.toCopy) {
      ui.success(`${a.reason === 'new' ? 'Added' : 'Updated'} ${a.dest}`);
    }
  }

  // Report user-modified skips
  for (const s of actions.toSkip) {
    if (s.reason === 'user modified') {
      ui.warn(`Skipped ${s.dest} (user modified \u2014 use --force to overwrite)`);
    }
  }

  // Remove obsolete files
  if (actions.toRemove.length > 0) {
    removeFiles(targetDir, actions.toRemove);
    for (const r of actions.toRemove) {
      ui.info(`Removed obsolete ${r.dest}`);
    }
  }

  // Merge MCP config — degrade gracefully so the manifest is still written
  try {
    mergeConfig(configPath);
    ui.success(`MCP config updated: ${configPath}`);
  } catch (err) {
    ui.warn(`MCP config not updated: ${err.message}`);
  }

  // Ensure shared env file exists
  try {
    const envResult = ensureEnvFile();
    if (envResult?.created) {
      ui.success(`Created config template: ${envResult.path}`);
    } else if (envResult?.added > 0) {
      ui.success(`Added ${envResult.added} new key(s) to ${envResult.path}`);
    }
  } catch {
    // Non-fatal — server works without it
  }

  // Write manifest — preserve old hash for user-modified files so uninstall
  // can still detect the modification and skip removal.
  const userModified = new Set(
    actions.toSkip.filter((s) => s.reason === 'user modified').map((s) => s.dest),
  );
  const newManifest = {
    version: VERSION,
    mode,
    installedAt: new Date().toISOString(),
    files: {},
  };
  for (const destRel of Object.values(FILE_MAP)) {
    if (userModified.has(destRel) && manifest.files[destRel]) {
      newManifest.files[destRel] = manifest.files[destRel];
    } else {
      const hash = hashFile(path.join(targetDir, destRel));
      if (hash) newManifest.files[destRel] = { hash };
    }
  }
  writeManifest(targetDir, newManifest);

  // Summary
  ui.blank();
  const upToDate = actions.toSkip.filter((s) => s.reason === 'up to date').length;
  const userMod = actions.toSkip.filter((s) => s.reason === 'user modified').length;
  ui.step(
    `${actions.toCopy.length} copied, ${upToDate} up to date, ` +
    `${userMod} user-modified, ${actions.toRemove.length} removed`,
  );
  ui.blank();

  // Next steps
  ui.header('Next steps');
  let stepNum = 1;
  if (!process.env.GEMINI_API_KEY) {
    ui.step(`${stepNum}. Get a Gemini API key (free):`);
    ui.step('   https://aistudio.google.com/apikey');
    ui.blank();
    stepNum++;
    ui.step(`${stepNum}. Paste it in the config file:`);
    ui.step('   ~/.config/video-research-mcp/.env');
    ui.step('   (This file stays on your machine — never uploaded or shared)');
    ui.blank();
    stepNum++;
  }
  ui.step(`${stepNum}. Restart Claude Code, then run:`);
  ui.step('   /gr:getting-started');
  ui.blank();
  ui.step('   This will verify your setup and show you what\'s available.');
  ui.blank();
}

// ---------------------------------------------------------------------------
// Uninstall
// ---------------------------------------------------------------------------

async function uninstall(mode) {
  const targetDir = getTargetDir(mode);
  const configPath = getConfigPath(mode);
  const manifest = readManifest(targetDir);

  if (!manifest.installedAt) {
    ui.info(`No ${mode} installation found`);
    return;
  }

  ui.header(`Uninstalling video-research-mcp (${mode})`);

  let removed = 0;
  let skipped = 0;
  const dirsToClean = new Set();

  for (const [destRel, entry] of Object.entries(manifest.files)) {
    const destPath = path.join(targetDir, destRel);
    const currentHash = hashFile(destPath);

    if (!currentHash) continue;

    if (currentHash !== entry.hash) {
      ui.warn(`Kept ${destRel} (user modified)`);
      skipped++;
    } else {
      try {
        fs.unlinkSync(destPath);
        ui.success(`Removed ${destRel}`);
        removed++;
        dirsToClean.add(path.dirname(destRel));
      } catch {
        skipped++;
      }
    }
  }

  cleanEmptyDirs(targetDir, [...dirsToClean]);

  // Remove MCP config entries
  try {
    if (removeFromConfig(configPath)) {
      ui.success(`MCP config cleaned: ${configPath}`);
    }
  } catch {
    // Config file might not exist
  }

  deleteManifest(targetDir);

  ui.blank();
  ui.step(`${removed} removed, ${skipped} kept`);
  ui.blank();
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const flags = parseArgs(process.argv);

  if (flags.help) {
    showHelp();
    return;
  }

  if (flags.check) {
    showStatus('global');
    showStatus('local');
    return;
  }

  // Determine mode
  let mode;
  if (flags.global) {
    mode = 'global';
  } else if (flags.local) {
    mode = 'local';
  } else if (flags.uninstall) {
    // Uninstall without mode flag: clean up whichever installations exist
    const globalManifest = readManifest(getTargetDir('global'));
    const localManifest = readManifest(getTargetDir('local'));
    if (globalManifest.installedAt) await uninstall('global');
    if (localManifest.installedAt) await uninstall('local');
    if (!globalManifest.installedAt && !localManifest.installedAt) {
      ui.info('No installation found');
    }
    return;
  } else {
    mode = await promptMode();
  }

  if (flags.uninstall) {
    await uninstall(mode);
  } else {
    await install(mode, flags.force);
  }
}

main().catch((err) => {
  ui.error(err.message);
  process.exit(1);
});
