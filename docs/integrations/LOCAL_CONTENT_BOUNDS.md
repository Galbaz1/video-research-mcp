# Local content and batch limits

Local `content_analyze` inputs and each `content_batch_analyze` file must be
regular files within `LOCAL_FILE_ACCESS_ROOT` when configured. They are bounded
by `DOC_MAX_DOWNLOAD_BYTES`, which defaults to 50 MiB. Special files, changed
files and oversize reads fail before inference. Compare mode applies the same
ceiling to all input bytes combined; use individual mode for a larger collection
of independently bounded files, or deliberately configure the operator ceiling.

Directory batches inspect at most 5,000 directory entries, including entries
that do not match the glob and revisits during recursion. They retain at most
`max_files` matching files in sorted order. Explicit content lists retain the
published input-order subset behavior. Narrow the directory to stay within the
visit ceiling; `max_files` controls selection within its published maximum of 50.
The visit ceiling is enforced before provider submission.

Globs support `*`, `?`, character classes, nested paths and recursive `**`.
A terminal `**` selects files recursively across supported Python versions;
directory-only patterns ending in `/` select no input files. Absolute patterns
and `..` segments are rejected. Scans do not follow directory symlinks; matching
files still pass the configured root policy. Recursive patterns count revisits,
so the unique-entry capacity is lower than the visit ceiling.

Direct text inputs retain their published schemas. The historical proposal for
a 200,000-character cap is not adopted because it narrows that frozen contract.
File and batch limits do not establish a provider spending limit or observed
media coverage.

URL sources for `research_document` use private staging under
`GEMINI_CACHE_DIR/media/views`, followed by the normal fenced snapshot/upload
route. Set `GEMINI_CACHE_DIR` inside `LOCAL_FILE_ACCESS_ROOT` when that root is
configured. Preparation removes its staging directory after success or failure;
URL downloads retain per-hop URL and peer-IP checks.

These are source-level safeguards. Offline tests mock inference and transport;
a successful test does not establish live provider acceptance of every payload.
