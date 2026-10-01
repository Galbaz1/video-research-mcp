"""Admit authorized PNG bytes, source clocks and finite spatial scene estimates."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import stat
import struct

SCENE = "video-spatio/scene@1"


def digest(path: Path) -> str:
    """Hash exact admitted file bytes without loading image or foreign code."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def finite(value, name: str, positive=False) -> float:
    """Require a real finite number and optionally a positive value."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def bounded_int(value, name: str, low: int, high: int) -> int:
    """Reject fractional and boolean resource counts before expert dispatch."""
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def admit_file(row: dict) -> Path:
    """Require the exact absolute regular file selected by the trusted manifest."""
    path = Path(row["path"])
    if not path.is_absolute() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Input must be an absolute regular file")
    if path != path.resolve() or path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
        raise ValueError("Input path, bytes or SHA256 differs from its admitted selection")
    return path


def png_size(path: Path) -> tuple[int, int]:
    """Read PNG dimensions without importing or decoding through Pillow."""
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError("Selected frame must have a PNG IHDR header")
    width, height = struct.unpack(">II", header[16:24])
    if not width or not height or width * height > 16_000_000:
        raise ValueError("PNG dimensions exceed the 16M-pixel frame bound")
    return width, height


class Inputs:
    """Bind every scene path and frame reference to an independently admitted manifest."""

    def __init__(self, manifest: Path, sha256: str):
        if digest(manifest) != sha256:
            raise ValueError("Input manifest differs from the trusted SHA256")
        self.manifest, self.sha256 = manifest, sha256
        self.data = json.loads(manifest.read_text())
        if self.data["schema_version"] != 1:
            raise ValueError("Unsupported input manifest schema")
        source = self.data["source"]
        if len(source["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in source["sha256"]):
            raise ValueError("Source SHA256 must be an explicit lowercase digest")
        if not isinstance(source["revision"], str) or not source["revision"].strip():
            raise ValueError("Source revision must be explicit")
        rows = self.data["frames"]
        bounded_int(len(rows), "frames", 1, 64)
        self.frames, self.ids, self.sizes = {}, {}, {}
        previous = -math.inf
        for row in rows:
            path = admit_file(row)
            frame = bounded_int(row["source_frame_id"], "source_frame_id", 0, 2**63 - 1)
            pts = bounded_int(row["pts"], "pts", 0, 2**63 - 1)
            num, den = row["time_base"]
            bounded_int(num, "time_base numerator", 1, 2**31 - 1)
            bounded_int(den, "time_base denominator", 1, 2**31 - 1)
            seconds = finite(pts * num / den, "source clock")
            if str(path) in self.frames or frame in self.ids or seconds <= previous:
                raise ValueError("Frame paths/IDs must be unique and source clocks strictly increasing")
            self.frames[str(path)], self.ids[frame], self.sizes[str(path)] = row, row, png_size(path)
            previous = seconds
        self.scenes = {}
        for row in self.data.get("scenes", []):
            path = admit_file(row)
            if str(path) in self.scenes:
                raise ValueError("Scene files must be unique")
            self.scenes[str(path)] = row
        self.generated = set()
        self.readback()
        for path in self.scenes:
            self.validate_scene(json.loads(Path(path).read_text()))

    def readback(self) -> None:
        """Rehash source input authority and all selected frame/scene files for each call."""
        if digest(self.manifest) != self.sha256:
            raise ValueError("Input manifest changed during the owned session")
        for row in (*self.frames.values(), *self.scenes.values()):
            admit_file(row)

    def image(self, path: str) -> dict:
        """Resolve only an explicitly authorized path; no file/base64 guessing."""
        if path not in self.frames:
            raise ValueError("Image path is outside the admitted input manifest")
        return self.frames[path]

    def frame_ids(self, paths: list[str]) -> list[int]:
        """Map selected ordered paths to exact original source frame IDs."""
        bounded_int(len(paths), "frames", 1, 64)
        ids = [self.image(path)["source_frame_id"] for path in paths]
        if len(set(ids)) != len(ids):
            raise ValueError("Selected frame paths must be unique")
        clocks = [self.ids[frame]["pts"] * self.ids[frame]["time_base"][0] / self.ids[frame]["time_base"][1] for frame in ids]
        if clocks != sorted(clocks):
            raise ValueError("Selected frames must follow their actual source clocks")
        return ids

    def load_scene(self, arguments: dict) -> dict:
        """Accept finite inline scene estimates or a specifically admitted scene file."""
        scene = arguments.get("scene")
        if scene is None:
            path = arguments.get("scene_file")
            if path not in self.scenes:
                raise ValueError("scene_file is outside the admitted input manifest")
            scene = json.loads(Path(path).read_text())
        elif arguments.get("scene_file") is not None:
            raise ValueError("Select either scene or scene_file")
        if isinstance(scene, str):
            scene = json.loads(scene)
        self.validate_scene(scene)
        return scene

    def validate_scene(self, scene: dict) -> None:
        """Require aligned finite frames, keys, cameras and per-frame instance identity."""
        if not isinstance(scene, dict) or scene.get("type") != SCENE:
            raise ValueError("Expected the selected scene schema")
        finite_tree(scene)
        ids = self.frame_ids(scene["frames"])
        if scene["frame_indices"] != ids or any(type(value) is not int for value in scene["frame_indices"]):
            raise ValueError("Scene frames must align to admitted source IDs")
        keys = {str(frame) for frame in ids}
        if set(scene["instances"]) != keys or set(scene["cameras"]) != keys:
            raise ValueError("Scene instance/camera keys must match every source frame")
        finite(scene["metric_scale"], "metric_scale", positive=True)
        width, height = self.sizes[scene["frames"][0]]
        if any(self.sizes[p] != (width, height) for p in scene["frames"]):
            raise ValueError("Scene frames require one shared image size")
        if scene["image_size"] != {"w": width, "h": height}:
            raise ValueError("Scene image dimensions differ from admitted PNG bytes")
        self.intrinsics(scene["intrinsics"], width, height)
        labels = {}
        for frame in ids:
            camera = scene["cameras"][str(frame)]
            if type(camera["frame_idx"]) is not int or camera["frame_idx"] != frame:
                raise ValueError("Camera references an unknown source frame")
            for key in ("pos_bev", "move_vec_bev"):
                vector(camera[key], key, 2)
            for key in ("yaw_deg", "yaw_delta_deg", "pitch_deg", "roll_deg", "fov_deg"):
                finite(camera[key], key)
            if not 0 < camera["fov_deg"] < 180:
                raise ValueError("Camera FOV must be between zero and 180 degrees")
            self.intrinsics(camera["intrinsics"], width, height)
            seen = set()
            for instance in scene["instances"][str(frame)]:
                self.instance(instance, frame, width, height)
                identity, label = instance["id"], instance["label"]
                if identity in seen or identity in labels and labels[identity] != label:
                    raise ValueError("Duplicate instance ID within frame or conflicting track labels")
                seen.add(identity)
                labels[identity] = label

    @staticmethod
    def intrinsics(value: dict, width: int, height: int) -> None:
        """Check declared pinhole parameters without claiming calibrated optics."""
        for key in ("fx", "fy"):
            finite(value[key], key, positive=True)
        for key, bound in (("cx", width), ("cy", height)):
            if not 0 <= finite(value[key], key) <= bound:
                raise ValueError("Principal point must lie within the admitted image")

    @staticmethod
    def instance(value: dict, frame: int, width: int, height: int) -> None:
        """Validate an explicit estimate and its original source-frame association."""
        if type(value["frame_idx"]) is not int or value["frame_idx"] != frame or not isinstance(value["id"], str) or not value["id"].strip():
            raise ValueError("Instance ID/frame must be explicit")
        if not isinstance(value["label"], str) or not value["label"].strip():
            raise ValueError("Instance label must be nonempty")
        finite(value["depth_m"], "depth_m", positive=True)
        finite(value["conf"], "conf")
        bbox(value["bbox_1000"], 1000, 1000)
        bbox(value["bbox_pixel"], width, height)
        point = vector(value["point_1000"], "point_1000", 2)
        if any(not 0 <= x <= 1000 for x in point):
            raise ValueError("Normalized center lies outside the image")

    def provenance(self, scene=None) -> dict:
        """Expose source clocks and the unverified assumptions beside every result."""
        generated = scene is not None and scene_hash(scene) in self.generated
        return {"input_manifest_sha256": self.sha256, "source": self.data["source"],
                "frames": list(self.frames.values()),
                "identity": "frame_local_generated; cross_view_heuristic" if generated else "caller_asserted_unverified",
                "depth_camera": "caller_estimates; generated cameras may be identity",
                "optics": "generated horizontal FOV60/pinhole assumed; supplied intrinsics uncalibrated",
                "metric_scale": "declared only; downstream does not consistently apply metric_scale",
                "geometry": "coarse planar estimates; counts/matching are heuristics, not physical proof"}


def vector(value, name: str, dimensions: int) -> list:
    """Require one finite vector with the selected dimensionality."""
    if not isinstance(value, (list, tuple)) or len(value) != dimensions:
        raise ValueError(f"{name} must have {dimensions} coordinates")
    return [finite(x, name) for x in value]


def finite_tree(value) -> None:
    """Reject nonfinite numeric extensions as well as the required scene fields."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Scene numeric values must all be finite")
    if isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            finite_tree(item)


def bbox(value, width: float, height: float) -> None:
    """Check ordered bounded x-first image coordinates."""
    x1, y1, x2, y2 = vector(value, "bbox", 4)
    if not 0 <= x1 < x2 <= width or not 0 <= y1 < y2 <= height:
        raise ValueError("BBox must be ordered and contained in the admitted image")


def scene_hash(scene: dict) -> str:
    """Bind generated identity provenance to the actual returned scene content."""
    return hashlib.sha256(json.dumps(scene, sort_keys=True, allow_nan=False).encode()).hexdigest()
