"""Bounded first-party file, syntax and snapshot checks for ordinary host skills."""

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import yaml

MAX_BYTES = 8 * 1024 * 1024
MAX_METADATA = 256 * 1024
MAX_SOURCE = 512 * 1024 * 1024
MAX_FILES = 64
HASH = re.compile(r"[0-9a-f]{64}\Z")
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".sh", ".js", ".ts"}
UNSAFE = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous|prior|system)\s+instructions|"
    r"(?:api[_-]?key|access[_-]?token|password|secret)['\"]?\s*[=:]\s*['\"]?[A-Za-z0-9_/-]{12,}|"
    r"\b(?:rm\s+-[a-z]*r[a-z]*f|sudo|mkfs|shutdown)\b|"
    r"\b(?:curl|wget)\s+[^\n]*https?://|"
    r"\b(?:exfiltrate|send\s+(?:an?\s+)?email|delete\s+all\s+files)\b|"
    r"\b(?:upload|publish)\s+[^\n]*https?://|"
    r"\b(?:requests\.(?:post|put|delete)|fetch)\s*\([^\n]*https?://",
    re.IGNORECASE,
)
EXCLUDED = {".build", "build", "debug", "cache", ".cache", "node_modules", "__pycache__", ".git"}


class InvalidSkill(ValueError):
    """A retained authoring directory does not satisfy the bounded contract."""


def require(condition, message):
    """Reject a concrete contract violation."""
    if not condition:
        raise InvalidSkill(message)


def sha(data):
    """Return the full SHA-256 commitment of bytes."""
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    """Serialize finite JSON deterministically."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode()


def pairs(items):
    """Reject ambiguous duplicate JSON or YAML keys."""
    result = {}
    for key, value in items:
        require(isinstance(key, str) and key not in result, "duplicate or non-string metadata key")
        result[key] = value
    return result


def _bounded(value, depth=0):
    require(depth <= 16, "metadata nesting exceeds 16")
    if isinstance(value, dict):
        require(len(value) <= 256, "metadata object exceeds 256 fields")
        for item in value.values():
            _bounded(item, depth + 1)
    elif isinstance(value, list):
        require(len(value) <= 256, "metadata list exceeds 256 entries")
        for item in value:
            _bounded(item, depth + 1)
    elif isinstance(value, float):
        require(math.isfinite(value), "nonfinite metadata number")
    elif isinstance(value, str):
        require(len(value) <= 32768, "metadata string exceeds 32768 characters")
    else:
        require(value is None or type(value) in (bool, int), "unsupported metadata value")


def parse_json(data):
    """Read bounded finite JSON with unambiguous keys."""
    require(len(data) <= MAX_METADATA, "JSON exceeds 256 KiB")
    value = json.loads(data, object_pairs_hook=pairs,
                       parse_constant=lambda _: require(False, "nonfinite JSON number"))
    _bounded(value)
    return value


def scan(data, label):
    """Refuse known unsafe patterns; this is not a semantic safety certificate."""
    text = data.decode("utf-8")
    require(not UNSAFE.search(text), f"unsafe embedded instruction or task pattern: {label}")
    return text


class _Loader(yaml.SafeLoader):
    yaml_implicit_resolvers = {
        key: [(tag, pattern) for tag, pattern in values
              if tag != "tag:yaml.org,2002:timestamp"]
        for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    def compose_node(self, parent, index):
        require(not self.check_event(yaml.AliasEvent), "YAML aliases are unsupported")
        return super().compose_node(parent, index)


def _mapping(loader, node):
    return pairs((loader.construct_object(k), loader.construct_object(v)) for k, v in node.value)


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def frontmatter(data):
    """Read ordinary host name/description YAML without arbitrary constructors."""
    text = scan(data, "SKILL.md")
    require(text.startswith("---\n"), "SKILL.md requires YAML frontmatter")
    end = text.find("\n---\n", 4)
    require(0 < end <= 16384, "missing or oversized YAML frontmatter")
    metadata = yaml.load(text[4:end], Loader=_Loader)
    require(isinstance(metadata, dict), "frontmatter must be an object")
    _bounded(metadata)
    name, description = metadata.get("name"), metadata.get("description")
    require(isinstance(name, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
            and len(name) < 64, "invalid skill name")
    require(isinstance(description, str) and 0 < len(description) <= 1024,
            "invalid skill description")
    return metadata, text[end + 5:]


def relative(value):
    """Require a normalized relative POSIX path without traversal."""
    require(isinstance(value, str) and 0 < len(value) <= 256, "invalid relative path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and path.as_posix() == value and
            all(part not in {"", ".", ".."} for part in path.parts) and
            "\\" not in value and ":" not in value and "\x00" not in value,
            "escaping or noncanonical relative path")
    return path


def portable(value):
    """Fence the positive archive set without enumerating or reading extras."""
    path = relative(value)
    require(not any(part in EXCLUDED or part.startswith(".env") or
                    re.search(r"credential|secret|token", part, re.I) for part in path.parts),
            "private or credential path cannot be packaged")
    require(path.name != "package-manifest.json", "reserved package manifest name")


class Snapshot:
    """Retain explicit regular inputs and their frozen commitments only."""

    def __init__(self, root):
        self.root = Path(os.path.abspath(root))
        self._check_components(self.root, directory=True)
        self.bindings = {}
        self.members = {}
        self.bytes_read = 0

    @staticmethod
    def _check_components(path, directory=False):
        for component in [*reversed(path.parents), path]:
            mode = component.lstat().st_mode
            require(not stat.S_ISLNK(mode), "symlink path component refused")
        require(stat.S_ISDIR(path.stat().st_mode) if directory else stat.S_ISREG(path.stat().st_mode),
                "expected regular file or owned directory")

    def _path(self, name):
        path = self.root.joinpath(*relative(name).parts)
        self._check_components(path)
        return path

    @staticmethod
    def _open_regular(path):
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in path.parts[1:-1]:
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                    dir_fd=descriptor)
                os.close(descriptor)
                descriptor = following
            return os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                           dir_fd=descriptor)
        finally:
            os.close(descriptor)

    def _read(self, name, limit, retain):
        path = self._path(name)
        with os.fdopen(self._open_regular(path), "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_size <= limit, "file size/type bound")
            digest, chunks, size = hashlib.sha256(), [], 0
            while chunk := stream.read(65536):
                size += len(chunk)
                require(size <= limit, "file grew beyond bound")
                digest.update(chunk)
                if retain:
                    chunks.append(chunk)
            after = os.fstat(stream.fileno())
        require((before.st_ino, before.st_size, before.st_mtime_ns) ==
                (after.st_ino, after.st_size, after.st_mtime_ns), "input changed during read")
        return b"".join(chunks), {"sha256": digest.hexdigest(), "bytes": size, "limit": limit}

    def read(self, name, *, member=False, limit=MAX_METADATA):
        """Read an explicitly selected input, enforcing frozen identity and total bounds."""
        if member:
            portable(name)
        data, binding = self._read(name, limit, True)
        previous = self.bindings.get(name)
        require(previous is None or all(previous[key] == binding[key] for key in ("sha256", "bytes")), "input changed during validation")
        if previous is None:
            require(len(self.bindings) < MAX_FILES, "input count exceeds 64")
            self.bytes_read += len(data)
            require(self.bytes_read <= MAX_BYTES, "retained inputs exceed 8 MiB")
        self.bindings[name] = previous or binding
        if member:
            self.members[name] = data
        return data

    def source(self, name):
        """Hash the nonempty original without retaining or packaging its bytes."""
        _, binding = self._read(name, MAX_SOURCE, False)
        require(binding["bytes"] > 0 and name not in self.bindings, "empty or reused source path")
        require(len(self.bindings) < MAX_FILES, "input count exceeds 64")
        self.bindings[name] = binding
        return binding["sha256"]

    def document(self, name, *, member=False):
        """Read and pattern-scan a referenced JSON document."""
        data = self.read(name, member=member)
        scan(data, name)
        return parse_json(data)

    def bound(self, ref, *, member=False):
        """Read a path/full-hash binding exactly."""
        require(isinstance(ref, dict) and set(ref) == {"path", "sha256"}, "invalid file binding")
        require(isinstance(ref["sha256"], str) and HASH.fullmatch(ref["sha256"]), "invalid SHA-256")
        data = self.read(ref["path"], member=member, limit=MAX_BYTES)
        require(sha(data) == ref["sha256"], "file SHA-256 mismatch")
        return data

    def recheck(self):
        """Rehash every frozen input immediately before atomic promotion."""
        for name, expected in self.bindings.items():
            _, current = self._read(name, expected["limit"], False)
            require(current == expected, "frozen input changed before promotion")


def linked_files(snapshot, start="SKILL.md"):
    """Follow bounded Markdown local links; remote HTTP citations remain unfetched data."""
    pending, visited = [start], set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        data = snapshot.read(name, member=True, limit=MAX_METADATA)
        if Path(name).suffix not in TEXT_SUFFIXES:
            continue
        text = scan(data, name)
        if Path(name).suffix != ".md":
            continue
        definitions = dict(re.findall(r"^\[([^\]]+)\]:\s*(\S+)", text, re.M))
        targets = re.findall(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+['\"][^)]*)?\)", text)
        for key in re.findall(r"!?\[[^\]]+\]\[([^\]]+)\]", text):
            require(key in definitions, "undefined Markdown reference")
            targets.append(definitions[key])
        targets.extend(definitions.values())
        for raw in targets:
            parsed = urlsplit(raw.strip("<>"))
            if parsed.scheme in {"http", "https"}:
                continue
            require(not parsed.scheme and not parsed.netloc and not parsed.query,
                    "unsupported link scheme or query")
            target = name if not parsed.path else (
                PurePosixPath(name).parent / unquote(parsed.path)).as_posix()
            relative(target)
            target_data = snapshot.read(target, member=True, limit=MAX_BYTES)
            if parsed.fragment:
                headings = re.findall(r"^#{1,6}\s+(.+)$", target_data.decode(), re.M)
                slugs = {re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-")
                         for heading in headings}
                require(unquote(parsed.fragment) in slugs, "missing Markdown fragment")
            if Path(target).suffix in TEXT_SUFFIXES:
                pending.append(target)
