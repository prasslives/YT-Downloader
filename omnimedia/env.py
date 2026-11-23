"""Environment helpers: PATH fixing, tool detection, settings, time parsing."""

from __future__ import annotations

import json
import os
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# Apps launched from Finder get a minimal PATH that excludes Homebrew, so
# ffmpeg / deno would not be found. Prepend the usual install locations.
_EXTRA_PATHS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    str(Path.home() / ".deno" / "bin"),
    str(Path.home() / ".bun" / "bin"),
]

JS_RUNTIMES = ("deno", "node", "bun")


def ensure_path() -> None:
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    for d in reversed(_EXTRA_PATHS):
        if os.path.isdir(d) and d not in parts:
            parts.insert(0, d)
    os.environ["PATH"] = os.pathsep.join(parts)


def _pkg_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def js_runtime() -> str | None:
    """First JavaScript runtime yt-dlp can use to solve YouTube challenges."""
    return next((rt for rt in JS_RUNTIMES if shutil.which(rt)), None)


def tool_status() -> dict:
    return {
        "ytdlp": _pkg_version("yt-dlp"),
        "ejs": _pkg_version("yt-dlp-ejs"),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "jsRuntime": js_runtime(),
        "platform": sys.platform,
    }


# ---------------------------------------------------------------- settings

def _settings_file() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "OmniMedia" / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(_settings_file().read_text())
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    f = _settings_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(settings, indent=2))


def default_output_dir() -> str:
    return str(Path.home() / "Downloads")


# ---------------------------------------------------------------- time codes

def parse_timecode(value: str | None) -> float | None:
    """Parse '90', '1:30', '01:02:03.5' into seconds. Empty -> None."""
    text = (value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"Invalid time '{text}'. Use H:MM:SS, M:SS or seconds.")
    total = 0.0
    for i, part in enumerate(parts):
        try:
            n = float(part) if part else 0.0
        except ValueError:
            raise ValueError(f"Invalid time '{text}'. Use H:MM:SS, M:SS or seconds.") from None
        if n < 0 or (i > 0 and n >= 60):
            raise ValueError(f"Invalid time '{text}'. Minutes/seconds must be 0-59.")
        total = total * 60 + n
    return total


def parse_range(start: str | None, end: str | None) -> tuple[float | None, float | None]:
    s, e = parse_timecode(start), parse_timecode(end)
    if s is not None and e is not None and e <= s:
        raise ValueError("End time must be after start time.")
    return s, e


def format_seconds(sec: float | None) -> str:
    if sec is None:
        return ""
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
