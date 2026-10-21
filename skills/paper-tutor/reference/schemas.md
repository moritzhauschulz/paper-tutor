# Store layout and file formats

```
<store>/                       # $PAPER_TUTOR_HOME, else ~/.config/paper-tutor/config.json "store", else ~/papers
  index.md                     # all papers, rebuilt by log.py
  <safe-id>/                   # math/0601001 -> math_0601001; local files -> local_<name>
    meta.json
    src/<version>/             # extracted source tree, as shipped (comments kept)
    main.flat.tex              # \input-resolved single file (LaTeX papers)
    macros.tex                 # \newcommand/\def/\DeclareMathOperator/\newtheorem from preamble
    sections.tsv labels.tsv figures.tsv proofs.tsv   # indexes with line numbers into main.flat.tex
    refs.bbl | refs.bib        # bibliography, if shipped
    paper.html, paper.txt      # HTML fallback (txt keeps math as $alttext$)
    paper.pdf, paper.txt       # PDF fallback (pdftotext -layout)
    cache/                     # converted figure PNGs
    digest.md                  # written by Claude (reference/digest-template.md)
    sessions.md                # append-only, via log.py
    quiz.jsonl                 # append-only, via log.py
    notes.md                   # append-only, user's own notes, via log.py
```

Only `log.py` writes the three append-only files. Never edit or rewrite them by hand.

## meta.json

```json
{"id": "2312.15796", "safe_id": "2312.15796", "version": "v2", "versions": ["v2"],
 "latest_version": "v2", "title": "...", "authors": ["..."], "abstract": "...",
 "published": "2023-12-25", "source_type": "tex", "main_file": "main.tex",
 "fetched": "2026-10-21", "url": "https://arxiv.org/abs/2312.15796v2",
 "digest_version": "v2", "digest_date": "2026-10-21",
 "last_session": {"date": "2026-10-21", "mode": "explain+quiz", "level": 6},
 "related": [{"id": "2206.00364", "why": "EDM preconditioning used in §D.3"}]}
```

## sessions.md

```
## 2026-10-21 14:03 — mode: explain+quiz, level 6
- Covered [§2]: forward SDE and score-matching objective
- Switched to socratic [Eq. (7)]
- Misconception [Eq. (7)]: thought λ(t) is a free hyperparameter with no effect on the optimum
- Hint given [Eq. (7)]: what happens to the minimiser if λ(t) > 0 everywhere?
- Insight [Eq. (7)]: λ only reweights; the minimiser is the true score for any positive λ
- Level → 7
- Open question [Thm 1]: is the Lipschitz assumption needed for the discrete sampler?
- Next: §4 proofs
- Ended (modes: explain+quiz → socratic; quiz: 2/3 correct)
```

## quiz.jsonl

One JSON object per line:

```json
{"ts": "2026-10-21T14:10:00", "mode": "explain+quiz", "format": "questions", "level": 6,
 "where": "Eq. (7)", "q": "...", "user_answer": "...", "grade": "partial",
 "feedback": "...", "followup": false, "qid": "3fa2b1c9"}
```

- `grade`: `correct | partial | wrong`, or `misconception` (created by `log.py event --kind
  misconception`; a re-quiz candidate).
- `retry_of`: qid of an earlier item this one re-asks. An item stops being weak once its latest
  retry is `correct`.
