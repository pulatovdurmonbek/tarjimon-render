# Adabiy Tarjimon AI — video montaj (GitHub Actions). Topshiriq (spec) Supabase'dan vaqtinchalik havola orqali keladi.
import json, os, subprocess, sys, time, urllib.parse, urllib.request, zipfile

SPEC = json.load(urllib.request.urlopen(os.environ["SPEC_URL"], timeout=60))
W, H = int(SPEC["w"]), int(SPEC["h"])
POLL = os.environ.get("POLL_BASE", "https://image.pollinations.ai/prompt/")


def get(url, path, tries=3, wait=6, minlen=1500):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tarjimon-render/1.0"})
            with urllib.request.urlopen(req, timeout=150) as r:
                data = r.read()
            if len(data) >= minlen:
                open(path, "wb").write(data)
                return True
            print("short response", len(data))
        except Exception as e:  # noqa: BLE001
            print("get fail", url[:80], e)
        time.sleep(wait * (i + 1))
    return False


def put(url, path, ctype):
    data = open(path, "rb").read()
    req = urllib.request.Request(url, data=data, method="PUT", headers={"content-type": ctype, "x-upsert": "true"})
    with urllib.request.urlopen(req, timeout=300) as r:
        r.read()


def report(status, error=""):
    body = json.dumps({"job": SPEC["job"], "token": SPEC["token"], "status": status, "error": error[:300]}).encode()
    req = urllib.request.Request(SPEC["callback"], data=body, headers={"content-type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=60).read()
    except Exception as e:  # noqa: BLE001
        print("report fail", e)


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-600:])


def main():
    os.makedirs("frames", exist_ok=True)
    audio = "audio.mp3" if SPEC.get("audio_url") and get(SPEC["audio_url"], "audio.mp3", minlen=500) else None
    if not get(SPEC["srt_url"], "subs.srt", minlen=5):
        raise RuntimeError("srt")
    parts, last = [], 0.0
    for i, s in enumerate(SPEC["scenes"]):
        img = f"frames/sahna_{i + 1:02d}.jpg"
        # bepul FLUX: anonim so'rovlar ~15 soniyada bittadan
        gap = time.time() - last
        if gap < 16:
            time.sleep(16 - gap)
        q = urllib.parse.quote(s["image_prompt"][:900], safe="")
        url = f"{POLL}{q}?width={W}&height={H}&model=flux&nologo=true&seed={int(SPEC['seed']) + i}"
        ok = get(url, img, tries=3, wait=10)
        last = time.time()
        if not ok:
            run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"gradients=s={W}x{H}:c0=0x1d3557:c1=0x2a9d8f:x0=0:y0=0:x1={W}:y1={H}:d=1",
                 "-frames:v", "1", img])
        d = max(1.5, float(s["dur"]))
        frames = int(round(d * 25))
        z = "min(zoom+0.0010,1.20)" if i % 2 == 0 else "if(eq(on,0),1.20,max(zoom-0.0010,1.0))"
        vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
              f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps=25,format=yuv420p")
        out = f"p{i:02d}.mp4"
        run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", img, "-vf", vf, "-frames:v", str(frames),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", out])
        parts.append(out)
    open("list.txt", "w").write("".join(f"file '{p}'\n" for p in parts))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "raw.mp4"])
    vertical = H > W
    style = (f"FontName=DejaVu Sans,FontSize={13 if vertical else 18},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
             f"BackColour=&H64000000,BorderStyle=1,Outline=1.6,Shadow=0.6,Bold=1,Alignment=2,MarginV={48 if vertical else 22},MarginL=18,MarginR=18")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", "raw.mp4"] + (["-i", audio] if audio else [])
    cmd += ["-vf", f"subtitles=subs.srt:force_style='{style}'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p"]
    cmd += (["-c:a", "aac", "-b:a", "128k", "-shortest"] if audio else []) + ["-movflags", "+faststart", "video.mp4"]
    run(cmd)
    with zipfile.ZipFile("frames.zip", "w", zipfile.ZIP_STORED) as z:
        for f in sorted(os.listdir("frames")):
            z.write(os.path.join("frames", f), f)
    put(SPEC["put"]["video"], "video.mp4", "video/mp4")
    put(SPEC["put"]["frames"], "frames.zip", "application/zip")
    print("video", os.path.getsize("video.mp4"), "bytes")


try:
    main()
    report("ok")
except Exception as e:  # noqa: BLE001
    print("ERROR", e)
    report("error", str(e))
    sys.exit(1)
