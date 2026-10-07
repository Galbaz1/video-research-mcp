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
  'skills/plugin-maintenance/SKILL.md':                          'skills/plugin-maintenance/SKILL.md',
  'skills/gemini-visualize/SKILL.md':                             'skills/gemini-visualize/SKILL.md',
  'skills/gemini-visualize/templates/video-concept-map.md':       'skills/gemini-visualize/templates/video-concept-map.md',
  'skills/gemini-visualize/templates/research-evidence-net.md':   'skills/gemini-visualize/templates/research-evidence-net.md',
  'skills/gemini-visualize/templates/content-knowledge-graph.md': 'skills/gemini-visualize/templates/content-knowledge-graph.md',

  'skills/video-explainer/SKILL.md':                             'skills/video-explainer/SKILL.md',
  'skills/weaviate-setup/SKILL.md':                             'skills/weaviate-setup/SKILL.md',
  'skills/mlflow-traces/SKILL.md':                              'skills/mlflow-traces/SKILL.md',
  'skills/research-brief-builder/SKILL.md':                      'skills/research-brief-builder/SKILL.md',
  'skills/gr-advisor/SKILL.md':                                  'skills/gr-advisor/SKILL.md',
  'skills/tts-production/SKILL.md':                              'skills/tts-production/SKILL.md',
  'skills/tts-production/references/ffmpeg-audio-recipes.md':    'skills/tts-production/references/ffmpeg-audio-recipes.md',
  'skills/ffmpeg-production/SKILL.md':                           'skills/ffmpeg-production/SKILL.md',
  'skills/ffmpeg-production/references/platform-presets.md':     'skills/ffmpeg-production/references/platform-presets.md',
  'skills/video-generation/SKILL.md':                            'skills/video-generation/SKILL.md',
  'skills/video-generation/references/provider-details.md':      'skills/video-generation/references/provider-details.md',
  'skills/video-production/SKILL.md':                            'skills/video-production/SKILL.md',
  'skills/video-production/references/workflow-patterns.md':     'skills/video-production/references/workflow-patterns.md',
  'skills/image-generation/SKILL.md':                            'skills/image-generation/SKILL.md',
  'skills/reverse-search-video-frame/SKILL.md':                 'skills/reverse-search-video-frame/SKILL.md',
  'skills/hardware-evidence-capture/SKILL.md':                  'skills/hardware-evidence-capture/SKILL.md',
  'skills/video-to-skill/SKILL.md':                             'skills/video-to-skill/SKILL.md',
  'scripts/video_skill_contract.py':                           'skills/video-to-skill/scripts/video_skill_contract.py',
  'scripts/validate_video_skill.py':                           'skills/video-to-skill/scripts/validate_video_skill.py',
  'scripts/package_video_skill.py':                            'skills/video-to-skill/scripts/package_video_skill.py',

  'skills/av-events/SKILL.md':                                  'skills/av-events/SKILL.md',
  'skills/educational-explainer/SKILL.md':                       'skills/educational-explainer/SKILL.md',
  'skills/educational-explainer/scripts/lesson.py':              'skills/educational-explainer/scripts/lesson.py',
  'skills/footage-edit/SKILL.md':                               'skills/footage-edit/SKILL.md',
  'skills/research-visualization-blender/SKILL.md':               'skills/research-visualization-blender/SKILL.md',
  'skills/research-visualization-freecad/SKILL.md':               'skills/research-visualization-freecad/SKILL.md',
  'skills/spatial-video-analysis/SKILL.md':                      'skills/spatial-video-analysis/SKILL.md',
  'skills/video-translation/SKILL.md':                           'skills/video-translation/SKILL.md',
  'skills/movie-commentary/SKILL.md':                            'skills/movie-commentary/SKILL.md',

  'skills/qwen-image-integration/SKILL.md': 'skills/qwen-image-integration/SKILL.md',
  'skills/qwen-video-integration/SKILL.md': 'skills/qwen-video-integration/SKILL.md',

  // Preserve the support tree's relative docs/descriptors and adjacent helper imports.
  'LICENSE':                              'skills/video-research-resources/LICENSE',
  'licenses/fpdf2/GPL-3.0.txt':            'skills/video-research-resources/licenses/fpdf2/GPL-3.0.txt',
  'licenses/fpdf2/LGPL-3.0.txt':           'skills/video-research-resources/licenses/fpdf2/LGPL-3.0.txt',
  'THIRD_PARTY_NOTICES.md':                 'skills/video-research-resources/THIRD_PARTY_NOTICES.md',
  'docs/integrations/AV_EVENTS.md':         'skills/video-research-resources/docs/integrations/AV_EVENTS.md',
  'docs/integrations/FOOTAGE_EDIT.md':       'skills/video-research-resources/docs/integrations/FOOTAGE_EDIT.md',
  'docs/integrations/qwen-education.md':     'skills/video-research-resources/docs/integrations/qwen-education.md',
  'docs/integrations/qwen-blender.md':       'skills/video-research-resources/docs/integrations/qwen-blender.md',
  'docs/integrations/qwen-freecad.md':       'skills/video-research-resources/docs/integrations/qwen-freecad.md',
  'docs/integrations/qwen-spatial.md':       'skills/video-research-resources/docs/integrations/qwen-spatial.md',
  'docs/integrations/local-asr.md':          'skills/video-research-resources/docs/integrations/local-asr.md',
  'docs/integrations/qwen-dubbing.md':       'skills/video-research-resources/docs/integrations/qwen-dubbing.md',
  'docs/integrations/movie-commentary.md':   'skills/video-research-resources/docs/integrations/movie-commentary.md',
  'docs/integrations/qwen-video-edit.md': 'skills/video-research-resources/docs/integrations/qwen-video-edit.md',
  'integrations/qwen/video-edit.json': 'skills/video-research-resources/integrations/qwen/video-edit.json',
  'integrations/qwen/av-events.json':        'skills/video-research-resources/integrations/qwen/av-events.json',
  'integrations/qwen/footage-edit.json':     'skills/video-research-resources/integrations/qwen/footage-edit.json',
  'integrations/qwen/education.json':        'skills/video-research-resources/integrations/qwen/education.json',
  'integrations/qwen/blender.json':          'skills/video-research-resources/integrations/qwen/blender.json',
  'integrations/qwen/freecad.json':          'skills/video-research-resources/integrations/qwen/freecad.json',
  'integrations/qwen/video-spatio.json':     'skills/video-research-resources/integrations/qwen/video-spatio.json',
  'scripts/blender_session.py':             'skills/video-research-resources/scripts/blender_session.py',
  'scripts/blender_startup.py':             'skills/video-research-resources/scripts/blender_startup.py',
  'scripts/blender_stdio.py':               'skills/video-research-resources/scripts/blender_stdio.py',
  'scripts/freecad_session.py':             'skills/video-research-resources/scripts/freecad_session.py',
  'scripts/freecad_startup.py':             'skills/video-research-resources/scripts/freecad_startup.py',
  'scripts/freecad_jobs.py':                'skills/video-research-resources/scripts/freecad_jobs.py',
  'scripts/spatial_session.py':             'skills/video-research-resources/scripts/spatial_session.py',
  'scripts/spatial_launch.py':              'skills/video-research-resources/scripts/spatial_launch.py',
  'scripts/spatial_runtime.py':             'skills/video-research-resources/scripts/spatial_runtime.py',
  'scripts/spatial_fonts.py':               'skills/video-research-resources/scripts/spatial_fonts.py',
  'scripts/local_asr_service.py':           'skills/video-research-resources/scripts/local_asr_service.py',
  'scripts/local_asr_launch.py':            'skills/video-research-resources/scripts/local_asr_launch.py',
  'scripts/local_asr_worker.py':            'skills/video-research-resources/scripts/local_asr_worker.py',
  'scripts/spatial_inputs.py':              'skills/video-research-resources/scripts/spatial_inputs.py',
  'scripts/spatial_dispatch.py':            'skills/video-research-resources/scripts/spatial_dispatch.py',
  'scripts/spatial_motion.py':              'skills/video-research-resources/scripts/spatial_motion.py',

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
  'skills/qwen-image-integration',
  'skills/qwen-video-integration',
  'skills/av-events',
  'skills/educational-explainer/scripts',
  'skills/educational-explainer',
  'skills/footage-edit',
  'skills/research-visualization-blender',
  'skills/research-visualization-freecad',
  'skills/spatial-video-analysis',
  'skills/video-translation',
  'skills/movie-commentary',
  'skills/video-research-resources/docs/integrations',
  'skills/video-research-resources/docs',
  'skills/video-research-resources/integrations/qwen',
  'skills/video-research-resources/integrations',
  'skills/video-research-resources/licenses/fpdf2',
  'skills/video-research-resources/licenses',
  'skills/video-research-resources/scripts',
  'skills/video-research-resources',
  'skills/video-to-skill/scripts',
  'skills/video-to-skill',
  'skills/gemini-visualize/templates',
  'skills/gemini-visualize',
  'skills/video-research',
  'skills/video-explainer',
  'skills/weaviate-setup',
  'skills/mlflow-traces',
  'skills/research-brief-builder',
  'skills/gr-advisor',
  'skills/tts-production/references',
  'skills/tts-production',
  'skills/ffmpeg-production/references',
  'skills/ffmpeg-production',
  'skills/video-generation/references',
  'skills/video-generation',
  'skills/video-production/references',
  'skills/video-production',
  'skills/image-generation',
  'skills/reverse-search-video-frame',
  'skills/hardware-evidence-capture',
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
