# Adabiy Tarjimon AI — kitob (PDF) sahifalarini asl ko'rinishida tarjima qilish (GitHub Actions).
#   extract: PDF -> matn bloklari (bet, joyi, shrift o'lchami) -> blocks.json
#   build:   asl PDF + tarjimalar -> har bet o'z joyida: rasmlar, bezaklar, chiziqlar saqlanadi, faqat matn almashtiriladi
#            -> translated.pdf (+ translated.docx, tahrirlash uchun)
import glob, html, json, os, re, sys, urllib.request

import pymupdf as fitz

SPEC = json.load(urllib.request.urlopen(os.environ["SPEC_URL"], timeout=60))


def get(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "tarjimon-book/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        open(path, "wb").write(r.read())


def put(url, path, ctype):
    if url.startswith("file://"):  # mahalliy sinov
        open(url[7:], "wb").write(open(path, "rb").read())
        return
    data = open(path, "rb").read()
    req = urllib.request.Request(url, data=data, method="PUT", headers={"content-type": ctype, "x-upsert": "true"})
    with urllib.request.urlopen(req, timeout=600) as r:
        r.read()


def report(status, error="", **extra):
    body = json.dumps({"job": SPEC["job"], "token": SPEC["token"], "status": status, "error": error[:300], **extra}).encode()
    if not SPEC["callback"].startswith("http"):
        print("report", status, error, extra)
        return
    req = urllib.request.Request(SPEC["callback"], data=body, headers={"content-type": "application/json"})
    for _ in range(3):
        try:
            urllib.request.urlopen(req, timeout=60).read()
            return
        except Exception as e:  # noqa: BLE001
            print("report fail", e)


HAS_LETTER = re.compile(r"[^\W\d_]", re.U)


def block_text(b):
    """Blok qatorlarini gapga birlashtiradi (bo'g'in ko'chirishini tiklaydi), abzaslarni saqlaydi."""
    out, prev_x = "", None
    for ln in b["lines"]:
        t = "".join(s["text"] for s in ln["spans"]).strip()
        if not t:
            continue
        x0 = ln["bbox"][0]
        if not out:
            out = t
        elif out.endswith("-") and t[:1].islower():
            out = out[:-1] + t
        elif prev_x is not None and x0 - prev_x > 8 and out[-1:] in ".!?…:»\"”":
            out += "\n" + t  # xatboshi (qizil satr) — yangi abzas
        else:
            out += " " + t
        prev_x = x0 if prev_x is None else min(prev_x, x0)
    return out


def extract():
    get(SPEC["pdf_url"], "in.pdf")
    doc = fitz.open("in.pdf")
    blocks, chars = [], 0
    for pno, page in enumerate(doc, start=1):
        pw = page.rect.width
        d = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)
        i = 0
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            t = block_text(b)
            if len(t) < 2 or not HAS_LETTER.search(t):
                continue  # bet raqami, belgilar — o'z holicha qoladi
            spans = [s for ln in b["lines"] for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            main = max(spans, key=lambda s: len(s["text"]))
            sizes = sorted(s["size"] for s in spans)
            x0, y0, x1, y1 = b["bbox"]
            cx = (x0 + x1) / 2
            nlines = len(b["lines"])
            ys = [ln["bbox"][1] for ln in b["lines"]]
            lh = ((ys[-1] - ys[0]) / (nlines - 1) / max(1.0, sizes[len(sizes) // 2])) if nlines > 1 else 1.2
            lh = min(2.2, max(1.0, lh))
            tol = pw * (0.08 if nlines == 1 else 0.04)
            align = "center" if abs(cx - pw / 2) < tol and (x1 - x0) < pw * 0.62 else ("justify" if nlines > 1 else "left")
            i += 1
            if i >= 999:
                break
            blocks.append({
                "p": pno, "i": i, "t": t, "bbox": [round(v, 2) for v in b["bbox"]],
                "size": round(sizes[len(sizes) // 2], 2), "bold": bool(main["flags"] & 16), "italic": bool(main["flags"] & 2),
                "serif": bool(main["flags"] & 4) or "serif" in main["font"].lower() or "times" in main["font"].lower(),
                "color": main["color"], "align": align, "lh": round(lh, 2),
            })
            chars += len(t)
    json.dump({"pages": len(doc), "blocks": blocks}, open("blocks.json", "w"), ensure_ascii=False)
    put(SPEC["put"]["blocks"], "blocks.json", "application/json")
    print("pages", len(doc), "blocks", len(blocks), "chars", chars)
    return {"pages": len(doc), "blocks": len(blocks), "chars": chars}


def font_dir():
    for pat in ["/usr/share/fonts/truetype/liberation*/LiberationSerif-Regular.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]:
        g = glob.glob(pat)
        if g:
            return os.path.dirname(g[0]), ("Liberation" if "Liberation" in g[0] else "DejaVu")
    raise RuntimeError("font")


def css_fonts(kind):
    if kind == "Liberation":
        f = {"serif": "LiberationSerif", "sans": "LiberationSans"}
        names = {"": "Regular", "b": "Bold", "i": "Italic", "bi": "BoldItalic"}
    else:
        f = {"serif": "DejaVuSerif", "sans": "DejaVuSans"}
        names = {"": "", "b": "-Bold", "i": "-Italic", "bi": "-BoldItalic"}
    out = []
    for fam, base in f.items():
        for k, suf in names.items():
            fn = f"{base}-{suf}.ttf" if kind == "Liberation" else f"{base}{suf}.ttf"
            w = "bold" if "b" in k else "normal"
            s = "italic" if "i" in k else "normal"
            out.append(f"@font-face {{font-family: t{fam}; src: url({fn}); font-weight: {w}; font-style: {s};}}")
    return "\n".join(out)


def build():
    get(SPEC["pdf_url"], "in.pdf")
    get(SPEC["blocks_url"], "blocks.json")
    get(SPEC["tr_url"], "tr.json")
    meta = json.load(open("blocks.json"))
    tr = json.load(open("tr.json"))
    fdir, kind = font_dir()
    arch = fitz.Archive(fdir)
    css = css_fonts(kind) + "\n* {margin: 0; padding: 0;} p {margin: 0 0 0.25em 0;}"
    doc = fitz.open("in.pdf")
    by_page = {}
    for b in meta["blocks"]:
        key = str(b["p"] * 1000 + b["i"])
        if tr.get(key, "").strip():
            by_page.setdefault(b["p"], []).append((b, tr[key].strip()))
    small = 0
    for pno, items in by_page.items():
        page = doc[pno - 1]
        for b, _ in items:
            page.add_redact_annot(fitz.Rect(b["bbox"]), fill=False)
        try:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE, text=fitz.PDF_REDACT_TEXT_REMOVE)
        except TypeError:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        for b, t in items:
            r = fitz.Rect(b["bbox"])
            r = fitz.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1)
            c = int(b["color"])
            col = f"#{(c >> 16) & 255:02x}{(c >> 8) & 255:02x}{c & 255:02x}"
            fam = "tserif" if b.get("serif", True) else "tsans"
            style = (f"font-family: {fam}; font-size: {b['size']}px; line-height: {b.get('lh', 1.2)}; color: {col}; text-align: {b['align']};"
                     f"font-weight: {'bold' if b['bold'] else 'normal'}; font-style: {'italic' if b['italic'] else 'normal'};")
            body = "".join(f"<p>{html.escape(p)}</p>" for p in t.split("\n") if p.strip())
            res = page.insert_htmlbox(r, f'<div style="{style}">{body}</div>', css=css, archive=arch, scale_low=0)
            if res and len(res) > 1 and res[1] < 0.8:
                small += 1
    doc.subset_fonts()
    doc.save("translated.pdf", garbage=3, deflate=True)
    put(SPEC["put"]["pdf"], "translated.pdf", "application/pdf")
    print("pdf", os.path.getsize("translated.pdf"), "bytes; shrunk blocks:", small)
    docx = False
    if SPEC["put"].get("docx"):
        try:
            from pdf2docx import Converter
            cv = Converter("translated.pdf")
            cv.convert("translated.docx", multi_processing=False)
            cv.close()
            put(SPEC["put"]["docx"], "translated.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            docx = True
        except Exception as e:  # noqa: BLE001
            print("docx fail", e)
    return {"docx": docx, "shrunk": small}


try:
    info = extract() if SPEC["mode"] == "extract" else build()
    report("ok", **info)
except Exception as e:  # noqa: BLE001
    print("ERROR", e)
    report("error", str(e))
    sys.exit(1)
