"""Serialized original-tool boundary tests with owned expert and provider stubs."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

from tests.test_spatial_inputs import build_inputs

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import spatial_dispatch as sd  # noqa: E402


def value(result):
    return json.loads(result[0]["text"])


def spec(name, handle):
    return SimpleNamespace(name=name, handle=handle, description="original description", schema={"original": True})


def configured(tmp_path, name, handle, imports=None, sources=lambda: None, receipt=lambda *a: None):
    inputs, _, scene = build_inputs(tmp_path)
    barrier = sd.ProviderBarrier()
    tool = spec(name, handle)
    sd.configure_specs([tool], inputs, barrier, imports or (lambda name: pytest.fail(f"Unexpected import {name}")), sources, receipt)
    return tool, inputs, scene, barrier


def test_all_original_specs_keep_schema_and_wrap_one_shared_lock(tmp_path):
    """GIVEN concurrent handlers WHEN first owns the lock THEN second cannot admit or return."""
    inputs, _, scene = build_inputs(tmp_path)
    entered, release, second = threading.Event(), threading.Event(), threading.Event()
    calls, receipts = [], []
    def first(args):
        entered.set()
        assert release.wait(3)
        return sd.blocks({"first": True})
    def other(args):
        second.set()
        return sd.blocks({"second": True})
    tools = [spec("camera_motion", first), spec("scene_map", other)]
    before = [(tool.schema, tool.description) for tool in tools]
    def source():
        calls.append(threading.current_thread().name)
    def receipt(name, result):
        receipts.append(name)
        if name == "camera_motion":
            assert not second.is_set()
    sd.configure_specs(tools, inputs, sd.ProviderBarrier(), lambda _: None, source, receipt)
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(tools[0].handle, {"scene": scene, "frame_i": 101, "frame_j": 205})
        assert entered.wait(3)
        b = pool.submit(tools[1].handle, {"scene": scene})
        assert not second.wait(0.1) and len(calls) == 1
        release.set()
        assert value(a.result())["first"] and value(b.result())["second"]
    assert receipts == ["camera_motion", "scene_map"] and len(calls) == 4
    assert [(tool.schema, tool.description) for tool in tools] == before


def test_swallowed_dispatch_refuses_instead_of_false_absence(tmp_path):
    class Shim:
        def _dispatch(self, *a, **k):
            pytest.fail("provider escaped barrier")
    def upstream(args):
        try:
            Shim()._dispatch("expensive model", images=["private.png"])
        except RuntimeError:
            pass
        return sd.blocks({"present": False, "found": False})
    tool, _, scene, barrier = configured(tmp_path, "scene_map", upstream)
    barrier.install(Shim)
    result = value(tool.handle({"scene": scene}))
    assert result["reason"] == "provider_unavailable" and result["denied_dispatches"] == 1
    assert "found" not in result and "present" not in result
    assert barrier.attempts() == 1


@pytest.mark.parametrize("name,arguments", [("orient_facing", {"image": 0, "label": "anchor"}),
                                              ("verify_grounding", {"image": 0, "label": "anchor", "bbox": [1, 1, 2, 2]})])
def test_mandatory_provider_tools_are_advertised_but_refused(tmp_path, name, arguments):
    tool, inputs, _, _ = configured(tmp_path, name, lambda a: pytest.fail("provider-required handler executed"))
    arguments["image"] = next(iter(inputs.frames))
    result = value(tool.handle(arguments))
    assert result == {"status": "refused", "reason": "provider_unavailable"}
    assert tool.schema == {"original": True}


def test_source_and_input_changes_are_read_back_before_and_after_handler(tmp_path):
    called = []
    def mutate(args):
        Path(args["scene"]["frames"][0]).write_bytes(b"changed")
        called.append(True)
        return sd.blocks({"false_success": True})
    tool, _, scene, _ = configured(tmp_path, "camera_motion", mutate)
    result = value(tool.handle({"scene": scene, "frame_i": 101, "frame_j": 205}))
    assert called == [True] and result["status"] == "refused" and "false_success" not in result


@pytest.mark.parametrize("name,arguments", [
    ("visualize_bev", {"points_file": "private.npy"}), ("visualize_bev", {"points_b64": "legacy"}),
    ("assess_reachable", {"grid_size": 101}), ("orient_facing", {"votes": 6}),
    ("mobile_manip", {"max_reach_m": 0}), ("calibrate_scale", {"known_size_m": float("inf")}),
    ("calibrate_scale", {"dim": "diagonal"}), ("camera_motion", {"frame_i": 999}),
    ("view_reason", {"frame": 101, "viewpoint": "missing"}), ("view_reason", {"op": "invented"}),
    ("select_keyframes", {"strategy": "invented"}), ("mobile_manip", {"op": "invented"}),
    ("render_scene_views", {"faces": ["rear"]}), ("visualize_bev", {"xlim": [1, 1]}),
])
def test_invalid_evidence_and_bounds_refuse_before_original_handler(tmp_path, name, arguments):
    tool, _, scene, _ = configured(tmp_path, name, lambda a: pytest.fail("invalid dispatch"))
    result = value(tool.handle({"scene": scene, **arguments}))
    assert result["status"] == "refused" and result["reason"] == "invalid_or_unavailable_evidence"


def test_generated_ids_are_frame_local_and_uniform_indices_map_to_source_ids(tmp_path):
    inputs, _, scene = build_inputs(tmp_path)
    generated = deepcopy(scene)
    tool = spec("build_scene", lambda args: sd.blocks(generated))
    uniform = spec("select_keyframes", lambda args: sd.blocks({"frames": [0, 2]}))
    sd.configure_specs([tool, uniform], inputs, sd.ProviderBarrier(), lambda _: None, lambda: None, lambda *a: None)
    result = tool.handle({"frames": scene["frames"]})
    created = value(result)
    assert [created["instances"][str(f)][0]["id"] for f in (101, 205, 309)] == [
        "frame:101:instance:0", "frame:205:instance:0", "frame:309:instance:0"]
    assert "frame_local_generated" in json.loads(result[-1]["text"])["provenance"]["identity"]
    chosen = value(uniform.handle({"strategy": "uniform", "n": 2, "total_frames": 3}))
    assert chosen["frames"] == [101, 309]
    refused = value(uniform.handle({"strategy": "uniform", "n": 2, "total_frames": 999}))
    assert refused["status"] == "refused"


@pytest.mark.parametrize("payload", [{"pos_a": None, "pos_b": [1, 2], "frames": [101, 205], "is_moving": False},
                                      {"pos_a": [0, 0], "pos_b": [0, 0], "frames": [101, 101], "is_moving": False}])
def test_missing_or_same_frame_motion_is_unknown(tmp_path, payload):
    tool, _, scene, _ = configured(tmp_path, "object_world_motion", lambda a: sd.blocks(payload))
    result = value(tool.handle({"scene": scene, "frame_a": 101, "frame_b": 205, "target": "missing"}))
    assert result["is_moving"] is None and result["motion_state"] == "unknown"


def test_geometric_view_does_not_load_images_or_model_orientation(tmp_path):
    calls = []
    class Expert:
        def scene_layout(self, recon, frame=None, viewpoint=0, images=None):
            calls.append((frame, viewpoint, images))
            return {"relative": "left", "assumed_orientation": True}
    def imports(name):
        if name.endswith("tools._scene"):
            def recon(scene, with_images):
                assert with_images is False
                return SimpleNamespace()
            return SimpleNamespace(scene_to_recon=recon)
        assert name.endswith("experts.view_expert")
        return SimpleNamespace(ViewExpert=Expert)
    tool, _, scene, _ = configured(tmp_path, "view_reason", lambda a: pytest.fail("stock with_images handler"), imports)
    result = value(tool.handle({"scene": scene, "frame": 101, "viewpoint": "anchor"}))
    assert calls == [(101, "anchor", None)]
    assert result["geometry_assumed_facing"] and result["model_orientation_unverified"]
    refusal = value(tool.handle({"scene": scene, "frame": 101, "viewpoint": "anchor", "target": "anchor", "op": "visible_from"}))
    assert refusal["reason"] == "provider_unavailable" and len(calls) == 1


class Mobile:
    """Concrete signatures from the pinned source; wrong positional dispatch raises."""
    calls = []
    def set_vlm_module(self, module):
        pass
    def plan_navigation(self, recon, frame=None, target=0):
        return self.record("plan_navigation", frame, target)
    def plan_movement(self, recon, frame=None, target=0, max_reach_m=1):
        return self.record("plan_movement", frame, target, max_reach_m)
    def suggest_approach(self, recon, frame=None, target=0, obstacles=None):
        return self.record("suggest_approach", frame, target)
    def reachability(self, recon, frame=None, objects=None, max_reach_m=1):
        return self.record("reachability", frame, objects, max_reach_m)
    def check_object_in_view(self, recon, images, frame=None, target=0):
        return self.record("check_object_in_view", frame, target, images)
    def search_object_across_frames(self, recon, images, target):
        return self.record("search_object_across_frames", None, target, images)
    def plan_active_search(self, recon, frames, target, max_moves=3):
        return self.record("plan_active_search", None, target, frames, max_moves)
    def track_object_trajectory(self, recon, target):
        return self.record("track_object_trajectory", None, target)
    @classmethod
    def record(cls, op, frame, target, *extra):
        cls.calls.append((op, frame, target, extra))
        return {"op": op, "frame": frame, "target": target, "extra": extra}


def mobile_import(name):
    if name.endswith("tools._scene"):
        return SimpleNamespace(scene_to_recon=lambda scene, with_images: SimpleNamespace(_input_images=["admitted-image"]))
    if name.endswith("experts.mobile_expert"):
        return SimpleNamespace(MobileManipulationExpert=Mobile)
    assert name.endswith("tools._vlm")
    return SimpleNamespace(VLMShim=lambda **k: SimpleNamespace())


@pytest.mark.parametrize("op", sorted(sd.CHOICES["mobile_manip"][2]))
def test_mobile_dispatch_passes_actual_target_frame_and_images_signatures(tmp_path, op):
    Mobile.calls.clear()
    tool, _, scene, _ = configured(tmp_path, "mobile_manip", lambda a: pytest.fail("stock broken dispatch"), mobile_import)
    args = {"scene": scene, "op": op, "target": "anchor", "max_reach_m": 2, "max_moves": 4}
    if op not in ("track_object_trajectory", "search_object_across_frames", "plan_active_search"):
        args["frame"] = 205
    result = value(tool.handle(args))
    assert result["op"] == op
    assert result["target"] == (["anchor"] if op == "reachability" else "anchor")
    assert result["frame"] == args.get("frame") and len(Mobile.calls) == 1
    if op in ("check_object_in_view", "search_object_across_frames", "plan_active_search"):
        assert ["admitted-image"] in result["extra"]


@pytest.mark.parametrize("op", ["track_object_trajectory", "search_object_across_frames", "plan_active_search"])
def test_mobile_does_not_silently_ignore_selected_frame(tmp_path, op):
    tool, _, scene, _ = configured(tmp_path, "mobile_manip", lambda a: None, mobile_import)
    result = value(tool.handle({"scene": scene, "op": op, "target": "anchor", "frame": 101}))
    assert result["status"] == "refused" and "frame" in result["error"]


def test_triangulation_requires_target_in_each_selected_frame(tmp_path):
    tool, _, scene, _ = configured(tmp_path, "triangulate", lambda a: pytest.fail("missing target dispatched"))
    scene["instances"]["205"] = []
    result = value(tool.handle({"scene": scene, "target": "anchor", "frame_a": 101, "frame_b": 205}))
    assert result["status"] == "refused" and "missing" in result["error"]


def matcher_import(entities):
    class Matcher:
        def _collect_entities(self, recon, frames, label):
            return entities
        @staticmethod
        def _base_label(label):
            return label
        @staticmethod
        def _inst_bev_xz(instance, camera):
            return (camera["frame_idx"] / 100, -instance["depth_m"])
    def imports(name):
        if name.endswith("tools._scene"):
            return SimpleNamespace(scene_to_recon=lambda scene, with_images: SimpleNamespace())
        assert name.endswith("experts.entity_matcher")
        return SimpleNamespace(EntityMatcher=Matcher)
    return imports


def test_matching_refuses_transitive_same_frame_collision_preserves_count(tmp_path):
    entities = [{"id": "a", "label": "chair", "frame": 101, "bev": [0, 0]},
                {"id": "b", "label": "chair", "frame": 101, "bev": [0.2, 0]},
                {"id": "c", "label": "chair", "frame": 205, "bev": [0.1, 0]}]
    tool, _, scene, _ = configured(tmp_path, "count_objects", lambda a: sd.blocks({"count": 2}), matcher_import(entities))
    assert value(tool.handle({"scene": scene, "label": "chair", "frame": 101}))["count"] == 2
    result = value(tool.handle({"scene": scene, "label": "chair"}))
    assert result["status"] == "refused" and "same-frame" in result["error"]
    entities[1]["bev"] = [5, 5]
    assert value(tool.handle({"scene": scene, "label": "chair"}))["count"] == 2


@pytest.mark.parametrize("op", ["deduplicate", "match_across_views"])
@pytest.mark.parametrize("canonical_edge", [False, True])
def test_matching_refuses_compatible_label_and_canonical_id_bridges(tmp_path, op, canonical_edge):
    """GIVEN two same-frame sightings WHEN a compatible bridge joins them THEN refuse."""
    entities = [{"id": "a", "label": "cup", "frame": 101, "bev": [0, -4.0]},
                {"id": "b", "label": "blue cup", "frame": 101, "bev": [0, -4.2]},
                {"id": "c", "label": "cup", "frame": 205, "bev": [0, -4.1]}]
    if canonical_edge:
        entities[0].update(label="plate", bev=[8, -4.0])
        entities[2]["id"] = "a"
    dispatched = []
    tool, _, scene, _ = configured(tmp_path, "match_entities",
                                   lambda args: dispatched.append(args) or sd.blocks({"groups": []}),
                                   matcher_import(entities))
    result = value(tool.handle({"scene": scene, "op": op, "match_dist_m": 0.6}))
    assert result["status"] == "refused" and "same-frame" in result["error"]
    assert not dispatched


def test_virtual_viewpoint_frame_is_respected_and_missing_targets_refuse(tmp_path):
    seen = []
    tool, _, scene, _ = configured(tmp_path, "visualize_bev", lambda a: (seen.append(a["viewpoint"]) or sd.blocks({"rendered": True})), matcher_import([]))
    result = value(tool.handle({"scene": scene, "viewpoint": {"at": {"frame": 205, "label": "anchor"}, "facing": 90}}))
    assert result["rendered"] and seen == [{"at": [2.05, -4], "facing": 90}]
    for vp in ({"frame": 999}, {"at": "missing", "facing": 0}, {"at": "anchor", "facing": 0},
               {"at": [0, 0]}, {"at": [0, 0], "facing": [0, 0]}, {"at": [0, 0], "facing": float("nan")}):
        assert value(tool.handle({"scene": scene, "viewpoint": vp}))["status"] == "refused"
    assert len(seen) == 1


def test_original_exception_error_block_and_missing_receipt_are_honest_refusals(tmp_path):
    tool, _, scene, _ = configured(tmp_path / "exception", "scene_map", lambda a: (_ for _ in ()).throw(RuntimeError("original error")))
    assert value(tool.handle({"scene": scene}))["status"] == "refused"
    tool, _, scene, _ = configured(tmp_path / "error", "scene_map", lambda a: [{"type": "text", "text": "Error: source failure"}])
    assert value(tool.handle({"scene": scene}))["status"] == "refused"
    tool, _, scene, _ = configured(tmp_path / "receipt", "scene_map", lambda a: sd.blocks({"complete": True}), receipt=lambda *a: (_ for _ in ()).throw(OSError("disk unavailable")))
    assert value(tool.handle({"scene": scene}))["reason"] == "evidence_receipt_unavailable"
