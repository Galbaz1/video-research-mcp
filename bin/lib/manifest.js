'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const MANIFEST_FILE = 'gr-file-manifest.json';

/** Return SHA-256 of readable bytes; only an absent file has a null identity. */
function hashFile(filePath) {
  try {
    const content = fs.readFileSync(filePath);
    return crypto.createHash('sha256').update(content).digest('hex');
  } catch (err) {
    if (err.code === 'ENOENT') return null;
    throw new Error('Installer file identity is unreadable');
  }
}

/** Reject escaping paths and symlink ancestors before touching managed files. */
function validatePath(targetDir, rel) {
  const components = rel.split('/');
  if (!/^(commands|skills|agents)\//.test(rel) || rel.includes('\\') ||
      components.some((part) => !part || part === '.' || part === '..')) {
    throw new Error(`Unsafe install manifest path: ${rel}`);
  }
  let current = path.resolve(targetDir);
  for (const component of components) {
    current = path.join(current, component);
    try {
      if (fs.lstatSync(current).isSymbolicLink()) {
        throw new Error(`Unsafe symlink in install path: ${rel}`);
      }
    } catch (err) {
      if (err.code === 'ENOENT') break;
      throw err;
    }
  }
}

/** Validate ownership evidence supplied by the install manifest. */
function validateManifest(targetDir, manifest) {
  if (!manifest.files || typeof manifest.files !== 'object' || Array.isArray(manifest.files)) {
    throw new Error('Invalid install manifest: files must be an object');
  }
  for (const rel of Object.keys(manifest.files)) {
    validatePath(targetDir, rel);
    if (!/^[a-f0-9]{64}$/.test(manifest.files[rel]?.hash || '')) {
      throw new Error(`Invalid install manifest hash: ${rel}`);
    }
  }
  return manifest;
}

/** Read the manifest; malformed state fails safely instead of adopting existing files. */
function readManifest(targetDir) {
  const manifestPath = path.join(targetDir, MANIFEST_FILE);
  try {
    return validateManifest(targetDir, JSON.parse(fs.readFileSync(manifestPath, 'utf8')));
  } catch (err) {
    if (err.code === 'ENOENT') return { version: null, files: {}, installedAt: null, mode: null };
    throw err;
  }
}

/** Write the install manifest to targetDir. Creates directory if needed. */
function writeManifest(targetDir, manifest) {
  const manifestPath = path.join(targetDir, MANIFEST_FILE);
  fs.mkdirSync(targetDir, { recursive: true });
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
}

/** Delete the manifest file. Returns true if deleted. */
function deleteManifest(targetDir) {
  const manifestPath = path.join(targetDir, MANIFEST_FILE);
  try {
    fs.unlinkSync(manifestPath);
    return true;
  } catch {
    return false;
  }
}

/**
 * Compute install actions by comparing source, destination, and manifest hashes.
 *
 * Returns { toCopy, toSkip, toRemove } arrays describing what to do for each file.
 */
function computeActions(sourceDir, targetDir, fileMap, manifest, force) {
  validateManifest(targetDir, manifest);
  const toCopy = [];
  const toSkip = [];
  const toRemove = [];

  for (const [srcRel, destRel] of Object.entries(fileMap)) {
    validatePath(targetDir, destRel);
    const srcPath = path.join(sourceDir, srcRel);
    const destPath = path.join(targetDir, destRel);
    const srcHash = hashFile(srcPath);

    if (!srcHash) {
      toSkip.push({ dest: destRel, reason: 'source missing' });
      continue;
    }

    const destHash = hashFile(destPath);
    const manifestHash = manifest.files[destRel]?.hash;

    if (!destHash) {
      toCopy.push({ src: srcRel, dest: destRel, reason: 'new' });
    } else if (destHash === srcHash) {
      toSkip.push({ dest: destRel, reason: 'up to date' });
    } else if ((!manifestHash || destHash !== manifestHash) && !force) {
      toSkip.push({ dest: destRel, reason: 'user modified' });
    } else {
      toCopy.push({ src: srcRel, dest: destRel, reason: 'updated' });
    }
  }

  // Detect files removed from the file map since last install
  if (manifest.files) {
    const destValues = new Set(Object.values(fileMap));
    for (const destRel of Object.keys(manifest.files)) {
      if (!destValues.has(destRel)) {
        const destPath = path.join(targetDir, destRel);
        const currentHash = hashFile(destPath);
        if (!currentHash) continue;
        const manifestHash = manifest.files[destRel]?.hash;
        if (manifestHash && currentHash !== manifestHash && !force) {
          toSkip.push({ dest: destRel, reason: 'user modified (obsolete)' });
        } else {
          toRemove.push({ dest: destRel });
        }
      }
    }
  }

  return { toCopy, toSkip, toRemove };
}

module.exports = {
  MANIFEST_FILE,
  hashFile,
  readManifest,
  writeManifest,
  deleteManifest,
  computeActions,
};
