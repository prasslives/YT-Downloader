# OmniMedia

Desktop YouTube downloader and media converter for macOS: a native window (pywebview) on top of **yt-dlp** and **ffmpeg**.

- **Download**: paste a link to preview it, then save as MP4 / MOV / MKV / MP3 / M4A / WAV. You can trim, and only the trimmed part is downloaded.
- **Convert**: drop any local video or audio file and convert or trim it. Fast mode copies streams without re-encoding and falls back to re-encoding when it can't.

## Run

Double-click **OmniMedia.app**, or run:

```bash
./run.sh
```

The first launch creates `.venv/` and installs dependencies. Each day's first launch updates yt-dlp, because YouTube changes often and an outdated yt-dlp is the most common reason downloads fail.

Logs from the `.app` launch go to `~/Library/Logs/OmniMedia.log`.

### Requirements

```bash
brew install python ffmpeg deno
```

- **ffmpeg** merges video and audio, extracts audio, and converts files.
- **deno** solves YouTube's JavaScript challenges. Without it, many videos fail with "Signature solving failed". Node or Bun also work.

The top-right badges in the app show whether each tool was found.

## Format notes

| Choice | What you get |
| --- | --- |
| MP4 / MOV | H.264 + AAC, which plays in QuickTime, Photos, and iMovie. YouTube only offers H.264 up to 1080p. |
| MKV | The best stream YouTube has (VP9/AV1, up to 4K/8K). Play it with VLC or IINA. |
| MP3 / M4A / WAV | Audio only. |

## Layout

```
omnimedia/
  app.py       window + API exposed to the UI
  youtube.py   yt-dlp download logic
  convert.py   ffmpeg conversion logic
  env.py       PATH fixes, tool detection, settings, time parsing
  jobs.py      progress/cancel helpers
  web/         UI (plain HTML/CSS/JS, no build step)
run.sh         launcher (venv + daily yt-dlp update)
```

Debug with the WebKit inspector: `OMNIMEDIA_DEBUG=1 ./run.sh`.

## Troubleshooting

- **"Sign in to confirm you're not a bot"**: YouTube is rate-limiting your IP. Wait a bit and try again.
- **Downloads suddenly stop working**: force a yt-dlp update with `rm .venv/.last-update && ./run.sh`.
- **Start over**: `rm -rf .venv && ./run.sh`.
