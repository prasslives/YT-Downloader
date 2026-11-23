"""YouTube (and other yt-dlp supported sites) downloading."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading

import yt_dlp
from yt_dlp.utils import DownloadCancelled, download_range_func

from .env import format_seconds, js_runtime
from .jobs import Cancelled, Reporter, Throttle, human_bytes, unique_path

VIDEO_FORMATS = {"mp4", "mov", "mkv"}
AUDIO_FORMATS = {"mp3", "m4a", "wav"}


def _base_opts(reporter: Reporter | None = None) -> dict:
    opts: dict = {
        "noplaylist": True,  # a watch?v=...&list=... URL downloads just that video
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
    }
    runtime = js_runtime()
    if runtime:
        # Deno is yt-dlp's default; node/bun must be enabled explicitly.
        opts["js_runtimes"] = {runtime: {}}
    if reporter:
        opts["logger"] = _Logger(reporter)
    return opts


class _Logger:
    def __init__(self, reporter: Reporter):
        self.r = reporter

    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug] "):
            self.r.log(msg, "info")

    def info(self, msg: str) -> None:
        self.r.log(msg, "info")

    def warning(self, msg: str) -> None:
        self.r.log(msg, "warning")

    def error(self, msg: str) -> None:
        self.r.log(msg, "error")


def fetch_info(url: str) -> dict:
    """Lightweight metadata lookup for the preview card."""
    with yt_dlp.YoutubeDL({**_base_opts(), "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False, process=False)
    if info.get("_type") in ("playlist", "multi_video"):
        raise ValueError("That link is a playlist. Paste a link to a single video.")
    return {
        "title": info.get("title") or "Untitled",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": info.get("duration"),
        "durationText": format_seconds(info.get("duration")),
        "thumbnail": info.get("thumbnail") or _best_thumb(info.get("thumbnails")),
        "isLive": bool(info.get("is_live")),
    }


def _best_thumb(thumbs) -> str | None:
    if not thumbs:
        return None
    return sorted(thumbs, key=lambda t: t.get("preference") or 0)[-1].get("url")


def _format_opts(fmt: str, max_height: int | None) -> dict:
    if fmt in AUDIO_FORMATS:
        return {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": fmt,
                "preferredquality": "0",  # best VBR for mp3; ignored for wav
            }],
        }
    sort = []
    if fmt in ("mp4", "mov"):
        # Prefer H.264 + AAC so the file plays in QuickTime/Photos/iMovie.
        # (YouTube serves H.264 up to 1080p; pick MKV for 4K VP9/AV1.)
        sort += ["vcodec:h264", "acodec:aac"]
    if max_height:
        sort.insert(0, f"res:{max_height}")
    return {
        "format": "bestvideo*+bestaudio/best",
        "format_sort": sort,
        "merge_output_format": fmt,
        # If the best match isn't in the right container, remux it.
        "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": fmt}],
    }


def download(
    url: str,
    out_dir: str,
    fmt: str,
    max_height: int | None,
    start: float | None,
    end: float | None,
    reporter: Reporter,
    cancel: threading.Event,
) -> str:
    """Download `url` into `out_dir`. Returns the final file path."""
    if fmt not in VIDEO_FORMATS | AUDIO_FORMATS:
        raise ValueError(f"Unsupported format: {fmt}")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg was not found. Install it with:  brew install ffmpeg")

    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="omnimedia-")
    throttle = Throttle()
    state = {"part": 0}

    def on_progress(d: dict) -> None:
        if cancel.is_set():
            raise DownloadCancelled("Cancelled by user")
        status = d.get("status")
        is_audio_stream = (d.get("info_dict") or {}).get("vcodec") == "none"
        what = "audio" if is_audio_stream and fmt in VIDEO_FORMATS else (
            "audio" if fmt in AUDIO_FORMATS else "video")
        if status == "downloading":
            if not throttle.ready():
                return
            done = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            pct = done / total * 100 if total else None
            bits = [f"{human_bytes(done)}" + (f" of {human_bytes(total)}" if total else "")]
            if d.get("speed"):
                bits.append(f"{human_bytes(d['speed'])}/s")
            if d.get("eta") is not None:
                bits.append(f"ETA {format_seconds(d['eta'])}")
            reporter.progress(pct, f"Downloading {what}…", " · ".join(bits))
        elif status == "finished":
            state["part"] += 1
            reporter.progress(100, f"Downloaded {what}", "")

    def on_postprocess(d: dict) -> None:
        if d.get("status") == "started":
            name = d.get("postprocessor", "")
            label = {
                "Merger": "Merging video and audio…",
                "ExtractAudio": f"Converting to {fmt.upper()}…",
                "VideoRemuxer": f"Packaging as {fmt.upper()}…",
                "FixupM3u8": "Fixing container…",
            }.get(name, f"Post-processing ({name})…")
            reporter.progress(None, label, "")

    clip = start is not None or end is not None
    opts = {
        **_base_opts(reporter),
        **_format_opts(fmt, max_height),
        "paths": {"home": tmp, "temp": tmp},
        "outtmpl": "%(title).150B.%(ext)s",
        "windowsfilenames": True,  # strip characters illegal on any OS
        "progress_hooks": [on_progress],
        "postprocessor_hooks": [on_postprocess],
    }
    if clip:
        # Only download the requested section; cut precisely on keyframes.
        opts["download_ranges"] = download_range_func(None, [(start or 0, end if end is not None else float("inf"))])
        opts["force_keyframes_at_cuts"] = True

    try:
        reporter.log(f"Starting download: {url}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if info.get("_type") == "playlist":
            raise ValueError("That link is a playlist. Paste a link to a single video.")

        produced = [d.get("filepath") for d in info.get("requested_downloads") or []]
        produced = [p for p in produced if p and os.path.exists(p)]
        if not produced:  # fall back to whatever landed in the temp dir
            produced = [os.path.join(tmp, f) for f in os.listdir(tmp)
                        if f.endswith("." + fmt)]
        if not produced:
            raise RuntimeError("Download finished but the output file could not be found.")

        src = produced[0]
        stem, ext = os.path.splitext(os.path.basename(src))
        if clip:
            stem += f" (clip {format_seconds(start or 0)}-{format_seconds(end) or 'end'})".replace(":", "_")
        dest = unique_path(os.path.join(out_dir, stem + ext))
        shutil.move(src, dest)
        return dest
    except DownloadCancelled:
        raise Cancelled() from None
    except yt_dlp.utils.DownloadError as e:
        raise RuntimeError(_friendly_error(str(e))) from None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _friendly_error(msg: str) -> str:
    msg = msg.removeprefix("ERROR: ").strip()
    low = msg.lower()
    if "sign in to confirm" in low or "not a bot" in low:
        return ("YouTube is asking to confirm you're not a bot. Wait a few minutes and try again, "
                "or update yt-dlp (restart the app; it updates itself daily).\n\n" + msg)
    if "private video" in low:
        return "This video is private."
    if "video unavailable" in low:
        return "This video is unavailable (removed, region-locked, or the link is wrong)."
    if "age" in low and "confirm" in low:
        return "This video is age-restricted and requires sign-in, which OmniMedia doesn't support."
    if "unsupported url" in low:
        return "That link isn't a supported video URL."
    return msg
