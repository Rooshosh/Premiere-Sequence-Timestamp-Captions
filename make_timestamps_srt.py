#!/usr/bin/env python3
import sys, re, subprocess, xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import os
import time

# --- Helpers ---------------------------------------------------------

def run_exiftool(path):
    # Try several datetime tags in priority order; return first non-empty.
    tags = [
        "QuickTime:CreateDate",
        "QuickTime:MediaCreateDate",
        "QuickTime:TrackCreateDate",
        "QuickTime:ModifyDate",
        "Keys:CreationDate",            # Apple keys (lower priority)
        "System:FileCreateDate",        # use filesystem create date if available
        "System:FileModifyDate"         # last resort
    ]
    args = ["exiftool", "-api", "largefilesupport=1", "-api", "QuickTimeUTC=1", "-S", "-s", "-s", "-d", "%Y-%m-%d %H:%M:%S%z"]
    for t in tags:
        try:
            out = subprocess.check_output(args + [f"-{t}", path], stderr=subprocess.DEVNULL).decode("utf-8").strip()
        except subprocess.CalledProcessError:
            out = ""
        # Treat invalid/zero dates as empty so we can fall back
        if out and not out.endswith(":"):
            if out.startswith("0000") or out == "0000:00:00 00:00:00" or out == "0000-00-00 00:00:00":
                out = ""
            else:
                return out
    # Try filename-based fallback (e.g., ScreenRecording_10-01-2025 07-20-37_1.mp4, or "2025-09-29 22-51-34.mov")
    fn = path.split("/")[-1]
    # Patterns: YYYY-MM-DD HH-MM-SS or HH.MM.SS
    m = re.search(r"(20\d{2})[-_](\d{2})[-_](\d{2})[ _](\d{2})[:\.-](\d{2})[:\.-](\d{2})", fn)
    if m:
        y, mo, d, H, M, S = m.groups()
        return f"{y}-{mo}-{d} {H}:{M}:00+0000"
    # Patterns: MM-DD-YYYY HH-MM-SS
    m = re.search(r"(\d{2})-(\d{2})-(20\d{2})[ _](\d{2})[-](\d{2})[-](\d{2})", fn)
    if m:
        mo, d, y, H, M, S = m.groups()
        return f"{y}-{mo}-{d} {H}:{M}:00+0000"
    return None


# Helper to convert ExifTool datetime string to local time, drop seconds/tz
def to_local_no_seconds(dt_str):
    """
    Convert a datetime string (possibly with or without timezone) to local time,
    and return 'YYYY-MM-DD HH:MM' (24h) with no timezone suffix.
    If input is timezone-naive, assume UTC (common for QuickTime CreateDate).
    """
    if not dt_str:
        return None
    fmts = [
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]
    dt = None
    for f in fmts:
        try:
            dt = datetime.strptime(dt_str, f)
            break
        except ValueError:
            continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Treat metadata without tz as UTC, then convert to local
        dt = dt.replace(tzinfo=timezone.utc)
    local_tz = datetime.now().astimezone().tzinfo
    local_dt = dt.astimezone(local_tz)
    return local_dt.strftime("%Y-%m-%d %H:%M")

def url_to_path(url):
    # Handle file:// URLs from FCP XML
    if url.startswith("file://"):
        parsed = urlparse(url)
        p = parsed.path
        return unquote(p)
    return url

def frames_to_tc_ms(frames, fps):
    # Convert timeline frames -> (hh, mm, ss, mmm)
    seconds = frames / fps
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds)
    hh = s // 3600
    mm = (s % 3600) // 60
    ss = s % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"

def get_sequence_rate(root):
    # XMEML: sequence/rate: timebase + ntsc flag (true => 29.97 etc.)
    rate = root.find(".//sequence/rate")
    if rate is None:
        return 25.0
    tb = rate.findtext("timebase")
    ntsc = rate.findtext("ntsc")
    try:
        tb = int(tb)
    except:
        tb = 25
    if (ntsc or "").lower() == "true":
        # common NTSC timebases
        if tb == 30: return 29.97
        if tb == 60: return 59.94
        if tb == 24: return 23.976
    return float(tb)

def gather_v1_clips(root):
    # Walk first video track only: sequence/media/video/track[0]/clipitem
    clips = []
    video = root.find(".//sequence/media/video")
    if video is None:
        return clips
    tracks = video.findall("./track")
    if not tracks:
        return clips
    v1 = tracks[0]
    for ci in v1.findall("./clipitem"):
        enabled = ci.findtext("enabled")
        if enabled and enabled.strip() == "FALSE":
            continue
        start = ci.findtext("start")
        end = ci.findtext("end")
        file_el = ci.find(".//file")
        pathurl = file_el.findtext("pathurl") if file_el is not None else None
        name = file_el.findtext("name") if file_el is not None else ci.findtext("name")
        if start is None or end is None or pathurl is None:
            continue
        try:
            start = int(start); end = int(end)
        except:
            continue
        path = url_to_path(pathurl)
        clips.append({
            "start_frames": start,
            "end_frames": end,
            "path": path,
            "name": name or ""
        })
    # Sort by timeline start just in case
    clips.sort(key=lambda x: x["start_frames"])
    return clips

# --- Main ------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 make_timestamps_srt.py <sequence.xml>", file=sys.stderr)
        sys.exit(1)

    xml_path = sys.argv[1]
    base_name = os.path.splitext(os.path.basename(xml_path))[0]
    out_dir = os.path.dirname(xml_path)
    out_path = os.path.join(out_dir, f"timestamps_{base_name}.srt")

    # parse XML
    root = ET.parse(xml_path).getroot()
    fps = get_sequence_rate(root)
    clips = gather_v1_clips(root)

    if not clips:
        print("No clips found on V1. Make sure your sequence has clips on the first video track.", file=sys.stderr)
        sys.exit(2)

    # Build SRT
    lines = []
    idx = 1
    total_clips = len(clips)
    last_print = time.time()
    for i, c in enumerate(clips, start=1):
        start_tc = frames_to_tc_ms(c["start_frames"], fps)
        end_tc   = frames_to_tc_ms(c["end_frames"], fps)

        dt = run_exiftool(c["path"])
        if not dt:
            # If no datetime found, mark clearly so you spot it
            caption = f"[NO-DATE] {c['name']}"
        else:
            # Normalize to local time and drop seconds/timezone
            local_fmt = to_local_no_seconds(dt)
            caption = local_fmt if local_fmt else dt

        lines.append(f"{idx}")
        lines.append(f"{start_tc} --> {end_tc}")
        lines.append(caption)
        lines.append("")  # blank line between cues
        idx += 1

        now = time.time()
        if now - last_print >= 3:
            percent = (i / total_clips) * 100
            print(f"Processed {i} of {total_clips} clips ({percent:.1f}%)", file=sys.stderr)
            last_print = now

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Wrote {out_path} with {idx-1} cues at {fps} fps", file=sys.stderr)

if __name__ == "__main__":
    main()