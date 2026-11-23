"""Local file conversion / trimming with ffmpeg."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections import deque

from .env import format_seconds
from .jobs import Cancelled, Reporter, Throttle, unique_path

AUDIO_FORMATS = {"mp3", "m4a", "wav", "flac"}

ENCODERS: dict[str, list[str]] = {
    "mp4": ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"],
    "mov": ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k"],
    "mkv": ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "192k"],
    "avi": ["-c:v", "mpeg4", "-q:v", "3", "-c:a", "libmp3lame", "-q:a", "2"],
    "mp3": ["-vn", "-c:a", "libmp3lame", "-q:a", "2"],
    "m4a": ["-vn", "-c:a", "aac", "-b:a", "256k"],
    "wav": ["-vn", "-c:a", "pcm_s16le"],
    "flac": ["-vn", "-c:a", "flac"],
}

MEDIA_EXTENSIONS = ["mp4", "mkv", "mov", "avi", "webm", "m4v", "flv", "wmv",
                    "mp3", "m4a", "wav", "flac", "aac", "ogg", "opus"]


def probe_duration(path: str) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return None


def _build_cmd(src: str, dest: str, fmt: str, start: float | None, end: float | None,
               copy: bool) -> list[str]:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "warning",
           "-progress", "pipe:1", "-nostats"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]  # input seeking: fast
    cmd += ["-i", src]
    if end is not None:
        # After input seeking timestamps restart at 0, so use a duration.
        cmd += ["-t", f"{end - (start or 0):.3f}"]
    if copy:
        cmd += ["-map", "0:v?", "-map", "0:a?", "-c", "copy"]
        if fmt == "mp4":
            cmd += ["-movflags", "+faststart"]
    else:
        cmd += ENCODERS[fmt]
    cmd.append(dest)
    return cmd


def _run(cmd: list[str], total: float | None, reporter: Reporter, cancel: threading.Event,
         label: str) -> None:
    reporter.log("$ " + " ".join(f'"{a}"' if " " in a else a for a in cmd), "command")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    errors: deque[str] = deque(maxlen=40)

    def drain_stderr():
        for line in proc.stderr:
            if line.strip():
                errors.append(line.rstrip())
                reporter.log(line.rstrip(), "warning")

    t = threading.Thread(target=drain_stderr, daemon=True)
    t.start()
    throttle = Throttle()
    for line in proc.stdout:
        if cancel.is_set():
            proc.terminate()
            break
        key, _, val = line.strip().partition("=")
        if key == "out_time_us" and total and val.isdigit() and throttle.ready():
            done = int(val) / 1_000_000
            reporter.progress(min(100.0, done / total * 100), label,
                              f"{format_seconds(done)} of {format_seconds(total)}")
    proc.wait()
    t.join(timeout=2)
    if cancel.is_set():
        raise Cancelled()
    if proc.returncode != 0:
        tail = "\n".join(list(errors)[-6:]) or f"ffmpeg exited with code {proc.returncode}"
        raise RuntimeError(tail)


def convert(src: str, out_dir: str, fmt: str, start: float | None, end: float | None,
            fast: bool, reporter: Reporter, cancel: threading.Event) -> str:
    if fmt not in ENCODERS:
        raise ValueError(f"Unsupported format: {fmt}")
    if not os.path.isfile(src):
        raise FileNotFoundError(f"File not found: {src}")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg was not found. Install it with:  brew install ffmpeg")

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    if start is not None or end is not None:
        stem += f" (clip {format_seconds(start or 0)}-{format_seconds(end) or 'end'})".replace(":", "_")
    dest = unique_path(os.path.join(out_dir, f"{stem}.{fmt}"))

    duration = probe_duration(src)
    if duration is not None and start is not None and start >= duration:
        raise ValueError(f"Start time is past the end of the file ({format_seconds(duration)}).")
    clip_end = end if end is not None else duration
    if clip_end is not None and duration is not None:
        clip_end = min(clip_end, duration)
    total = clip_end - (start or 0) if clip_end is not None else None
    if total is not None and total <= 0:
        total = None

    # Stream copy only makes sense for video targets; audio encodes are quick anyway.
    copy = fast and fmt not in AUDIO_FORMATS
    reporter.log(f"Converting {os.path.basename(src)} → {os.path.basename(dest)}"
                 + (" (fast stream copy)" if copy else ""))
    try:
        try:
            _run(_build_cmd(src, dest, fmt, start, end, copy), total, reporter, cancel,
                 "Copying streams…" if copy else "Converting…")
        except RuntimeError:
            if not copy:
                raise
            # Codecs don't fit the target container: fall back to re-encoding.
            reporter.log("Stream copy isn't possible for this file/format; re-encoding instead.", "warning")
            _run(_build_cmd(src, dest, fmt, start, end, False), total, reporter, cancel, "Converting…")
    except BaseException:
        if os.path.exists(dest):
            os.remove(dest)
        raise
    return dest
