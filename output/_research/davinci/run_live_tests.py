#!/usr/bin/env python3
"""Disposable, headless DaVinci Resolve 21 API probe for ClipFactory."""

import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VIDEO = ROOT / "output/VideoConGuionYouTube/video_horizontal.mp4"
PLAN = ROOT / "output/VideoConGuionYouTube/clip_plan.json"
SRT = ROOT / "output/VideoConGuionYouTube/clips/c1.srt"
RESULTS = HERE / "live_results.json"
EVENTS = HERE / "live_events.jsonl"
PROJECT_NAME = f"ClipFactory_RESEARCH_{datetime.now():%Y%m%d_%H%M%S}_{os.getpid()}"


def event(action, **data):
    row = {"at": datetime.now().isoformat(timespec="seconds"), "action": action, **data}
    print(json.dumps(row, ensure_ascii=False), flush=True)
    with EVENTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def wait_for_resolve(timeout=180):
    import DaVinciResolveScript as dvr

    started = time.monotonic()
    while time.monotonic() - started < timeout:
        resolve = dvr.scriptapp("Resolve")
        if resolve:
            event("connected", wait_seconds=round(time.monotonic() - started, 2), version=resolve.GetVersionString())
            return resolve
        time.sleep(2)
    raise TimeoutError(f"Resolve API did not answer within {timeout}s")


def ffprobe(path):
    command = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,duration",
        "-of", "json", str(path),
    ]
    return json.loads(subprocess.check_output(command, text=True))


def render(project, timeline, name, width, height, mark_out=None, subtitles=False):
    assert project.SetCurrentTimeline(timeline)
    formats = project.GetRenderFormats()
    mp4_format = next((key for key, ext in formats.items() if ext == "mp4"), None)
    if not mp4_format:
        raise RuntimeError(f"No MP4 format: {formats}")
    codecs = project.GetRenderCodecs(mp4_format)
    h264 = next((value for key, value in codecs.items() if "264" in key), None)
    if not h264 or not project.SetCurrentRenderFormatAndCodec(mp4_format, h264):
        raise RuntimeError(f"No usable H.264 codec: {codecs}")
    settings = {
        "SelectAllFrames": mark_out is None,
        "TargetDir": str(HERE),
        "CustomName": name,
        "ExportVideo": True,
        "ExportAudio": True,
        "FormatWidth": width,
        "FormatHeight": height,
        "FrameRate": 24,
        "VideoQuality": "Least",
        "ReplaceExistingFilesInPlace": True,
    }
    if mark_out is not None:
        settings.update({"MarkIn": timeline.GetStartFrame(), "MarkOut": timeline.GetStartFrame() + mark_out})
    if subtitles:
        settings.update({"ExportSubtitle": True, "SubtitleFormat": "BurnIn"})
    set_ok = project.SetRenderSettings(settings)
    job = project.AddRenderJob()
    event("render_job_added", name=name, timeline=timeline.GetName(), settings=settings, set_ok=set_ok, job=job)
    if not job or not project.StartRendering([job], False):
        raise RuntimeError(f"Could not start render {name}")
    while project.IsRenderingInProgress():
        time.sleep(1)
    status = project.GetRenderJobStatus(job)
    matches = sorted(HERE.glob(name + "*.mp4"))
    probe = ffprobe(matches[-1]) if matches else None
    event("render_complete", name=name, status=status, files=[str(p) for p in matches], ffprobe=probe)
    return {"status": status, "files": [str(p) for p in matches], "ffprobe": probe}


def main():
    EVENTS.unlink(missing_ok=True)
    results = {"project_name": PROJECT_NAME, "commands": {"script": "python3 run_live_tests.py"}}
    resolve = wait_for_resolve()
    pm = resolve.GetProjectManager()
    project = None
    try:
        event("database", value=pm.GetCurrentDatabase())
        project = pm.CreateProject(PROJECT_NAME)
        if not project:
            raise RuntimeError("CreateProject returned None")
        event("project_created", name=PROJECT_NAME)
        results["project_created"] = True

        for key, value in {
            "timelineFrameRate": "24",
            "timelinePlaybackFrameRate": "24",
            "timelineResolutionWidth": "3840",
            "timelineResolutionHeight": "2160",
        }.items():
            event("project_setting", key=key, value=value, result=project.SetSetting(key, value))

        pool = project.GetMediaPool()
        imported = pool.ImportMedia([str(VIDEO)])
        if not imported:
            raise RuntimeError("Video ImportMedia returned no items")
        media = imported[0]
        props = media.GetClipProperty()
        event("video_imported", count=len(imported), properties=props)
        fps = float(str(props.get("FPS", "24")).split()[0])

        timelines = {}
        cut_results = []
        for clip in json.loads(PLAN.read_text(encoding="utf-8")):
            start_frame = round(clip["start"] * fps)
            end_frame = round(clip["end"] * fps) - 1
            timeline = pool.CreateTimelineFromClips(
                "research_" + clip["id"],
                [{"mediaPoolItem": media, "startFrame": start_frame, "endFrame": end_frame, "recordFrame": 0}],
            )
            if not timeline:
                raise RuntimeError(f"CreateTimelineFromClips failed for {clip['id']}")
            timelines[clip["id"]] = timeline
            item = timeline.GetItemListInTrack("video", 1)[0]
            actual_frames = item.GetDuration(True)
            row = {
                "id": clip["id"], "requested_seconds": clip["duration"],
                "source_start_frame": item.GetSourceStartFrame(), "source_end_frame": item.GetSourceEndFrame(),
                "actual_frames": actual_frames, "actual_seconds": actual_frames / fps,
                "difference_seconds": actual_frames / fps - clip["duration"],
                "timeline_start": timeline.GetStartFrame(), "timeline_end": timeline.GetEndFrame(),
            }
            cut_results.append(row)
            event("timeline_created", **row)
        results["cuts"] = cut_results

        quick = project.GetQuickExportRenderPresets()
        results["quick_export_presets"] = quick
        event("quick_export_presets", presets=quick)
        results["render_capabilities"] = {
            "presets": project.GetRenderPresetList(),
            "formats": project.GetRenderFormats(),
            "codecs_mp4": project.GetRenderCodecs("mp4"),
        }
        event("render_capabilities", **results["render_capabilities"])

        # Free-edition control: SmartReframe is expected to return False.
        c4 = timelines["c4"]
        assert project.SetCurrentTimeline(c4)
        c4_item = c4.GetItemListInTrack("video", 1)[0]
        smart = c4_item.SmartReframe()
        results["smart_reframe"] = smart
        event("smart_reframe", result=smart)

        vertical_settings = {
            "timelineResolutionWidth": "1080", "timelineResolutionHeight": "1920",
            "timelineOutputResolutionWidth": "1080", "timelineOutputResolutionHeight": "1920",
        }
        results["vertical_timeline_settings"] = {k: c4.SetSetting(k, v) for k, v in vertical_settings.items()}
        comp = c4_item.AddFusionComp()
        fusion_result = {"comp_created": bool(comp)}
        if comp:
            tools = comp.GetToolList(False)
            media_in = next((tool for tool in tools.values() if tool.GetAttrs().get("TOOLS_RegID") == "MediaIn"), None)
            media_out = next((tool for tool in tools.values() if tool.GetAttrs().get("TOOLS_RegID") == "MediaOut"), None)
            transform = comp.AddTool("Transform", -32768, -32768)
            connected_in = transform.ConnectInput("Input", media_in) if media_in else False
            connected_out = media_out.ConnectInput("Input", transform) if media_out else False
            transform.Size = 3.16
            transform.Center = {1: 0.5, 2: 0.5}
            fusion_result.update({
                "tools_before": {str(k): v.GetAttrs().get("TOOLS_RegID") for k, v in tools.items()},
                "transform_created": bool(transform), "connected_in": connected_in,
                "connected_out": connected_out, "size": transform.Size,
            })
        results["fusion_crop"] = fusion_result
        event("fusion_crop", **fusion_result)

        results["renders"] = {
            "horizontal_16x9": render(project, timelines["c3"], "c3_horizontal_640x360_5s", 640, 360, 119),
            "fusion_vertical_9x16": render(project, c4, "c4_fusion_360x640", 360, 640),
        }

        c1 = timelines["c1"]
        assert project.SetCurrentTimeline(c1)
        srt_items = pool.ImportMedia([str(SRT)])
        sub_result = {"import_count": len(srt_items or []), "track_before": c1.GetTrackCount("subtitle")}
        if srt_items:
            sub_result["properties"] = srt_items[0].GetClipProperty()
            sub_result["add_track"] = c1.AddTrack("subtitle")
            sub_result["append_result"] = bool(pool.AppendToTimeline([{
                "mediaPoolItem": srt_items[0], "recordFrame": c1.GetStartFrame()
            }]))
        sub_result["track_after"] = c1.GetTrackCount("subtitle")
        sub_result["subtitle_items"] = [x.GetName() for x in (c1.GetItemListInTrack("subtitle", 1) or [])]
        results["external_srt"] = sub_result
        event("external_srt", **sub_result)
        if sub_result["subtitle_items"]:
            results["renders"]["srt_burnin_sample"] = render(project, c1, "c1_srt_burnin_10s", 640, 360, 239, True)

        results["saved"] = pm.SaveProject()
    except Exception as exc:
        results["error"] = {"type": type(exc).__name__, "message": str(exc)}
        event("error", **results["error"])
        raise
    finally:
        if project:
            project.DeleteAllRenderJobs()
            closed = pm.CloseProject(project)
            deleted = pm.DeleteProject(PROJECT_NAME)
            results["cleanup"] = {"closed": closed, "deleted": deleted, "still_present": PROJECT_NAME in pm.GetProjectListInCurrentFolder()}
            event("cleanup", **results["cleanup"])
        RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
