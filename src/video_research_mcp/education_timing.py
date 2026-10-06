"""Integer narration sample boundaries and their explicitly quantized video presentation."""

RATE = 48000
FPS = 12
SAMPLES_PER_FRAME = RATE // FPS
MAX_SAMPLES = 30 * RATE
MAX_FRAMES = 30 * FPS
RGB_BYTES = 640 * 360 * 3
MAX_RGB_BYTES = 268435456
MAX_RECEIPT_BYTES = 524288
IDS = ["triangle", "curve", "circuit"]


def timeline_from_counts(counts):
    """Measure half-open scene/caption intervals; never adjust PCM to the frame grid."""
    if len(counts) != 3 or any(type(n) is not int or not 1 <= n <= MAX_SAMPLES for n in counts):
        raise ValueError("Lesson requires three positive measured segment sample counts")
    total = sum(counts)
    if total > MAX_SAMPLES:
        raise ValueError("Measured narration exceeds30 seconds in total")
    scenes, start = [], 0
    for scene_id, count in zip(IDS, counts, strict=True):
        end = start + count
        first = (start + SAMPLES_PER_FRAME - 1) // SAMPLES_PER_FRAME
        stop = (end + SAMPLES_PER_FRAME - 1) // SAMPLES_PER_FRAME
        if first == stop:
            raise ValueError("Measured scene has no12fps presentation frame; cannot silently skip it")
        scenes.append({"scene_id": scene_id, "start_sample": start, "end_sample": end,
                       "sample_count": count, "first_frame": first, "stop_frame": stop,
                       "visual_start_sample": first * SAMPLES_PER_FRAME,
                       "visual_delay_samples": first * SAMPLES_PER_FRAME - start})
        start = end
    frames = (total + SAMPLES_PER_FRAME - 1) // SAMPLES_PER_FRAME
    return {"sample_rate": RATE, "total_samples": total, "duration_seconds": total / RATE,
            "fps": FPS, "frame_count": frames, "video_duration_seconds": frames / FPS,
            "video_tail_samples": frames * SAMPLES_PER_FRAME - total,
            "frame_scene_policy": "scene_at_frame_start_sample; transitions_round_up",
            "scenes": scenes, "caption_speech_alignment_verified": False}


def frame_schedule(timeline):
    """Enumerate every frame once, including a fractional final audio interval."""
    for index, scene in enumerate(timeline["scenes"]):
        for number in range(scene["first_frame"], scene["stop_frame"]):
            yield number, index


def legacy_timeline():
    """Retain the accepted six-second/two-second schema1 clocks."""
    return timeline_from_counts([96000, 96000, 96000])
