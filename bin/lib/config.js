'use strict';

const fs = require('fs');
const path = require('path');
const ui = require('./ui');

/**
 * MCP server entries to install.
 *
 * Only include servers that are published to a public registry (PyPI or npm).
 * Unpublished packages (video-explainer-mcp, video-agent-mcp) are excluded
 * because `uvx` cannot resolve them — users who need them must add local
 * `uv run --directory` entries manually.
 */
const MCP_SERVERS = {
  'video-research': {
    command: 'uvx',
    args: ['video-research-mcp[tracing]'],
  },
  playwright: {
    command: 'npx',
    args: ['@playwright/mcp@0.0.68', '--headless', '--caps=vision,pdf'],
  },
  'mlflow-mcp': {
    command: 'uvx',
    args: ['--with', 'mlflow[mcp]>=3.5.1', 'mlflow', 'mcp', 'run'],
  },
};

/**
 * Servers previously installed by older versions that should be removed on
 * upgrade. These packages were never published to PyPI, so their entries
 * always fail. Cleaned up automatically during mergeConfig().
 */
const DEPRECATED_SERVERS = ['video-explainer', 'video-agent'];

/**
 * Return the path to the MCP config file.
 * Global: ~/.claude/.mcp.json
 * Local:  ./.mcp.json (project root, not inside .claude/)
 */
function getConfigPath(mode) {
  if (mode === 'global') {
    const home = process.env.HOME || process.env.USERPROFILE;
    if (!home) {
      throw new Error(
        'Cannot determine home directory: HOME and USERPROFILE are both unset',
      );
    }
    return path.join(home, '.claude', '.mcp.json');
  }
  return path.join(process.cwd(), '.mcp.json');
}

/** Read and parse a JSON config file. Returns null if not found. Throws on malformed JSON. */
function readConfig(configPath) {
  try {
    const raw = fs.readFileSync(configPath, 'utf8');
    return JSON.parse(raw);
  } catch (err) {
    if (err.code === 'ENOENT') return null;
    if (err instanceof SyntaxError) {
      ui.error(`Malformed JSON in ${configPath}`);
      ui.info('Fix the file manually or delete it to start fresh');
      throw err;
    }
    throw err;
  }
}

/** Merge MCP_SERVERS into the config file. Creates the file if it doesn't exist. */
function mergeConfig(configPath) {
  const existing = readConfig(configPath) || {};
  existing.mcpServers = existing.mcpServers || {};

  for (const [name, config] of Object.entries(MCP_SERVERS)) {
    existing.mcpServers[name] = config;
  }

  // Remove deprecated servers left by older installer versions
  for (const name of DEPRECATED_SERVERS) {
    delete existing.mcpServers[name];
  }

  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  fs.writeFileSync(configPath, JSON.stringify(existing, null, 2) + '\n');
  return existing;
}

/** Remove MCP_SERVERS entries from the config file. Returns true if any were removed. */
function removeFromConfig(configPath) {
  const existing = readConfig(configPath);
  if (!existing?.mcpServers) return false;

  let removed = false;
  for (const name of Object.keys(MCP_SERVERS)) {
    if (existing.mcpServers[name]) {
      delete existing.mcpServers[name];
      removed = true;
    }
  }

  if (removed) {
    fs.writeFileSync(configPath, JSON.stringify(existing, null, 2) + '\n');
  }
  return removed;
}

/**
 * Template for ~/.config/video-research-mcp/.env.
 * Keys listed here will be appended (commented) if missing from an existing file.
 */
const ENV_TEMPLATE_KEYS = [
  'GEMINI_API_KEY',
  'YOUTUBE_API_KEY',
  'WEAVIATE_URL',
  'WEAVIATE_API_KEY',
  'WEAVIATE_GRPC_URL',
  'MLFLOW_TRACKING_URI',
  'MLFLOW_EXPERIMENT_NAME',
  'EXPLAINER_PATH',
  'EXPLAINER_TTS_PROVIDER',
  'ELEVENLABS_API_KEY',
  'OPENAI_API_KEY',
  'WEAVIATE_VECTORIZER',
  'WEAVIATE_AUTO_MIGRATE',
];

/**
 * Ensure ~/.config/video-research-mcp/.env exists with a commented template.
 * If the file already exists, append any new keys that are missing.
 * Returns the path to the env file.
 */
function ensureEnvFile() {
  const home = process.env.HOME || process.env.USERPROFILE;
  if (!home) return null;

  const envDir = path.join(home, '.config', 'video-research-mcp');
  const envPath = path.join(envDir, '.env');

  fs.mkdirSync(envDir, { recursive: true });

  if (!fs.existsSync(envPath)) {
    const lines = [
      '# video-research-mcp shared configuration',
      '# ─────────────────────────────────────────────────────────────',
      '# This file is read by the MCP server at startup.',
      '# It lives on YOUR machine only — it is NOT uploaded anywhere.',
      '# Process env vars always take precedence over values here.',
      '#',
      '# Security:',
      '#   - This file is stored in your user config dir (chmod 600 recommended)',
      '#   - It is never committed to git or sent to any remote service',
      '#   - The server reads it locally at startup, that\'s it',
      '# ─────────────────────────────────────────────────────────────',
      '',
      '# Required — get yours at https://aistudio.google.com/apikey',
      '# GEMINI_API_KEY=',
      '',
      '# Optional — falls back to GEMINI_API_KEY if not set',
      '# YOUTUBE_API_KEY=',
      '',
      '# Optional — knowledge store (leave commented to disable)',
      '# WEAVIATE_URL=',
      '# WEAVIATE_API_KEY=',
      '# WEAVIATE_GRPC_URL=',
      '#',
      '# Vectorizer: auto-detects based on OPENAI_API_KEY.',
      '#   weaviate = built-in embeddings, no extra key (good for Docker)',
      '#   openai   = text2vec-openai, requires OPENAI_API_KEY',
      '# WEAVIATE_VECTORIZER=',
      '# WEAVIATE_AUTO_MIGRATE=',
      '',
      '# Optional — MLflow tracing (leave commented to disable)',
      '# MLFLOW_TRACKING_URI=http://127.0.0.1:5001',
      '# MLFLOW_EXPERIMENT_NAME=video-research-mcp',
      '',
      '# Video Explainer — path to cloned video_explainer repo (required for /ve: commands)',
      '# EXPLAINER_PATH=',
      '# EXPLAINER_TTS_PROVIDER=mock',
      '',
      '# Optional — ElevenLabs TTS (recommended for production)',
      '# ELEVENLABS_API_KEY=',
      '',
      '# Optional — OpenAI TTS (budget alternative)',
      '# OPENAI_API_KEY=',
      '',
    ];
    fs.writeFileSync(envPath, lines.join('\n'), { mode: 0o600 });
    return { path: envPath, created: true, added: 0 };
  }

  // Append missing keys
  const existing = fs.readFileSync(envPath, 'utf8');
  const missing = ENV_TEMPLATE_KEYS.filter(
    (k) => !existing.includes(`${k}=`),
  );
  if (missing.length > 0) {
    const suffix =
      '\n# Added by installer\n' + missing.map((k) => `# ${k}=`).join('\n') + '\n';
    fs.appendFileSync(envPath, suffix);
  }
  return { path: envPath, created: false, added: missing.length };
}

module.exports = {
  MCP_SERVERS,
  DEPRECATED_SERVERS,
  getConfigPath,
  readConfig,
  mergeConfig,
  removeFromConfig,
  ensureEnvFile,
};
