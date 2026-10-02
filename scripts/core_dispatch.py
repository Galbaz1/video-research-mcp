"""Serialized original-core calls with owned copies, strict refusals and joined workers."""

import base64
import functools
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import uuid

from core_inputs import RESULT_BYTES, canonical, page_selection, read_body, require_preview_grid, sha256, trusted_json, verify, write_json


class Barrier:
    """Deny Python network/provider/native attempts; this is not an OS sandbox."""

    def __init__(self, output):
        self.output, self.local, self.violation = output.resolve(), threading.local(), None

    def audit(self, event, arguments):
        """Record denied attempts even if an original handler catches the exception."""
        denied = event.startswith("socket.") and event not in {"socket.__new__"}
        denied |= event in {"os.system", "os.posix_spawn", "os.fork", "os.forkpty", "os.exec", "pty.spawn"}
        if event == "subprocess.Popen":
            denied |= tuple(arguments[1]) != getattr(self.local, "spawn", None)
        if event == "import":
            denied |= arguments[0].split(".")[0] in {"numpy", "matplotlib", "pandas", "pypdfium2", "resvg_py", "lxml", "nbformat", "geopandas", "nibabel", "trimesh", "pyrender", "cascadio", "playwright"} or arguments[0] == "shared.api_openai"
        if event == "os.putenv":
            key = os.fsdecode(arguments[0])
            denied |= key == "QWEN_MM_NATIVE_MODE" or key.endswith(("API_KEY", "TOKEN", "SECRET"))
        if event == "open" and isinstance(arguments[0], (str, bytes, os.PathLike)):
            mode, flags = arguments[1:3]
            writable = any(v in (mode or "") for v in "wax+") or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            denied |= bool(writable) and not Path(os.fsdecode(arguments[0])).resolve().is_relative_to(self.output)
        if event in {"os.remove", "os.mkdir", "os.rmdir", "os.chmod", "os.rename"}:
            paths = arguments[:2] if event == "os.rename" else arguments[:1]
            denied |= any(isinstance(p, (str, bytes)) and not Path(os.fsdecode(p)).resolve().is_relative_to(self.output) for p in paths)
        if denied:
            self.violation = "python-network-provider-native-or-external-write-denied"
            raise PermissionError(self.violation)

    def check(self):
        """A swallowed audit refusal cannot become a complete preview."""
        if self.violation:
            raise PermissionError(self.violation)


def family(data, path):
    """Preserve the compound NIfTI suffix and the complete source-derived denominator."""
    value = path.lower()
    extension = ".nii.gz" if value.endswith(".nii.gz") else Path(value).suffix
    for name, extensions in data["family_extensions"].items():
        if extension in {e.lower() for e in extensions}:
            return name
    raise ValueError("Extension is outside the original75 spelling inventory")


def prepare_call(name, arguments, data, inputs, directory):
    """Fence the actual original arguments before dispatching any source/native branch."""
    key = {"read_image": "image_path", "crop": "image_path", "draw_bbox": "image_path", "read_video": "video_path", "media_info": "path"}.get(name, "file_path")
    row = inputs.selected(arguments.get(key, ""))
    selected = family(data, row["path"])
    pages = page_selection(arguments.get("pages"), arguments.get("max_pages", 4))
    if name in {"read_video", "media_info", "save_view"}:
        raise ValueError("Original native/materialized-view backend is unqualified; handler was not invoked")
    if name == "draw_bbox":
        raise ValueError("Original draw_bbox unconditionally loads an unqualified font; handler was not invoked")
    if selected not in {"code", "subtitle", "image"} or data["format_clearance"][selected]["state"] != "verified-selected-format-profile":
        raise ValueError("Selected format/backend grants are unavailable; handler was not invoked")
    if selected != "image" and name != "visualize":
        raise ValueError("This original operation requires a selected PNG image")
    if pages and (selected in {"code", "subtitle", "image"}) and pages != [1]:
        raise ValueError("This selected original renderer ignores pages; requested coverage cannot be asserted")
    if name == "crop":
        box = arguments.get("box")
        if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int or not 0 <= v <= 1000 for v in box) or box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError("Crop requires ordered integer normalized corners within0..1000")
    if selected == "image":
        require_preview_grid(verify(row), name, arguments)
    adjusted = dict(arguments)
    for output_key in ("output_path", "output_dir"):
        if output_key in adjusted:
            value = adjusted.pop(output_key)
            if value is not None and (not isinstance(value, str) or Path(value).name != value or value in {"", ".", ".."}):
                raise ValueError("Output request must be a fresh owned leaf name, never an original/external path")
    local = inputs.copy(row, directory / "inputs")
    adjusted[key] = local["path"]
    if name == "crop":
        adjusted["output_path"] = str(directory / "products/result.png")
    return {"original": row, "copy": local, "family": selected, "arguments": adjusted, "requested_pages": pages}


def content_result(blocks, selected, directory):
    """Preserve actual blocks and encoded/pixel identities without promoting fallback text."""
    if not isinstance(blocks, list) or not blocks or len(blocks) > 64:
        raise ValueError("Original handler returned an empty/malformed/oversized block population")
    encoded = json.dumps(blocks, allow_nan=False, ensure_ascii=False).encode()
    if len(encoded) > RESULT_BYTES:
        raise ValueError("Original result exceeds4MiB; refused without truncation")
    images, text, pixels = [], [], 0
    for index, block in enumerate(blocks):
        if not isinstance(block, dict) or block.get("type") not in {"text", "image"}:
            raise ValueError("Original block type is outside the selected contract")
        if block["type"] == "text":
            if not isinstance(block.get("text"), str):
                raise ValueError("Original text block is malformed")
            text.append(block["text"])
            continue
        body = base64.b64decode(block["data"], validate=True)
        from PIL import Image
        with Image.open(io.BytesIO(body)) as image:
            pixels += image.width * image.height
            if image.format not in {"PNG", "JPEG"} or getattr(image, "n_frames", 1) != 1 or pixels > 16777216:
                raise ValueError("Actual original preview grid/format is outside the bounded profile")
            if block.get("mimeType") != {"PNG": "image/png", "JPEG": "image/jpeg"}[image.format]:
                raise ValueError("Actual original preview MIME differs from its decoded format")
            image.load()
            record = {"block_index": index, "sha256": sha256(body), "bytes": len(body), "dimensions": list(image.size), "pixel_sha256": sha256(image.convert("RGBA").tobytes()), "mime": block["mimeType"]}
        suffix = "png" if body.startswith(b"\x89PNG") else "jpg"
        path = directory / "products" / f"block-{index:02}.{suffix}"
        with path.open("xb") as writer:
            writer.write(body)
        images.append({**record, "path": str(path)})
    joined = "\n".join(text)
    state = "failed" if any(t.startswith(("Error:", "Error rendering")) for t in text) else "abstained" if any(t.startswith("Warning:") for t in text) else "complete"
    labels = [{"first_line_prefix": t.partition("\n")[0][:1024], "prefix_truncated": len(t.partition("\n")[0]) > 1024,
               "text_sha256": sha256(t.encode()), "text_bytes": len(t.encode())} for t in text]
    coverage = {"requested_pages": selected["requested_pages"], "original_labels": labels, "full_text_in_result": True, "semantic_accuracy_verified": False}
    if selected["family"] == "code":
        count = len(io.StringIO(verify(selected["copy"]).decode("utf-8", errors="replace"), newline=None).readlines())
        coverage.update(total_lines=count, retained_lines=min(count, 500), skipped_lines=max(0, count - 500), preview_kind="fenced_text_not_execution")
        if count > 500:
            state = "partial"
    if selected["family"] == "subtitle":
        coverage.update(preview_kind="original_cue_text_extraction", timestamp_alignment_validated=False, empty="(empty)" in joined)
    return {"state": state, "blocks": blocks, "images": images, "artifacts": products(directory), "coverage": coverage, "result_sha256": sha256(encoded), "result_bytes": len(encoded)}


def products(directory):
    """Bind every actual saved product, including a crop file distinct from its preview."""
    paths = sorted((directory / "products").iterdir())
    if len(paths) > 64:
        raise ValueError("Actual derived product population exceeds64")
    rows = []
    for path in paths:
        body = read_body(path, RESULT_BYTES)
        if not body:
            raise ValueError("Actual derived product is empty")
        rows.append({"path": str(path), "sha256": sha256(body), "bytes": len(body)})
    if sum(row["bytes"] for row in rows) > RESULT_BYTES:
        raise ValueError("Actual derived products exceed4MiB aggregate")
    return rows


def execute_handler(args, data, inputs, loader, footprint):
    """Run exactly one original handler inside the parent's current owned worker group."""
    job = trusted_json(args.worker_job, args.worker_sha256)
    directory = canonical(job["directory"])
    if not directory.is_relative_to(args.output / "calls") or job["parent_pid"] != os.getppid() or not 0 < job["deadline"] - time.monotonic() <= 30 or (directory / "result.json").exists():
        raise ValueError("Worker job is stale, unrelated or outside its exclusive session")
    verify(job["selection"]["copy"])
    package, _, barrier = loader(data, args.source_root, args.output)
    try:
        blocks = package.get_handler(job["tool"])(job["selection"]["arguments"])
        barrier.check()
        result = content_result(blocks, job["selection"], directory)
        inputs.readback()
        verify(job["selection"]["copy"])
        result.update(job_id=job["job_id"], pid=os.getpid(), session=str(args.output), loaded=footprint(data, args.source_root))
        write_json(directory / "result.json", result, RESULT_BYTES)
        return 0
    except Exception as error:
        write_json(directory / "result.json", {"state": "failed", "error_type": type(error).__name__, "reason": "original-handler-or-boundary-refused", "job_id": job["job_id"], "pid": os.getpid(), "session": str(args.output)})
        return 2


def reap(process):
    """Terminate/reap only the owned new process group, including queued native descendants."""
    if process is None:
        return
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=4)


class Dispatch:
    """Hold one lock across admission, original execution and complete result readback."""

    def __init__(self, args, data, inputs, output, recheck, barrier):
        self.args, self.data, self.inputs, self.output, self.recheck, self.barrier = args, data, inputs, output, recheck, barrier
        self.lock, self.process_lock = threading.Lock(), threading.Lock()
        self.process, self.closed = None, False

    def handler(self, name):
        """Keep every original schema/name while substituting only its execution boundary."""
        return functools.partial(self.call, name)

    def close(self):
        """EOF closes the worker before AnyIO joins its shielded calling thread."""
        with self.process_lock:
            self.closed = True
            reap(self.process)

    def launch(self, directory, job, deadline):
        """Launch only the selected interpreter/owned script with absent bytecode cache prefix."""
        record = write_json(directory / "job.json", job)
        a = self.args
        command = [self.data["runtime_fields"]["python_executable"], "-I", "-B", "-X", f"pycache_prefix={directory / 'bytecode'}", str(Path(__file__).with_name("core_session.py")),
                   "--source-root", str(a.source_root), "--manifest", str(a.manifest), "--manifest-sha256", a.manifest_sha256,
                   "--inputs", str(a.inputs), "--inputs-sha256", a.inputs_sha256, "--output", str(self.output),
                   "--worker-job", record["path"], "--worker-sha256", record["sha256"]]
        with (directory / "worker.log").open("xb") as log, self.process_lock:
            if self.closed or time.monotonic() >= deadline:
                raise TimeoutError("Owned core session is closed or its call deadline expired")
            self.barrier.local.spawn = tuple(command)
            try:
                self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=self.output / "cwd", start_new_session=True, env=dict(os.environ))
            finally:
                self.barrier.local.spawn = None
            write_json(directory / "process.json", {"pid": self.process.pid, "owned_group": True, "job_id": job["job_id"]})
        while self.process.poll() is None:
            if self.closed or time.monotonic() >= deadline or (directory / "worker.log").stat().st_size > 65536:
                raise TimeoutError("Owned core worker interrupted/deadline/output ceiling")
            time.sleep(0.01)
        self.process.wait(timeout=1)
        if (directory / "worker.log").stat().st_size > 65536:
            raise ValueError("Actual worker log exceeds64KiB; result refused")
        result_body = read_body(directory / "result.json", RESULT_BYTES)
        result = trusted_json(directory / "result.json", sha256(result_body), RESULT_BYTES)
        if (result["pid"], result["job_id"], result["session"]) != (self.process.pid, job["job_id"], str(self.output)):
            raise ValueError("Worker result identity does not bind its actual owned process/session")
        return result, {"path": str(directory / "result.json"), "sha256": sha256(result_body), "bytes": len(result_body)}

    def call(self, name, arguments):
        """Persist every refusal/partial/failure and never label truncated preview as complete."""
        deadline, directory = time.monotonic() + 30, self.output / "calls" / uuid.uuid4().hex
        receipt = {"state": "pending", "tool": name, "job_id": directory.name, "session": str(self.output), "semantic_accuracy_verified": False}
        directory.mkdir(mode=0o700)
        for leaf in ("inputs", "products"):
            (directory / leaf).mkdir(mode=0o700)
        write_json(directory / "receipt.json", receipt)
        if not self.lock.acquire(timeout=max(0, deadline - time.monotonic())):
            receipt.update(state="failed", reason="serialized-admission-deadline-expired")
            return self.finish(directory, receipt, [])
        try:
            if self.closed:
                raise ValueError("Owned session was closed; late work is refused")
            request = json.dumps({"tool": name, "arguments": arguments}, allow_nan=False, ensure_ascii=False).encode()
            if len(request) > 131072:
                raise ValueError("Original call arguments exceed128KiB")
            receipt["request"] = {"sha256": sha256(request), "bytes": len(request)}
            self.recheck()
            selected = prepare_call(name, arguments, self.data, self.inputs, directory)
            job = {"tool": name, "selection": selected, "job_id": directory.name, "directory": str(directory), "parent_pid": os.getpid(), "deadline": deadline}
            result, binding = self.launch(directory, job, deadline)
            self.recheck()
            verify(selected["copy"])
            verify(binding, RESULT_BYTES)
            for artifact in [*result.get("images", []), *result.get("artifacts", [])]:
                verify(artifact, RESULT_BYTES)
            if self.closed or time.monotonic() >= deadline:
                raise TimeoutError("Late original result cannot be accepted")
            receipt.update(state=result["state"], source=selected["original"], copy=selected["copy"], family=selected["family"], result=binding, coverage=result.get("coverage"), images=result.get("images", []), artifacts=result.get("artifacts", []))
            return self.finish(directory, receipt, result.get("blocks", []))
        except Exception as error:
            receipt = {k: v for k, v in receipt.items() if k in {"state", "tool", "job_id", "session", "semantic_accuracy_verified", "request", "result"}}
            receipt.update(state="interrupted" if self.closed else "failed", error_type=type(error).__name__, reason=str(error) if isinstance(error, ValueError) else "owned-worker-or-admission-refused")
            return self.finish(directory, receipt, [])
        finally:
            with self.process_lock:
                reap(self.process)
                self.process = None
            self.lock.release()

    def finish(self, directory, receipt, blocks):
        """Admit the entire caller-visible result before committing a terminal receipt."""
        body = (json.dumps(receipt, allow_nan=False, ensure_ascii=False, indent=2) + "\n").encode()
        binding = {"path": str(directory / "receipt.json"), "bytes": len(body), "sha256": sha256(body)}
        result = [*blocks, {"type": "text", "text": json.dumps({"core_session": receipt, "receipt": binding}, allow_nan=False, ensure_ascii=False)}]
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > RESULT_BYTES:
            raise ValueError("Complete original blocks plus metadata exceed4MiB; no truncated completion")
        write_json(directory / "receipt.json", receipt)
        return result
