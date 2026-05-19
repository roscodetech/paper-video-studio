#!/usr/bin/env python3
"""paper_video.py — Turn a scientific paper into an annotated scrolling video.

Subcommands:
  fetch <input> --out <work_dir>           Fetch PDF + metadata + per-page text
  render --work <work_dir> --out file.mp4  Render the highlight video

Designed to be driven by Claude via the 'paper-video' skill.
"""

from __future__ import annotations

# Use the OS certificate store when available — required behind TLS-intercepting
# AV / corporate proxies on Windows. Falls back to certifi if truststore is absent.
try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except ImportError:
    pass

import argparse
import asyncio
import io
import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

LOG = logging.getLogger("paper_video")

# ---------- Constants ----------

VIDEO_W = 1920
VIDEO_H = 1080
FPS = 30
PDF_DPI = 200
BG_RGB = (18, 22, 32)
BG_HEX = "0x121620"

TITLE_CARD_SEC = 4.0
END_CARD_SEC = 3.0
MIN_POINT_SEC = 5.0
WORDS_PER_SECOND = 2.6
PAN_DURATION_S = 1.1  # pan + simultaneous highlight reveal, fixed regardless of clip length

DEFAULT_VOICE = "en-US-AriaNeural"

UA = "Mozilla/5.0 (paper-video/1.0; +https://roscodetech.com)"


# ---------- Dataclasses ----------

@dataclass
class PaperMeta:
    title: str = ""
    authors: list = field(default_factory=list)
    journal: str = ""
    year: str = ""
    pmid: str = ""
    pmcid: str = ""
    doi: str = ""
    url: str = ""


@dataclass
class KeyPoint:
    text: str
    narration: str = ""


# ---------- Input parsing ----------

def parse_input(s: str) -> dict:
    s = s.strip().strip('"').strip("'")
    p = Path(s)
    if p.exists() and p.suffix.lower() == ".pdf":
        return {"kind": "local", "path": str(p)}

    m = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", s)
    if m:
        return {"kind": "pmid", "id": m.group(1)}

    m = re.search(r"PMC(\d+)", s, re.I)
    if m:
        return {"kind": "pmcid", "id": "PMC" + m.group(1)}

    if s.lower().startswith(("http://", "https://")) and ".pdf" in s.lower():
        return {"kind": "pdf_url", "url": s}

    if s.isdigit():
        return {"kind": "pmid", "id": s}

    raise ValueError(f"Unsupported input: {s!r}")


# ---------- PubMed / PMC fetching ----------

def fetch_pubmed_meta(pmid: str) -> PaperMeta:
    import requests
    r = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        params={"db": "pubmed", "id": pmid, "retmode": "json"},
        timeout=30,
        headers={"User-Agent": UA},
    )
    r.raise_for_status()
    j = r.json()["result"][pmid]
    return PaperMeta(
        title=(j.get("title") or "").strip().rstrip("."),
        authors=[a["name"] for a in j.get("authors", [])][:6],
        journal=j.get("fulljournalname") or j.get("source") or "",
        year=(j.get("pubdate") or "").split(" ")[0],
        pmid=pmid,
        doi=next((a["value"] for a in j.get("articleids", [])
                  if a.get("idtype") == "doi"), ""),
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    )


def pmcid_for_pmid(pmid: str) -> Optional[str]:
    import requests
    try:
        r = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi",
            params={"dbfrom": "pubmed", "db": "pmc", "id": pmid, "retmode": "json"},
            timeout=30,
            headers={"User-Agent": UA},
        )
        r.raise_for_status()
        for ls in r.json()["linksets"][0].get("linksetdbs", []):
            if ls.get("linkname") == "pubmed_pmc":
                ids = ls.get("links") or []
                if ids:
                    return "PMC" + str(ids[0])
    except Exception as e:
        LOG.warning("PMC link lookup failed: %s", e)
    return None


def download_pmc_pdf(pmcid: str, dest: Path) -> bool:
    """Download a PMC OA article PDF via the official OA API + tgz archive."""
    import io as _io
    import tarfile
    import xml.etree.ElementTree as ET
    import requests

    try:
        r = requests.get(
            "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi",
            params={"id": pmcid}, timeout=30, headers={"User-Agent": UA},
        )
        r.raise_for_status()
        root = ET.fromstring(r.text)

        # OA returns <error code="..."> when the article isn't in the OA subset
        err = root.find(".//error")
        if err is not None:
            LOG.warning("PMC OA error for %s: %s", pmcid, err.text or err.attrib)
            return False

        # Prefer pdf link, fall back to tgz
        pdf_link = root.find(".//link[@format='pdf']")
        tgz_link = root.find(".//link[@format='tgz']")

        def _candidates(ftp_url: str) -> list:
            """Build HTTPS candidates. NCBI moved legacy OA files into deprecated/
            in 2026 — try that path first, then the original."""
            base = ftp_url.replace("ftp://", "https://", 1)
            deprecated = base.replace("/pub/pmc/", "/pub/pmc/deprecated/", 1)
            return [deprecated, base]

        if pdf_link is not None:
            for url in _candidates(pdf_link.attrib["href"]):
                try:
                    rp = requests.get(url, headers={"User-Agent": UA}, timeout=120)
                    if rp.ok and rp.content[:4] == b"%PDF":
                        dest.write_bytes(rp.content)
                        return True
                except Exception:
                    continue

        if tgz_link is not None:
            tgz_bytes = None
            for url in _candidates(tgz_link.attrib["href"]):
                try:
                    rt = requests.get(url, headers={"User-Agent": UA}, timeout=180)
                    if rt.ok and rt.content[:2] == b"\x1f\x8b":
                        tgz_bytes = rt.content
                        break
                except Exception:
                    continue
            if tgz_bytes is None:
                LOG.warning("Could not download tgz for %s from any mirror", pmcid)
                return False
            with tarfile.open(fileobj=_io.BytesIO(tgz_bytes), mode="r:gz") as tf:
                pdfs = [m for m in tf.getmembers()
                        if m.isfile() and m.name.lower().endswith(".pdf")]
                if not pdfs:
                    LOG.warning("PMC tgz had no PDF for %s", pmcid)
                    return False
                # Prefer the largest PDF (usually the main article)
                pdfs.sort(key=lambda m: m.size, reverse=True)
                f = tf.extractfile(pdfs[0])
                if f is None:
                    return False
                data = f.read()
                if data[:4] != b"%PDF":
                    return False
                dest.write_bytes(data)
                return True

        LOG.warning("PMC OA record had no pdf/tgz link for %s", pmcid)
    except Exception as e:
        LOG.warning("PMC OA download error for %s: %s", pmcid, e)
    return False


def download_pdf(url: str, dest: Path):
    import requests
    r = requests.get(url, headers={"User-Agent": UA}, timeout=60, allow_redirects=True)
    r.raise_for_status()
    if r.content[:4] != b"%PDF":
        raise RuntimeError(f"URL did not return a PDF: {url}")
    dest.write_bytes(r.content)


# ---------- Fetch command ----------

def cmd_fetch(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pdf_path = out / "paper.pdf"

    parsed = parse_input(args.input)
    meta = PaperMeta()

    if parsed["kind"] == "local":
        shutil.copy(parsed["path"], pdf_path)
        meta.title = Path(parsed["path"]).stem

    elif parsed["kind"] == "pmid":
        meta = fetch_pubmed_meta(parsed["id"])
        pmcid = pmcid_for_pmid(parsed["id"])
        if pmcid and download_pmc_pdf(pmcid, pdf_path):
            meta.pmcid = pmcid
        else:
            raise SystemExit(
                f"No free PDF available for PMID {parsed['id']}. "
                "Provide a local PDF or a PMCID instead."
            )

    elif parsed["kind"] == "pmcid":
        if not download_pmc_pdf(parsed["id"], pdf_path):
            raise SystemExit(f"Could not download PDF for {parsed['id']}")
        meta.pmcid = parsed["id"]

    elif parsed["kind"] == "pdf_url":
        download_pdf(parsed["url"], pdf_path)
        meta.url = parsed["url"]
        meta.title = Path(urlparse(parsed["url"]).path).stem

    # Extract per-page text
    import fitz
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        pages.append({
            "page": i,
            "text": page.get_text("text"),
            "width": page.rect.width,
            "height": page.rect.height,
        })
    doc.close()

    if not meta.title or meta.title in ("paper", ""):
        first_lines = [ln.strip() for ln in (pages[0]["text"].splitlines() if pages else [])
                       if len(ln.strip()) > 10][:3]
        if first_lines:
            meta.title = " ".join(first_lines)[:200]

    (out / "meta.json").write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")
    (out / "pages.json").write_text(json.dumps(pages, indent=2), encoding="utf-8")

    print(f"OK fetched: {pdf_path}")
    print(f"   pages:  {len(pages)}")
    print(f"   title:  {meta.title[:100]}")
    print(f"   meta:   {out / 'meta.json'}")
    print(f"   text:   {out / 'pages.json'}")


# ---------- Quote location ----------

_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "ft",
    "ﬆ": "st",
}


def _ligate(s: str) -> str:
    """Insert PDF ligatures into a plain-ASCII string so it can match ligated PDF text."""
    for ascii_form, lig in [("ffi", "ﬃ"), ("ffl", "ﬄ"),
                            ("ff", "ﬀ"), ("fi", "ﬁ"), ("fl", "ﬂ")]:
        s = s.replace(ascii_form, lig)
    return s


def _norm(s: str) -> str:
    for _k, _v in _LIGATURES.items():
        s = s.replace(_k, _v)
    s = s.replace("‐", "-").replace("‑", "-").replace("–", "-").replace("—", "-")
    s = s.replace(" ", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def _norm_token(s: str) -> str:
    """Normalize a single word for matching: lowercase, de-ligate, strip punctuation."""
    for _k, _v in _LIGATURES.items():
        s = s.replace(_k, _v)
    s = s.lower()
    s = re.sub(r"[^\w]", "", s)
    return s


# Words that should never be the visible last token of a highlight.
_STOP_WORDS_AT_END = {
    "a", "an", "the",
    "and", "or", "but", "nor", "so", "yet",
    "of", "to", "in", "on", "at", "by", "with", "from", "for",
    "into", "onto", "over", "under", "through", "between", "across",
    "as", "than", "that", "which", "who", "whom",
    "is", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "do", "does", "did",
    "will", "would", "shall", "should", "can", "could", "may", "might", "must",
}

# Punctuation chars that terminate a clause/sentence/list-item.
_BOUNDARY_PUNCT_RE = re.compile(r"[.,;:!?—–\)\]]\s*$")


def _ends_at_natural_boundary(word_text: str) -> bool:
    """True if this raw word ends with sentence/clause punctuation."""
    return bool(_BOUNDARY_PUNCT_RE.search(word_text))


def _smart_extend_forward(words, end_idx: int, max_extra: int = 6) -> int:
    """Adjust the matched-range end so the highlight lands at a natural boundary.

    If the matched-range's last word already ends with punctuation, leave it alone.
    Otherwise look ahead up to max_extra words on or near the same line:
      - if any of them ends with punctuation, extend through that word;
      - otherwise, if the original last word is a stop word (preposition, article,
        conjunction, auxiliary), extend by exactly one word so the highlight never
        terminates on a weak word;
      - otherwise leave the range unchanged.

    Stops if we cross what looks like a paragraph break (vertical jump > 2x line height)."""
    if end_idx <= 0 or end_idx >= len(words):
        return end_idx

    last = words[end_idx - 1]
    if _ends_at_natural_boundary(last[4]):
        return end_idx

    last_y_mid = (last[1] + last[3]) / 2
    last_h = max(1.0, last[3] - last[1])

    found_punct_end = end_idx
    for j in range(end_idx, min(end_idx + max_extra, len(words))):
        w = words[j]
        w_y_mid = (w[1] + w[3]) / 2
        if abs(w_y_mid - last_y_mid) > last_h * 2.0:
            break
        if _ends_at_natural_boundary(w[4]):
            found_punct_end = j + 1
            break
        last_y_mid = w_y_mid

    if found_punct_end > end_idx:
        return found_punct_end

    if _norm_token(last[4]) in _STOP_WORDS_AT_END:
        return min(end_idx + 1, len(words))

    return end_idx


def _bridge_word_gaps(matched_words):
    """Extend each word's right edge to the next word's left edge when they're on
    the same PDF line, so adjacent highlighted words form a continuous strip."""
    bridged = []
    n = len(matched_words)
    for idx, w in enumerate(matched_words):
        x0, y0, x1, y1 = float(w[0]), float(w[1]), float(w[2]), float(w[3])
        if idx < n - 1:
            nxt = matched_words[idx + 1]
            nx0, ny0, ny1 = float(nxt[0]), float(nxt[1]), float(nxt[3])
            same_line = abs(((ny0 + ny1) / 2) - ((y0 + y1) / 2)) < (y1 - y0) * 0.6
            if same_line and nx0 > x1:
                x1 = nx0
        bridged.append([x0, y0, x1, y1])
    return bridged


def locate_quote(doc, quote: str):
    """Return (page_index, [bbox, ...]) or None.

    Bboxes are word-level (one per matched word in reading order), bridged
    horizontally so adjacent words on the same PDF line form a continuous strip.
    Word granularity is what keeps the highlight from cutting mid-word during
    animation or at hold time."""
    if not quote.strip():
        return None

    target_tokens = [_norm_token(t) for t in _norm(quote).split()]
    target_tokens = [t for t in target_tokens if t]
    if len(target_tokens) < 2:
        return None

    # Primary path: word-sequence match against page.get_text("words").
    for i in range(len(doc)):
        page = doc[i]
        words = page.get_text("words")
        if not words:
            continue
        page_tokens = [_norm_token(w[4]) for w in words]

        n = len(target_tokens)
        for start in range(len(page_tokens) - n + 1):
            if page_tokens[start:start + n] == target_tokens:
                end = _smart_extend_forward(words, start + n)
                matched = list(words[start:end])
                return i, _bridge_word_gaps(matched)

        # Looser fallback on this page: match the first ~10 distinctive tokens.
        if len(target_tokens) >= 6:
            needle = target_tokens[:min(10, len(target_tokens))]
            k = len(needle)
            for start in range(len(page_tokens) - k + 1):
                if page_tokens[start:start + k] == needle:
                    # Extend as far forward as tokens keep matching.
                    end = start + k
                    while (end < len(page_tokens)
                           and end - start < len(target_tokens)
                           and page_tokens[end] == target_tokens[end - start]):
                        end += 1
                    end = _smart_extend_forward(words, end)
                    matched = list(words[start:end])
                    return i, _bridge_word_gaps(matched)

    # Last-ditch fallback: existing search_for path. Returns line-level rects
    # without word granularity; the animation may then cut mid-word, but this
    # only fires when word-sequence matching fails entirely.
    snippet = quote.strip().split("\n")[0]
    snippet = snippet[:120] if len(snippet) > 120 else snippet
    snippet_lig = _ligate(snippet)

    for i in range(len(doc)):
        page = doc[i]
        for s in (snippet, snippet_lig) if snippet_lig != snippet else (snippet,):
            rects = page.search_for(s, quads=False)
            if rects:
                return i, [[r.x0, r.y0, r.x1, r.y1] for r in rects]

    return None


# ---------- Rendering helpers ----------

def render_pdf_page(doc, page_index: int, dpi: int = PDF_DPI):
    import fitz
    from PIL import Image
    page = doc[page_index]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def draw_highlight(img, bboxes_pdf, page_w_pdf, page_h_pdf,
                   fill=(255, 235, 59, 110), outline=(255, 193, 7, 230)):
    from PIL import Image, ImageDraw
    sx = img.width / page_w_pdf
    sy = img.height / page_h_pdf
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    pad = 6
    for bb in bboxes_pdf:
        x0, y0, x1, y1 = bb
        rx0, ry0 = int(x0 * sx) - pad, int(y0 * sy) - pad
        rx1, ry1 = int(x1 * sx) + pad, int(y1 * sy) + pad
        od.rectangle([rx0, ry0, rx1, ry1], fill=fill)
        od.rectangle([rx0, ry0, rx1, ry1], outline=outline, width=3)
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def highlight_pixel_bbox(img_w, img_h, bbox_pdf, page_w_pdf, page_h_pdf, pad_px=12):
    sx = img_w / page_w_pdf
    sy = img_h / page_h_pdf
    x0, y0, x1, y1 = bbox_pdf
    return (int(x0 * sx) - pad_px, int(y0 * sy) - pad_px,
            int(x1 * sx) + pad_px, int(y1 * sy) + pad_px)


# ---------- Font + text helpers ----------

def _load_font(size, bold=False):
    from PIL import ImageFont
    candidates = []
    if bold:
        candidates += [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]
    candidates += [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_text(text, font, max_width):
    from PIL import Image, ImageDraw
    dummy = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    words = text.split()
    lines, cur = [], []
    for w in words:
        cand = " ".join(cur + [w])
        if dummy.textlength(cand, font=font) <= max_width or not cur:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines


# ---------- Static frames ----------

def make_title_frame(meta: PaperMeta):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (VIDEO_W, VIDEO_H), BG_RGB)
    d = ImageDraw.Draw(img)

    f_title = _load_font(60, bold=True)
    f_sub = _load_font(32)
    f_meta = _load_font(26)

    title_lines = _wrap_text(meta.title or "Untitled", f_title, VIDEO_W - 240)
    title_lines = title_lines[:5]
    line_h = 76
    total_h = len(title_lines) * line_h
    y = (VIDEO_H - total_h) // 2 - 80
    for line in title_lines:
        tw = d.textlength(line, font=f_title)
        d.text(((VIDEO_W - tw) / 2, y), line, font=f_title, fill=(245, 245, 245))
        y += line_h

    y += 30
    if meta.authors:
        authors = ", ".join(meta.authors[:4])
        if len(meta.authors) > 4:
            authors += " et al."
        tw = d.textlength(authors, font=f_sub)
        d.text(((VIDEO_W - tw) / 2, y), authors, font=f_sub, fill=(180, 200, 220))
        y += 50

    cite_bits = [b for b in [meta.journal, meta.year] if b]
    if cite_bits:
        cite = "  ·  ".join(cite_bits)
        tw = d.textlength(cite, font=f_meta)
        d.text(((VIDEO_W - tw) / 2, y), cite, font=f_meta, fill=(140, 160, 180))

    return img


def make_end_frame(meta: PaperMeta):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (VIDEO_W, VIDEO_H), BG_RGB)
    d = ImageDraw.Draw(img)
    f_big = _load_font(54, bold=True)
    f_sm = _load_font(28)

    txt = "End of summary"
    tw = d.textlength(txt, font=f_big)
    d.text(((VIDEO_W - tw) / 2, VIDEO_H / 2 - 60), txt, font=f_big, fill=(245, 245, 245))

    bits = [b for b in [meta.journal, meta.year,
                        meta.doi or meta.pmcid or meta.pmid or meta.url] if b]
    if bits:
        cite = "  ·  ".join(bits)
        tw = d.textlength(cite, font=f_sm)
        d.text(((VIDEO_W - tw) / 2, VIDEO_H / 2 + 20), cite, font=f_sm, fill=(160, 180, 200))

    return img


# ---------- Clip encoding ----------

def write_static_clip(img, out_path: Path, duration: float):
    img_path = out_path.with_suffix(".png")
    img.save(img_path)
    vf = (f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,"
          f"pad={VIDEO_W}:{VIDEO_H}:(ow-iw)/2:(oh-ih)/2:color={BG_HEX}")
    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(img_path),
           "-c:v", "libx264", "-t", f"{duration:.2f}",
           "-pix_fmt", "yuv420p", "-r", str(FPS),
           "-vf", vf, "-an", str(out_path)]
    _run_ffmpeg(cmd)
    img_path.unlink(missing_ok=True)


def _ease_in_out(t):
    return t * t * (3 - 2 * t)


def _normalize_line_heights(bboxes, pad_x: int = 6):
    """Replace each line group's vertical bounds with a canonical (cy ± half_h)
    so every line of the highlight has the same height. Adjacent lines get a
    consistent gap regardless of which words sit on them (descenders like 'g',
    ascenders like 'h', or superscripts won't deform the outline).

    Input bboxes are in page-pixel coords without padding. Output bboxes carry
    `pad_x` of horizontal padding and a uniform vertical extent per line."""
    if not bboxes:
        return list(bboxes)

    heights = sorted(b[3] - b[1] for b in bboxes)
    typical_h = max(1, heights[len(heights) // 2])

    lines = []  # each: {"centers": [...], "members": [bb...]}
    for bb in bboxes:
        x0, y0, x1, y1 = bb
        cy = (y0 + y1) / 2.0
        placed = False
        for line in lines:
            line_cy = sum(line["centers"]) / len(line["centers"])
            if abs(cy - line_cy) < typical_h * 0.7:
                line["centers"].append(cy)
                line["members"].append(bb)
                placed = True
                break
        if not placed:
            lines.append({"centers": [cy], "members": [bb]})

    line_centers = [sum(L["centers"]) / len(L["centers"]) for L in lines]
    sorted_centers = sorted(line_centers)
    if len(sorted_centers) >= 2:
        gaps = [sorted_centers[i + 1] - sorted_centers[i]
                for i in range(len(sorted_centers) - 1)]
        median_gap = sorted(gaps)[len(gaps) // 2]
        # Half-height stays inside ~42% of the line-to-line spacing so adjacent
        # outlines never touch, regardless of which letters sit on each line.
        half_h = max(int(typical_h * 0.55), int(median_gap * 0.42))
    else:
        half_h = int(typical_h * 0.7)

    normalized = []
    for cy, line in zip(line_centers, lines):
        y0 = int(round(cy - half_h))
        y1 = int(round(cy + half_h))
        for bb in line["members"]:
            x0, _, x1, _ = bb
            normalized.append((x0 - pad_x, y0, x1 + pad_x, y1))

    normalized.sort(key=lambda b: (b[1], b[0]))
    return normalized


HL_FILL = (255, 235, 59, 110)
HL_OUTLINE = (255, 193, 7, 230)


def write_pan_clip(page_img, bboxes_pdf, page_w_pdf, page_h_pdf,
                   out_path: Path, duration: float):
    """Two stages:
      1) Pan + simultaneous smooth reveal (fixed ~1.1s): camera zooms toward the
         highlight closeup while the yellow highlight wipes in left-to-right at
         a pixel-smooth rate. Reveal ends word-aligned because the underlying
         bboxes are word-bridged. Narration and highlight start together.
      2) Hold: full highlight, single looped PNG.

    Pan shares one ffmpeg encode (raw RGB pipe). Hold is a separate static encode.
    The two are concatenated with -c copy."""
    from PIL import Image, ImageDraw

    pw, ph = page_img.size
    sx = pw / page_w_pdf
    sy = ph / page_h_pdf

    # Highlight bboxes in page-pixel coords. Each line is normalized to a
    # canonical vertical extent so descenders/ascenders/superscripts can't make
    # adjacent line outlines overlap unevenly.
    raw = []
    for x0, y0, x1, y1 in bboxes_pdf:
        raw.append((
            int(x0 * sx),
            int(y0 * sy),
            int(x1 * sx),
            int(y1 * sy),
        ))
    hl_page = _normalize_line_heights(raw, pad_x=6)

    # Union bbox = camera target
    ux0 = min(b[0] for b in hl_page)
    uy0 = min(b[1] for b in hl_page)
    ux1 = max(b[2] for b in hl_page)
    uy1 = max(b[3] for b in hl_page)

    start_zoom = min(VIDEO_W / pw, VIDEO_H / ph)
    hw, hh = max(1, ux1 - ux0), max(1, uy1 - uy0)
    end_zoom_y = (VIDEO_H * 0.42) / hh
    end_zoom_x = (VIDEO_W * 0.78) / hw
    end_zoom = max(start_zoom * 1.10, min(end_zoom_x, end_zoom_y, start_zoom * 3.2))

    sxc, syc = pw / 2, ph / 2
    exc, eyc = (ux0 + ux1) / 2, (uy0 + uy1) / 2

    # Stage durations: fixed-length pan/reveal, then long hold while narration plays.
    pan_dur = min(PAN_DURATION_S, duration * 0.4)
    hold_dur = max(0.4, duration - pan_dur)
    pan_frames = max(2, int(pan_dur * FPS))

    def _view_at(te):
        """Return (PIL.Image, cx0, cy0, zoom)."""
        zoom = start_zoom + (end_zoom - start_zoom) * te
        cx = sxc + (exc - sxc) * te
        cy = syc + (eyc - syc) * te
        crop_w = VIDEO_W / zoom
        crop_h = VIDEO_H / zoom
        cx0 = max(0.0, min(pw - crop_w, cx - crop_w / 2))
        cy0 = max(0.0, min(ph - crop_h, cy - crop_h / 2))
        crop = page_img.crop(
            (int(cx0), int(cy0), int(cx0 + crop_w), int(cy0 + crop_h))
        )
        if crop.mode != "RGB":
            crop = crop.convert("RGB")
        return crop.resize((VIDEO_W, VIDEO_H), Image.LANCZOS), cx0, cy0, zoom

    # End-zoom view = base for hold
    end_view, end_cx0, end_cy0, end_z = _view_at(1.0)

    def _group_visible_by_line(visible_bboxes):
        """Group bboxes that share approximately the same vertical band."""
        lines = []
        for bb in visible_bboxes:
            x0, y0, x1, y1 = bb
            placed = False
            for line in lines:
                ly0, ly1 = line["y0"], line["y1"]
                line_h = max(1, ly1 - ly0)
                if abs(((y0 + y1) / 2) - ((ly0 + ly1) / 2)) < line_h * 0.6:
                    line["y0"] = min(line["y0"], y0)
                    line["y1"] = max(line["y1"], y1)
                    line["bboxes"].append(bb)
                    placed = True
                    break
            if not placed:
                lines.append({"y0": y0, "y1": y1, "bboxes": [bb]})
        return lines

    def _bboxes_in_view(cx0, cy0, zoom):
        """Map the page-pixel bboxes into viewport coords for this camera frame."""
        return [
            (
                int((x0 - cx0) * zoom),
                int((y0 - cy0) * zoom),
                int((x1 - cx0) * zoom),
                int((y1 - cy0) * zoom),
            )
            for x0, y0, x1, y1 in hl_page
        ]

    def _draw_partial_highlight(base_img, bboxes_in_view, progress):
        """Composite a smooth pixel-progressive highlight at the given progress
        (0..1) on top of base_img. Within each line the fill grows continuously
        left-to-right; the amber outline is drawn once per partially-visible line.

        At progress=1.0 the entire word-bridged region is filled, so the held
        end-frame is always word-aligned."""
        overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
        if not bboxes_in_view or progress <= 0.0:
            return base_img.convert("RGB")
        od = ImageDraw.Draw(overlay)
        widths = [max(0, b[2] - b[0]) for b in bboxes_in_view]
        total_w = sum(widths) or 1
        target = total_w * min(1.0, max(0.0, progress))
        cum = 0
        partial_rects = []
        for (x0, y0, x1, y1), w in zip(bboxes_in_view, widths):
            if cum >= target:
                break
            rem = target - cum
            px1 = x0 + min(int(round(rem)), w)
            if px1 > x0:
                od.rectangle([x0, y0, px1, y1], fill=HL_FILL)
                partial_rects.append([x0, y0, px1, y1])
            cum += w

        for line in _group_visible_by_line(partial_rects):
            gxs0 = min(b[0] for b in line["bboxes"])
            gys0 = min(b[1] for b in line["bboxes"])
            gxs1 = max(b[2] for b in line["bboxes"])
            gys1 = max(b[3] for b in line["bboxes"])
            od.rectangle([gxs0, gys0, gxs1, gys1], outline=HL_OUTLINE, width=3)

        return Image.alpha_composite(base_img.convert("RGBA"), overlay).convert("RGB")

    tmpdir = out_path.parent
    pan_path = tmpdir / (out_path.stem + "_pan.mp4")
    hold_path = tmpdir / (out_path.stem + "_hold.mp4")
    hold_png = tmpdir / (out_path.stem + "_hold.png")
    stderr_log = tmpdir / (out_path.stem + "_stderr.log")

    # --- Pan + reveal: single rawvideo pipe ---
    stderr_fh = open(stderr_log, "wb")
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{VIDEO_W}x{VIDEO_H}",
         "-framerate", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-an", str(pan_path)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr_fh,
    )
    try:
        last_idx = max(1, pan_frames - 1)
        for fi in range(pan_frames):
            te = _ease_in_out(fi / last_idx)
            frame, cx0, cy0, zoom = _view_at(te)
            bb_view = _bboxes_in_view(cx0, cy0, zoom)
            # Reveal slightly ahead of camera so it feels "led" by the highlight,
            # but settles to fully revealed exactly at the end of the pan.
            reveal_p = min(1.0, (fi + 1) / last_idx * 1.05)
            frame_hl = _draw_partial_highlight(frame, bb_view, reveal_p)
            proc.stdin.write(frame_hl.tobytes())

        proc.stdin.close()
        rc = proc.wait(timeout=240)
        stderr_fh.close()
        if rc != 0:
            tail = stderr_log.read_text(encoding="utf-8", errors="ignore").splitlines()[-15:]
            raise RuntimeError("ffmpeg pan stage failed:\n" + "\n".join(tail))
    except Exception:
        try:
            proc.kill()
        finally:
            try:
                stderr_fh.close()
            except Exception:
                pass
        raise
    finally:
        stderr_log.unlink(missing_ok=True)

    # --- Hold: full highlight on the end-view, looped PNG ---
    full_hold = _draw_partial_highlight(end_view, _bboxes_in_view(end_cx0, end_cy0, end_z), 1.0)
    full_hold.save(hold_png)
    _run_ffmpeg([
        "ffmpeg", "-y", "-loop", "1", "-i", str(hold_png),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-t", f"{hold_dur:.3f}", "-an", str(hold_path),
    ])

    # --- Concat pan+anim and hold (same encoder params on both) ---
    list_file = tmpdir / (out_path.stem + "_concat.txt")
    list_file.write_text(
        f"file '{pan_path.resolve().as_posix()}'\nfile '{hold_path.resolve().as_posix()}'\n",
        encoding="utf-8",
    )
    _run_ffmpeg([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file), "-c", "copy", str(out_path),
    ])

    for p in (pan_path, hold_path, hold_png, list_file):
        p.unlink(missing_ok=True)


def _run_ffmpeg(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        tail = "\n".join((res.stderr or "").splitlines()[-15:])
        LOG.error("ffmpeg failed: %s\n%s", " ".join(cmd[:4]), tail)
        raise RuntimeError("ffmpeg failed")


# ---------- TTS ----------

def tts_edge(text: str, out_path: Path, voice: str = DEFAULT_VOICE):
    import edge_tts

    async def _gen():
        comm = edge_tts.Communicate(text, voice)
        await comm.save(str(out_path))

    asyncio.run(_gen())


def probe_duration(media_path: Path) -> float:
    if not media_path or not Path(media_path).exists():
        return 0.0
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(media_path)],
        capture_output=True, text=True,
    )
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0


# ---------- Concat ----------

def mux_clip_with_audio(clip: Path, audio: Optional[Path], out: Path):
    if audio and audio.exists():
        cmd = ["ffmpeg", "-y",
               "-i", str(clip), "-i", str(audio),
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-map", "0:v:0", "-map", "1:a:0",
               "-shortest", str(out)]
    else:
        # Generate silent track of matching duration
        dur = probe_duration(clip)
        cmd = ["ffmpeg", "-y",
               "-i", str(clip),
               "-f", "lavfi", "-t", f"{dur:.3f}",
               "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-map", "0:v:0", "-map", "1:a:0",
               "-shortest", str(out)]
    _run_ffmpeg(cmd)


def concat_clips(merged_clips, out_path: Path, work_tmp: Path):
    """Concat via the concat filter, which re-encodes and rebuilds timestamps.

    The concat demuxer with -c copy duplicates AAC packets when source clips
    have different encoder delay/priming, producing an audio stream much longer
    than the video. The concat filter avoids this at the cost of a re-encode."""
    n = len(merged_clips)
    cmd = ["ffmpeg", "-y"]
    for c in merged_clips:
        cmd.extend(["-i", str(c)])

    streams = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n))
    filter_str = f"{streams}concat=n={n}:v=1:a=1[v][a]"

    cmd.extend([
        "-filter_complex", filter_str,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        str(out_path),
    ])
    _run_ffmpeg(cmd)


# ---------- Render command ----------

def cmd_render(args):
    work = Path(args.work)
    if not (work / "meta.json").exists() or not (work / "paper.pdf").exists():
        raise SystemExit(f"Missing meta.json or paper.pdf in {work}")
    if not (work / "points.json").exists():
        raise SystemExit(f"Missing {work / 'points.json'} — write the key points first")

    meta = PaperMeta(**json.loads((work / "meta.json").read_text(encoding="utf-8")))
    raw_points = json.loads((work / "points.json").read_text(encoding="utf-8"))
    points = [KeyPoint(text=p["text"], narration=(p.get("narration") or p["text"]).strip())
              for p in raw_points if p.get("text")]
    if not points:
        raise SystemExit("points.json is empty")

    import fitz
    doc = fitz.open(work / "paper.pdf")

    voice_on = args.voice == "edge"
    voice_name = args.voice_name or DEFAULT_VOICE

    tmpdir = work / "tmp"
    tmpdir.mkdir(exist_ok=True)
    clips: list[Path] = []
    audios: list[Optional[Path]] = []

    # Title card
    title_audio: Optional[Path] = None
    if voice_on:
        title_narr = (meta.title or "Untitled").rstrip(".") + "."
        if meta.authors:
            title_narr += " By " + ", ".join(meta.authors[:3]) + "."
        title_audio = tmpdir / "00_title.mp3"
        try:
            tts_edge(title_narr, title_audio, voice_name)
        except Exception as e:
            LOG.warning("TTS title failed: %s", e)
            title_audio = None

    title_dur = max(TITLE_CARD_SEC,
                    (probe_duration(title_audio) + 0.6) if title_audio else 0.0)
    title_clip = tmpdir / "00_title.mp4"
    write_static_clip(make_title_frame(meta), title_clip, title_dur)
    clips.append(title_clip)
    audios.append(title_audio)

    # Per-point clips
    rendered_points = 0
    for idx, kp in enumerate(points, 1):
        found = locate_quote(doc, kp.text)
        if not found:
            LOG.warning("Could not locate quote (skipping): %r", kp.text[:80])
            continue
        page_idx, bboxes = found

        page_img = render_pdf_page(doc, page_idx, dpi=PDF_DPI)
        page = doc[page_idx]

        clip_audio: Optional[Path] = None
        if voice_on:
            clip_audio = tmpdir / f"{idx:02d}_point.mp3"
            try:
                tts_edge(kp.narration, clip_audio, voice_name)
            except Exception as e:
                LOG.warning("TTS point %d failed: %s", idx, e)
                clip_audio = None

        if clip_audio:
            dur = max(MIN_POINT_SEC, probe_duration(clip_audio) + 1.2)
        else:
            words = len(kp.narration.split())
            dur = max(MIN_POINT_SEC, words / WORDS_PER_SECOND + 1.8)

        clip_path = tmpdir / f"{idx:02d}_point.mp4"
        write_pan_clip(page_img, bboxes, page.rect.width, page.rect.height,
                       clip_path, dur)
        clips.append(clip_path)
        audios.append(clip_audio)
        rendered_points += 1
        print(f"  point {idx}/{len(points)} on page {page_idx + 1} ({dur:.1f}s)")

    if rendered_points == 0:
        raise SystemExit("None of the key points could be located in the PDF.")

    # End card
    end_clip = tmpdir / "99_end.mp4"
    write_static_clip(make_end_frame(meta), end_clip, END_CARD_SEC)
    clips.append(end_clip)
    audios.append(None)

    # Mux each clip with its audio, then concat
    mux_dir = tmpdir / "mux"
    mux_dir.mkdir(exist_ok=True)
    merged = []
    for i, (clip, audio) in enumerate(zip(clips, audios)):
        out = mux_dir / f"m_{i:02d}.mp4"
        mux_clip_with_audio(clip, audio, out)
        merged.append(out)

    final = Path(args.out)
    final.parent.mkdir(parents=True, exist_ok=True)
    concat_clips(merged, final, tmpdir)

    if not args.keep:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"\nOK rendered: {final}")
    print(f"   points rendered: {rendered_points}/{len(points)}")
    print(f"   duration: {probe_duration(final):.1f}s")


# ---------- Edit subcommand ----------

def cmd_edit(args):
    from paper_video_editor import launch_editor
    launch_editor(args.work)


# ---------- Main ----------

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    p = argparse.ArgumentParser(prog="paper_video",
                                description="Turn a paper into an annotated scrolling video")
    sub = p.add_subparsers(dest="cmd", required=True)

    fp = sub.add_parser("fetch", help="Fetch PDF + extract text")
    fp.add_argument("input",
                    help="PubMed URL/PMID, PMC URL/PMCID, PDF URL, or local PDF path")
    fp.add_argument("--out", default="work",
                    help="Output directory (default: work)")
    fp.set_defaults(func=cmd_fetch)

    rp = sub.add_parser("render", help="Render the video")
    rp.add_argument("--work", default="work",
                    help="Work dir with paper.pdf, meta.json, points.json")
    rp.add_argument("--out", required=True, help="Output MP4 path")
    rp.add_argument("--voice", choices=["edge", "none"], default="edge",
                    help="Voiceover (default: edge)")
    rp.add_argument("--voice-name", default=DEFAULT_VOICE,
                    help="edge-tts voice name (default: %(default)s)")
    rp.add_argument("--keep", action="store_true",
                    help="Keep tmp directory for debugging")
    rp.set_defaults(func=cmd_render)

    ep = sub.add_parser("edit", help="Open Tkinter editor for points.json")
    ep.add_argument("--work", required=True, type=Path,
                    help="Work directory containing pages.json")
    ep.set_defaults(func=cmd_edit)

    args = p.parse_args()
    try:
        args.func(args)
    except SystemExit:
        raise
    except Exception as e:
        LOG.error("%s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
