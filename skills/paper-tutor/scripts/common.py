"""Shared helpers for paper-tutor scripts: store location, paper ids, safe appends."""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "paper-tutor" / "config.json"
DEFAULT_STORE = Path.home() / "papers"
ICLOUD_SUGGESTION = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/papers"

NEW_ID = r"\d{4}\.\d{4,5}"
OLD_ID = r"[a-z][a-z\-]*(?:\.[A-Z]{2})?/\d{7}"
ARXIV_ID_RE = re.compile(rf"^(?P<id>{NEW_ID}|{OLD_ID})(?P<ver>v\d+)?$")
ARXIV_URL_RE = re.compile(
    rf"arxiv\.org/(?:abs|pdf|html|e-print|src)/(?P<id>{NEW_ID}|{OLD_ID})(?P<ver>v\d+)?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- store

def store_info():
    """Return (store_path, how_it_was_chosen)."""
    env = os.environ.get("PAPER_TUTOR_HOME")
    if env:
        return Path(env).expanduser(), "env:PAPER_TUTOR_HOME"
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
            if cfg.get("store"):
                return Path(cfg["store"]).expanduser(), f"config:{CONFIG_PATH}"
        except (OSError, ValueError):
            pass
    return DEFAULT_STORE, "default"


def store_dir(create=True):
    path, _ = store_info()
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def set_store(path):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
        except ValueError:
            cfg = {}
    cfg["store"] = str(Path(path).expanduser())
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    Path(cfg["store"]).mkdir(parents=True, exist_ok=True)
    return cfg["store"]


# ---------------------------------------------------------------- ids

def safe_id(paper_id):
    """math/0601001 -> math_0601001; anything else unsafe -> '_'."""
    s = paper_id.strip().replace("/", "_")
    s = re.sub(r"[^A-Za-z0-9._\-]", "_", s)
    return s.strip("._") or "paper"


def parse_arxiv(s):
    """Return (id, version|None) if s is an arXiv id or URL, else None."""
    s = s.strip()
    m = ARXIV_URL_RE.search(s)
    if m:
        return m.group("id"), m.group("ver")
    s2 = re.sub(r"^arxiv:", "", s, flags=re.IGNORECASE)
    s2 = re.sub(r"\.pdf$", "", s2)
    m = ARXIV_ID_RE.match(s2)
    if m:
        return m.group("id"), m.group("ver")
    # sanitized old-style id, e.g. math_0601001
    m = re.match(r"^([a-z][a-z\-]*(?:\.[A-Z]{2})?)_(\d{7})(v\d+)?$", s2)
    if m:
        return f"{m.group(1)}/{m.group(2)}", m.group(3)
    return None


def paper_dir(ref, must_exist=True):
    """Resolve a paper reference (id, URL, sanitized id or directory) to its directory."""
    p = Path(ref).expanduser()
    if p.is_dir() and (p / "meta.json").exists():
        return p
    parsed = parse_arxiv(ref)
    key = safe_id(parsed[0]) if parsed else safe_id(ref)
    d = store_dir() / key
    if must_exist and not (d / "meta.json").exists():
        sys.exit(f"error: no paper '{ref}' in store {store_dir()} (expected {d}/meta.json)")
    return d


# ---------------------------------------------------------------- files

def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def today():
    return datetime.now().strftime("%Y-%m-%d")


def append_text(path, text):
    """Append in a single write and fsync, so a crash or sync never leaves half an entry."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def read_meta(d):
    return json.loads((Path(d) / "meta.json").read_text(encoding="utf-8"))


def write_meta(d, meta):
    path = Path(d) / "meta.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_tsv(path):
    path = Path(path)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    return [dict(zip(header, ln.split("\t"))) for ln in lines[1:] if ln.strip()]


def write_tsv(path, header, rows):
    def clean(v):
        return re.sub(r"[\t\r\n]+", " ", str(v if v is not None else ""))
    out = ["\t".join(header)]
    out += ["\t".join(clean(r.get(h, "")) for h in header) for r in rows]
    Path(path).write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- iCloud

def ensure_local(d, timeout=30):
    """Download iCloud-evicted files ('.name.icloud' placeholders). Returns warnings."""
    d = Path(d)
    if not d.exists():
        return []
    placeholders = [p for p in d.rglob(".*.icloud")]
    if not placeholders:
        return []
    if not shutil.which("brctl"):
        return [f"{len(placeholders)} file(s) are evicted to iCloud and brctl is unavailable; "
                f"open the folder in Finder to download them: {d}"]
    for ph in placeholders:
        real = ph.with_name(ph.name[1:-len(".icloud")])
        subprocess.run(["brctl", "download", str(real)], capture_output=True)
    deadline = time.time() + timeout
    while time.time() < deadline and any(p.exists() for p in placeholders):
        time.sleep(1)
    left = [p for p in placeholders if p.exists()]
    if left:
        return [f"{len(left)} iCloud file(s) still downloading in {d}; retry in a moment"]
    return []
