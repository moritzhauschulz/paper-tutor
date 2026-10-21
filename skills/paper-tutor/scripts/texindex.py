"""LaTeX handling: find main file, flatten \\input trees, build label/section/figure indexes.

Numbers (sections, theorems, equations, figures) are recomputed from the source and are
approximate: custom counters, packages like cleveref/thmtools or \\setcounter can shift them.
"""

import bisect
import re
from pathlib import Path

from common import write_tsv

# ---------------------------------------------------------------- comments & braces


def strip_comments(text):
    """Blank out LaTeX comments, keeping offsets and line numbers intact."""
    out = []
    for line in text.split("\n"):
        i = 0
        cut = None
        while i < len(line):
            c = line[i]
            if c == "\\":
                i += 2
                continue
            if c == "%":
                cut = i
                break
            i += 1
        out.append(line if cut is None else line[:cut] + " " * (len(line) - cut))
    return "\n".join(out)


def read_group(text, i, open_ch="{", close_ch="}"):
    """text[i] must be open_ch. Return (content, index after the closing char)."""
    assert text[i] == open_ch
    depth = 0
    j = i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
        j += 1
    return text[i + 1:], len(text)


def skip_ws(text, i):
    while i < len(text) and text[i] in " \t\n":
        i += 1
    return i


def squash(s, limit=None):
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit - 1] + "…"
    return s


# ---------------------------------------------------------------- main file


def find_main(root):
    """Pick the .tex file with \\documentclass (or 2.09 \\documentstyle) and \\begin{document}.

    Falls back to the largest .tex file (plain TeX, e.g. harvmac papers); check is_latex() on it.
    """
    root = Path(root)
    cands, plain = [], []
    for p in sorted(root.rglob("*.tex")):
        try:
            t = strip_comments(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if is_latex(t):
            name = p.stem.lower()
            pref = 0 if name in ("main", "ms", "paper", "article") else 1
            depth = len(p.relative_to(root).parts)
            cands.append((pref, depth, -p.stat().st_size, p))
        else:
            plain.append((-p.stat().st_size, p))
    if cands:
        cands.sort(key=lambda c: c[:3])
        return cands[0][3]
    if plain:
        return sorted(plain)[0][1]
    return None


def is_latex(text):
    return bool(re.search(r"\\document(?:class|style)", text) and re.search(r"\\begin\s*\{document\}", text))


# ---------------------------------------------------------------- flatten

INPUT_RE = re.compile(
    r"\\(?:(input|include|subfile)\s*\{([^}]+)\}|(input)\s+([^\s{}\\]+)"
    r"|(import|subimport|inputfrom|subinputfrom)\s*\{([^}]*)\}\s*\{([^}]+)\})"
)


def _resolve(name, bases):
    name = name.strip().strip('"')
    for base in bases:
        for cand in (base / name, base / (name + ".tex")):
            if cand.is_file():
                return cand
    return None


def flatten(main, root, max_depth=20):
    """Inline \\input/\\include/\\subfile/\\import. Returns (text, unresolved_names)."""
    main, root = Path(main), Path(root).resolve()
    unresolved = []

    def expand(path, depth, stack):
        raw = path.read_text(encoding="utf-8", errors="replace")
        if depth > max_depth:
            return raw
        nocomment = strip_comments(raw)
        out, last = [], 0
        for m in INPUT_RE.finditer(nocomment):
            if m.group(1) or m.group(3):
                name = m.group(2) or m.group(4)
                bases = [root, path.parent]
            else:
                sub = m.group(6).strip()
                name = m.group(7)
                bases = [path.parent / sub, root / sub] if m.group(5).startswith("sub") \
                    else [root / sub, path.parent / sub]
            target = _resolve(name, bases)
            if target is not None:
                try:
                    target.resolve().relative_to(root)
                except ValueError:
                    target = None  # never read outside the source tree
            out.append(raw[last:m.start()])
            if target is None or target.resolve() in stack:
                unresolved.append(name)
                out.append(raw[m.start():m.end()])
            else:
                rel = target.resolve().relative_to(root)
                body = expand(target, depth + 1, stack | {target.resolve()})
                out.append(f"% >>> paper-tutor: begin {rel}\n{body}\n% <<< paper-tutor: end {rel}\n")
            last = m.end()
        out.append(raw[last:])
        return "".join(out)

    return expand(main, 0, {main.resolve()}), unresolved


# ---------------------------------------------------------------- macros

MACRO_CMDS = r"newcommand|renewcommand|providecommand|DeclareMathOperator|DeclareRobustCommand|" \
             r"newtheorem|def|let|newenvironment|declaretheorem|DeclarePairedDelimiter"
MACRO_RE = re.compile(rf"\\({MACRO_CMDS})\*?(?![A-Za-z])")


def extract_macros(preamble):
    """Return the full text of each macro/theorem definition in the preamble."""
    text = strip_comments(preamble)
    defs = []
    for m in MACRO_RE.finditer(text):
        i = m.end()
        # consume the definition: command name + up to 4 bracket/brace groups
        groups = 0
        while i < len(text) and groups < 6:
            i = skip_ws(text, i)
            if i >= len(text):
                break
            c = text[i]
            if c == "{":
                _, i = read_group(text, i)
                groups += 1
            elif c == "[":
                _, i = read_group(text, i, "[", "]")
            elif c == "\\" and groups == 0:
                n = re.match(r"\\[A-Za-z@]+|\\.", text[i:])
                i += n.end()
                groups += 1
            elif m.group(1) in ("def",) and c == "#":
                while i < len(text) and text[i] not in "{\n":
                    i += 1
            else:
                break
        defs.append(squash(text[m.start():i]))
    return defs


# ---------------------------------------------------------------- index

SECTION_LEVELS = ["part", "chapter", "section", "subsection", "subsubsection", "paragraph"]
EQ_SINGLE = {"equation", "multline", "eqnarray_single"}
EQ_MULTI = {"align", "gather", "flalign", "alignat", "eqnarray", "xalignat"}
FLOATS = {"figure": "Figure", "figure*": "Figure", "table": "Table", "table*": "Table"}
LISTS = {"enumerate", "itemize", "description"}
DEFAULT_THMS = {
    "theorem": "Theorem", "thm": "Theorem", "lemma": "Lemma", "lem": "Lemma",
    "proposition": "Proposition", "prop": "Proposition", "corollary": "Corollary",
    "cor": "Corollary", "definition": "Definition", "defn": "Definition", "dfn": "Definition",
    "assumption": "Assumption", "ass": "Assumption", "remark": "Remark", "rem": "Remark",
    "example": "Example", "conjecture": "Conjecture", "claim": "Claim", "condition": "Condition",
    "hypothesis": "Hypothesis", "fact": "Fact", "problem": "Problem", "question": "Question",
}

TOKEN_RE = re.compile(
    r"\\(?:"
    r"(?P<be>begin|end)\s*\{(?P<env>[^}]*)\}"
    r"|(?P<sec>part|chapter|section|subsection|subsubsection|paragraph)(?P<star>\*?)\s*(?=[\[{])"
    r"|label\s*\{(?P<label>[^}]*)\}"
    r"|(?P<appendix>appendix)(?![A-Za-z])"
    r"|(?:counterwithin|numberwithin)\*?\s*\{(?P<cw>[^}]*)\}\s*\{(?P<cwin>[^}]*)\}"
    r"|(?P<caption>caption)\s*(?=[\[{])"
    r"|includegraphics\s*(?:\[[^\]]*\])?\s*\{(?P<img>[^}]*)\}"
    r"|(?P<nonum>nonumber|notag)(?![A-Za-z])"
    r"|(?P<item>item)(?![A-Za-z])"
    r"|(?P<row>\\)"
    r")"
)


def parse_theorem_defs(text):
    """Map env -> {title, counter, within, numbered} from \\newtheorem / \\declaretheorem."""
    thms = {}
    for m in re.finditer(r"\\newtheorem(\*?)\s*\{([^}]+)\}\s*(?:\[([^\]]+)\])?\s*\{([^}]*)\}"
                         r"\s*(?:\[([^\]]+)\])?", text):
        star, env, shared, title, within = m.groups()
        thms[env.strip()] = {"title": squash(title), "counter": (shared or env).strip(),
                             "within": (within or "").strip(), "numbered": not star}
    for m in re.finditer(r"\\declaretheorem\s*(?:\[([^\]]*)\])?\s*\{([^}]+)\}", text):
        opts, env = m.group(1) or "", m.group(2).strip()
        kv = dict(re.findall(r"(\w+)\s*=\s*([^,\]]+)", opts))
        thms[env] = {"title": kv.get("name", env.capitalize()).strip(),
                     "counter": kv.get("sibling", kv.get("sharenumber", env)).strip(),
                     "within": kv.get("numberwithin", kv.get("parent", "")).strip(),
                     "numbered": kv.get("numbered", "yes").strip() != "no"}
    # shared counters inherit the 'within' of the counter they share
    for env, d in thms.items():
        if d["counter"] != env and d["counter"] in thms and not d["within"]:
            d["within"] = thms[d["counter"]]["within"]
    return thms


def _counter_name(c):
    return {"figure": "Figure", "table": "Table"}.get(c, c)


def _alpha(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def build_index(flat_text, src_root=None, extra_defs=""):
    """Scan flattened LaTeX. Returns dict with sections, labels, figures, proofs, macros."""
    text = strip_comments(flat_text)
    nl = [i for i, c in enumerate(text) if c == "\n"]

    def line_of(pos):
        return bisect.bisect_right(nl, pos - 1) + 1

    doc = re.search(r"\\begin\s*\{document\}", text)
    preamble = text[:doc.start()] if doc else ""
    thms = {k: {"title": v, "counter": k, "within": "", "numbered": True}
            for k, v in DEFAULT_THMS.items()}
    defined = parse_theorem_defs(preamble + "\n" + strip_comments(extra_defs))
    thms.update(defined)
    within = {}  # counter -> section level it resets with (equation, Figure, Table)
    for m in re.finditer(r"\\(?:numberwithin|counterwithin)\*?\s*\{(\w+)\}\s*\{(\w+)\}", preamble):
        within[_counter_name(m.group(1))] = m.group(2)
    if re.search(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{(?:book|report|memoir|scrbook|scrreprt)\}",
                 preamble):
        top = "chapter"
    else:
        top = "section"

    sec_counter = {lvl: 0 for lvl in SECTION_LEVELS}
    in_appendix = False
    sections, labels, figures, proofs = [], [], [], []
    counters = {}  # theorem counters, figure/table, equation
    stack = []  # open envs: dicts
    cur_sec = {"num": "", "title": "(front matter)"}
    last_numbered = None  # target for a bare \label
    pending_eq_labels = []

    def sec_number(level):
        if level not in sec_counter:
            return ""
        idx = SECTION_LEVELS.index(level)
        parts = []
        start = SECTION_LEVELS.index(top) if level != "part" else 0
        for lvl in SECTION_LEVELS[start:idx + 1]:
            n = sec_counter[lvl]
            parts.append(_alpha(n) if (in_appendix and lvl == top) else str(n))
        return ".".join(parts)

    def within_prefix(within):
        if not within or within not in sec_counter:
            return ""
        return sec_number(within) + "."

    def step(counter, within):
        key = (counter, within_prefix(within))
        counters[key] = counters.get(key, 0) + 1
        return f"{within_prefix(within)}{counters[key]}"

    def eq_step():
        return step("equation", within.get("equation", ""))

    def innermost(pred):
        for env in reversed(stack):
            if pred(env):
                return env
        return None

    def finish_row(env, pos):
        nonlocal last_numbered
        if not env.get("nonum") and env["numbered"]:
            num = eq_step()
            rec = {"kind": "equation", "display": f"Eq. ({num})", "num": num}
            for lab in env["pending"]:
                lab.update(rec)
            last_numbered = rec
        else:
            for lab in env["pending"]:
                lab.update({"kind": "equation", "display": "Eq. (unnumbered)", "num": ""})
        env["pending"] = []
        env["nonum"] = False

    for m in TOKEN_RE.finditer(text):
        pos = m.start()
        if doc and pos < doc.end():
            continue
        ln = line_of(pos)

        if m.group("be"):
            env = m.group("env").strip()
            base = env.rstrip("*")
            if m.group("be") == "begin":
                rec = {"env": env, "start": ln, "pending": [], "nonum": False}
                if env in ("appendices", "subappendices") and not in_appendix:
                    in_appendix = True
                    sec_counter[top] = 0
                if base in EQ_SINGLE or base in EQ_MULTI:
                    rec.update(kind="eq", numbered=not env.endswith("*"), multi=base in EQ_MULTI,
                               row_start=m.end())
                elif env in thms:
                    d = thms[env]
                    num = step(d["counter"], d["within"]) if d["numbered"] else ""
                    after = text[m.end():m.end() + 400]
                    j = skip_ws(after, 0)
                    title = ""
                    if j < len(after) and after[j] == "[":
                        title, _ = read_group(after, j, "[", "]")
                    rec.update(kind="thm", display=f"{d['title']} {num}".strip(), num=num,
                               title=squash(title, 120), name=d["title"])
                    last_numbered = rec
                elif env in FLOATS:
                    num = step(FLOATS[env], within.get(FLOATS[env], ""))
                    rec.update(kind="float", display=f"{FLOATS[env]} {num}", num=num,
                               images=[], caption="")
                    last_numbered = rec
                elif base == "proof":
                    after = text[m.end():m.end() + 400]
                    j = skip_ws(after, 0)
                    title = ""
                    if j < len(after) and after[j] == "[":
                        title, _ = read_group(after, j, "[", "]")
                    rec.update(kind="proof", title=squash(title, 160))
                elif base in LISTS:
                    rec.update(kind="list")
                else:
                    rec.update(kind="other")
                stack.append(rec)
            else:
                # pop to the matching env (tolerate mismatches)
                idx = None
                for k in range(len(stack) - 1, -1, -1):
                    if stack[k]["env"] == env:
                        idx = k
                        break
                if idx is None:
                    continue
                for closed in reversed(stack[idx:]):
                    closed["end"] = ln
                    if closed["kind"] == "eq":
                        # the last row has no trailing \\; skip it if it is empty
                        if not (closed["multi"] and not text[closed["row_start"]:pos].strip()):
                            finish_row(closed, pos)
                    elif closed["kind"] == "thm":
                        for lab in labels:
                            if lab.get("_env") is closed:
                                lab["end"] = ln
                    elif closed["kind"] == "float":
                        figures.append({"label": closed.get("label", ""), "display": closed["display"],
                                        "start": closed["start"], "end": ln,
                                        "images": ";".join(closed["images"]),
                                        "caption": squash(closed["caption"], 400)})
                        for lab in labels:
                            if lab.get("_env") is closed:
                                lab["end"] = ln
                    elif closed["kind"] == "proof":
                        proofs.append({"start": closed["start"], "end": ln, "title": closed["title"],
                                       "section": cur_sec["num"]})
                del stack[idx:]

        elif m.group("sec"):
            level, star = m.group("sec"), m.group("star")
            j = m.end()
            if j < len(text) and text[j] == "[":
                _, j = read_group(text, j, "[", "]")
                j = skip_ws(text, j)
            title = ""
            if j < len(text) and text[j] == "{":
                title, _ = read_group(text, j)
            num = ""
            if not star and level != "paragraph":
                sec_counter[level] += 1
                for lower in SECTION_LEVELS[SECTION_LEVELS.index(level) + 1:]:
                    sec_counter[lower] = 0
                num = sec_number(level)
            cur_sec = {"num": num, "title": squash(title, 160), "level": level, "start": ln}
            sections.append(cur_sec)
            last_numbered = {"kind": "section", "display": f"§{num}" if num else squash(title, 60),
                             "num": num, "start": ln}

        elif m.group("label") is not None:
            key = m.group("label").strip()
            lab = {"key": key, "line": ln, "section": cur_sec["num"], "sec_title": cur_sec["title"]}
            target = stack[-1] if stack else None
            eqenv = innermost(lambda e: e["kind"] == "eq")
            if eqenv is not None and (target is eqenv or target["kind"] == "other"):
                lab["start"] = eqenv["start"]
                lab["_eq"] = eqenv
                eqenv["pending"].append(lab)
            elif target is not None and target["kind"] == "list" and \
                    innermost(lambda e: e["kind"] in ("thm", "float")):
                outer = innermost(lambda e: e["kind"] in ("thm", "float"))
                lab.update(kind="item", display=f"item of {outer['display']}",
                           start=outer["start"], num=outer.get("num", ""))
            else:
                owner = innermost(lambda e: e["kind"] in ("thm", "float"))
                if owner is not None:
                    lab.update(kind="theorem" if owner["kind"] == "thm" else owner["display"].split()[0].lower(),
                               display=owner["display"], num=owner["num"], start=owner["start"],
                               title=owner.get("title", ""), _env=owner)
                    if owner["kind"] == "float":
                        owner["label"] = key
                elif last_numbered is not None:
                    lab.update(kind=last_numbered["kind"], display=last_numbered["display"],
                               num=last_numbered.get("num", ""), start=last_numbered.get("start", ln))
                else:
                    lab.update(kind="other", display="", num="", start=ln)
            labels.append(lab)

        elif m.group("appendix"):
            in_appendix = True
            sec_counter[top] = 0

        elif m.group("cw"):
            within[_counter_name(m.group("cw").strip())] = m.group("cwin").strip()

        elif m.group("caption"):
            fl = innermost(lambda e: e["kind"] == "float")
            j = m.end()
            if j < len(text) and text[j] == "[":
                _, j = read_group(text, j, "[", "]")
                j = skip_ws(text, j)
            if fl is not None and j < len(text) and text[j] == "{":
                cap, _ = read_group(text, j)
                fl["caption"] = fl["caption"] or cap

        elif m.group("img") is not None:
            fl = innermost(lambda e: e["kind"] == "float")
            if fl is not None:
                fl["images"].append(_resolve_image(m.group("img").strip(), src_root))

        elif m.group("nonum"):
            eqenv = innermost(lambda e: e["kind"] == "eq")
            if eqenv is not None:
                eqenv["nonum"] = True

        elif m.group("row"):
            if stack and stack[-1]["kind"] == "eq" and stack[-1]["multi"]:
                finish_row(stack[-1], pos)
                stack[-1]["row_start"] = m.end()

    # section end lines
    total = line_of(len(text))
    for i, s in enumerate(sections):
        lvl = SECTION_LEVELS.index(s["level"])
        end = total
        for t in sections[i + 1:]:
            if SECTION_LEVELS.index(t["level"]) <= lvl:
                end = t["start"] - 1
                break
        s["end"] = end
    # theorem/float labels missing an end, equations: end = env end
    for lab in labels:
        if "_eq" in lab:
            lab["end"] = lab["_eq"].get("end", lab["line"])
        lab.setdefault("end", lab.get("start", lab["line"]))
        if lab.get("kind") == "section":
            for s in sections:
                if s["start"] == lab.get("start"):
                    lab["end"] = s["end"]
    # proofs: which result do they belong to?
    thm_labels = [lab for lab in labels if lab.get("kind") == "theorem"]
    for p in proofs:
        ref = re.search(r"\\(?:ref|cref|Cref|autoref)\s*\{([^},]+)", p["title"])
        p["of"] = ref.group(1) if ref else ""
        if not p["of"]:
            prev = [lab for lab in thm_labels if lab["end"] <= p["start"] <= lab["end"] + 6]
            if prev:
                p["of"] = prev[-1]["key"]

    return {
        "sections": sections,
        "labels": labels,
        "figures": figures,
        "proofs": proofs,
        "macros": extract_macros(preamble + "\n" + extra_defs),
        "theorem_envs": {k: v for k, v in defined.items()},
    }


IMG_EXTS = ["", ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".PNG", ".JPG"]


def _resolve_image(name, src_root):
    if not src_root:
        return name
    root = Path(src_root)
    for ext in IMG_EXTS:
        cand = root / (name + ext)
        if cand.is_file():
            return str(cand.relative_to(root))
    hits = [p for p in root.rglob(Path(name).name + "*") if p.suffix.lower() in
            (".pdf", ".png", ".jpg", ".jpeg", ".eps")]
    return str(hits[0].relative_to(root)) if hits else name


def write_indexes(paper_dir, idx):
    d = Path(paper_dir)
    write_tsv(d / "sections.tsv", ["num", "level", "title", "start", "end"], idx["sections"])
    write_tsv(d / "labels.tsv", ["key", "kind", "display", "num", "title", "section", "line", "start", "end"],
              [{k: v for k, v in lab.items() if not k.startswith("_")} for lab in idx["labels"]])
    write_tsv(d / "figures.tsv", ["display", "label", "images", "caption", "start", "end"], idx["figures"])
    write_tsv(d / "proofs.tsv", ["of", "title", "section", "start", "end"], idx["proofs"])
    header = ("% Macro and theorem definitions collected by paper-tutor from the preamble\n"
              "% (and local .sty/.cls files). Use these to read custom notation.\n")
    (d / "macros.tex").write_text(header + "\n".join(idx["macros"]) + "\n", encoding="utf-8")
