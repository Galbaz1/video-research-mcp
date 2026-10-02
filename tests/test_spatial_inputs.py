"""Exact first-party input admission tests; no Pillow or external source is imported."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import spatial_inputs as si  # noqa: E402


def png(path, width=8, height=6, value=0):
    """Write a small valid PNG using only stdlib to avoid a scientific runtime import."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    body = zlib.compress((b"\0" + bytes([value]) * width) * height)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
                     + chunk(b"IDAT", body) + chunk(b"IEND", b""))
    return path


def row(path, **extra):
    """Bind one absolute temporary fixture's exact bytes."""
    return {"path": str(path.resolve()), "sha256": si.digest(path), "bytes": path.stat().st_size, **extra}


def make_scene(frames, ids=(101, 205, 309)):
    """Supply a small scene with declared estimates and persistent caller IDs."""
    intrinsics = {"fx": 7.0, "fy": 7.0, "cx": 4.0, "cy": 3.0}
    return {"type": si.SCENE, "frames": frames, "frame_indices": list(ids), "metric_scale": 1.0,
            "image_size": {"w": 8, "h": 6}, "intrinsics": intrinsics,
            "cameras": {str(f): {"frame_idx": f, "pos_bev": [0.0, 0.0], "move_vec_bev": [0.0, 0.0],
                                "yaw_deg": 0.0, "yaw_delta_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0,
                                "fov_deg": 60.0, "intrinsics": dict(intrinsics)} for f in ids},
            "instances": {str(f): [{"id": "anchor", "label": "anchor", "frame_idx": f,
                                    "depth_m": 4.0, "conf": 1.0, "bbox_1000": [400, 400, 600, 600],
                                    "bbox_pixel": [3.2, 2.4, 4.8, 3.6], "point_1000": [500, 500]}] for f in ids}}


def build_inputs(tmp_path, with_scene=True):
    """Freeze explicit PNG selection and optional authorized scene bytes."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    frames = [png(tmp_path / f"frame-{i}.png", value=k * 10) for k, i in enumerate((101, 205, 309))]
    data = {"schema_version": 1, "source": {"sha256": "a" * 64, "revision": "firstparty-fixture-v1"},
            "frames": [row(p, source_frame_id=f, pts=k * 25, time_base=[1, 25])
                       for k, (p, f) in enumerate(zip(frames, (101, 205, 309)))], "scenes": []}
    scene = make_scene([str(p.resolve()) for p in frames])
    if with_scene:
        scene_path = tmp_path / "scene.json"
        scene_path.write_text(json.dumps(scene))
        data["scenes"].append(row(scene_path))
    manifest = tmp_path / "inputs.json"
    manifest.write_text(json.dumps(data))
    return si.Inputs(manifest, si.digest(manifest)), data, scene


def refreeze(inputs, data):
    """Issue a new test authority for a deliberately malformed candidate manifest."""
    inputs.manifest.write_text(json.dumps(data))
    return si.Inputs(inputs.manifest, si.digest(inputs.manifest))


def test_admitted_source_clocks_and_scene_readback(tmp_path):
    """GIVEN selected PNG bytes WHEN admitted THEN source IDs and clocks remain explicit."""
    inputs, data, scene = build_inputs(tmp_path)
    assert inputs.frame_ids(scene["frames"]) == [101, 205, 309]
    assert inputs.load_scene({"scene_file": data["scenes"][0]["path"]}) == scene
    assert inputs.load_scene({"scene": json.dumps(scene)}) == scene
    inputs.readback()
    provenance = inputs.provenance(scene)
    assert provenance["identity"] == "caller_asserted_unverified"
    assert provenance["frames"][1]["pts"] == 25
    assert provenance["frames"][1]["time_base"] == [1, 25]
    assert "not physical proof" in provenance["geometry"]


@pytest.mark.parametrize("kind", ["manifest", "frame", "scene"])
def test_changed_bytes_refuse_fresh_readback(tmp_path, kind):
    inputs, data, _ = build_inputs(tmp_path)
    path = inputs.manifest if kind == "manifest" else Path(data["frames" if kind == "frame" else "scenes"][0]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed|differs"):
        inputs.readback()


@pytest.mark.parametrize("change", ["duplicate_id", "duplicate_path", "clock", "clock_boolean", "timebase_zero", "bad_source", "empty_revision", "too_many"])
def test_bad_manifest_metadata_refuses(tmp_path, change):
    inputs, data, _ = build_inputs(tmp_path)
    if change == "duplicate_id":
        data["frames"][1]["source_frame_id"] = 101
    elif change == "duplicate_path":
        data["frames"][1].update({k: data["frames"][0][k] for k in ("path", "sha256", "bytes")})
    elif change == "clock":
        data["frames"][1]["pts"] = 0
    elif change == "clock_boolean":
        data["frames"][1]["pts"] = True
    elif change == "timebase_zero":
        data["frames"][0]["time_base"] = [1, 0]
    elif change == "bad_source":
        data["source"]["sha256"] = "wrong"
    elif change == "empty_revision":
        data["source"]["revision"] = " "
    else:
        data["frames"] *= 22
    with pytest.raises(ValueError):
        refreeze(inputs, data)


def test_symlink_relative_and_oversized_png_refused(tmp_path):
    target = png(tmp_path / "target.png")
    link = tmp_path / "link.png"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        si.admit_file({**row(target), "path": str(link)})
    with pytest.raises(ValueError):
        si.admit_file({**row(target), "path": "relative.png"})
    target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 5000, 5000))
    with pytest.raises(ValueError, match="16M"):
        si.png_size(target)


@pytest.mark.parametrize("change", ["unknown_frame", "extra_key", "duplicate_instance", "label_conflict", "negative_depth", "nan_camera", "nan_extension", "bad_bbox", "bad_intrinsics", "image_size", "camera_id"])
def test_scene_estimates_must_be_finite_aligned_and_unambiguous(tmp_path, change):
    inputs, _, original = build_inputs(tmp_path)
    scene = deepcopy(original)
    instance = scene["instances"]["101"][0]
    if change == "unknown_frame":
        scene["frame_indices"][0] = 999
    elif change == "extra_key":
        scene["instances"]["999"] = []
    elif change == "duplicate_instance":
        scene["instances"]["101"].append(deepcopy(instance))
    elif change == "label_conflict":
        scene["instances"]["205"][0]["label"] = "different"
    elif change == "negative_depth":
        instance["depth_m"] = -1
    elif change == "nan_camera":
        scene["cameras"]["101"]["pos_bev"] = [float("nan"), 0]
    elif change == "nan_extension":
        scene["extension"] = {"estimate": float("inf")}
    elif change == "bad_bbox":
        instance["bbox_1000"] = [600, 400, 400, 600]
    elif change == "bad_intrinsics":
        scene["intrinsics"]["fx"] = 0
    elif change == "image_size":
        scene["image_size"]["w"] = 9
    else:
        scene["cameras"]["101"]["frame_idx"] = 205
    with pytest.raises(ValueError):
        inputs.load_scene({"scene": scene})


def test_paths_and_selection_cannot_escape_authority(tmp_path):
    inputs, _, scene = build_inputs(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        inputs.image(str(tmp_path / "unselected.png"))
    with pytest.raises(ValueError, match="outside"):
        inputs.load_scene({"scene_file": str(tmp_path / "other.json")})
    with pytest.raises(ValueError, match="either"):
        inputs.load_scene({"scene": scene, "scene_file": "anything"})
    with pytest.raises(ValueError, match="unique"):
        inputs.frame_ids([scene["frames"][0]] * 2)
    with pytest.raises(ValueError, match="clocks"):
        inputs.frame_ids(list(reversed(scene["frames"])))
    assert si.scene_hash(scene) == hashlib.sha256(json.dumps(scene, sort_keys=True, allow_nan=False).encode()).hexdigest()
