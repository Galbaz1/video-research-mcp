"""Explicit, serial loopback transport for the pinned optional timed ASR worker."""

if __name__ == "__main__":
    raise SystemExit("Use trusted Python -I -S -B scripts/local_asr_launch.py --entry service")

import argparse
from importlib.metadata import PackageNotFoundError
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import tempfile
import time
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer

import local_asr_launch

from local_asr_worker import MAX_REQUEST, MAX_RESPONSE, PROTOCOL, admit, decode_request, json_bytes, parse_json


def run_worker(raw, descriptor_path, descriptor_digest, connection):
    """Bound one inference group; disconnect, deadline and parent signals kill and join."""
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "TMPDIR"}}
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
               TOKENIZERS_PARALLELISM="false", PYTHONDONTWRITEBYTECODE="1")
    command = [local_asr_launch.TRUSTED_PYTHON, "-I", "-S", "-B",
               str(Path(__file__).with_name("local_asr_launch.py")), "--entry", "worker",
               "--descriptor", str(descriptor_path), "--expected-descriptor-sha256", descriptor_digest]
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
    process, started = None, time.monotonic()
    try:
        with tempfile.TemporaryFile() as request_file:
            request_file.write(raw)
            request_file.seek(0)
            process = subprocess.Popen(command, stdin=request_file, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=env, start_new_session=True)
        print(json_bytes({"event": "worker_started", "worker_pid": process.pid}).decode(), flush=True)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        deadline = started + 60
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, 60)
            if select.select([connection], [], [], 0)[0]:
                if not connection.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT):
                    raise ConnectionAbortedError("Client disconnected")
            try:
                stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                break
            except subprocess.TimeoutExpired:
                pass
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
        if len(stdout) > MAX_RESPONSE:
            raise ValueError("Worker response exceeds bound")
        value = parse_json(stdout)
        value["receipt"]["service_pid"] = os.getpid()
        return value
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            print(json_bytes({"event": "worker_joined", "worker_pid": process.pid,
                  "returncode": process.returncode, "elapsed_seconds": time.monotonic() - started}).decode(), flush=True)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


class Handler(BaseHTTPRequestHandler):
    """Serve explicit loopback requests serially without browser CORS access."""

    def setup(self):
        """Bound socket reads for incomplete clients."""
        self.request.settimeout(10)
        super().setup()

    def log_message(self, *_):
        """Keep audio, hints and client-controlled strings out of server logs."""

    def reply(self, status, value):
        """Return one bounded JSON response and close the connection."""
        body = json_bytes(value)
        if len(body) > MAX_RESPONSE:
            status, body = 502, json_bytes({"error": {"code": "ANSWER_TOO_LARGE"}})
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_GET(self):
        """Expose an inert admitted identity without loading a model."""
        self.reply(200 if self.path == "/healthz" else 404, {"protocol": PROTOCOL,
                   "descriptor_sha256": self.server.descriptor_digest, "inference": False})

    def do_POST(self):
        """Validate actual audio and delegate only the explicit timed endpoint."""
        if self.path != "/v1/transcribe":
            return self.reply(404, {"error": {"code": "UNKNOWN_ENDPOINT"}})
        if "Origin" in self.headers or len(self.headers.get_all("Host", [])) != 1 or self.headers.get("Host") != self.server.origin:
            return self.reply(403, {"error": {"code": "LOOPBACK_CLIENT_REQUIRED"}})
        if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Type") != "application/json":
            return self.reply(415, {"error": {"code": "JSON_CONTENT_LENGTH_REQUIRED"}})
        try:
            if len(self.headers.get_all("Content-Length", [])) > 1:
                raise ValueError("Ambiguous body length")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST:
                return self.reply(413, {"error": {"code": "REQUEST_TOO_LARGE_OR_EMPTY"}})
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Incomplete body")
            decode_request(raw)
        except (ValueError, EOFError, wave.Error, TimeoutError):
            return self.reply(400, {"error": {"code": "INVALID_AUDIO_REQUEST"}})
        try:
            admit(self.server.descriptor_path, self.server.descriptor_digest)
        except (ValueError, OSError, KeyError, TypeError, PackageNotFoundError):
            return self.reply(503, {"error": {"code": "ADMISSION_CHANGED"}})
        try:
            value = run_worker(raw, self.server.descriptor_path, self.server.descriptor_digest, self.connection)
        except ConnectionAbortedError:
            self.close_connection = True
            return
        except subprocess.TimeoutExpired:
            return self.reply(504, {"error": {"code": "INFERENCE_DEADLINE"}})
        except (ValueError, subprocess.CalledProcessError, OSError):
            return self.reply(502, {"error": {"code": "INFERENCE_FAILED"}})
        try:
            self.reply(200, value)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True


def stop_server(*_):
    """Interrupt the serial loop; the inference finally block kills and joins its group."""
    raise KeyboardInterrupt


def main():
    """Admit before listening; bind only an explicitly selected literal loopback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", required=True)
    parser.add_argument("--expected-descriptor-sha256", required=True)
    parser.add_argument("--host", choices=("127.0.0.1", "::1"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    admit(args.descriptor, args.expected_descriptor_sha256)
    HTTPServer.address_family = socket.AF_INET6 if args.host == "::1" else socket.AF_INET
    signal.signal(signal.SIGTERM, stop_server)
    with HTTPServer((args.host, args.port), Handler) as server:
        server.descriptor_path, server.descriptor_digest = args.descriptor, args.expected_descriptor_sha256
        server.origin = f"[{args.host}]:{server.server_port}" if args.host == "::1" else f"{args.host}:{server.server_port}"
        print(json_bytes({"protocol": PROTOCOL, "host": args.host, "port": server.server_port,
                          "service_pid": os.getpid(), "descriptor_sha256": server.descriptor_digest}).decode(), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
