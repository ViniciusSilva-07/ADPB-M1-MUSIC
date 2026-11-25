import os, re, sys, json, uuid, time, glob, shutil, signal, socket, threading, subprocess, tempfile
from pathlib import Path
from flask import Flask, request, jsonify, send_file, Response
import yt_dlp, imageio_ffmpeg
from yt_dlp.utils import DownloadCancelled

if sys.stdout is None: sys.stdout = sys.stderr = open(os.devnull, "w")

APP_NAME = "ADPB M1 MUSIC"
TITLE = APP_NAME
FF = imageio_ffmpeg.get_ffmpeg_exe()
ROOT = Path(__file__).parent
NOWIN = 0x08000000 if os.name == "nt" else 0
PY = sys.executable.replace("pythonw", "python")
JOBS = {}
LOSSY = ("mp3", "m4a", "opus", "ogg")
EXT = {"mp3": "mp3", "m4a": "m4a", "opus": "opus", "ogg": "ogg", "flac": "flac", "wav": "wav"}
CODEC = {"mp3": ["-c:a", "libmp3lame"], "m4a": ["-c:a", "aac"], "opus": ["-c:a", "libopus"],
         "ogg": ["-c:a", "libvorbis"], "flac": ["-c:a", "flac"], "wav": ["-c:a", "pcm_s16le"]}
PPC = {"mp3": "mp3", "m4a": "m4a", "opus": "opus", "ogg": "vorbis", "flac": "flac", "wav": "wav"}
TPL = {"title_id": "%(title).150B [%(id)s]", "title": "%(title).180B",
       "channel_title": "%(channel,uploader)s - %(title).150B", "date_title": "%(upload_date>%Y-%m-%d)s - %(title).150B"}

# ───────────────────────── Configurações ─────────────────────────
CF = ROOT / "config.json"
DEF = dict(
    theme="auto", accent="blue", scale=100, reduce_motion=False,
    dest=str(Path.home() / "Downloads" / APP_NAME), organize=False, name_tpl="title_id",
    hist_on=True, hist_max=300,
    mode="video", height=0, container="mp4", afmt="best", kbps=320,
    frag=8, limit=0.0, retries=10,
    meta=True, thumb=False, subs=False, sublangs="pt,en", subauto=False,
    sound=True, open_when_done=False, results=18,
    cookies="", proxy="",
    auto_update=True, update_ytdlp=True,
)
CHOICES = {
    "theme": ("auto", "light", "dark"),
    "accent": ("blue", "purple", "pink", "red", "orange", "green", "graphite"),
    "mode": ("video", "audio"), "container": ("mp4", "mkv", "webm"),
    "afmt": ("best",) + tuple(EXT), "name_tpl": tuple(TPL),
    "cookies": ("", "chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium"),
}
RANGE = {"scale": (80, 140), "frag": (1, 16), "retries": (0, 50), "results": (6, 40),
         "hist_max": (0, 1000), "limit": (0, 1000), "kbps": (32, 320), "height": (0, 4320)}
CFG = dict(DEF)
_lock = threading.Lock()

def cfg_save():
    try: CF.write_text(json.dumps(CFG, ensure_ascii=False, indent=2), "utf-8")
    except Exception: pass

def cfg_load():
    try: raw = json.loads(CF.read_text("utf-8"))
    except Exception: raw = {}
    cfg_set(raw, save=False, strict=False)

def cfg_set(d, save=True, strict=True):
    with _lock:
        for k, v in d.items():
            if k not in DEF: continue
            try:
                t = type(DEF[k])
                if t is bool: v = v if isinstance(v, bool) else str(v).lower() == "true"
                elif t is int: v = int(float(v))
                elif t is float: v = float(v)
                else: v = str(v).strip()
                if k in CHOICES and v not in CHOICES[k]: continue
                if k in RANGE: v = min(max(v, RANGE[k][0]), RANGE[k][1])
                if k == "dest":
                    if not v: continue
                    Path(v).mkdir(parents=True, exist_ok=True)
                CFG[k] = v
            except Exception as e:
                if strict: raise Exception(f"Valor inválido para '{k}': {clean(e)}")
        if save: cfg_save()

app = Flask(__name__)
clean = lambda s: re.sub(r"\x1b\[[0-9;]*m", "", str(s))[:300]
cfg_load()
try: Path(CFG["dest"]).mkdir(parents=True, exist_ok=True)
except Exception: CFG["dest"] = DEF["dest"]; Path(CFG["dest"]).mkdir(parents=True, exist_ok=True)

@app.errorhandler(Exception)
def _err(e): return jsonify(error=clean(e)), 400

def card(e):
    i = e["id"]
    return dict(id=i, url=f"https://www.youtube.com/watch?v={i}", title=e.get("title"),
                channel=e.get("channel") or e.get("uploader"), dur=e.get("duration"),
                thumb=f"https://i.ytimg.com/vi/{i}/hqdefault.jpg")

def base_opts(**extra):
    o = {"quiet": True}
    if CFG["proxy"]: o["proxy"] = CFG["proxy"]
    if CFG["cookies"]: o["cookiesfrombrowser"] = (CFG["cookies"],)
    return {**o, **extra}

def out_dir(kind, folder=""):
    p = Path(CFG["dest"])
    if CFG["organize"]: p = p / kind
    if folder: p = p / folder
    p.mkdir(parents=True, exist_ok=True)
    return p

# ───────────────────────── Histórico ─────────────────────────
HF = ROOT / "historico.json"

def hist():
    try: return json.loads(HF.read_text("utf-8"))
    except Exception: return []

def hist_add(j):
    if not CFG["hist_on"] or CFG["hist_max"] <= 0: return
    try:
        h = hist(); h.insert(0, dict(title=j["title"], kind=j["kind"], file=j["file"], ts=time.strftime("%d/%m/%Y %H:%M")))
        HF.write_text(json.dumps(h[:CFG["hist_max"]], ensure_ascii=False), "utf-8")
    except Exception: pass

# ───────────────────────── Janela / ícone ─────────────────────────
def update_ytdlp():
    try: subprocess.run([PY, "-m", "pip", "install", "-U", "-q", "yt-dlp[default]"], capture_output=True, timeout=300, creationflags=NOWIN)
    except Exception: pass

def set_icon():
    import ctypes
    u = ctypes.windll.user32; ico = str(ROOT / "icone.ico")
    for _ in range(60):
        hwnd = u.FindWindowW(None, TITLE)
        if hwnd: break
        time.sleep(.25)
    else: return
    for kind, size in ((1, 256), (0, 16)):
        u.SendMessageW(hwnd, 0x80, kind, u.LoadImageW(None, ico, 1, size, size, 0x10))

# ───────────────────────── Tarefas (downloads / conversões) ─────────────────────────
class Stop(DownloadCancelled): pass
FINAL = ("done", "err", "canc")

def _reveal(p):
    try:
        if os.name == "nt": subprocess.Popen(["explorer", "/select," + os.path.normpath(p)])
        else: subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(Path(p).parent)])
    except Exception: pass

def _susp(pid, on):
    if os.name == "nt":
        import ctypes
        k, n = ctypes.windll.kernel32, ctypes.windll.ntdll
        k.OpenProcess.restype = ctypes.c_void_p
        n.NtSuspendProcess.argtypes = n.NtResumeProcess.argtypes = [ctypes.c_void_p]
        h = k.OpenProcess(0x1F0FFF, False, pid)
        (n.NtSuspendProcess if on else n.NtResumeProcess)(h)
        k.CloseHandle.argtypes = [ctypes.c_void_p]; k.CloseHandle(h)
    else: os.kill(pid, signal.SIGSTOP if on else signal.SIGCONT)

def _cleanup(j):
    for fn in list(j["_files"]):
        try:
            for q in Path(fn).parent.glob(glob.escape(Path(fn).name) + "*"): q.unlink(missing_ok=True)
        except Exception: pass
    j["_files"].clear()

def start(title, fn, kind="Vídeo"):
    j = dict(id=uuid.uuid4().hex[:8], title=title, st="run", p=0, speed="", eta="", file=None, err=None, kind=kind,
             sub="", note="", post=False, _req=None, _ev=threading.Event(), _files=set(), _proc=None)
    JOBS[j["id"]] = j
    def w():
        try:
            fn(j); j["st"] = "done"; j["p"] = 100; j["post"] = False
            if j["file"]:
                hist_add(j)
                if CFG["open_when_done"]: _reveal(j["file"])
        except Stop: j["st"] = "canc"; j["speed"] = j["eta"] = ""; _cleanup(j)
        except Exception as e: j["st"] = "err"; j["err"] = clean(e)
    threading.Thread(target=w, daemon=True).start()
    return j["id"]

def hook(j, n, base=0, span=100):
    seen = {}
    def h(x):
        if j["_req"] in ("pause", "cancel"): raise Stop()
        fn = x.get("filename")
        if fn: j["_files"].add(fn)
        if x.get("tmpfilename"): j["_files"].add(x["tmpfilename"])
        idx = seen.setdefault(fn, len(seen))
        if x["status"] == "finished":
            if idx + 1 >= n: j["post"] = True
            return
        if x["status"] != "downloading": return
        t = x.get("total_bytes") or x.get("total_bytes_estimate")
        if t: j["p"] = min(99, base + (idx + x["downloaded_bytes"] / t) / n * span)
        j["speed"] = clean(x.get("_speed_str", "")).strip(); j["eta"] = clean(x.get("_eta_str", "")).strip()
    return h

@app.post("/api/jobs/<jid>/<act>")
def job_act(jid, act):
    j = JOBS.get(jid)
    if not j: raise Exception("Tarefa não encontrada.")
    if act == "remove":
        if j["st"] in FINAL: JOBS.pop(jid, None)
        return jsonify(ok=1)
    if j["st"] in FINAL: return jsonify(ok=1)
    if j["post"] and act in ("pause", "cancel"): raise Exception("Finalizando o arquivo… aguarde alguns segundos.")
    p = j["_proc"]
    if act == "pause" and j["st"] == "run":
        if p: _susp(p.pid, True); j["st"] = "paused"
        else: j["_ev"].clear(); j["_req"] = "pause"; j["st"] = "pausing"
    elif act == "resume" and j["st"] == "paused":
        if p: _susp(p.pid, False); j["st"] = "run"
        else: j["_req"] = "resume"; j["_ev"].set()
    elif act == "cancel":
        j["_req"] = "cancel"
        if p:
            if j["st"] == "paused": _susp(p.pid, False)
            p.kill()
        else: j["_ev"].set()
    return jsonify(ok=1)

@app.get("/api/jobs")
def jobs():
    return jsonify([{k: v for k, v in j.items() if k[0] != "_"} for j in list(JOBS.values())[::-1]])

# ───────────────────────── Páginas ─────────────────────────
@app.get("/icone.png")
def icon(): return send_file(ROOT / "icone.png")

@app.get("/")
def home():
    esc = lambda o: json.dumps(o, ensure_ascii=False).replace("<", "\\u003c")
    html = (ROOT / "index.html").read_text("utf-8").replace("/*CFG*/{}", esc(CFG)).replace("/*DEF*/{}", esc(DEF))
    return Response(html, mimetype="text/html")

# ───────────────────────── Busca / info ─────────────────────────
@app.get("/api/search")
def search():
    with yt_dlp.YoutubeDL(base_opts(extract_flat=True)) as y:
        r = y.extract_info(f"ytsearch{CFG['results']}:{request.args['q']}", download=False)
    return jsonify([card(e) for e in r["entries"] if e and e.get("id")])

@app.get("/api/info")
def info():
    with yt_dlp.YoutubeDL(base_opts(noplaylist=True)) as y:
        i = y.extract_info(request.args["url"], download=False)
    F = i["formats"]
    hs = sorted({f["height"] for f in F if f.get("vcodec") not in (None, "none") and f.get("height")}, reverse=True)
    ab = sorted({round(f["abr"]) for f in F if f.get("vcodec") == "none" and f.get("abr")}, reverse=True)
    return jsonify({**card(i), "heights": hs, "abr": ab, "thumb": i.get("thumbnail")})

@app.get("/api/playlist")
def playlist():
    with yt_dlp.YoutubeDL(base_opts(extract_flat=True, playlistend=200)) as y:
        r = y.extract_info(request.args["url"], download=False)
    return jsonify(title=r.get("title") or "Playlist", entries=[card(e) for e in r["entries"] if e and e.get("id")])

# ───────────────────────── Download ─────────────────────────
@app.post("/api/download")
def download():
    d = request.json; urls = d.get("urls") or [d["url"]]; audio = d["mode"] == "audio"; h = int(d.get("height") or 0)
    o = base_opts(noplaylist=True, concurrent_fragment_downloads=CFG["frag"], http_chunk_size=10 * 1024 * 1024,
                  retries=CFG["retries"], fragment_retries=CFG["retries"], ffmpeg_location=FF)
    if CFG["limit"] > 0: o["ratelimit"] = int(CFG["limit"] * 1048576)
    pps = []
    if audio:
        o["format"] = "bestaudio/best"; f = d.get("afmt", "best")
        if f != "best":
            pp = {"key": "FFmpegExtractAudio", "preferredcodec": PPC[f]}
            if f in LOSSY: pp["preferredquality"] = str(d.get("kbps", 320))
            pps.append(pp)
        can_thumb = f in LOSSY or f == "flac"
    else:
        c = d.get("container", "mp4")
        o["format"] = "bv*+ba/b"; o["merge_output_format"] = c
        o["format_sort"] = [f"res:{h}" if h else "res"] + {"mp4": ["vcodec:h264", "acodec:aac"],
                                                          "webm": ["vcodec:vp9", "acodec:opus"]}.get(c, [])
        can_thumb = c in ("mp4", "mkv")
    if CFG["subs"]:
        langs = [s.strip() for s in CFG["sublangs"].split(",") if s.strip()] or ["pt", "en"]
        o.update(writesubtitles=True, writeautomaticsub=CFG["subauto"], subtitleslangs=langs)
        pps.append({"key": "FFmpegSubtitlesConvertor", "format": "srt"})
    if CFG["meta"]: pps.append({"key": "FFmpegMetadata"})
    if CFG["thumb"] and can_thumb:
        o["writethumbnail"] = True
        pps += [{"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"}, {"key": "EmbedThumbnail"}]
    o["postprocessors"] = pps
    kind = (f"Playlist · " if len(urls) > 1 else "") + ("Áudio" if audio else "Vídeo")
    sub = re.sub(r'[\\/:*?"<>|]', "_", d.get("folder") or "").strip()
    out = out_dir("Áudios" if audio else "Vídeos", sub)
    tpl = TPL[CFG["name_tpl"]]
    def run(j):
        N = len(urls); fails = 0
        for k, u in enumerate(urls):
            j["sub"] = f"{k+1}/{N}" if N > 1 else ""; j["_files"].clear(); j["post"] = False
            oo = {**o, "outtmpl": str(out / ((f"{k+1:02d} - " if N > 1 else "") + tpl + ".%(ext)s")),
                  "progress_hooks": [hook(j, 1 if audio else 2, k / N * 100, 100 / N)]}
            while True:
                try:
                    with yt_dlp.YoutubeDL(oo) as y: i = y.extract_info(u, download=True)
                    j["file"] = i["requested_downloads"][0]["filepath"]; break
                except Stop:
                    if j["_req"] == "cancel": raise
                    j["st"] = "paused"; j["speed"] = j["eta"] = ""
                    j["_ev"].wait()
                    if j["_req"] == "cancel": raise Stop()
                    j["_req"] = None; j["st"] = "run"
                except Exception:
                    if N == 1: raise
                    fails += 1; break
            j["_files"].clear()
        if fails: j["note"] = f"{fails} falharam"
        if not j["file"]: raise Exception("Nenhum item foi baixado.")
    return jsonify(id=start(d.get("title") or urls[0], run, kind))

@app.post("/api/convert")
def convert():
    f = request.files["file"]; fmt = request.form.get("afmt", "mp3"); kb = request.form.get("kbps", "320")
    src = Path(tempfile.mkdtemp()) / Path(f.filename).name; f.save(src)
    out = out_dir("Conversões") / f"{src.stem}.{EXT[fmt]}"
    def run(j):
        j["_files"].add(str(out))
        cmd = [FF, "-y", "-i", str(src), "-vn", *CODEC[fmt], *(["-b:a", kb + "k"] if fmt in LOSSY else []),
               "-map_metadata", "0", "-progress", "pipe:1", "-nostats", str(out)]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", creationflags=NOWIN)
        j["_proc"] = p
        dur, tail = 0, []
        for l in p.stdout:
            tail = (tail + [l.strip()])[-4:]
            m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", l)
            if m: dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
            m = re.search(r"out_time_(?:us|ms)=(\d+)", l)
            if m and dur: j["p"] = min(99, int(m[1]) / 1e6 / dur * 100)
            m = re.search(r"speed=\s*([\d.]+x)", l)
            if m: j["speed"] = m[1]
        rc = p.wait(); j["_proc"] = None; shutil.rmtree(src.parent, True)
        if j["_req"] == "cancel": raise Stop()
        if rc: raise Exception("Falha na conversão: " + " ".join(tail))
        j["file"] = str(out); j["_files"].clear()
    return jsonify(id=start(f.filename, run, "Conversão"))

# ───────────────────────── Histórico / pasta / ajustes ─────────────────────────
@app.get("/api/history")
def history(): return jsonify(hist())

@app.post("/api/history/clear")
def history_clear(): HF.write_text("[]", "utf-8"); return jsonify(ok=1)

@app.get("/api/dest")
def dest(): return jsonify(dest=CFG["dest"])

@app.post("/api/pick")
def pick():
    code = "import tkinter as t,tkinter.filedialog as f;r=t.Tk();r.withdraw();r.attributes('-topmost',1);print(f.askdirectory())"
    r = subprocess.run([PY, "-c", code], capture_output=True, text=True, creationflags=NOWIN).stdout.strip()
    if r: cfg_set({"dest": os.path.normpath(r)})
    return jsonify(dest=CFG["dest"])

@app.post("/api/dest/open")
def dest_open():
    p = Path(CFG["dest"]); p.mkdir(parents=True, exist_ok=True)
    if os.name == "nt": os.startfile(str(p))
    else: subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(p)])
    return jsonify(ok=1)

@app.post("/api/reveal")
def reveal(): _reveal(request.json["path"]); return jsonify(ok=1)

@app.get("/api/settings")
def settings_get(): return jsonify(cfg=CFG, defaults=DEF)

@app.post("/api/settings")
def settings_set(): cfg_set(request.json or {}); return jsonify(cfg=CFG)

@app.post("/api/settings/reset")
def settings_reset(): cfg_set(dict(DEF)); return jsonify(cfg=CFG)

# ───────────────────────── Atualização via Git ─────────────────────────
UPD = dict(state="idle", msg="", cur="", new="", log=[])
GENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

def _git_exe():
    g = shutil.which("git")
    if g: return g
    for p in (r"C:\Program Files\Git\cmd\git.exe", r"C:\Program Files (x86)\Git\cmd\git.exe",
              str(Path.home() / r"AppData\Local\Programs\Git\cmd\git.exe")):
        if os.path.exists(p): return p

GIT = _git_exe()

def git(*a, t=60):
    return subprocess.run([GIT, "-C", str(ROOT), *a], capture_output=True, text=True, timeout=t,
                          creationflags=NOWIN, encoding="utf-8", errors="replace", env=GENV)

def update_check():
    UPD.update(state="checking", msg="", log=[], new="")
    try:
        if not GIT: UPD["state"] = "nogit"; return
        if git("rev-parse", "--show-toplevel").returncode: UPD["state"] = "norepo"; return
        r = git("fetch", "--quiet", t=45)
        if r.returncode: UPD.update(state="error", msg=clean(r.stderr or r.stdout)); return
        up = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if up.returncode: up = "origin/" + git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        else: up = up.stdout.strip()
        UPD["cur"] = git("rev-parse", "--short", "HEAD").stdout.strip()
        n = git("rev-list", "--count", f"HEAD..{up}")
        if n.returncode: UPD.update(state="error", msg=clean(n.stderr)); return
        if int(n.stdout.strip() or 0) > 0:
            UPD["new"] = git("rev-parse", "--short", up).stdout.strip()
            UPD["log"] = [l for l in git("log", "-n", "8", "--pretty=format:%s", f"HEAD..{up}").stdout.splitlines() if l.strip()]
            UPD["state"] = "available"
        else: UPD["state"] = "uptodate"
    except Exception as e: UPD.update(state="error", msg=clean(e))

def update_async():
    if UPD["state"] == "checking": return
    UPD["state"] = "checking"
    threading.Thread(target=update_check, daemon=True).start()

def restart():
    time.sleep(1.2)
    subprocess.Popen([sys.executable, str(ROOT / "app.py")], cwd=str(ROOT), close_fds=True,
                     creationflags=(0x00000008 | 0x00000200) if os.name == "nt" else 0)
    os._exit(0)

@app.get("/api/update/status")
def update_status():
    return jsonify({**UPD, "active": sum(j["st"] in ("run", "paused", "pausing") for j in JOBS.values())})

@app.post("/api/update/check")
def update_check_api(): update_async(); return jsonify(ok=1)

@app.post("/api/update/apply")
def update_apply():
    if not GIT: raise Exception("Git não encontrado neste computador.")
    r = git("pull", "--ff-only", t=240)
    if r.returncode:
        raise Exception("Não foi possível atualizar. " + clean(r.stderr or r.stdout))
    if (ROOT / "requirements.txt").exists():
        try: subprocess.run([PY, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")],
                            capture_output=True, timeout=600, creationflags=NOWIN)
        except Exception: pass
    threading.Thread(target=restart, daemon=True).start()
    return jsonify(ok=1)

@app.get("/api/about")
def about():
    ver = ""
    if GIT:
        try:
            r = git("log", "-1", "--pretty=format:%h · %cd", "--date=format:%d/%m/%Y")
            ver = r.stdout.strip() if r.returncode == 0 else ""
        except Exception: pass
    return jsonify(name=APP_NAME, ver=ver, ytdlp=yt_dlp.version.__version__, root=str(ROOT), git=bool(GIT))

# ───────────────────────── Inicialização ─────────────────────────
if __name__ == "__main__":
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    if CFG["auto_update"]: UPD["state"] = "checking"
    threading.Thread(target=lambda: app.run("127.0.0.1", port, threaded=True), daemon=True).start()
    time.sleep(.8); url = f"http://127.0.0.1:{port}"
    if CFG["auto_update"]: threading.Thread(target=update_check, daemon=True).start()
    if CFG["update_ytdlp"]: threading.Thread(target=update_ytdlp, daemon=True).start()
    if os.name == "nt":
        import ctypes; ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ADPB.M1Music.App")
        threading.Thread(target=set_icon, daemon=True).start()
    try:
        import webview
        webview.create_window(TITLE, url, width=1180, height=800, min_size=(820, 600))
        webview.start()
    except ImportError:
        import webbrowser; webbrowser.open(url); threading.Event().wait()
