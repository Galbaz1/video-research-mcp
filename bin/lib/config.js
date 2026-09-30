'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const VERSION = require('../../package.json').version;

const MCP_SERVERS = {
  'video-research': { command: 'uvx', args: [`video-research-mcp==${VERSION}`] },
};
const OPTIONAL_SERVERS = {
  playwright: { command: 'npx', args: ['@playwright/mcp@0.0.83', '--headless', '--caps=vision,pdf'] },
  'mlflow-mcp': { command: 'uvx', args: ['--with', 'mlflow[mcp]>=3.16.1,<4', 'mlflow', 'mcp', 'run'] },
};
const DEPRECATED_SERVERS = ['video-explainer', 'video-agent'];

/** Resolve the intended Claude config without inspecting other clients. */
function getConfigPath(mode) {
  if (mode === 'local') return path.join(process.cwd(), '.mcp.json');
  const home = process.env.HOME || process.env.USERPROFILE;
  if (!home) throw new Error('Home directory is unavailable');
  return path.join(home, '.claude.json');
}

/** Refuse links at installer-owned destinations before reading or writing. */
function assertRegularDestination(filePath) {
  for (const candidate of [path.dirname(filePath), filePath]) {
    try {
      if (fs.lstatSync(candidate).isSymbolicLink()) throw new Error('Symlinked installer destination');
    } catch (err) {
      if (err.code !== 'ENOENT') throw err;
    }
  }
}

/** Atomically promote a private file; interruption cannot leave partial JSON. */
function atomicWrite(filePath, content) {
  assertRegularDestination(filePath);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.${crypto.randomUUID()}.tmp`;
  try {
    fs.writeFileSync(temporary, content, { flag: 'wx', mode: 0o600 });
    fs.renameSync(temporary, filePath);
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
}

/** Read JSON without echoing malformed bytes, paths, or credentials. */
function readConfig(configPath) {
  assertRegularDestination(configPath);
  let raw;
  try {
    if (fs.statSync(configPath).size > 16 * 1024 * 1024) throw new Error('Config exceeds installer size bound');
    raw = fs.readFileSync(configPath, 'utf8');
  }
  catch (err) { if (err.code === 'ENOENT') return null; throw new Error('Config is unreadable'); }
  let result;
  try { result = JSON.parse(raw); }
  catch { throw new Error('Malformed MCP configuration; repair it manually before installing'); }
  if (!result || typeof result !== 'object' || Array.isArray(result) ||
      (Object.hasOwn(result, 'mcpServers') && (!result.mcpServers ||
        typeof result.mcpServers !== 'object' || Array.isArray(result.mcpServers)))) {
    throw new Error('MCP configuration must contain an object');
  }
  return result;
}

/** Fingerprint owned config entries without retaining their values in diagnostics. */
function entryHash(entry) {
  return crypto.createHash('sha256').update(JSON.stringify(entry === undefined ? null : entry)).digest('hex');
}

/** Add the core entry; update only an entry proved unchanged since this installer owned it. */
function mergedConfig(existing, owned = {}) {
  existing = structuredClone(existing || {});
  existing.mcpServers = existing.mcpServers || {};
  for (const [name, entry] of Object.entries(MCP_SERVERS)) {
    const current = existing.mcpServers[name];
    if (current === undefined || (owned[name] && entryHash(current) === owned[name])) {
      existing.mcpServers[name] = entry;
    }
  }
  return existing;
}

/** Atomically register only the entries authorized by ownership evidence. */
function mergeConfig(configPath, owned = {}) {
  const result = mergedConfig(readConfig(configPath), owned);
  atomicWrite(configPath, JSON.stringify(result, null, 2) + '\n');
  return result;
}

/** Remove only unchanged installer-owned entries, retaining unrelated and customized servers. */
function removeFromConfig(configPath, owned = null) {
  const existing = readConfig(configPath);
  if (!existing?.mcpServers) return false;
  let removed = false;
  for (const [name, entry] of Object.entries(MCP_SERVERS)) {
    const expected = owned ? owned[name] : entryHash(entry);
    if (expected && entryHash(existing.mcpServers[name]) === expected) {
      delete existing.mcpServers[name];
      removed = true;
    }
  }
  if (removed) atomicWrite(configPath, JSON.stringify(existing, null, 2) + '\n');
  return removed;
}

const ENV_TEMPLATE_KEYS = [
  'GEMINI_API_KEY', 'GEMINI_MODEL', 'GEMINI_FLASH_MODEL', 'GEMINI_THINKING_LEVEL',
  'GEMINI_RETRY_MAX_ATTEMPTS', 'DEEP_RESEARCH_AGENT', 'YOUTUBE_API_KEY', 'S2_API_KEY',
  'WEAVIATE_URL', 'WEAVIATE_API_KEY', 'WEAVIATE_GRPC_URL', 'COHERE_API_KEY',
  'WEAVIATE_VECTORIZER', 'WEAVIATE_AUTO_MIGRATE', 'RERANKER_ENABLED',
  'GEMINI_TRACING_ENABLED', 'MLFLOW_TRACKING_URI', 'MLFLOW_EXPERIMENT_NAME',
  'EXPLAINER_PATH', 'EXPLAINER_TTS_PROVIDER', 'ELEVENLABS_API_KEY', 'OPENAI_API_KEY',
  'AGENT_MODEL', 'AGENT_CONCURRENCY', 'LOCAL_FILE_ACCESS_ROOT', 'MEDIA_MAX_INPUT_BYTES',
];

/** Create or append a private commented template; defaults come from the selected runtime. */
function envTemplate(existing) {
  const missing = ENV_TEMPLATE_KEYS.filter((key) => !existing.includes(`${key}=`));
  if (!missing.length) return existing;
  const header = existing ? '\n# Added by installer\n' :
    '# Private video-research-mcp configuration. Never share credential values.\n' +
    '# Unset settings inherit the selected Python runtime config defaults.\n' +
    '# Selected input is sent to configured providers only by authorized operations.\n';
  return existing + header + missing.map((key) => `# ${key}=`).join('\n') + '\n';
}

/** Ensure the shared template exists without choosing provider or model defaults. */
function ensureEnvFile() {
  const home = process.env.HOME || process.env.USERPROFILE;
  if (!home) return null;
  const envPath = path.join(home, '.config', 'video-research-mcp', '.env');
  assertRegularDestination(envPath);
  let existing = '';
  try { existing = fs.readFileSync(envPath, 'utf8'); }
  catch (err) { if (err.code !== 'ENOENT') throw err; }
  const template = envTemplate(existing);
  if (template !== existing) atomicWrite(envPath, template);
  return { path: envPath, created: !existing, added: ENV_TEMPLATE_KEYS.filter((key) => !existing.includes(`${key}=`)).length };
}

module.exports = {
  MCP_SERVERS, OPTIONAL_SERVERS, DEPRECATED_SERVERS, ENV_TEMPLATE_KEYS,
  getConfigPath, readConfig, mergeConfig, removeFromConfig, ensureEnvFile,
  atomicWrite, assertRegularDestination, entryHash, mergedConfig, envTemplate,
};
