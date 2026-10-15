"""Word <-> PDF conversion.

Backends, best first:
  1. Microsoft Word (COM automation) - best fidelity, DOC/DOCX/RTF/ODT/HTML;
  2. LibreOffice (soffice --headless), if installed;
  3. built-in converters (no external software):
     DOCX/TXT/HTML -> PDF via mammoth + PyMuPDF Story layout,
     PDF -> DOCX via PyMuPDF text/image extraction + python-docx.

Conversions run in a separate process (``run_job``) so the GUI stays
responsive and a cancelled Word conversion can be killed cleanly. This module
must not import Qt.
"""
from __future__ import annotations

import html
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

WORD_EXT = (".docx", ".doc", ".docm", ".dotx", ".dot", ".rtf", ".odt", ".wps")
TEXT_EXT = (".txt", ".htm", ".html", ".md")
CONVERTIBLE_EXT = WORD_EXT + TEXT_EXT
BUILTIN_TO_PDF = (".docx", ".docm", ".dotx") + TEXT_EXT

WD_FORMAT_PDF = 17          # WdExportFormat.wdExportFormatPDF
WD_FORMAT_DOCX = 16         # WdSaveFormat.wdFormatXMLDocument
NO_WINDOW = 0x08000000      # CREATE_NO_WINDOW


class ConversionError(Exception):
    pass


# ----------------------------------------------------------------- detection
def word_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"):
            return True
    except OSError:
        return False


def libreoffice_path() -> str | None:
    candidates = [shutil.which("soffice")]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            candidates.append(os.path.join(base, "LibreOffice", "program", "soffice.exe"))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def backends() -> dict:
    return {"word": word_available(), "libreoffice": libreoffice_path() is not None}


def describe_backend(name: str) -> str:
    return {"word": "Microsoft Word", "libreoffice": "LibreOffice",
            "builtin": "встроенный конвертер"}.get(name, name)


def pick_backend(kind: str, src: str) -> str:
    """kind: 'to_pdf' or 'to_docx'."""
    ext = os.path.splitext(src)[1].lower()
    forced = os.environ.get("PDFREADER_CONVERTER")  # word / libreoffice / builtin
    if forced in ("word", "libreoffice", "builtin"):
        return forced
    if word_available():
        return "word"
    if libreoffice_path():
        return "libreoffice"
    if kind == "to_pdf" and ext not in BUILTIN_TO_PDF:
        raise ConversionError(
            f"Для преобразования файлов {ext} нужен Microsoft Word или LibreOffice.\n"
            "Встроенный конвертер поддерживает DOCX, TXT и HTML.")
    return "builtin"


# ===================================================================== jobs
def run_job(conn, kind: str, src: str, dst: str, backend: str):
    """Entry point of the conversion process. Reports through ``conn``:
    ("pid", word_pid) / ("progress", i, n) / ("done", backend) / ("error", message)."""
    try:
        if backend == "word":
            _word_convert(conn, kind, src, dst)
        elif backend == "libreoffice":
            _libreoffice_convert(kind, src, dst)
        elif kind == "to_pdf":
            builtin_to_pdf(src, dst)
        else:
            builtin_pdf_to_docx(src, dst, lambda i, n: conn.send(("progress", i, n)))
        if not os.path.exists(dst) or os.path.getsize(dst) == 0:
            raise ConversionError("Конвертер не создал файл.")
        conn.send(("done", backend))
    except Exception as exc:  # reported to the GUI
        msg = str(exc) or exc.__class__.__name__
        conn.send(("error", msg))
    finally:
        conn.close()


# --------------------------------------------------------------- MS Word
def _word_pids() -> set[int]:
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq WINWORD.EXE", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, creationflags=NO_WINDOW, timeout=10).stdout
    except Exception:
        return set()
    pids = set()
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            pids.add(int(parts[1]))
    return pids


def _word_convert(conn, kind, src, dst):
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    before = _word_pids()
    word = win32com.client.DispatchEx("Word.Application")
    try:
        # report our own (new) Word process so a cancel can terminate it
        for pid in _word_pids() - before:
            conn.send(("pid", pid))
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(os.path.abspath(src), ConfirmConversions=False, ReadOnly=True,
                                  AddToRecentFiles=False, Visible=False)
        try:
            if kind == "to_pdf":
                doc.ExportAsFixedFormat(os.path.abspath(dst), WD_FORMAT_PDF,
                                        OptimizeFor=0, CreateBookmarks=1, DocStructureTags=True)
            else:
                doc.SaveAs2(os.path.abspath(dst), FileFormat=WD_FORMAT_DOCX)
        finally:
            doc.Close(0)
    finally:
        try:
            word.Quit(0)
        except Exception:
            pass
        pythoncom.CoUninitialize()


# ------------------------------------------------------------ LibreOffice
def _libreoffice_convert(kind, src, dst):
    soffice = libreoffice_path()
    out_dir = tempfile.mkdtemp(prefix="pdfreader_lo_")
    try:
        args = [soffice, "--headless", "--norestore"]
        if kind == "to_pdf":
            args += ["--convert-to", "pdf"]
        else:
            args += ["--infilter=writer_pdf_import", "--convert-to", "docx:MS Word 2007 XML"]
        args += ["--outdir", out_dir, os.path.abspath(src)]
        subprocess.run(args, check=True, timeout=600, creationflags=NO_WINDOW,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        produced = [f for f in os.listdir(out_dir)]
        if not produced:
            raise ConversionError("LibreOffice не смог преобразовать файл.")
        shutil.move(os.path.join(out_dir, produced[0]), dst)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


# ---------------------------------------------------- built-in: -> PDF
_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_FONT_FACES = [("arial.ttf", "normal", "normal"), ("arialbd.ttf", "bold", "normal"),
               ("ariali.ttf", "normal", "italic"), ("arialbi.ttf", "bold", "italic")]

_CSS = """
body { font-family: DocSans, sans-serif; font-size: 11pt; line-height: 1.3; }
h1 { font-size: 20pt; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }
p { margin: 0 0 6pt 0; }
table { border-collapse: collapse; margin: 6pt 0; }
td, th { border: 1px solid #808080; padding: 3pt 5pt; vertical-align: top; }
img { max-width: 100%; }
pre { font-family: DocMono, monospace; font-size: 9.5pt; white-space: pre-wrap; }
"""


def _font_css(archive_dir: str) -> str:
    """@font-face rules for Arial/Courier copied into the Story archive."""
    rules = []
    for fname, weight, style in _FONT_FACES:
        path = os.path.join(_FONT_DIR, fname)
        if os.path.exists(path):
            shutil.copy(path, os.path.join(archive_dir, fname))
            rules.append(f"@font-face {{ font-family: DocSans; src: url({fname}); "
                         f"font-weight: {weight}; font-style: {style}; }}")
    mono = os.path.join(_FONT_DIR, "cour.ttf")
    if os.path.exists(mono):
        shutil.copy(mono, os.path.join(archive_dir, "cour.ttf"))
        rules.append("@font-face { font-family: DocMono; src: url(cour.ttf); }")
    return "\n".join(rules)


def _docx_to_html(src: str, img_dir: str) -> str:
    import mammoth

    counter = [0]

    def save_image(image):
        counter[0] += 1
        ext = (image.content_type or "image/png").split("/")[-1].replace("jpeg", "jpg")
        name = f"img{counter[0]}.{ext}"
        with image.open() as data, open(os.path.join(img_dir, name), "wb") as f:
            f.write(data.read())
        return {"src": name}

    style_map = "\n".join([
        "p[style-name='Title'] => h1.title:fresh",
        "p[style-name='Заголовок'] => h1.title:fresh",
        "p[style-name='Subtitle'] => h2:fresh",
        "p[style-name='Подзаголовок'] => h2:fresh",
    ])
    with open(src, "rb") as f:
        result = mammoth.convert_to_html(f, style_map=style_map,
                                         convert_image=mammoth.images.img_element(save_image))
    return result.value


def builtin_to_pdf(src: str, dst: str):
    import pymupdf as fitz

    ext = os.path.splitext(src)[1].lower()
    work = tempfile.mkdtemp(prefix="pdfreader_conv_")
    try:
        if ext in (".docx", ".docm", ".dotx"):
            body = _docx_to_html(src, work)
        elif ext in (".htm", ".html"):
            with open(src, "rb") as f:
                body = f.read().decode("utf-8", "replace")
            body = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", body)
        else:  # plain text / markdown
            with open(src, "rb") as f:
                raw = f.read()
            for enc in ("utf-8", "cp1251"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = raw.decode("utf-8", "replace")
            body = f"<pre>{html.escape(text)}</pre>"
        css = _font_css(work) + _CSS
        story = fitz.Story(html=body, user_css=css, archive=fitz.Archive(work))
        mediabox = fitz.paper_rect("a4")
        where = mediabox + (57, 57, -57, -57)  # 2 cm margins
        writer = fitz.DocumentWriter(dst)
        more = True
        pages = 0
        while more:
            dev = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
            pages += 1
            if pages > 5000:
                break
        writer.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------- built-in: PDF -> DOCX
_SUBSET = re.compile(r"^[A-Z]{6}\+")


def _span_style(s) -> tuple:
    name = _SUBSET.sub("", s.get("font", ""))
    low = name.lower()
    sflags = s.get("flags", 0)
    bold = bool(sflags & 16) or "bold" in low
    italic = bool(sflags & 2) or "italic" in low or "oblique" in low
    base = name.split("-")[0].split(",")[0]
    return (base, round(s["size"] * 2) / 2, bold, italic, s.get("color", 0))


def builtin_pdf_to_docx(src: str, dst: str, progress=None):
    """Reflowing PDF -> DOCX: paragraphs with fonts/sizes/styles, images,
    one Word page per PDF page."""
    import pymupdf as fitz
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.shared import Pt, RGBColor

    pdf = fitz.open(src)
    out = Document()
    sec = out.sections[0]
    if len(pdf):
        r = pdf[0].rect
        sec.page_width, sec.page_height = Pt(r.width), Pt(r.height)
    margin = Pt(42)
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = margin
    content_w = (sec.page_width - 2 * margin) / 12700  # in points

    flags = fitz.TEXT_PRESERVE_IMAGES | fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP
    n = len(pdf)
    for pno, page in enumerate(pdf):
        if progress:
            progress(pno, n)
        if pno:
            out.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        pw = page.rect.width
        blocks = page.get_text("dict", flags=flags)["blocks"]
        blocks.sort(key=lambda b: (round(b["bbox"][1] / 4), b["bbox"][0]))
        for b in blocks:
            x0, y0, x1, y1 = b["bbox"]
            if b.get("type") == 1:  # image
                data = b.get("image")
                if not data:
                    continue
                try:
                    out.add_picture(io.BytesIO(data), width=Pt(min(max(x1 - x0, 12), content_w)))
                except Exception:
                    pass
                continue
            # collect (text, style) pieces, merging equal neighbours
            pieces: list[list] = []
            for line in b.get("lines", []):
                spans = [sp for sp in line.get("spans", []) if sp.get("text")]
                if not spans:
                    continue
                if pieces:
                    prev = pieces[-1][0]
                    if prev.endswith("-") and len(prev) > 1 and prev[-2].isalpha():
                        pieces[-1][0] = prev[:-1]   # join hyphenated words
                    elif not prev.endswith(" "):
                        pieces[-1][0] = prev + " "
                for sp in spans:
                    st = _span_style(sp)
                    if pieces and pieces[-1][1] == st:
                        pieces[-1][0] += sp["text"]
                    else:
                        pieces.append([sp["text"], st])
            if not pieces:
                continue
            para = out.add_paragraph()
            pf = para.paragraph_format
            pf.space_after = Pt(4)
            pf.space_before = Pt(0)
            center = (x0 + x1) / 2
            if abs(center - pw / 2) < pw * 0.04 and (x1 - x0) < pw * 0.7:
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for text, (base, size, bold, italic, color) in pieces:
                run = para.add_run(text)
                font = run.font
                font.size = Pt(max(1.0, size))
                if bold:
                    font.bold = True
                if italic:
                    font.italic = True
                if base:
                    font.name = base
                if color:
                    font.color.rgb = RGBColor((color >> 16) & 255, (color >> 8) & 255, color & 255)
    pdf.close()
    out.save(dst)
