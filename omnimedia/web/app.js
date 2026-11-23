"use strict";

const $ = (sel) => document.querySelector(sel);
const api = () => window.pywebview?.api;

const state = {
  busy: false,
  file: null,       // { path, name, duration }
  lastPath: null,   // last produced file
  infoUrl: null,    // URL currently previewed
};

// ------------------------------------------------------------------ tabs
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => {
      t.classList.toggle("active", t === tab);
      t.setAttribute("aria-selected", t === tab);
    });
    document.querySelectorAll(".panel").forEach((p) =>
      p.classList.toggle("active", p.id === `panel-${tab.dataset.tab}`));
  });
});

// ------------------------------------------------------------------ time inputs
const TIME_RE = /^(\d+(\.\d+)?|\d+:[0-5]?\d(\.\d+)?|\d+:[0-5]?\d:[0-5]?\d(\.\d+)?)$/;
function validTime(input) {
  const v = input.value.trim();
  const ok = v === "" || TIME_RE.test(v);
  input.classList.toggle("invalid", !ok);
  return ok;
}
document.querySelectorAll("input.time").forEach((el) =>
  el.addEventListener("input", () => validTime(el)));

// ------------------------------------------------------------------ download tab
const urlInput = $("#url");
const fmtSelect = $("#dl-format");
const AUDIO = new Set(["mp3", "m4a", "wav"]);
const HINTS = {
  mp4: "H.264 video + AAC audio — plays in QuickTime, Photos, iMovie and browsers. YouTube serves H.264 up to 1080p; pick MKV for 4K.",
  mov: "H.264 + AAC in a QuickTime container. Up to 1080p.",
  mkv: "Best quality YouTube offers (VP9/AV1, up to 4K/8K). Use VLC or IINA to play.",
  mp3: "Best-quality VBR MP3.",
  m4a: "AAC audio — great quality, small files, native on Apple devices.",
  wav: "Uncompressed PCM audio — large files, for editing.",
};
function onFormatChange() {
  const f = fmtSelect.value;
  $("#quality-field").style.visibility = AUDIO.has(f) ? "hidden" : "visible";
  $("#format-hint").textContent = HINTS[f] || "";
}
fmtSelect.addEventListener("change", onFormatChange);
onFormatChange();

$("#paste-btn").addEventListener("click", async () => {
  try {
    urlInput.value = (await navigator.clipboard.readText()).trim();
    urlInput.dispatchEvent(new Event("input"));
  } catch {
    urlInput.focus();
    showPreviewMsg("Press ⌘V to paste.", false);
  }
});

let infoTimer;
urlInput.addEventListener("input", () => {
  clearTimeout(infoTimer);
  const url = urlInput.value.trim();
  if (!/^https?:\/\/\S+\.\S+/.test(url)) {
    $("#preview").hidden = true;
    $("#preview-msg").hidden = true;
    state.infoUrl = null;
    return;
  }
  infoTimer = setTimeout(() => loadPreview(url), 450);
});
urlInput.addEventListener("keydown", (e) => { if (e.key === "Enter") startDownload(); });

async function loadPreview(url) {
  if (!api() || url === state.infoUrl) return;
  state.infoUrl = url;
  showPreviewMsg("Looking up video…", false);
  $("#preview").hidden = true;
  const res = await api().fetch_info(url);
  if (url !== urlInput.value.trim()) return; // input changed meanwhile
  if (!res.ok) {
    showPreviewMsg(res.error, true);
    return;
  }
  const i = res.info;
  $("#preview-msg").hidden = true;
  $("#preview").hidden = false;
  $("#preview-thumb").src = i.thumbnail || "";
  $("#preview-thumb").hidden = !i.thumbnail;
  $("#preview-title").textContent = i.title;
  $("#preview-sub").textContent = [i.uploader, i.isLive ? "LIVE" : i.durationText].filter(Boolean).join(" · ");
  if (i.durationText) $("#dl-end").placeholder = i.durationText;
}
function showPreviewMsg(text, isError) {
  const m = $("#preview-msg");
  m.hidden = false;
  m.textContent = text;
  m.classList.toggle("error", isError);
}

async function startDownload() {
  if (state.busy || !api()) return;
  const url = urlInput.value.trim();
  if (!url) { urlInput.focus(); return setStatus("error", "Paste a video link first."); }
  if (![$("#dl-start"), $("#dl-end")].every(validTime)) return setStatus("error", "Fix the trim times (e.g. 1:30).");
  const res = await api().start_download({
    url,
    format: fmtSelect.value,
    quality: $("#dl-quality").value,
    start: $("#dl-start").value,
    end: $("#dl-end").value,
  });
  if (!res.ok) setStatus("error", res.error);
}
$("#dl-btn").addEventListener("click", startDownload);

// ------------------------------------------------------------------ convert tab
const drop = $("#drop-zone");
async function browseFile() {
  if (state.busy || !api()) return;
  const f = await api().choose_file();
  if (f) setFile(f);
}
drop.addEventListener("click", browseFile);
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); browseFile(); } });
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
// Never let a dropped file navigate the window away.
["dragover", "drop"].forEach((ev) => window.addEventListener(ev, (e) => e.preventDefault()));

function setFile(f) {
  state.file = f;
  $("#file-chip").hidden = !f;
  drop.hidden = !!f;
  if (f) {
    $("#file-name").textContent = f.name + (f.duration ? `  ·  ${f.duration}` : "");
    $("#file-path").textContent = f.path;
    $("#cv-end").placeholder = f.duration || "end";
  }
}
$("#file-clear").addEventListener("click", () => setFile(null));

async function startConvert() {
  if (state.busy || !api()) return;
  if (!state.file) return setStatus("error", "Choose a file to convert first.");
  if (![$("#cv-start"), $("#cv-end")].every(validTime)) return setStatus("error", "Fix the trim times (e.g. 1:30).");
  const res = await api().start_convert({
    path: state.file.path,
    format: $("#cv-format").value,
    start: $("#cv-start").value,
    end: $("#cv-end").value,
    fast: $("#cv-fast").checked,
  });
  if (!res.ok) setStatus("error", res.error);
}
$("#cv-btn").addEventListener("click", startConvert);

// ------------------------------------------------------------------ output folder
function setOutDir(dir) {
  const el = $("#out-dir");
  el.textContent = dir.replace(/^\/Users\/[^/]+/, "~");
  el.title = `Open ${dir}`;
}
$("#out-dir").addEventListener("click", () => api()?.open_folder());
$("#out-change").addEventListener("click", async () => {
  const d = await api()?.choose_output_dir();
  if (d) setOutDir(d);
});

// ------------------------------------------------------------------ status
function setStatus(kind, text, detail = "", percent = null) {
  const s = $("#status");
  s.dataset.state = kind;
  $("#status-text").textContent = text;
  $("#status-detail").textContent = detail;
  if (percent != null) $("#bar-fill").style.width = `${Math.max(0, Math.min(100, percent))}%`;
  if (kind === "error" || kind === "idle") $("#bar-fill").style.width = kind === "idle" ? "0%" : "100%";
}
function setBusy(busy) {
  state.busy = busy;
  $("#dl-btn").disabled = busy;
  $("#cv-btn").disabled = busy;
  $("#out-change").disabled = busy;
  $("#cancel-btn").hidden = !busy;
  if (busy) $("#reveal-btn").hidden = true;
}
$("#cancel-btn").addEventListener("click", () => {
  api()?.cancel();
  $("#cancel-btn").disabled = true;
  $("#status-text").textContent = "Cancelling…";
});
$("#reveal-btn").addEventListener("click", () => state.lastPath && api()?.reveal(state.lastPath));

// ------------------------------------------------------------------ log
const logBody = $("#log-body");
function log(message, level = "info") {
  const line = document.createElement("div");
  line.className = `log-line ${level}`;
  line.textContent = message;
  logBody.append(line);
  while (logBody.childElementCount > 1500) logBody.firstChild.remove();
  logBody.scrollTop = logBody.scrollHeight;
  if (level === "error") $("#log-panel").open = true;
}
$("#log-clear").addEventListener("click", (e) => { e.preventDefault(); logBody.replaceChildren(); });
$("#log-copy").addEventListener("click", async (e) => {
  e.preventDefault();
  try { await navigator.clipboard.writeText(logBody.innerText); e.target.textContent = "Copied"; }
  catch { e.target.textContent = "Failed"; }
  setTimeout(() => (e.target.textContent = "Copy"), 1200);
});

// ------------------------------------------------------------------ events from Python
window.omni = {
  emit(ev) {
    switch (ev.type) {
      case "log": return log(ev.message, ev.level);
      case "started":
        setBusy(true);
        $("#cancel-btn").disabled = false;
        return setStatus("indeterminate", `${ev.label} starting…`, "", 0);
      case "progress":
        return setStatus(ev.percent == null ? "indeterminate" : "running", ev.status, ev.detail, ev.percent);
      case "done":
        setBusy(false);
        state.lastPath = ev.path;
        $("#reveal-btn").hidden = false;
        return setStatus("done", `${ev.label} complete`, ev.name, 100);
      case "failed":
        setBusy(false);
        return setStatus("error", `${ev.label} failed`, ev.error);
      case "cancelled":
        setBusy(false);
        return setStatus("idle", "Cancelled");
      case "fileSelected":
        return setFile(ev.file);
    }
  },
};

// ------------------------------------------------------------------ startup
function renderHealth(t) {
  const pills = [
    [`yt-dlp ${t.ytdlp || "missing"}`, !!t.ytdlp && !!t.ejs, t.ejs ? "" : "yt-dlp-ejs missing — run ./run.sh to repair"],
    ["ffmpeg", t.ffmpeg, t.ffmpeg ? "" : "Install with: brew install ffmpeg"],
    [t.jsRuntime || "JS runtime", !!t.jsRuntime, t.jsRuntime ? "Solves YouTube JS challenges" : "Install Deno: brew install deno"],
  ];
  $("#health").replaceChildren(...pills.map(([label, ok, tip]) => {
    const el = document.createElement("span");
    el.className = `pill ${ok ? "ok" : "bad"}`;
    el.textContent = label;
    if (tip) el.title = tip;
    return el;
  }));
  if (!t.ffmpeg) log("ffmpeg not found — install it with: brew install ffmpeg", "error");
  if (!t.jsRuntime) log("No JavaScript runtime found — many YouTube videos will fail. Install Deno: brew install deno", "error");
}

window.addEventListener("pywebviewready", async () => {
  const s = await api().get_status();
  renderHealth(s.tools);
  setOutDir(s.outputDir);
  log(`OmniMedia ${s.version} ready · yt-dlp ${s.tools.ytdlp}`, "success");
});
