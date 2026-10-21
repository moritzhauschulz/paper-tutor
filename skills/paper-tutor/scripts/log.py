#!/usr/bin/env python3
"""Append-only logging for paper-tutor. Every call writes immediately.

  log.py start   <paper> --mode MODE --level N
  log.py event   <paper> --kind KIND --text TEXT [--where "§3.2" | "Thm 2"]
  log.py quiz    <paper> --level N --q Q --answer A --grade G --feedback F
                         [--where REF] [--mode MODE] [--format questions|teach-back]
                         [--retry-of QID] [--followup]
  log.py note    <paper> --text TEXT [--where REF]
  log.py end     <paper>
  log.py digest  <paper>            # mark digest.md as built from the current source version
  log.py relate  <paper> <other-id> [--text WHY]
  log.py index                      # rebuild <store>/index.md
  log.py set-store PATH             # choose where papers are stored

KIND: covered | asked | open | next | switch | level | insight | misconception | hint
MODE: explain | explain+quiz | socratic | quiz | interrogate
GRADE: correct | partial | wrong
Text arguments are stored verbatim (LaTeX is fine); quote them for the shell.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

MODES = ["explain", "explain+quiz", "socratic", "quiz", "interrogate"]
KINDS = {"covered": "Covered", "asked": "Asked", "open": "Open question", "next": "Next", "switch": "Switched to",
         "level": "Level", "insight": "Insight", "misconception": "Misconception", "hint": "Hint given"}
GRADES = ["correct", "partial", "wrong"]


def _where(w):
    return f" [{w.strip()}]" if w and w.strip() else ""


def _sessions(d):
    return Path(d) / "sessions.md"


def cmd_start(a):
    d = common.paper_dir(a.paper)
    mode = _mode(a.mode)
    stamp = common.now_iso().replace("T", " ")[:16]
    common.append_text(_sessions(d), f"\n## {stamp} — mode: {mode}, level {a.level}\n")
    meta = common.read_meta(d)
    meta["last_session"] = {"date": common.today(), "mode": mode, "level": a.level}
    common.write_meta(d, meta)
    rebuild_index()
    print(f"session started: {mode}, level {a.level}")


def cmd_event(a):
    d = common.paper_dir(a.paper)
    kind = a.kind.lower()
    if kind not in KINDS:
        sys.exit(f"error: --kind must be one of {list(KINDS)}")
    text = a.text.strip()
    if kind == "switch":
        text = _mode(text.split()[0]) + (" " + " ".join(text.split()[1:]) if len(text.split()) > 1 else "")
        line = f"- Switched to {text}{_where(a.where)}\n"
    elif kind == "level":
        line = f"- Level → {text}{_where(a.where)}\n"
    else:
        line = f"- {KINDS[kind]}{_where(a.where)}: {text}\n"
    common.append_text(_sessions(d), line)
    if kind in ("switch", "level"):
        meta = common.read_meta(d)
        ls = meta.setdefault("last_session", {"date": common.today()})
        if kind == "switch":
            ls["mode"] = text.split()[0]
        else:
            ls["level"] = _int(text.split()[0], ls.get("level"))
        common.write_meta(d, meta)
    if kind == "misconception":
        # becomes a re-quiz candidate
        rec = {"ts": common.now_iso(), "mode": "socratic", "format": "misconception",
               "level": _current_level(d), "where": (a.where or "").strip(),
               "q": f"Revisit misconception: {text}", "user_answer": "", "grade": "misconception",
               "feedback": "", "followup": True}
        rec["qid"] = _qid(rec)
        common.append_text(Path(d) / "quiz.jsonl", json.dumps(rec, ensure_ascii=False) + "\n")
    print("logged: " + line.strip())


def cmd_quiz(a):
    d = common.paper_dir(a.paper)
    grade = a.grade.lower()
    if grade not in GRADES:
        sys.exit(f"error: --grade must be one of {GRADES}")
    rec = {"ts": common.now_iso(), "mode": _mode(a.mode) if a.mode else "quiz",
           "format": a.format or "questions", "level": a.level, "where": (a.where or "").strip(),
           "q": a.q, "user_answer": a.answer, "grade": grade, "feedback": a.feedback,
           "followup": bool(a.followup)}
    if a.retry_of:
        rec["retry_of"] = a.retry_of
    rec["qid"] = _qid(rec)
    common.append_text(Path(d) / "quiz.jsonl", json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"logged quiz item {rec['qid']}: {grade}")


def cmd_note(a):
    d = common.paper_dir(a.paper)
    stamp = common.now_iso().replace("T", " ")[:16]
    common.append_text(Path(d) / "notes.md", f"- {stamp}{_where(a.where)}: {a.text.strip()}\n")
    print("note saved")


def cmd_end(a):
    d = common.paper_dir(a.paper)
    block = _current_block(d)
    modes = []
    for ln in block.splitlines():
        m = re.match(r"## .* — mode: ([\w+]+)", ln) or re.match(r"- Switched to ([\w+]+)", ln)
        if m and (not modes or modes[-1] != m.group(1)):
            modes.append(m.group(1))
    start = re.search(r"## (\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})", block)
    asked = right = 0
    if start:
        t0 = start.group(1).replace(" ", "T")
        for rec in _quiz(d):
            if rec.get("ts", "") >= t0 and rec.get("grade") in GRADES:
                asked += 1
                right += rec["grade"] == "correct"
    line = f"- Ended (modes: {' → '.join(modes) or '?'}; quiz: {right}/{asked} correct)\n"
    common.append_text(_sessions(d), line)
    rebuild_index()
    print(line.strip())


def cmd_digest(a):
    d = common.paper_dir(a.paper)
    if not (Path(d) / "digest.md").exists():
        sys.exit("error: digest.md does not exist yet")
    meta = common.read_meta(d)
    meta["digest_version"] = meta.get("version")
    meta["digest_date"] = common.today()
    common.write_meta(d, meta)
    rebuild_index()
    print(f"digest marked as built from {meta['digest_version']}")


def cmd_relate(a):
    d = common.paper_dir(a.paper)
    meta = common.read_meta(d)
    rel = meta.setdefault("related", [])
    if not any(r.get("id") == a.other for r in rel):
        rel.append({"id": a.other, "why": a.text or ""})
    common.write_meta(d, meta)
    print(f"related: {a.other}")


def cmd_index(_a):
    print(rebuild_index())


def cmd_set_store(a):
    print(f"store set to {common.set_store(a.path)} (saved in {common.CONFIG_PATH})")


# ---------------------------------------------------------------- helpers

def rebuild_index():
    store = common.store_dir()
    rows = []
    for mp in sorted(store.glob("*/meta.json")):
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        ls = meta.get("last_session") or {}
        recs = _quiz(mp.parent)
        graded = [r for r in recs if r.get("grade") in GRADES]
        right = sum(r["grade"] == "correct" for r in graded)
        title = (meta.get("title") or "").replace("|", "/")
        rows.append((ls.get("date", ""), f"| {meta.get('id', mp.parent.name)} | {title[:80]} | "
                     f"{meta.get('source_type', '?')} | {ls.get('date', '—')} | "
                     f"{ls.get('mode', '—')} L{ls.get('level', '—')} | {right}/{len(graded)} |"))
    rows.sort(reverse=True)
    out = ["# Papers", "", "| id | title | source | last session | mode/level | quiz |",
           "|---|---|---|---|---|---|"] + [r for _, r in rows]
    (store / "index.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    return str(store / "index.md")


def _quiz(d):
    p = Path(d) / "quiz.jsonl"
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def _current_block(d):
    p = _sessions(d)
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8")
    i = text.rfind("\n## ")
    return text[i + 1:] if i >= 0 else text


def _current_level(d):
    lvl = None
    for ln in _current_block(d).splitlines():
        m = re.match(r"## .* level (\d+)", ln) or re.match(r"- Level → (\d+)", ln)
        if m:
            lvl = int(m.group(1))
    return lvl


def _mode(m):
    m = m.lower().replace(" ", "").replace("_", "+").replace("-", "+")
    aliases = {"explain+quiz": "explain+quiz", "interleaved": "explain+quiz", "explainquiz": "explain+quiz",
               "socratic": "socratic", "quiz": "quiz", "explain": "explain",
               "interrogate": "interrogate", "interrogation": "interrogate", "ask": "interrogate"}
    if m not in aliases:
        sys.exit(f"error: mode must be one of {MODES}")
    return aliases[m]


def _int(s, default):
    try:
        return int(s)
    except (TypeError, ValueError):
        return default


def _qid(rec):
    return hashlib.sha1(f"{rec['ts']}|{rec['q']}".encode()).hexdigest()[:8]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start"); p.add_argument("paper"); p.add_argument("--mode", required=True)
    p.add_argument("--level", type=int, required=True); p.set_defaults(fn=cmd_start)

    p = sub.add_parser("event"); p.add_argument("paper"); p.add_argument("--kind", required=True)
    p.add_argument("--text", required=True); p.add_argument("--where"); p.set_defaults(fn=cmd_event)

    p = sub.add_parser("quiz"); p.add_argument("paper"); p.add_argument("--level", type=int, required=True)
    p.add_argument("--q", required=True); p.add_argument("--answer", required=True)
    p.add_argument("--grade", required=True); p.add_argument("--feedback", required=True)
    p.add_argument("--where"); p.add_argument("--mode"); p.add_argument("--format")
    p.add_argument("--retry-of"); p.add_argument("--followup", action="store_true")
    p.set_defaults(fn=cmd_quiz)

    p = sub.add_parser("note"); p.add_argument("paper"); p.add_argument("--text", required=True)
    p.add_argument("--where"); p.set_defaults(fn=cmd_note)

    p = sub.add_parser("end"); p.add_argument("paper"); p.set_defaults(fn=cmd_end)
    p = sub.add_parser("digest"); p.add_argument("paper"); p.set_defaults(fn=cmd_digest)
    p = sub.add_parser("relate"); p.add_argument("paper"); p.add_argument("other")
    p.add_argument("--text"); p.set_defaults(fn=cmd_relate)
    p = sub.add_parser("index"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("set-store"); p.add_argument("path"); p.set_defaults(fn=cmd_set_store)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
