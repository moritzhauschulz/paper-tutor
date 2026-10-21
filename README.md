# paper-tutor

A [Claude Code](https://claude.com/claude-code) skill for studying research papers.

Give it an arXiv id. It fetches the **LaTeX source** (not the lossy PDF), reads the whole paper and
writes a careful digest. It then tutors you at a depth you choose from 1 to 10, in four modes.
Everything is kept per paper on your disk, so the next session picks up where the last one ended.

```
> /paper-tutor 2011.13456
  Got LaTeX v2 (122k chars, 45 sections, 93 labels). Reading… digest written.
  Score-Based Generative Modeling through SDEs — … Which mode and level?
> explain+quiz, level 6
```

## Modes

| Mode | What happens | Graded |
|---|---|---|
| **explain** | Claude explains, you ask questions | — |
| **explain+quiz** | Claude explains one chunk, then asks 1–2 questions on it. If you miss one, it re-explains from a different angle and asks again | ✓ |
| **socratic** | Claude explains nothing up front and never gives the answer. You work it out through a series of small questions | misconceptions logged |
| **quiz** | Questions only, no teaching. Also *teach-back* (you explain a result and it gets graded) and *re-quiz* of items you got wrong | ✓ |

You can switch modes at any point ("let me work this out myself", "just tell me", "test me",
`level 8`). Your position in the paper and your level stay the same.

**Levels:** 1–2 intuition only · 3–4 setup and key equation · 5–6 full method and assumptions ·
7–8 derivations and proof sketches · 9–10 line-by-line proofs, gaps, alternatives.

Every claim cites its location in the paper (§, Eq., Thm, label), so you can check it.

## What it does under the hood

- **Fetch:** arXiv e-print (tar.gz, a single gzipped .tex, LaTeX 2.09 and plain TeX all handled).
  Falls back to arXiv HTML, with math kept as LaTeX, then to PDF text. Local PDFs, .tex files,
  source folders and other PDF URLs (e.g. OpenReview) also work. Archives are extracted safely,
  rejecting path traversal and links.
- **Index:** flattens `\input` trees, collects macros, and recomputes section, theorem, equation and
  figure numbers, appendices included. You can say "show me Lemma 3.2" or "Eq. (7)" and get the exact
  source lines, the proof, the figure image or the bibliography entry.
- **Digest:** after the first full read Claude writes `digest.md`, covering summary, prerequisites,
  notation, assumptions (implicit ones flagged), main results, proof skeletons, method, experiments
  (what is claimed vs. what is shown), dependency graph, suspected errors, and a section map. Later
  sessions load the digest and open the source only when needed.
- **Memory:** `sessions.md`, `quiz.jsonl` and `notes.md` are append-only and written during the
  session, not at the end. Returning to a paper shows a recap: last topics, open questions, weak
  quiz items, and per-section coverage ("§3 explained but never quizzed").

## Install

Requires Claude Code and Python ≥ 3.10 (standard library only).

**As a plugin:**

```
/plugin marketplace add moritzhauschulz/paper-tutor
/plugin install paper-tutor@paper-tutor
```

**Or as a plain skill:**

```bash
git clone https://github.com/moritzhauschulz/paper-tutor.git
ln -s "$PWD/paper-tutor/skills/paper-tutor" ~/.claude/skills/paper-tutor
```

**Optional:** install `pdftotext` for PDF-only papers (`brew install poppler` or
`apt install poppler-utils`; `pip install pypdf` also works).

### Fewer permission prompts

Claude runs the bundled scripts and writes to your paper store. To skip approving each call, add
allow rules to `~/.claude/settings.json`. Adjust the paths to your install and store (`Edit(...)` covers
writes too):

```json
{
  "permissions": {
    "allow": [
      "Bash(python3 -I ~/.claude/skills/paper-tutor/scripts/*)",
      "Read(~/papers/**)",
      "Edit(~/papers/**)"
    ]
  }
}
```

## Where your data lives

Nothing is stored in this repo. Papers go to the first of these that is set:

1. `$PAPER_TUTOR_HOME`
2. `~/.config/paper-tutor/config.json` → `{"store": "/path"}`, which the skill asks about on first run
3. `~/papers`

On macOS, an iCloud Drive folder works well if you use several Macs. The scripts re-download
files that iCloud has offloaded, and write each log entry in a single append so a sync never
catches half an entry.

Layout: `<store>/<arxiv-id>/{meta.json, src/, main.flat.tex, digest.md, sessions.md, quiz.jsonl, notes.md, …}`.
See [`skills/paper-tutor/reference/schemas.md`](skills/paper-tutor/reference/schemas.md).

## Using it from your phone or the Claude app

The skill needs Claude Code's local shell and file system, so it does not run inside a regular
claude.ai chat. You can still drive a Claude Code session on your computer from the Claude desktop
or mobile app with **Remote Control** (`/remote-control`).

## Notes

- Paper content is treated as data, never as instructions to Claude.
- Recomputed numbers can differ from the PDF in papers with unusual counter setups. Lookups by label
  or title always work.
- arXiv is asked politely: a User-Agent header, 3 s between requests, and no repeat downloads of a
  version already stored.

## Development

```bash
python3 -I tests/test_paper_tutor.py
```

MIT licensed.
