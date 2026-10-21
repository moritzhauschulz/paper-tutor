#!/usr/bin/env python3
"""Fetch a paper into the paper-tutor store and build its indexes.

Usage:
  python3 -I fetch_paper.py <arxiv-id | arxiv URL | other PDF URL | local path> [options]

Options:
  --id ID         store id for local files / non-arXiv URLs (default: derived from file name)
  --title TITLE   title for local files / non-arXiv URLs
  --force         re-download even if this version is already stored
  --reindex       rebuild flat file and indexes from the stored source, no network

Source preference: LaTeX (arXiv e-print) > arXiv HTML (LaTeXML) > PDF text.
Prints a JSON summary on stdout. Paper content is data; nothing in it is executed.
"""

import argparse
import gzip
import html.parser
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import texindex  # noqa: E402

USER_AGENT = "paper-tutor/0.1 (Claude Code skill; personal study tool)"
REQUEST_GAP = 3.0  # seconds between requests to arXiv, per their API guidance
MAX_DOWNLOAD = 200 * 1024 * 1024
_last_request = [0.0]


# ---------------------------------------------------------------- network

def http_get(url, timeout=60):
    """Return (status, bytes, content_type). Never raises on HTTP errors."""
    wait = REQUEST_GAP - (time.time() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(MAX_DOWNLOAD + 1)
            if len(data) > MAX_DOWNLOAD:
                raise RuntimeError(f"download from {url} exceeds {MAX_DOWNLOAD} bytes")
            return r.status, data, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, b"", ""
    except urllib.error.URLError as e:
        return 0, str(e.reason).encode(), ""
    finally:
        _last_request[0] = time.time()


def arxiv_meta(arxiv_id):
    """Query the arXiv API. Returns dict or None."""
    status, data, _ = http_get(f"https://export.arxiv.org/api/query?id_list={arxiv_id}&max_results=1")
    if status != 200 or not data:
        return None
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    entry = root.find("a:entry", ns)
    if entry is None:
        return None
    eid = (entry.findtext("a:id", "", ns) or "").strip()
    title = re.sub(r"\s+", " ", entry.findtext("a:title", "", ns) or "").strip()
    if not eid or title.lower() == "error":
        return None
    m = re.search(r"(v\d+)$", eid)
    return {
        "title": title,
        "authors": [re.sub(r"\s+", " ", a.findtext("a:name", "", ns)).strip()
                    for a in entry.findall("a:author", ns)],
        "abstract": re.sub(r"\s+", " ", entry.findtext("a:summary", "", ns) or "").strip(),
        "published": (entry.findtext("a:published", "", ns) or "")[:10],
        "latest_version": m.group(1) if m else "v1",
    }


# ---------------------------------------------------------------- archives

def sniff(data):
    if data[:2] == b"\x1f\x8b":
        return "gzip"
    if data[:5] == b"%PDF-":
        return "pdf"
    if len(data) > 262 and data[257:262] == b"ustar":
        return "tar"
    head = data[:2048].lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        return "html"
    return "text"


def safe_extract(tar_bytes, dest):
    """Extract a tar archive, refusing absolute paths, '..', links and special files."""
    dest = Path(dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    skipped = []
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:*") as tf:
        members = []
        for m in tf.getmembers():
            name = m.name
            parts = Path(name).parts
            bad = (name.startswith("/") or name.startswith("\\") or ".." in parts
                   or re.match(r"^[A-Za-z]:", name) or m.issym() or m.islnk()
                   or not (m.isfile() or m.isdir()))
            if not bad:
                try:
                    (dest / name).resolve().relative_to(dest)
                except ValueError:
                    bad = True
            if bad:
                skipped.append(name)
            else:
                members.append(m)
        kwargs = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tf.extractall(dest, members=members, **kwargs)
    return skipped


def unpack_source(data, dest):
    """Unpack an arXiv e-print payload into dest. Returns (kind, warnings)."""
    warnings = []
    kind = sniff(data)
    if kind == "gzip":
        try:
            data = gzip.decompress(data)
        except OSError as e:
            return "broken", [f"could not gunzip source: {e}"]
        kind = sniff(data)
        if kind == "text" and _is_tar(data):
            kind = "tar"
    elif kind == "text" and _is_tar(data):
        kind = "tar"
    if kind == "tar":
        skipped = safe_extract(data, dest)
        if skipped:
            warnings.append(f"skipped {len(skipped)} unsafe archive entries: {skipped[:5]}")
        return "tex", warnings
    if kind == "pdf":
        return "pdf", warnings
    if kind == "text":
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "main.tex").write_bytes(data)
        return "tex", warnings
    return kind, warnings


def _is_tar(data):
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tf:
            return len(tf.getmembers()) > 0
    except (tarfile.TarError, EOFError):
        return False


# ---------------------------------------------------------------- HTML -> text

class _HtmlToText(html.parser.HTMLParser):
    """LaTeXML HTML to readable text; math becomes $alttext$ so LaTeX survives."""
    BLOCK = {"p", "div", "section", "article", "li", "tr", "br", "table", "figure", "figcaption",
             "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}
    SKIP = {"script", "style", "nav", "header", "footer", "button"}
    # sections, appendices, equations, figures, tables, theorem-likes; not paragraphs or inline math
    ANCHOR = re.compile(r"^(?:S|A|Ch)\d+(?:\.(?:SS|SSS|E|EGx|F|T|Thm|Lem|Def|Ex|Prop|Cor|Rem|Ass)\d+)*$")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.math = [], 0, 0
        self.math_tex, self.math_block, self.math_buf = "", False, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "math":
            if self.math == 0 and not self.skip:
                self.math_tex = (a.get("alttext") or "").strip()
                self.math_block = a.get("display") == "block"
                self.math_buf = []
            self.math += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and not self.skip:
                self.out.append("#" * int(tag[1]) + " ")
        if a.get("id") and not self.skip and not self.math and self.ANCHOR.match(a["id"]):
            self.out.append(f"[#{a['id']}] ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "math":
            self.math = max(0, self.math - 1)
            if self.math == 0 and not self.skip:
                tex = self.math_tex or re.sub(r"\s+", " ", "".join(self.math_buf).replace("\u200b", "")).strip()
                sep = " " if self.out and self.out[-1].endswith("$") else ""
                self.out.append(f"\n$$ {tex} $$\n" if self.math_block else f"{sep}${tex}$")
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self.math:
            if not self.math_tex:
                self.math_buf.append(data)
        else:
            self.out.append(data)

    def text(self):
        t = "".join(self.out)
        t = re.sub(r"[ \t]+", " ", t)
        return re.sub(r"\n\s*\n+", "\n\n", t).strip() + "\n"


def html_to_text(html_bytes):
    p = _HtmlToText()
    p.feed(html_bytes.decode("utf-8", errors="replace"))
    return p.text()


def pdf_to_text(pdf_path, txt_path):
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", str(pdf_path), str(txt_path)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return None
        return f"pdftotext failed: {r.stderr.strip()[:200]}"
    try:
        import pypdf  # type: ignore
    except ImportError:
        return ("no PDF text extractor found. Install poppler (macOS: `brew install poppler`, "
                "Debian/Ubuntu: `apt install poppler-utils`) or `pip install pypdf`, then rerun "
                "with --reindex")
    reader = pypdf.PdfReader(str(pdf_path))
    txt_path.write_text("\n\f".join((pg.extract_text() or "") for pg in reader.pages),
                        encoding="utf-8")
    return None


# ---------------------------------------------------------------- indexing

def index_tex(d, src):
    """Find main, flatten, index. Returns summary fields and warnings."""
    warnings = []
    main = texindex.find_main(src)
    if main is None:
        return None, ["no .tex file found in the source archive"]
    flat, unresolved = texindex.flatten(main, src)
    if not texindex.is_latex(texindex.strip_comments(flat)):
        warnings.append("plain TeX source (not LaTeX): section/label/theorem indexes will be sparse; "
                        "read main.flat.tex directly and grep for headings")
    if unresolved:
        warnings.append(f"\\input targets not in the source tree (usually system packages such as "
                        f"harvmac; fine unless they look like paper sections): {sorted(set(unresolved))[:10]}")
    (d / "main.flat.tex").write_text(flat, encoding="utf-8")
    extra = ""
    for sty in list(src.rglob("*.sty")) + list(src.rglob("*.cls")):
        try:
            extra += sty.read_text(encoding="utf-8", errors="replace") + "\n"
        except OSError:
            pass
    idx = texindex.build_index(flat, src_root=src, extra_defs=_defs_only(extra))
    texindex.write_indexes(d, idx)
    bbls = sorted(src.rglob("*.bbl"), key=lambda p: (p.stem != main.stem, len(str(p))))
    bibs = sorted(src.rglob("*.bib"))
    if bbls:
        shutil.copyfile(bbls[0], d / "refs.bbl")
    elif bibs:
        (d / "refs.bib").write_text("\n".join(b.read_text(encoding="utf-8", errors="replace")
                                              for b in bibs), encoding="utf-8")
    else:
        warnings.append("no .bbl or .bib found; citation lookup unavailable")
    return {
        "main_file": str(main.relative_to(src)),
        "lines": flat.count("\n") + 1,
        "chars": len(flat),
        "n_sections": len(idx["sections"]),
        "n_labels": len(idx["labels"]),
        "n_results": sum(1 for lab in idx["labels"] if lab.get("kind") == "theorem"),
        "n_figures": len(idx["figures"]),
        "n_proofs": len(idx["proofs"]),
    }, warnings


def _defs_only(sty_text):
    """Keep only definition lines from .sty/.cls files (they can be huge)."""
    keep = [ln for ln in sty_text.splitlines()
            if re.search(r"\\(newtheorem|declaretheorem|newcommand|DeclareMathOperator|def)\b", ln)]
    return "\n".join(keep[:2000])


# ---------------------------------------------------------------- main flow

def fetch_arxiv(arxiv_id, version, args):
    sid = common.safe_id(arxiv_id)
    d = common.store_dir() / sid
    d.mkdir(parents=True, exist_ok=True)
    warnings = common.ensure_local(d)
    meta_path = d / "meta.json"
    meta = common.read_meta(d) if meta_path.exists() else {}

    if args.reindex:
        return reindex(d, meta, warnings)

    info = arxiv_meta(arxiv_id)
    if info is None and not meta:
        warnings.append("arXiv API lookup failed; continuing without title/authors")
    latest = (info or {}).get("latest_version")
    ver = version or latest or meta.get("version") or "v1"

    src = d / "src" / ver
    have = (src.exists() and any(src.iterdir())) or \
        (meta.get("version") == ver and meta.get("source_type") in ("html", "pdf"))
    if have and not args.force:
        summary = {"status": "already_stored", "paper_dir": str(d), "version": ver,
                   "source_type": meta.get("source_type")}
        if latest and latest != meta.get("version"):
            summary["newer_version_available"] = latest
            warnings.append(f"arXiv has {latest}; stored is {meta.get('version')}. "
                            f"Fetch it with: fetch_paper.py {arxiv_id}{latest}")
        summary["warnings"] = warnings
        return summary

    meta.update({
        "id": arxiv_id, "safe_id": sid, "version": ver,
        "url": f"https://arxiv.org/abs/{arxiv_id}{ver}", "fetched": common.today(),
    })
    if info:
        meta.update({k: info[k] for k in ("title", "authors", "abstract", "published")})
        meta["latest_version"] = latest
    meta.setdefault("versions", [])
    if ver not in meta["versions"]:
        meta["versions"].append(ver)
    meta.setdefault("related", [])

    # 1. LaTeX source
    status, data, _ = http_get(f"https://arxiv.org/e-print/{arxiv_id}{ver}")
    kind = None
    if status == 200 and data:
        if src.exists():
            shutil.rmtree(src)
        kind, w = unpack_source(data, src)
        warnings += w
        if kind == "pdf":
            (d / "paper.pdf").write_bytes(data)
            warnings.append("arXiv has no LaTeX source for this paper (PDF-only submission)")
    else:
        warnings.append(f"e-print download failed (HTTP {status})")

    summary = None
    if kind == "tex":
        fields, w = index_tex(d, src)
        warnings += w
        if fields:
            meta["source_type"] = "tex"
            meta["main_file"] = fields["main_file"]
            summary = fields

    # 2. HTML (LaTeXML)
    if summary is None:
        status, data, ctype = http_get(f"https://arxiv.org/html/{arxiv_id}{ver}")
        if status == 200 and data and sniff(data) == "html" and b"ltx_" in data:
            (d / "paper.html").write_bytes(data)
            txt = html_to_text(data)
            (d / "paper.txt").write_text(txt, encoding="utf-8")
            meta["source_type"] = "html"
            meta["main_file"] = "paper.txt"
            summary = {"lines": txt.count("\n") + 1, "chars": len(txt)}
            warnings.append("using arXiv HTML; math is kept as LaTeX alt-text, labels index unavailable")

    # 3. PDF
    if summary is None:
        pdf = d / "paper.pdf"
        if not pdf.exists():
            status, data, _ = http_get(f"https://arxiv.org/pdf/{arxiv_id}{ver}")
            if status == 200 and sniff(data) == "pdf":
                pdf.write_bytes(data)
        if pdf.exists():
            err = pdf_to_text(pdf, d / "paper.txt")
            meta["source_type"] = "pdf"
            meta["main_file"] = "paper.txt"
            if err:
                warnings.append(err)
                summary = {"lines": 0, "chars": 0}
            else:
                txt = (d / "paper.txt").read_text(encoding="utf-8", errors="replace")
                summary = {"lines": txt.count("\n") + 1, "chars": len(txt)}
            warnings.append("PDF text only: equations are degraded; check them against the PDF")
        else:
            common.write_meta(d, meta)
            return {"status": "failed", "paper_dir": str(d), "warnings": warnings}

    finish_meta(d, meta, warnings)
    return {"status": "fetched", "paper_dir": str(d), "id": arxiv_id, "version": ver,
            "title": meta.get("title", ""), "source_type": meta["source_type"],
            **summary, "digest_exists": (d / "digest.md").exists(), "warnings": warnings}


def finish_meta(d, meta, warnings):
    if (d / "digest.md").exists() and meta.get("digest_version") and \
            meta["digest_version"] != meta["version"]:
        warnings.append(f"digest.md was built from {meta['digest_version']}, source is now "
                        f"{meta['version']}: update the digest")
    common.write_meta(d, meta)


def reindex(d, meta, warnings):
    ver = meta.get("version", "local")
    src = d / "src" / ver
    if meta.get("source_type") == "tex" and src.exists():
        fields, w = index_tex(d, src)
        warnings += w
        if fields:
            meta["main_file"] = fields["main_file"]
        common.write_meta(d, meta)
        return {"status": "reindexed", "paper_dir": str(d), **(fields or {}), "warnings": warnings}
    if (d / "paper.html").exists():
        txt = html_to_text((d / "paper.html").read_bytes())
        (d / "paper.txt").write_text(txt, encoding="utf-8")
    elif (d / "paper.pdf").exists():
        err = pdf_to_text(d / "paper.pdf", d / "paper.txt")
        if err:
            warnings.append(err)
    return {"status": "reindexed", "paper_dir": str(d), "warnings": warnings}


def fetch_local(path_or_url, args):
    """Local file/dir, or a non-arXiv URL (usually a PDF)."""
    warnings = []
    is_url = re.match(r"^https?://", path_or_url) is not None
    if is_url:
        stem = Path(path_or_url.split("?")[0].rstrip("/")).stem or "paper"
    else:
        p = Path(path_or_url).expanduser().resolve()
        if not p.exists():
            sys.exit(f"error: {p} does not exist")
        stem = p.stem.replace(".tar", "")
    sid = common.safe_id(args.id or f"local_{stem}")
    d = common.store_dir() / sid
    d.mkdir(parents=True, exist_ok=True)
    meta = common.read_meta(d) if (d / "meta.json").exists() else {}
    if args.reindex:
        return reindex(d, meta, warnings)
    if meta and not args.force:
        return {"status": "already_stored", "paper_dir": str(d), "source_type": meta.get("source_type"),
                "warnings": ["use --force to replace the stored copy"]}
    meta.update({"id": sid, "safe_id": sid, "version": "local", "versions": ["local"],
                 "title": args.title or meta.get("title") or stem, "authors": meta.get("authors", []),
                 "url": path_or_url if is_url else str(p), "fetched": common.today()})
    meta.setdefault("related", [])
    src = d / "src" / "local"
    if src.exists():
        shutil.rmtree(src)

    if is_url:
        status, data, _ = http_get(path_or_url)
        if status != 200 or not data:
            return {"status": "failed", "paper_dir": str(d), "warnings": [f"HTTP {status} for {path_or_url}"]}
        kind = sniff(data)
    elif p.is_dir():
        shutil.copytree(p, src, symlinks=False, ignore=shutil.ignore_patterns(".git"))
        kind, data = "dir", b""
    else:
        data = p.read_bytes()
        kind = sniff(data)
        if p.suffix.lower() == ".tex":
            kind = "text"

    summary = None
    if kind == "pdf":
        (d / "paper.pdf").write_bytes(data)
    elif kind == "html":
        (d / "paper.html").write_bytes(data)
    elif kind in ("gzip", "tar", "text"):
        k, w = unpack_source(data, src)
        warnings += w
        if k == "pdf":
            (d / "paper.pdf").write_bytes(data)
    if src.exists():
        fields, w = index_tex(d, src)
        warnings += w
        if fields:
            meta["source_type"], meta["main_file"] = "tex", fields["main_file"]
            summary = fields
    if summary is None and (d / "paper.html").exists():
        txt = html_to_text((d / "paper.html").read_bytes())
        (d / "paper.txt").write_text(txt, encoding="utf-8")
        meta["source_type"], meta["main_file"] = "html", "paper.txt"
        summary = {"lines": txt.count("\n") + 1, "chars": len(txt)}
    if summary is None and (d / "paper.pdf").exists():
        err = pdf_to_text(d / "paper.pdf", d / "paper.txt")
        meta["source_type"], meta["main_file"] = "pdf", "paper.txt"
        if err:
            warnings.append(err)
        txt = (d / "paper.txt").read_text(encoding="utf-8", errors="replace") \
            if (d / "paper.txt").exists() else ""
        summary = {"lines": txt.count("\n") + 1 if txt else 0, "chars": len(txt)}
        warnings.append("PDF text only: equations are degraded; check them against the PDF")
    if summary is None:
        return {"status": "failed", "paper_dir": str(d), "warnings": warnings + ["unrecognised input"]}
    finish_meta(d, meta, warnings)
    return {"status": "fetched", "paper_dir": str(d), "id": sid, "version": "local",
            "title": meta["title"], "source_type": meta["source_type"], **summary,
            "digest_exists": (d / "digest.md").exists(), "warnings": warnings}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--id")
    ap.add_argument("--title")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--reindex", action="store_true")
    args = ap.parse_args(argv)

    parsed = common.parse_arxiv(args.source)
    local = Path(args.source).expanduser()
    if parsed and not local.exists():
        result = fetch_arxiv(parsed[0], parsed[1], args)
    else:
        result = fetch_local(args.source, args)
    result["store"] = str(common.store_dir())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
