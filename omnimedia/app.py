"""Desktop window (pywebview) and the Python API exposed to the web UI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import webview
from webview.dom import DOMEventHandler

from . import __version__, convert, env, youtube
from .jobs import Cancelled

WEB_DIR = Path(__file__).parent / "web"


class Bridge:
    """Sends events from Python to the UI (window.omni.emit)."""

    def __init__(self, window: webview.Window):
        self._window = window

    def emit(self, kind: str, **data) -> None:
        payload = json.dumps({"type": kind, **data})
        try:
            self._window.evaluate_js(f"window.omni && window.omni.emit({payload})")
        except Exception:
            pass  # window closing

    # Reporter protocol
    def log(self, message: str, level: str = "info") -> None:
        print(f"[{level}] {message}", flush=True)
        self.emit("log", message=message, level=level)

    def progress(self, percent: float | None, status: str, detail: str = "") -> None:
        self.emit("progress", percent=percent, status=status, detail=detail)


class Api:
    """Methods callable from JavaScript as window.pywebview.api.<name>()."""

    def __init__(self):
        self._window: webview.Window | None = None
        self._bridge: Bridge | None = None
        self._job: threading.Thread | None = None
        self._cancel = threading.Event()
        self._settings = env.load_settings()

    def _attach(self, window: webview.Window) -> None:
        self._window = window
        self._bridge = Bridge(window)

    # ---------------------------------------------------------------- info

    def get_status(self) -> dict:
        return {
            "version": __version__,
            "tools": env.tool_status(),
            "outputDir": self._output_dir(),
        }

    def fetch_info(self, url: str) -> dict:
        try:
            return {"ok": True, "info": youtube.fetch_info(url.strip())}
        except Exception as e:
            return {"ok": False, "error": youtube._friendly_error(str(e))}

    # ---------------------------------------------------------------- dialogs

    def choose_output_dir(self) -> str | None:
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER,
                                                 directory=self._output_dir())
        if result:
            self._settings["outputDir"] = result[0]
            env.save_settings(self._settings)
            return result[0]
        return None

    def choose_file(self) -> dict | None:
        exts = ";".join(f"*.{e}" for e in convert.MEDIA_EXTENSIONS)
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=(f"Media files ({exts})", "All files (*.*)"))
        if result:
            return self._file_info(result[0])
        return None

    def reveal(self, path: str) -> None:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", path], check=False)
        elif sys.platform == "win32":
            subprocess.run(["explorer", "/select,", os.path.normpath(path)], check=False)
        else:
            subprocess.run(["xdg-open", os.path.dirname(path)], check=False)

    def open_folder(self) -> None:
        folder = self._output_dir()
        opener = {"darwin": "open", "win32": "explorer"}.get(sys.platform, "xdg-open")
        subprocess.run([opener, folder], check=False)

    # ---------------------------------------------------------------- jobs

    def start_download(self, opts: dict) -> dict:
        try:
            start, end = env.parse_range(opts.get("start"), opts.get("end"))
            url = (opts.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                raise ValueError("Please paste a full video link (starting with https://).")
            height = int(opts["quality"]) if str(opts.get("quality", "")).isdigit() else None
        except (ValueError, KeyError) as e:
            return {"ok": False, "error": str(e)}
        return self._start("Download", lambda cancel: youtube.download(
            url, self._output_dir(), opts.get("format", "mp4"), height, start, end,
            self._bridge, cancel))

    def start_convert(self, opts: dict) -> dict:
        try:
            start, end = env.parse_range(opts.get("start"), opts.get("end"))
            path = opts.get("path") or ""
            if not os.path.isfile(path):
                raise ValueError("Choose a file to convert first.")
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return self._start("Conversion", lambda cancel: convert.convert(
            path, self._output_dir(), opts.get("format", "mp4"), start, end,
            bool(opts.get("fast")), self._bridge, cancel))

    def cancel(self) -> None:
        self._cancel.set()

    # ---------------------------------------------------------------- internals

    def _output_dir(self) -> str:
        d = self._settings.get("outputDir")
        return d if d and os.path.isdir(d) else env.default_output_dir()

    @staticmethod
    def _file_info(path: str) -> dict:
        return {"path": path, "name": os.path.basename(path),
                "duration": env.format_seconds(convert.probe_duration(path))}

    def _start(self, label: str, work) -> dict:
        if self._job and self._job.is_alive():
            return {"ok": False, "error": "Another job is still running."}
        self._cancel = threading.Event()
        cancel = self._cancel
        bridge = self._bridge

        def run():
            bridge.emit("started", label=label)
            try:
                path = work(cancel)
                bridge.progress(100, f"{label} complete", os.path.basename(path))
                bridge.log(f"Saved to {path}", "success")
                bridge.emit("done", path=path, name=os.path.basename(path), label=label)
            except Cancelled:
                bridge.log(f"{label} cancelled.", "warning")
                bridge.emit("cancelled")
            except Exception as e:
                traceback.print_exc()
                bridge.log(str(e), "error")
                bridge.emit("failed", label=label, error=str(e))

        self._job = threading.Thread(target=run, daemon=True)
        self._job.start()
        return {"ok": True}

    def _on_drop(self, event: dict) -> None:
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            self._bridge.emit("fileSelected", file=self._file_info(paths[0]))


def main() -> None:
    env.ensure_path()
    api = Api()
    window = webview.create_window(
        "OmniMedia",
        str(WEB_DIR / "index.html"),
        js_api=api,
        width=880,
        height=820,
        min_size=(640, 640),
        background_color="#0f1117",
    )
    api._attach(window)

    def on_loaded():
        # Native drag & drop: pywebview gives us the real file path on drop.
        try:
            zone = window.dom.get_element("#drop-zone")
            if zone:
                zone.events.drop += DOMEventHandler(api._on_drop, prevent_default=True,
                                                    stop_propagation=True)
        except Exception:
            traceback.print_exc()

    window.events.loaded += on_loaded
    webview.start(debug=os.environ.get("OMNIMEDIA_DEBUG") == "1")


if __name__ == "__main__":
    main()
