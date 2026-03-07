'use strict';

const fs = require('fs');
const path = require('path');

/**
 * Source-to-destination file mapping.
 * Keys = paths relative to npm package root.
 * Values = paths relative to target dir (~/.claude/ or ./.claude/).
 * Commands land under commands/gr/ and commands/ve/ for their namespaces.
 */
const FILE_MAP = {
  'commands/video.md':      'commands/gr/video.md',
  'commands/video-chat.md': 'commands/gr/video-chat.md',
  'commands/research.md':   'commands/gr/research.md',
  'commands/analyze.md':    'commands/gr/analyze.md',
  'commands/search.md':     'commands/gr/search.md',
  'commands/recall.md':     'commands/gr/recall.md',
  'commands/models.md':     'commands/gr/models.md',
  'commands/doctor.md':        'commands/gr/doctor.md',
  'commands/traces.md':        'commands/gr/traces.md',
  'commands/research-doc.md':  'commands/gr/research-doc.md',
  'commands/ingest.md':        'commands/gr/ingest.md',
  'commands/getting-started.md': 'commands/gr/getting-started.md',
  'commands/research-deep.md':   'commands/gr/research-deep.md',
  'commands/advisor.md':         'commands/gr/advisor.md',

  'commands/explainer.md':      'commands/ve/explainer.md',
  'commands/explain-video.md':  'commands/ve/explain-video.md',
  'commands/explain-status.md': 'commands/ve/explain-status.md',

  'skills/video-research/SKILL.md':                              'skills/video-research/SKILL.md',
  'skills/gemini-visualize/SKILL.md':                             'skills/gemini-visualize/SKILL.md',
  'skills/gemini-visualize/templates/video-concept-map.md':       'skills/gemini-visualize/templates/video-concept-map.md',
  'skills/gemini-visualize/templates/research-evidence-net.md':   'skills/gemini-visualize/templates/research-evidence-net.md',
  'skills/gemini-visualize/templates/content-knowledge-graph.md': 'skills/gemini-visualize/templates/content-knowledge-graph.md',

  'skills/video-explainer/SKILL.md':                             'skills/video-explainer/SKILL.md',
  'skills/weaviate-setup/SKILL.md':                             'skills/weaviate-setup/SKILL.md',
  'skills/mlflow-traces/SKILL.md':                              'skills/mlflow-traces/SKILL.md',
  'skills/research-brief-builder/SKILL.md':                      'skills/research-brief-builder/SKILL.md',
  'skills/gr-advisor/SKILL.md':                                  'skills/gr-advisor/SKILL.md',

  'agents/researcher.md':      'agents/researcher.md',
  'agents/video-analyst.md':   'agents/video-analyst.md',
  'agents/visualizer.md':      'agents/visualizer.md',
  'agents/comment-analyst.md': 'agents/comment-analyst.md',
  'agents/video-producer.md':    'agents/video-producer.md',
  'agents/content-to-video.md':  'agents/content-to-video.md',
  'agents/gr-advisor.md':        'agents/gr-advisor.md',
};

/** Directories to clean up during uninstall (deepest first). */
const CLEANUP_DIRS = [
  'skills/gemini-visualize/templates',
  'skills/gemini-visualize',
  'skills/video-research',
  'skills/video-explainer',
  'skills/weaviate-setup',
  'skills/mlflow-traces',
  'skills/research-brief-builder',
  'skills/gr-advisor',
  'commands/gr',
  'commands/ve',
];

/** Copy files from sourceDir to targetDir based on action list. */
function copyFiles(sourceDir, targetDir, actions) {
  const copied = [];
  for (const action of actions) {
    const srcPath = path.join(sourceDir, action.src);
    const destPath = path.join(targetDir, action.dest);
    fs.mkdirSync(path.dirname(destPath), { recursive: true });
    fs.copyFileSync(srcPath, destPath);
    copied.push(action);
  }
  return copied;
}

/** Remove files from targetDir based on action list. */
function removeFiles(targetDir, actions) {
  const removed = [];
  for (const action of actions) {
    const destPath = path.join(targetDir, action.dest);
    try {
      fs.unlinkSync(destPath);
      removed.push(action);
    } catch {
      // Already gone
    }
  }
  return removed;
}

/** Remove empty directories, deepest first. */
function cleanEmptyDirs(targetDir, extraDirs) {
  const allDirs = [...CLEANUP_DIRS, ...extraDirs];
  const sorted = [...new Set(allDirs)].sort(
    (a, b) => b.split(/[/\\]/).length - a.split(/[/\\]/).length,
  );
  for (const dirRel of sorted) {
    const dirPath = path.join(targetDir, dirRel);
    try {
      const entries = fs.readdirSync(dirPath);
      if (entries.length === 0) fs.rmdirSync(dirPath);
    } catch {
      // Doesn't exist or not empty
    }
  }
}

module.exports = { FILE_MAP, CLEANUP_DIRS, copyFiles, removeFiles, cleanEmptyDirs };
