#!/usr/bin/env python3

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path

LOG_PATH = Path("/tmp/resolve_aac_current_clip.log")

try:
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    SCRIPT_DIR = Path.cwd()

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from resolve_aac_import import convert, get_resolve


DEFAULT_OUTPUT_SUBDIR = "aac_remux"
DEFAULT_TRACK_NAME = "AAC PCM"


def log(message):
    with LOG_PATH.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(message + "\n")


def clip_property(media_pool_item, key):
    value = media_pool_item.GetClipProperty(key)
    if value:
        return value
    properties = media_pool_item.GetClipProperty()
    return properties.get(key, "") if isinstance(properties, dict) else ""


def iter_media_pool_items(folder):
    for clip in folder.GetClipList() or []:
        yield clip
    for child in folder.GetSubFolderList() or []:
        yield from iter_media_pool_items(child)


def media_pool_item_path(media_pool_item):
    return clip_property(media_pool_item, "File Path")


def find_media_pool_item_by_path(media_pool, path):
    wanted = str(path.resolve())
    for item in iter_media_pool_items(media_pool.GetRootFolder()):
        item_path = media_pool_item_path(item)
        if item_path and str(Path(item_path).expanduser().resolve()) == wanted:
            return item
    return None


def import_or_find(media_pool, path):
    existing = find_media_pool_item_by_path(media_pool, path)
    if existing:
        return existing

    imported = media_pool.ImportMedia([str(path)])
    if imported:
        return imported[0]

    return find_media_pool_item_by_path(media_pool, path)


def ensure_audio_track(timeline, track_index, track_name):
    if track_index:
        count = timeline.GetTrackCount("audio")
        if track_index < 1 or track_index > count:
            raise RuntimeError(f"Audio track {track_index} does not exist")
        return track_index

    count = timeline.GetTrackCount("audio")
    for index in range(1, count + 1):
        if timeline.GetTrackName("audio", index) == track_name:
            return index

    if not timeline.AddTrack("audio", "stereo"):
        raise RuntimeError("Could not create audio track")

    index = timeline.GetTrackCount("audio")
    timeline.SetTrackName("audio", index, track_name)
    return index


def timeline_item_frame(value):
    return int(round(float(value)))


def timecode_to_frames(timecode, fps):
    clean = timecode.replace(";", ":")
    hours, minutes, seconds, frames = [int(part) for part in clean.split(":")]
    return int(round(((hours * 3600) + (minutes * 60) + seconds) * fps + frames))


def timeline_playhead_frame(project, timeline):
    fps = float(project.GetSetting("timelineFrameRate"))
    current = timecode_to_frames(timeline.GetCurrentTimecode(), fps)

    try:
        start_timecode = timecode_to_frames(timeline.GetStartTimecode(), fps)
        return timeline_item_frame(timeline.GetStartFrame()) + current - start_timecode
    except Exception:
        return current


def timeline_item_at_playhead(timeline, track_type, playhead_frame):
    items = timeline_items_at_playhead(timeline, track_type, playhead_frame)
    return items[0] if items else None


def timeline_items_at_playhead(timeline, track_type, playhead_frame):
    matches = []
    for track_index in range(1, timeline.GetTrackCount(track_type) + 1):
        items = timeline.GetItemsInTrack(track_type, track_index) or {}
        item_list = items.values() if hasattr(items, "values") else items
        for item in item_list:
            start = timeline_item_frame(item.GetStart(False))
            end = timeline_item_frame(item.GetEnd(False))
            if start <= playhead_frame < end:
                matches.append(item)
    return matches


def timeline_items(timeline, track_type):
    matches = []
    for track_index in range(1, timeline.GetTrackCount(track_type) + 1):
        items = timeline.GetItemsInTrack(track_type, track_index) or {}
        item_list = items.values() if hasattr(items, "values") else items
        matches.extend(item_list)
    return matches


def item_track_index(timeline_item):
    track_info = timeline_item.GetTrackTypeAndIndex()
    if not track_info or len(track_info) < 2:
        return None
    return track_info[0], int(track_info[1])


def current_timeline_item(project, timeline):
    current = timeline.GetCurrentVideoItem()
    if current:
        return current

    playhead_frame = timeline_playhead_frame(project, timeline)
    current = timeline_item_at_playhead(timeline, "audio", playhead_frame)
    if current:
        return current

    raise RuntimeError("No current timeline item. Put the playhead over a video or audio clip.")


def same_source_path(left, right_path):
    try:
        return timeline_item_path(left) == right_path
    except Exception:
        return False


def linked_video_for_audio(audio_item, input_path):
    for linked_item in audio_item.GetLinkedItems() or []:
        track = item_track_index(linked_item)
        if track and track[0] == "video" and same_source_path(linked_item, input_path):
            return linked_item
    return None


def current_source_and_replacement(project, timeline):
    playhead_frame = timeline_playhead_frame(project, timeline)
    audio_items = timeline_items_at_playhead(timeline, "audio", playhead_frame)
    current_video = timeline.GetCurrentVideoItem()

    if current_video:
        input_path = timeline_item_path(current_video)
        for linked_item in current_video.GetLinkedItems() or []:
            track = item_track_index(linked_item)
            if track and track[0] == "audio" and same_source_path(linked_item, input_path):
                return current_video, linked_item, input_path

        for audio_item in audio_items:
            if same_source_path(audio_item, input_path):
                return current_video, audio_item, input_path

        return current_video, None, input_path

    if audio_items:
        source_audio = audio_items[0]
        return source_audio, source_audio, timeline_item_path(source_audio)

    raise RuntimeError("No current timeline item. Put the playhead over a video or audio clip.")


def is_generated_remux_path(input_path):
    return any(part == DEFAULT_OUTPUT_SUBDIR for part in input_path.parts)


def output_dir_for_input(input_path, override):
    if override:
        return override.expanduser().resolve()
    return (input_path.parent / DEFAULT_OUTPUT_SUBDIR).resolve()


def cache_output_dir_for_input(input_path, cache_dir):
    if not cache_dir:
        return None

    digest = hashlib.sha1(str(input_path.parent).encode("utf-8")).hexdigest()[:12]
    safe_parent = input_path.parent.name or "root"
    return cache_dir.expanduser().resolve() / f"{safe_parent}_{digest}"


REMUX_MAP_PATH = Path.home() / ".config" / "resolve-aac-tools" / "remux_map.json"


def record_remux(output_path, original_path):
    """Remember that a remux came from an original, so the restore action can put
    the original back. Best-effort: never break a remux over bookkeeping."""
    try:
        REMUX_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if REMUX_MAP_PATH.exists():
            try:
                data = json.loads(REMUX_MAP_PATH.read_text())
            except Exception:
                data = {}
        data[str(Path(output_path).expanduser().resolve())] = str(Path(original_path).expanduser().resolve())
        REMUX_MAP_PATH.write_text(json.dumps(data, indent=2) + "\n")
    except Exception:
        pass


def load_remux_map():
    try:
        return json.loads(REMUX_MAP_PATH.read_text())
    except Exception:
        return {}


def clip_info_for_timeline_item(source_item, audio_item, audio_track):
    source_start = timeline_item_frame(source_item.GetSourceStartFrame())
    source_end = timeline_item_frame(source_item.GetSourceEndFrame()) + 1
    record_frame = timeline_item_frame(source_item.GetStart(False))

    if source_end <= source_start:
        duration = timeline_item_frame(source_item.GetDuration(False))
        source_end = source_start + max(1, duration)

    return {
        "mediaPoolItem": audio_item,
        "startFrame": source_start,
        "endFrame": source_end,
        "mediaType": 2,
        "trackIndex": audio_track,
        "recordFrame": record_frame,
    }


def add_audio_clip(timeline, media_pool, clip_info):
    before_timecode = timeline.GetCurrentTimecode()
    appended = media_pool.AppendToTimeline([clip_info])
    if before_timecode:
        timeline.SetCurrentTimecode(before_timecode)
    if not appended:
        raise RuntimeError("Could not append converted audio to timeline")
    return appended[0]


def timeline_item_path(timeline_item):
    media_pool_item = timeline_item.GetMediaPoolItem()
    if not media_pool_item:
        raise RuntimeError("Current timeline item has no Media Pool item")

    file_path = media_pool_item_path(media_pool_item)
    if not file_path:
        raise RuntimeError("Could not determine source file path for current timeline item")

    return Path(file_path).expanduser().resolve()


def replace_timeline_audio(
    timeline,
    media_pool,
    source_item,
    original_audio_item,
    input_path,
    output_dir_override=None,
    cache_dir=None,
    overwrite=True,
    track_index=None,
    track_name=DEFAULT_TRACK_NAME,
    keep_original=False,
    quiet=False,
):
    output_dir = cache_output_dir_for_input(input_path, cache_dir) or output_dir_for_input(input_path, output_dir_override)
    log(f"Output dir: {output_dir}")

    result = convert(
        input_path=input_path,
        output_dir=output_dir,
        root=input_path.parent,
        flat=True,
        overwrite=overwrite,
        dry_run=False,
        quiet=quiet,
    )
    if result.status == "skipped":
        log(f"Skipped non-AAC clip: {input_path}")
        return None
    if result.status == "error" or not result.output_path:
        raise RuntimeError(result.message or f"Could not convert {input_path}")

    audio_item = import_or_find(media_pool, result.output_path)
    if not audio_item:
        raise RuntimeError(f"Could not import converted media: {result.output_path}")

    if track_index:
        audio_track = ensure_audio_track(timeline, track_index, track_name)
    elif original_audio_item:
        track = item_track_index(original_audio_item)
        if not track or track[0] != "audio":
            raise RuntimeError("Could not determine original audio track")
        audio_track = track[1]
    else:
        audio_track = ensure_audio_track(timeline, None, track_name)

    placement_item = original_audio_item if original_audio_item else source_item
    clip_info = clip_info_for_timeline_item(placement_item, audio_item, audio_track)
    if original_audio_item and not keep_original:
        log(f"Deleting original audio on A{audio_track}")
        if original_audio_item != source_item:
            timeline.SetClipsLinked([source_item, original_audio_item], False)
        if not timeline.DeleteClips([original_audio_item], False):
            raise RuntimeError("Could not remove original AAC audio clip")

    appended_item = add_audio_clip(timeline, media_pool, clip_info)
    if original_audio_item and original_audio_item != source_item:
        timeline.SetClipsLinked([source_item, appended_item], True)

    log(f"Added PCM audio on A{audio_track}: {result.output_path}")
    return result.output_path


def replace_audio_item(timeline, media_pool, audio_item, **kwargs):
    input_path = timeline_item_path(audio_item)
    if is_generated_remux_path(input_path):
        log(f"Skipped generated remux clip: {input_path}")
        return None

    source_item = linked_video_for_audio(audio_item, input_path) or audio_item
    return replace_timeline_audio(
        timeline=timeline,
        media_pool=media_pool,
        source_item=source_item,
        original_audio_item=audio_item,
        input_path=input_path,
        **kwargs,
    )


def main():
    log("=== Resolve AAC Current Clip started ===")
    parser = argparse.ArgumentParser(
        description="Convert the current Resolve timeline clip's AAC audio to PCM and place it on the timeline."
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="Override output directory. Default: <source folder>/aac_remux",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Store remuxes in an external cache instead of next to source media",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite converted media")
    parser.add_argument("--track-index", type=int, help="Use an existing audio track index")
    parser.add_argument("--track-name", default=DEFAULT_TRACK_NAME, help="Audio track name to create/reuse")
    parser.add_argument("--keep-original", action="store_true", help="Keep the original AAC timeline audio clip")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    resolve = get_resolve()
    if not resolve:
        raise RuntimeError("Could not connect to Resolve. Is Resolve running and scripting enabled?")

    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject() if project_manager else None
    if not project:
        raise RuntimeError("Resolve has no current project")

    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("Resolve has no current timeline")

    media_pool = project.GetMediaPool()
    source_item, original_audio_item, input_path = current_source_and_replacement(project, timeline)
    log(f"Current clip: {input_path}")
    output_path = replace_timeline_audio(
        timeline=timeline,
        media_pool=media_pool,
        source_item=source_item,
        original_audio_item=original_audio_item,
        input_path=input_path,
        overwrite=args.overwrite,
        output_dir_override=args.output_dir,
        cache_dir=args.cache_dir,
        track_index=args.track_index,
        track_name=args.track_name,
        keep_original=args.keep_original,
        quiet=args.quiet,
    )
    if not output_path:
        print(f"Skipped: {input_path} has no AAC audio")
        return 0

    print(f"Added PCM audio: {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log("FAILED: " + str(exc))
        log(traceback.format_exc())
        print(f"Resolve AAC timeline import failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
