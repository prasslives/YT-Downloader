import os
import re
import sys
import json
import shutil
import tempfile
import threading
import subprocess
from pathlib import Path
import webview

def _ensure_system_path():
    """Add common macOS tool locations (Homebrew, /usr/local) to PATH.

    GUI-launched apps (.app bundles, Finder double-click) inherit a minimal
    PATH that excludes Homebrew, so ffmpeg/yt-dlp aren't found. This makes
    them discoverable regardless of how the app was launched.
    """
    extra_dirs = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    existing = os.environ.get("PATH", "").split(os.pathsep)
    for d in extra_dirs:
        if d not in existing and os.path.isdir(d):
            existing.append(d)
    os.environ["PATH"] = os.pathsep.join(existing)


class API:
    def __init__(self):
        self._window = None

    def set_window(self, window):
        self._window = window

    def select_file(self):
        """Open a native file dialog to choose a media file for conversion."""
        if not self._window:
            return None

        # Allow common video and audio files
        file_types = ('Media Files (*.mp4;*.mkv;*.mov;*.avi;*.mp3;*.wav;*.flac;*.m4a;*.webm)', 'All files (*.*)')
        
        # create_file_dialog returns a tuple of selected paths, or None
        result = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=file_types)
        
        if result and len(result) > 0:
            file_path = result[0]
            file_name = os.path.basename(file_path)
            return {"path": file_path, "name": file_name}
        return None

    def download_video(self, url, start_time, end_time, output_format):
        """Spawns a thread to download and process a YouTube video using yt-dlp."""
        threading.Thread(
            target=self._download_thread,
            args=(url, start_time, end_time, output_format),
            daemon=True
        ).start()
        return True

    def convert_file(self, input_path, start_time, end_time, output_format, fast_mode):
        """Spawns a thread to convert a local file using ffmpeg."""
        threading.Thread(
            target=self._convert_thread,
            args=(input_path, start_time, end_time, output_format, fast_mode),
            daemon=True
        ).start()
        return True

    def _log(self, message, level="info"):
        """Safely print message to Python console and evaluate Javascript logging in UI."""
        print(f"[{level.upper()}] {message}")
        if self._window:
            # Escape strings safely using json.dumps
            escaped_msg = json.dumps(message)
            self._window.evaluate_js(f"window.app.log({escaped_msg}, '{level}')")

    def _update_progress(self, status_text, percentage):
        """Update progress bar in UI."""
        if self._window:
            escaped_status = json.dumps(status_text)
            self._window.evaluate_js(f"window.app.updateProgress({escaped_status}, {int(percentage)})")

    def _on_success(self, title, filename):
        """Notify UI of successful operation."""
        if self._window:
            escaped_title = json.dumps(title)
            escaped_filename = json.dumps(filename)
            self._window.evaluate_js(f"window.app.onSuccess({escaped_title}, {escaped_filename})")

    def _on_error(self, title, error_message):
        """Notify UI of operation failure."""
        if self._window:
            escaped_title = json.dumps(title)
            escaped_err = json.dumps(error_message)
            self._window.evaluate_js(f"window.app.onError({escaped_title}, {escaped_err})")

    def _get_downloads_folder(self):
        """Finds user's home Downloads folder."""
        return str(Path.home() / "Downloads")

    def _clean_youtube_url(self, url):
        """Remove playlist/radio/list parameters from YouTube URL to get just the single video."""
        # Remove list and start_radio parameters
        cleaned = re.sub(r'[?&]list=[^&]+', '', url)
        cleaned = re.sub(r'[?&]start_radio=[^&]+', '', cleaned)
        cleaned = re.sub(r'[?&]si=[^&]+', '', cleaned)
        cleaned = re.sub(r'[?&]index=[^&]+', '', cleaned)
        # If we removed the first parameter, the URL might start with & instead of ?
        cleaned = re.sub(r'^([^?]*)&', r'\1?', cleaned)
        return cleaned

    def _get_video_title(self, url):
        """Queries yt-dlp to get the title of the video and sanitizes it."""
        try:
            clean_url = self._clean_youtube_url(url)
            self._log(f"Fetching video information from YouTube...", "info")
            import yt_dlp
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,  # Force single video only
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(clean_url, download=False)
                title = info.get('title', 'youtube_download')
            
            # Remove characters that are unsafe for filenames
            title = re.sub(r'[\\/*?:"<>|]', "", title)
            title = title.strip()
            if not title:
                title = "youtube_download"
            return title
        except Exception as e:
            self._log(f"Failed to fetch video title, using default. Details: {e}", "warning")
            return "youtube_download"

    def _download_thread(self, url, start_time, end_time, output_format):
        # Clean the URL to remove playlist/radio parameters first
        clean_url = self._clean_youtube_url(url)
        title = self._get_video_title(url)
        downloads_dir = self._get_downloads_folder()
        is_audio = output_format in ["mp3", "wav"]

        # If trim is requested, download to a temporary folder, then use ffmpeg to trim
        has_trim = bool(start_time or end_time)
        
        temp_dir = None
        try:
            import yt_dlp

            if has_trim or is_audio:
                temp_dir = tempfile.mkdtemp()
                output_template = os.path.join(temp_dir, "temp_download.%(ext)s")
                self._log(f"Downloading to temporary location...", "info")
            else:
                # Direct download to downloads directory
                output_template = os.path.join(downloads_dir, f"{title}.%(ext)s")
                self._log(f"Downloading directly to Downloads folder...", "info")

            # Progress hook
            def progress_hook(d):
                if d['status'] == 'downloading':
                    downloaded = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    if total > 0:
                        pct = (downloaded / total) * 100
                        self._update_progress(f"Downloading YouTube video... {pct:.1f}%", pct)
                    else:
                        self._update_progress("Downloading YouTube video...", 0)
                elif d['status'] == 'finished':
                    self._update_progress("Download complete!", 95)

            # Custom logger class
            class YTDLPSubprocessLogger:
                def __init__(self, api_instance):
                    self.api = api_instance
                def debug(self, msg):
                    if not msg.startswith('[debug]'):
                        self.api._log(msg, "info")
                def info(self, msg):
                    self.api._log(msg, "info")
                def warning(self, msg):
                    self.api._log(msg, "warning")
                def error(self, msg):
                    self.api._log(msg, "error")

            # Setup options
            ydl_opts = {
                'outtmpl': output_template,
                'progress_hooks': [progress_hook],
                'logger': YTDLPSubprocessLogger(self),
                'noprogress': True,
                'noplaylist': True,  # Force single video download only
                # ffmpeg is located via PATH (see _ensure_system_path),
                # which includes Homebrew dirs even for GUI-launched apps.
            }

            if is_audio:
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': output_format,
                        'preferredquality': '192',
                    }]
                })
            else:
                ydl_opts.update({
                    'format': 'bestvideo+bestaudio/best',
                    'merge_output_format': output_format,
                })

            self._log(f"Starting native yt-dlp downloader", "info")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([clean_url])

            # Determine what file was actually downloaded (handle post-processed files)
            downloaded_file = None
            if temp_dir and os.path.exists(temp_dir):
                files = os.listdir(temp_dir)
                if not files:
                    raise FileNotFoundError("Could not find the downloaded temporary file.")
                # Prefer the post-processed file — sort by modification time (newest first)
                files.sort(key=lambda f: os.path.getmtime(os.path.join(temp_dir, f)), reverse=True)
                downloaded_file = os.path.join(temp_dir, files[0])
                self._log(f"Downloaded file: {files[0]}", "info")
            else:
                # No temp dir — check if file was saved directly to downloads
                final_output = os.path.join(downloads_dir, f"{title}.{output_format}")
                if os.path.exists(final_output):
                    self._update_progress("Complete!", 100)
                    self._on_success("Download Complete", f"{title}.{output_format}")
                    return
                # Fallback: try to find any file with the title
                for f in os.listdir(downloads_dir):
                    if f.startswith(title):
                        downloaded_file = os.path.join(downloads_dir, f)
                        break

            if downloaded_file is None:
                raise FileNotFoundError("Could not locate the downloaded file.")

            # Apply trimming if needed, or just finalize if no trimming but was in temp
            if has_trim:
                self._update_progress("Finalizing trim with FFmpeg...", 95)
                final_output = os.path.join(downloads_dir, f"{title}.{output_format}")
                self._trim_media(downloaded_file, start_time, end_time, final_output, output_format)
                self._on_success("Download & Trim Complete", f"{title}.{output_format}")
            elif temp_dir:
                # No trim needed but file was in temp — just move to downloads
                final_output = os.path.join(downloads_dir, f"{title}.{output_format}")
                shutil.move(downloaded_file, final_output)
                self._update_progress("Complete!", 100)
                self._on_success("Download Complete", f"{title}.{output_format}")
            else:
                self._update_progress("Complete!", 100)
                final_filename = f"{title}.{output_format}"
                self._on_success("Download Complete", final_filename)

        except Exception as e:
            self._log(f"YouTube Download Failed: {e}", "error")
            self._on_error("Download Failed", str(e))
        finally:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _convert_thread(self, input_path, start_time, end_time, output_format, fast_mode):
        try:
            if not os.path.exists(input_path):
                raise FileNotFoundError(f"Input file not found at: {input_path}")

            downloads_dir = self._get_downloads_folder()
            input_filename = os.path.basename(input_path)
            input_name_without_ext = os.path.splitext(input_filename)[0]
            output_filename = f"{input_name_without_ext}_converted.{output_format}"
            output_path = os.path.join(downloads_dir, output_filename)

            self._log(f"Starting conversion for local file: {input_filename}", "info")
            self._trim_media(input_path, start_time, end_time, output_path, output_format, fast_mode)
            
            self._update_progress("Complete!", 100)
            self._on_success("Conversion Complete", output_filename)

        except Exception as e:
            self._log(f"Conversion Failed: {e}", "error")
            self._on_error("Conversion Failed", str(e))

    def _trim_media(self, input_path, start_time, end_time, output_path, output_format, fast_mode=False):
        """Helper to run ffmpeg with start and end times and display progress."""
        # Check if ffmpeg exists
        if not self._check_ffmpeg():
            raise RuntimeError("ffmpeg is not installed or not in PATH. Please install it with: brew install ffmpeg")
        
        cmd = ["ffmpeg", "-y"]
        
        # Put -ss BEFORE -i for much faster seeking (input-accurate, not output-accurate)
        if start_time:
            cmd.extend(["-ss", start_time])
        
        # Input file
        cmd.extend(["-i", input_path])
        
        if end_time:
            cmd.extend(["-to", end_time])

        # Formatting configurations
        is_audio = output_format in ["mp3", "wav"]
        
        if fast_mode:
            # Fast stream copy (no re-encoding)
            self._log("Fast Mode (stream copy) requested.", "info")
            cmd.extend(["-c", "copy"])
        else:
            # Re-encode for precision
            if is_audio:
                if output_format == "mp3":
                    cmd.extend(["-vn", "-c:a", "libmp3lame", "-q:a", "2"])
                elif output_format == "wav":
                    cmd.extend(["-vn", "-c:a", "pcm_s16le"])
            else:
                if output_format == "mp4":
                    cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"])
                elif output_format == "mkv":
                    cmd.extend(["-c:v", "libx264", "-c:a", "aac"])
                elif output_format == "mov":
                    cmd.extend(["-c:v", "libx264", "-c:a", "aac"])
                elif output_format == "avi":
                    cmd.extend(["-c:v", "mpeg4", "-c:a", "mp3"])

        cmd.append(output_path)

        # Print command out in console
        cmd_str_for_log = " ".join([f'"{arg}"' if " " in arg else arg for arg in cmd])
        self._log(f"Running Command: {cmd_str_for_log}", "command")

        # Run process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # FFmpeg outputs log info on stderr
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        total_duration = 0.0
        duration_regex = re.compile(r'Duration:\s*([0-9:.]+)')
        time_regex = re.compile(r'time=\s*([0-9:.]+)')

        # Parse output for progress updates
        for line in iter(process.stdout.readline, ''):
            line_str = line.strip()
            if line_str:
                self._log(line_str, "info")
                
                # Check for input file duration
                if total_duration == 0.0:
                    dur_match = duration_regex.search(line_str)
                    if dur_match:
                        total_duration = self._parse_ffmpeg_time(dur_match.group(1))
                        self._log(f"Determined source file duration: {total_duration} seconds", "info")

                # Parse current encoding progress time
                time_match = time_regex.search(line_str)
                if time_match and total_duration > 0.0:
                    current_time = self._parse_ffmpeg_time(time_match.group(1))
                    pct = min(100.0, (current_time / total_duration) * 100.0)
                    self._update_progress(f"Processing... {pct:.1f}%", pct)

        process.stdout.close()
        return_code = process.wait()

        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, cmd)

    def _parse_ffmpeg_time(self, time_str):
        """Converts HH:MM:SS.ms string format to seconds float."""
        try:
            parts = time_str.split(':')
            if len(parts) == 3:
                h, m, s = parts
                return float(h) * 3600 + float(m) * 60 + float(s)
            elif len(parts) == 2:
                m, s = parts
                return float(m) * 60 + float(s)
            else:
                return float(parts[0])
        except Exception:
            return 0.0

    def _check_ffmpeg(self):
        """Check if ffmpeg is available in PATH. Returns True if found."""
        found = shutil.which('ffmpeg')
        if found:
            return True
        # Fallback: check common macOS Homebrew locations directly
        for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
            if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                return True
        return False

def main():
    # Make Homebrew tools (ffmpeg, yt-dlp, etc.) visible even when launched
    # from a GUI .app bundle which inherits a minimal PATH.
    _ensure_system_path()

    # Setup working directory to the directory where app.py is located
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        current_dir = sys._MEIPASS
    else:
        current_dir = os.path.dirname(os.path.realpath(__file__))
    os.chdir(current_dir)

    # Initialize exposed python API
    api = API()

    # Launch PyWebView window
    window = webview.create_window(
        'OmniMedia Console',
        'index.html',
        js_api=api,
        width=800,
        height=720,
        min_size=(700, 600),
        resizable=True
    )
    api.set_window(window)
    # Debug mode opens the WebKit inspector panel (shows page source/DOM below the UI).
    # Only enable when explicitly requested via OMNIMEDIA_DEBUG=1.
    webview.start(debug=os.environ.get('OMNIMEDIA_DEBUG') == '1')

if __name__ == '__main__':
    main()
