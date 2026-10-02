"""Bounded fixed-call stdio collector, executed inside an owned media process group."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

MAX_LINE = 1024 * 1024
MAX_TOTAL = 4 * MAX_LINE
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


def exchange(process, identifier, method, params, trace, budget):
    """Send one request and bound every reply/notification before JSON parsing."""
    message = encode({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
    process.stdin.write(message + b"\n")
    process.stdin.flush()
    for _ in range(16):
        body = process.stdout.readline(MAX_LINE + 1)
        budget[0] += len(body)
        if not body.endswith(b"\n") or len(body) > MAX_LINE or budget[0] > MAX_TOTAL:
            raise ValueError(
                "Native DSP protocol response exceeds its byte/notification bound or closed early"
            )
        reply = json.loads(body, parse_constant=invalid_constant)
        if reply.get("jsonrpc") != "2.0":
            raise ValueError("Native DSP returned an invalid JSON-RPC envelope")
        if "method" in reply:
            if "id" in reply:
                raise ValueError("Native DSP requested an unauthorized client operation")
            continue
        if reply.get("id") != identifier or "error" in reply or "result" not in reply:
            raise ValueError("Native DSP returned an unmatched or failed protocol result")
        trace.append(
            {
                "method": method,
                "request_sha256": hashlib.sha256(message).hexdigest(),
                "response_sha256": hashlib.sha256(body).hexdigest(),
                "response_bytes": len(body),
            }
        )
        return reply["result"]
    raise ValueError("Native DSP exceeded the notification population limit")


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


def job_observation(process, text, trace, budget):
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
    )
    return json.loads(text_result(observed), parse_constant=invalid_constant)


def collect(process, request, trace):
    """Discover the pinned backend and collect one explicit analysis plus actual job readback."""
    budget = [0]
    initialized = exchange(
        process,
        1,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "vrm-audio-dsp", "version": "1"},
        },
        trace,
        budget,
    )
    process.stdin.write(encode({"jsonrpc": "2.0", "method": "notifications/initialized"}) + b"\n")
    process.stdin.flush()
    listing = exchange(process, 2, "tools/list", {}, trace, budget)
    if (
        listing.get("nextCursor")
        or len(listing["tools"]) != len(TOOLS[request["backend"]])
        or {tool["name"] for tool in listing["tools"]} != TOOLS[request["backend"]]
    ):
        raise ValueError("Native DSP tool discovery differs from the pinned source contract")
    selected = [tool for tool in listing["tools"] if tool["name"] == request["tool"]]
    if len(selected) != 1:
        raise ValueError("Native DSP selected tool is unavailable or repeated")
    result = exchange(
        process,
        3,
        "tools/call",
        {"name": request["tool"], "arguments": request["arguments"]},
        trace,
        budget,
    )
    text = text_result(result)
    status = None
    if request["backend"] == "ferrous" and request["tool"] == "analyze_audio":
        status = job_observation(process, text, trace, budget)
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


def main():
    """Run one operator-pinned executable with a private cwd/environment; always join it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request")
    path = Path(parser.parse_args().request)
    request = json.loads(path.read_bytes())
    executable = Path(request["executable"])
    if executable_digest(executable) != request["executable_sha256"]:
        raise ValueError("Native DSP executable changed before launch")
    environment = {"PATH": "/usr/bin:/bin", "TMPDIR": str(path.parent), "RUST_LOG": "error"}
    output = path.parent / "native-response.json"
    trace = []
    process = subprocess.Popen(
        [str(executable)],
        cwd=path.parent,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        payload = encode(collect(process, request, trace))
        if len(payload) > MAX_TOTAL:
            raise ValueError("Native DSP retained response exceeds4MiB")
        with output.open("xb") as writer:
            os.fchmod(writer.fileno(), 0o600)
            writer.write(payload)
        record = {
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
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        process.stdin.close()
        process.stdout.close()
        executable.unlink()
    record["process_joined"] = True
    print(encode(record).decode())


if __name__ == "__main__":
    main()
