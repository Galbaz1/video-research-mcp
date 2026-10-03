"""Bounded fixed-call stdio collector, executed inside an owned media process group."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import signal
import threading
import tempfile
import subprocess

MAX_LINE = 1024 * 1024
MAX_TOTAL = 4 * MAX_LINE
INITIALIZE = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "vrm-audio-dsp", "version": "1"},
}
TOOLS = {
    "juzzy": {
        "audio_info",
        "spectral_features",
        "harmonic_analysis",
        "rhythm_analysis",
        "full_analysis",
        "compare",
    },
    "ferrous": {"analyze_audio", "compare_audio", "get_job_status"},
}


def encode(value):
    """Encode finite JSON protocol data without invoking a shell or interpreting tool text."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def invalid_constant(value):
    """Reject non-JSON numerical constants received from an external process."""
    raise ValueError("Native DSP returned a nonfinite JSON constant")


def save_diagnostic(diagnostic, path):
    """Atomically retain only fixed safe observations, including before blocking reads."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as writer:
            writer.write(encode(diagnostic))
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def observe(diagnostic, path, reason):
    """Record a wire observation without claiming a native cause."""
    diagnostic["observation"] = reason
    save_diagnostic(diagnostic, path)


def exchange(process, identifier, method, params, trace, budget, diagnostic, path):
    """Send one request and retain bounded observations before parsing external replies."""
    message = encode({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
    phase = {
        "id": identifier,
        "method": method,
        "request_sha256": hashlib.sha256(message).hexdigest(),
    }
    diagnostic.update(phase=phase, response_bytes=0, notifications=0)
    observe(diagnostic, path, "pending")
    process.stdin.write(message + b"\n")
    process.stdin.flush()
    for _ in range(16):
        body = process.stdout.readline(MAX_LINE + 1)
        budget[0] += len(body)
        diagnostic.update(response_bytes=len(body), total_response_bytes=budget[0])
        reason = None
        if len(body) > MAX_LINE:
            reason = "line_overflow"
        elif budget[0] > MAX_TOTAL:
            reason = "aggregate_overflow"
        elif not body:
            reason = "empty_eof"
        elif not body.endswith(b"\n"):
            reason = "unterminated_line"
        observe(diagnostic, path, reason or "response_received")
        if reason:
            raise ValueError("Native DSP protocol boundary: " + reason)
        try:
            reply = protocol_reply(body, identifier)
        except (ValueError, TypeError):
            observe(diagnostic, path, "invalid_response")
            raise ValueError("Native DSP returned an invalid protocol response") from None
        if "method" in reply:
            diagnostic["notifications"] += 1
            continue
        trace.append(
            {
                "method": method,
                "request_sha256": phase["request_sha256"],
                "response_sha256": hashlib.sha256(body).hexdigest(),
                "response_bytes": len(body),
            }
        )
        return reply["result"]
    observe(diagnostic, path, "notification_exhaustion")
    raise ValueError("Native DSP exceeded the notification population limit")


def protocol_reply(body, identifier):
    """Validate the external envelope before admitting notifications or a fixed-call result."""
    reply = json.loads(body, parse_constant=invalid_constant)
    if not isinstance(reply, dict) or reply.get("jsonrpc") != "2.0":
        raise ValueError("Invalid JSON-RPC envelope")
    if "method" in reply:
        if "id" in reply:
            raise ValueError("Unauthorized client operation")
    elif reply.get("id") != identifier or "error" in reply or "result" not in reply:
        raise ValueError("Unmatched or failed protocol result")
    return reply


def text_result(result):
    """Accept only bounded text responses; embedded strings remain untrusted source data."""
    content = result.get("content")
    if result.get("isError", False) or not isinstance(content, list) or not 1 <= len(content) <= 8:
        raise ValueError("Native DSP tool returned an error or invalid content")
    if any(item.get("type") != "text" or not isinstance(item.get("text"), str) for item in content):
        raise ValueError("Native DSP returned an unsupported content kind")
    text = "\n".join(item["text"] for item in content)
    if text.lstrip().startswith("Error:"):
        raise ValueError("Native DSP returned an analysis error in text")
    return text


def job_observation(process, text, trace, budget, diagnostic, path):
    """Read the native process-local job without treating its status as durable attestation."""
    value = json.loads(text, parse_constant=invalid_constant)
    if value.get("status") != "success" or not isinstance(value.get("job_id"), str):
        raise ValueError("Native DSP did not return a completed analysis response")
    observed = exchange(
        process,
        4,
        "tools/call",
        {"name": "get_job_status", "arguments": {"job_id": value["job_id"]}},
        trace,
        budget,
        diagnostic,
        path,
    )
    return json.loads(text_result(observed), parse_constant=invalid_constant)


def collect(process, request, trace, diagnostic, path):
    """Discover the pinned backend and collect one explicit analysis plus actual job readback."""
    budget = [0]
    initialized = exchange(process, 1, "initialize", INITIALIZE, trace, budget, diagnostic, path)
    process.stdin.write(encode({"jsonrpc": "2.0", "method": "notifications/initialized"}) + b"\n")
    listing = exchange(process, 2, "tools/list", {}, trace, budget, diagnostic, path)
    if (
        listing.get("nextCursor")
        or len(listing["tools"]) != len(TOOLS[request["backend"]])
        or {tool["name"] for tool in listing["tools"]} != TOOLS[request["backend"]]
    ):
        raise ValueError("Native DSP tool discovery differs from the pinned source contract")
    result = exchange(
        process,
        3,
        "tools/call",
        {"name": request["tool"], "arguments": request["arguments"]},
        trace,
        budget,
        diagnostic,
        path,
    )
    text = text_result(result)
    status = None
    if request["backend"] == "ferrous" and request["tool"] == "analyze_audio":
        status = job_observation(process, text, trace, budget, diagnostic, path)
    return {
        "initialized": initialized,
        "discovery": listing,
        "result": result,
        "native_job_observation": status,
        "native_job_observation_is_result_attestation": False,
        "trace": trace,
        "protocol_response_bytes": budget[0],
    }


def executable_digest(path):
    """Admit one bounded regular owned executable without following substituted links."""
    initial = path.lstat()
    if not stat.S_ISREG(initial.st_mode) or not 0 < initial.st_size <= 256 * 1024 * 1024:
        raise ValueError("Native DSP executable is not a bounded regular file")
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as reader:
        opened = os.fstat(reader.fileno())
        if (initial.st_dev, initial.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("Native DSP executable changed at admission")
        for chunk in iter(lambda: reader.read(65536), b""):
            digest.update(chunk)
        final = path.lstat()
        if (
            initial.st_dev,
            initial.st_ino,
            initial.st_size,
            initial.st_mtime_ns,
            initial.st_ctime_ns,
        ) != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns, final.st_ctime_ns):
            raise ValueError("Native DSP executable changed during admission")
    return digest.hexdigest()


def drain_stderr(process, path, observation):
    """Continuously drain native stderr; retain and hash only its private64KiB prefix."""
    digest = hashlib.sha256()
    with path.open("xb") as writer:
        os.fchmod(writer.fileno(), 0o600)
        for chunk in iter(lambda: process.stderr.read(65536), b""):
            observation["observed_bytes"] += len(chunk)
            prefix = chunk[: max(0, 65536 - observation["retained_bytes"])]
            writer.write(prefix)
            writer.flush()
            digest.update(prefix)
            observation["retained_bytes"] += len(prefix)
        observation.update(
            retained_sha256=digest.hexdigest(),
            eof=True,
            truncated=observation["observed_bytes"] > observation["retained_bytes"],
        )


def joined_diagnostic(process, drain, diagnostic, path):
    """Publish terminal facts only after the native process and stderr reader actually join."""
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
    drain.join(timeout=3)
    if drain.is_alive() or not diagnostic["stderr"]["eof"]:
        raise RuntimeError("Native DSP stderr drain did not join")
    for stream in (process.stdin, process.stdout, process.stderr):
        stream.close()
    diagnostic.update(
        terminal=True,
        native_returncode=process.returncode,
        native_process_joined=True,
        stderr_drain_joined=True,
    )
    save_diagnostic(diagnostic, path)


def retained_response(process, request, trace, diagnostic, path):
    """Preserve the existing successful response and small public collector receipt."""
    payload = encode(collect(process, request, trace, diagnostic, path))
    if len(payload) > MAX_TOTAL:
        raise ValueError("Native DSP retained response exceeds4MiB")
    output = path.parent / "native-response.json"
    with output.open("xb") as writer:
        os.fchmod(writer.fileno(), 0o600)
        writer.write(payload)
    return {
        "path": str(output),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "mime": "application/json",
        "role": "untrusted_native_dsp_response",
        "pid": process.pid,
        "trace": trace,
        "tool": request["tool"],
        "backend": request["backend"],
    }


def interrupted(signum, frame):
    """Let the existing group termination interrupt collection and enter joined cleanup."""
    raise InterruptedError("Native DSP collection interrupted")


def initial_diagnostic(body, request):
    """Bind an initially pending observation to the admitted request, helper and executable."""
    return {
        "schema": 1,
        "request_sha256": hashlib.sha256(body).hexdigest(),
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        **{key: request[key] for key in ("backend", "tool", "executable_sha256")},
        "phase": None,
        "response_bytes": 0,
        "total_response_bytes": 0,
        "notifications": 0,
        "observation": "pending",
        "terminal": False,
        "native_returncode": None,
        "native_process_joined": False,
        "stderr_drain_joined": False,
        "stderr": None,
    }


def main():
    """Run one pinned executable; keep raw stderr private and public failures text-free."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request")
    path = Path(parser.parse_args().request)
    body = path.read_bytes()
    request = json.loads(body)
    executable = Path(request["executable"])
    if executable_digest(executable) != request["executable_sha256"]:
        raise ValueError("Native DSP executable changed before launch")
    diagnostic_path = path.parent / "native-diagnostic.json"
    diagnostic = initial_diagnostic(body, request)
    save_diagnostic(diagnostic, diagnostic_path)
    process = subprocess.Popen(
        [str(executable)],
        cwd=path.parent,
        env={"PATH": "/usr/bin:/bin", "TMPDIR": str(path.parent), "RUST_LOG": "error"},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stderr = {"observed_bytes": 0, "retained_bytes": 0, "eof": False}
    drain = threading.Thread(
        target=drain_stderr, args=(process, path.parent / "native-stderr.bin", stderr)
    )
    drain.start()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        record = retained_response(process, request, [], diagnostic, diagnostic_path)
        observe(diagnostic, diagnostic_path, "complete")
    except InterruptedError:
        observe(diagnostic, diagnostic_path, "interrupted")
        raise ValueError("Native DSP collection interrupted") from None
    except Exception:
        if diagnostic["observation"] in {"pending", "response_received"}:
            observe(diagnostic, diagnostic_path, "collector_error")
        raise ValueError("Native DSP collection failed; inspect safe job diagnostics") from None
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        diagnostic["stderr"] = stderr
        joined_diagnostic(process, drain, diagnostic, diagnostic_path)
        executable.unlink()
    record["process_joined"] = True
    print(encode(record).decode())


if __name__ == "__main__":
    main()
