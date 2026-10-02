# Video-derived host skills

The authoring workflow uses the host's ordinary `SKILL.md` directory format.
It records the inspected source, timed observations, media plan and asset
provenance before packaging. The validator and packager are local Python
commands; they do not run a provider, execute the skill or decide when the host
should trigger it.

From a source checkout with the locked Python environment:

```bash
uv run --no-sync --locked python scripts/validate_video_skill.py /absolute/skill-directory
uv run --no-sync --locked python scripts/package_video_skill.py /absolute/skill-directory /absolute/output.skill
```

The npm installer places the same scripts under
`.claude/skills/video-to-skill/scripts/` in the selected installation scope.
Select a POSIX host with Python 3.11 or later and PyYAML major version 6 installed. npm copies
workflow files; it does not install Python dependencies or execute the commands.
Read the installed `video-to-skill/SKILL.md` for the current evidence schema.

Each authoring directory supplies source type, relative path, full SHA-256,
extraction date and one of two statuses. `source-grounded` requires retained
source bytes and a reconciled event/media/asset record. Generated source and
assets retain their synthetic origin. Source times are finite, ordered and
bounded by the recorded source duration; asset references must resolve to
their declared events and intervals.

`execution-verified` additionally requires a retained host task-run record
bound to the candidate skill revision. That record includes the exact command,
ordered timestamps, successful exit, stdout/stderr, output hashes and expected
end-state artifact. The validator checks those records and bytes. Its result
does not authenticate who ran the command or establish factual task success;
actual execution evidence must come from an inspected host run. A trigger
judgment report supplies no substitute for that run. Optional model evaluation
needs a separately bounded and authorized operation.

Local references stay within the authoring directory and cannot traverse a
symlink. Referenced instruction text is screened for the bounded unsafe
patterns documented by the skill. Hash checks and that pattern screen do not
establish factual correctness or provide a general security certificate.

Every redistributed asset requires its own hash-bound grant, attribution and
redistribution declaration. A licensed asset also retains its license source.
Declarations and matching bytes permit a structural check; a human rights
audit remains a separate claim. A repository code license does not grant rights
to its video, fonts, model weights or other assets.

Packaging uses an explicit file set, rechecks the retained inputs, reads the
actual ZIP back and promotes it atomically. Unreferenced build/debug files,
caches and provider credentials are excluded. A failed validation or changed
input leaves an existing output intact. Keep the authoring source and run
evidence alongside the package when those private records are excluded from
redistribution; the archive alone cannot establish an independently observed
source or replayed task.

The pinned Qwen skill-creator contracts and Apache-2.0 code grant were inspected
at revision `07736672525443c7f8a3f6405eed37d2236f023f`. These commands implement
the requirements independently. No upstream implementation, model, credential,
demonstration video or asset is copied, imported or bundled.
