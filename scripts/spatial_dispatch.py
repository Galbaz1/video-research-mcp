"""Own bounded dispatch, provider refusal and honest spatial evidence boundaries."""

from __future__ import annotations

from functools import wraps
import json
import math
import threading

from spatial_inputs import bbox, bounded_int, finite, finite_tree, scene_hash, vector
from spatial_motion import handle as motion_handle

PACKAGE = "qwen_mm_plugins_video_spatio"
CHOICES = {
    "select_keyframes": ("strategy", "motion", {"uniform", "motion", "coverage", "covisibility"}),
    "view_reason": ("op", "scene_layout", {"scene_layout", "from_viewpoint", "visible_from", "line_of_sight"}),
    "scene_map": ("op", "cognitive_map", {"cognitive_map", "appearance_order", "locate_event", "diff_frames"}),
    "match_entities": ("op", "match_across_views", {"match_across_views", "deduplicate"}),
    "mobile_manip": ("op", "plan_navigation", {"plan_navigation", "plan_movement", "plan_active_search", "reachability",
                                            "suggest_approach", "check_object_in_view", "search_object_across_frames", "track_object_trajectory"}),
}


def blocks(value) -> list:
    """Return an explicit JSON evidence block without changing original input schemas."""
    return [{"type": "text", "text": json.dumps(value, allow_nan=False)}]


class ProviderBarrier:
    """Deny every actual VLM dispatch and expose swallowed attempts to the caller."""

    def __init__(self):
        self.state = threading.local()

    def install(self, shim) -> None:
        """Replace the real dispatch site before tool execution; no HTTP fallback remains."""
        barrier = self

        def denied(instance, *args, **kwargs):
            barrier.state.attempts = getattr(barrier.state, "attempts", 0) + 1
            raise RuntimeError("provider_unavailable: this owned spatial route has no provider authority")
        shim._dispatch = denied

    def reset(self) -> None:
        """Start a fresh per-handler attempt count on its actual worker thread."""
        self.state.attempts = 0

    def attempts(self) -> int:
        """Read the actual denied attempt count even if an upstream expert caught it."""
        return getattr(self.state, "attempts", 0)


def target_instance(scene, target: str, frame=None, missing_ok=False):
    """Reject absent or ambiguous substring matches used by the pinned experts."""
    if not isinstance(target, str) or not target.strip():
        raise ValueError("Requested target/viewpoint must be a nonempty label or ID")
    frames = [frame] if frame is not None else scene["frame_indices"]
    hits = []
    for source_id in frames:
        matches = [item for item in scene["instances"][str(source_id)]
                   if target.lower() == item["label"].lower() or target.lower() in item["label"].lower()
                   or item["label"].lower() in target.lower() or target.lower() in item["id"].lower()]
        if len(matches) > 1:
            raise ValueError("Requested target/viewpoint has ambiguous instance matches")
        hits.extend((source_id, item) for item in matches)
    if not hits and not missing_ok:
        raise ValueError("Requested target/viewpoint is missing from the selected scene frames")
    return hits


def validate(name: str, arguments: dict, inputs) -> tuple[dict, dict | None]:
    """Bound paths, resource counts, clocks, dimensions and selected scene references."""
    args = dict(arguments)
    finite_tree(args)
    if name in CHOICES:
        key, default, allowed = CHOICES[name]
        if args.get(key, default) not in allowed:
            raise ValueError(f"Unknown {name} {key}")
    for key in ("points_file", "points_b64", "masks_file", "masks_b64"):
        if args.get(key) is not None:
            raise ValueError("Legacy NPY/base64 inputs are outside the admitted scene route")
    if args.get("image") is not None:
        inputs.image(args["image"])
    if args.get("frames") is not None:
        ids = inputs.frame_ids(args["frames"])
        if name == "build_scene":
            if args.get("frame_indices") not in (None, ids):
                raise ValueError("build_scene frame_indices must match actual source IDs")
            args["frame_indices"] = ids
    for key, maximum in (("grid_size", 100), ("votes", 5), ("n", 64), ("total_frames", 64),
                         ("max_moves", 32), ("budget_moves", 32), ("n_future", 32), ("order", 5)):
        if args.get(key) is not None:
            bounded_int(args[key], key, 1, maximum)
    for key in ("known_size_m", "max_reach_m", "dup_threshold", "match_dist_m", "resolution"):
        if args.get(key) is not None:
            finite(args[key], key, positive=True)
    if args.get("dim", "width") not in ("width", "height"):
        raise ValueError("Scale dimension must be width or height")
    for key in ("xlim", "zlim"):
        if args.get(key) is not None:
            low, high = vector(args[key], key, 2)
            if low >= high:
                raise ValueError("Plot limits must be strictly ordered")
    if name == "verify_grounding":
        bbox(args["bbox"], 1000, 1000)
    if name in ("build_scene", "motion", "orient_facing", "verify_grounding"):
        return args, None
    uniform = name == "select_keyframes" and args.get("strategy", "motion") == "uniform"
    scene = None if uniform and args.get("scene") is None and args.get("scene_file") is None else inputs.load_scene(args)
    if scene is not None:
        args.pop("scene_file", None)
        args["scene"] = scene
        scene_references(name, args, scene)
    if name == "render_scene_views" and any(face not in ("front", "top", "bev", "left", "right") for face in args.get("faces", ["front", "top"])):
        raise ValueError("Unknown requested orthographic face")
    if uniform and args.get("total_frames") != len(scene["frame_indices"] if scene else inputs.ids):
        raise ValueError("Uniform total_frames must match the admitted source frame inventory")
    return args, scene


def scene_references(name: str, args: dict, scene: dict) -> None:
    """Refuse missing source frames and geometric targets before their silent defaults."""
    for key in ("frame", "frame_a", "frame_b", "frame_i", "frame_j"):
        if args.get(key) is not None and (type(args[key]) is not int or args[key] not in scene["frame_indices"]):
            raise ValueError("Requested frame is outside the selected scene")
    if name in ("view_reason", "calibrate_scale", "triangulate"):
        for target in [args.get("viewpoint"), args.get("target"), *(args.get("targets") or [])]:
            if target:
                target_instance(scene, target, args.get("frame"))
    if name == "mobile_manip" and args.get("op", "plan_navigation") not in (
            "plan_active_search", "check_object_in_view", "search_object_across_frames"):
        target_instance(scene, args["target"], args.get("frame"))
    if name == "triangulate":
        for frame in (args["frame_a"], args["frame_b"]):
            target_instance(scene, args["target"], frame)
    if name == "object_world_motion":
        for frame in (args.get("frame_a"), args.get("frame_b")):
            target_instance(scene, args["target"], frame, missing_ok=True)


def viewpoint(arguments: dict, scene: dict, import_module) -> None:
    """Resolve explicit virtual targets in their selected frame through original geometry."""
    value = arguments.get("viewpoint")
    if value is None:
        return
    value = json.loads(value) if isinstance(value, str) else value
    if not isinstance(value, dict):
        raise ValueError("BEV viewpoint must be an explicit camera or virtual viewpoint")
    if "frame" in value and "at" not in value:
        scene_references("visualize_bev", value, scene)
        arguments["viewpoint"] = value
        return
    if "at" not in value or ("facing" in value) == ("facing_away" in value):
        raise ValueError("Virtual viewpoint requires at and exactly one facing direction")

    def position(spec):
        if isinstance(spec, (list, tuple)):
            return vector(spec, "virtual viewpoint point", 2)
        frame = spec.get("frame") if isinstance(spec, dict) else None
        if frame is not None:
            scene_references("visualize_bev", {"frame": frame}, scene)
        label = spec.get("label") if isinstance(spec, dict) else spec
        hits = target_instance(scene, label, frame)
        if len(hits) != 1:
            raise ValueError("Virtual target across frames requires an explicit unique frame")
        source_id, instance = hits[0]
        expert = import_module(f"{PACKAGE}.experts.entity_matcher").EntityMatcher
        return vector(expert._inst_bev_xz(instance, scene["cameras"][str(source_id)]), "virtual target", 2)

    direction = "facing" if "facing" in value else "facing_away"
    origin = position(value["at"])
    facing = value[direction]
    facing = finite(facing, "virtual heading") if isinstance(facing, (int, float)) else position(facing)
    if isinstance(facing, list) and facing == origin:
        raise ValueError("Virtual facing point must differ from its origin")
    arguments["viewpoint"] = {"at": origin, direction: facing}


def mobile(arguments: dict, scene: dict, import_module) -> list:
    """Call the pinned expert with its actual target/frame/images signatures."""
    helper = import_module(f"{PACKAGE}.tools._scene")
    recon = helper.scene_to_recon(scene, with_images=True)
    images = getattr(recon, "_input_images", None) or []
    expert = import_module(f"{PACKAGE}.experts.mobile_expert").MobileManipulationExpert()
    expert.set_vlm_module(import_module(f"{PACKAGE}.tools._vlm").VLMShim(model=arguments.get("model")))
    op, target, frame = arguments.get("op", "plan_navigation"), arguments["target"], arguments.get("frame")
    kwargs = {"target": target, **({"frame": frame} if frame is not None else {})}
    if op in ("plan_navigation", "suggest_approach"):
        result = getattr(expert, op)(recon, **kwargs)
    elif op == "plan_movement":
        result = expert.plan_movement(recon, **kwargs, **({"max_reach_m": arguments["max_reach_m"]} if arguments.get("max_reach_m") is not None else {}))
    elif op == "reachability":
        result = expert.reachability(recon, objects=[target], **({"frame": frame} if frame is not None else {}),
                                    **({"max_reach_m": arguments["max_reach_m"]} if arguments.get("max_reach_m") is not None else {}))
    elif op == "plan_active_search":
        if frame is not None:
            raise ValueError("plan_active_search spans frames; a selected frame cannot be silently ignored")
        result = expert.plan_active_search(recon, images, target=target, max_moves=arguments.get("max_moves", 3))
    elif op == "check_object_in_view":
        result = expert.check_object_in_view(recon, images, **kwargs)
    elif op == "search_object_across_frames":
        if frame is not None:
            raise ValueError("search_object_across_frames does not accept a selected frame")
        result = expert.search_object_across_frames(recon, images, target=target)
    elif op == "track_object_trajectory":
        if frame is not None:
            raise ValueError("track_object_trajectory spans frames; a selected frame cannot be silently ignored")
        result = expert.track_object_trajectory(recon, target=target)
    else:
        raise ValueError("Unknown mobile manipulation operation")
    return blocks(result)


def view(arguments: dict, scene: dict, import_module) -> list:
    """Delegate deterministic viewpoint projection without invoking model orientation."""
    op = arguments.get("op", "scene_layout")
    if op not in ("scene_layout", "from_viewpoint"):
        return blocks({"status": "refused", "reason": "provider_unavailable", "visibility": "unverified"})
    recon = import_module(f"{PACKAGE}.tools._scene").scene_to_recon(scene, with_images=False)
    expert = import_module(f"{PACKAGE}.experts.view_expert").ViewExpert()
    kwargs = {"frame": arguments["frame"], "viewpoint": arguments["viewpoint"], "images": None}
    result = expert.scene_layout(recon, **kwargs) if op == "scene_layout" else expert.from_viewpoint(recon, targets=arguments.get("targets") or [], **kwargs)
    return blocks({"result": result, "geometry_assumed_facing": True, "model_orientation_unverified": True})


def reject_identity_collisions(scene: dict, arguments: dict, name: str, import_module) -> None:
    """Refuse proximity components that could merge two sightings from one frame."""
    if name == "count_objects" and arguments.get("frame") is not None:
        return
    recon = import_module(f"{PACKAGE}.tools._scene").scene_to_recon(scene, with_images=False)
    expert = import_module(f"{PACKAGE}.experts.entity_matcher").EntityMatcher()
    entities = expert._collect_entities(recon, scene["frame_indices"], arguments.get("label"))
    threshold = arguments.get("dup_threshold", 0.5) if name == "count_objects" else arguments.get("match_dist_m", 0.6)
    groups = [{i} for i in range(len(entities))]
    for i, a in enumerate(entities):
        for j, b in enumerate(entities[i + 1:], i + 1):
            if name == "match_entities" and a["frame"] == b["frame"]:
                continue
            la, lb = expert._base_label(a["label"]), expert._base_label(b["label"])
            compatible = la == lb or (name == "match_entities" and (la in lb or lb in la))
            same_id = bool(a.get("id")) and a["id"] == b.get("id")
            if same_id or (compatible and math.dist(a["bev"], b["bev"]) <= 2 * threshold):
                left, right = next(g for g in groups if i in g), next(g for g in groups if j in g)
                if left is not right:
                    left.update(right)
                    groups.remove(right)
    if any(len({entities[i]["frame"] for i in group}) != len(group) for group in groups):
        raise ValueError("Ambiguous proximity component would merge distinct same-frame instances")


def postprocess(name: str, result: list, scene, inputs, args: dict) -> list:
    """Retain source IDs and keep missing world-motion evidence explicitly unknown."""
    for block in result:
        if block.get("type") != "text":
            continue
        try:
            value = json.loads(block["text"])
        except json.JSONDecodeError:
            if block["text"].startswith("Error:"):
                raise ValueError(block["text"])
            continue
        if name == "build_scene" and isinstance(value, dict) and value.get("type") == "video-spatio/scene@1":
            for frame, instances in value["instances"].items():
                for index, instance in enumerate(instances):
                    instance["id"] = f"frame:{frame}:instance:{index}"
            inputs.validate_scene(value)
            inputs.generated.add(scene_hash(value))
            scene = value
        if name == "select_keyframes" and args.get("strategy") == "uniform":
            ids = scene["frame_indices"] if scene else list(inputs.ids)
            value["frames"] = [ids[index] for index in value["frames"]]
        if name == "object_world_motion" and (value.get("pos_a") is None or value.get("pos_b") is None or value.get("frames", [None, None])[0] == value.get("frames", [None, None])[-1]):
            value.update(is_moving=None, motion_state="unknown", note="Missing distinct source-frame object motion evidence")
        block["text"] = json.dumps(value, allow_nan=False)
    return result + blocks({"type": "owned/spatial-evidence@1", "provenance": inputs.provenance(scene)})


def configure_specs(specs, inputs, barrier, import_module, read_sources, evidence) -> None:
    """Hold one handler lock through source/frame admission, output and final readback."""
    lock = threading.Lock()

    def wrap(spec):
        original = spec.handle

        @wraps(original)
        def handle(arguments):
            with lock:
                barrier.reset()
                args, scene = {}, None
                try:
                    read_sources()
                    inputs.readback()
                    args, scene = validate(spec.name, arguments, inputs)
                    if spec.name in ("orient_facing", "verify_grounding"):
                        result = blocks({"status": "refused", "reason": "provider_unavailable"})
                    elif spec.name == "mobile_manip":
                        result = mobile(args, scene, import_module)
                    elif spec.name == "motion":
                        result = motion_handle(args, inputs, import_module)
                    elif spec.name == "view_reason":
                        result = view(args, scene, import_module)
                    else:
                        if spec.name == "visualize_bev":
                            viewpoint(args, scene, import_module)
                        if spec.name in ("count_objects", "match_entities"):
                            reject_identity_collisions(scene, args, spec.name, import_module)
                        result = original(args)
                    read_sources()
                    inputs.readback()
                    if barrier.attempts():
                        result = blocks({"status": "refused", "reason": "provider_unavailable", "denied_dispatches": barrier.attempts()})
                    result = postprocess(spec.name, result, scene, inputs, args)
                except Exception as error:
                    result = blocks({"status": "refused", "reason": "provider_unavailable" if barrier.attempts() else "invalid_or_unavailable_evidence",
                                     "error": str(error), "denied_dispatches": barrier.attempts(), "provenance": inputs.provenance(scene)})
                try:
                    evidence(spec.name, result)
                except Exception as error:
                    result = blocks({"status": "refused", "reason": "evidence_receipt_unavailable", "error": str(error)})
                return result
        return handle

    for spec in specs:
        spec.handle = wrap(spec)
