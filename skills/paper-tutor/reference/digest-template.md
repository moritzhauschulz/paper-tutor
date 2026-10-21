# digest.md template

The digest is what you read at the start of every later session instead of the full source, so it
has to be accurate, complete enough to tutor from, and full of locations. Write it after one careful
full read. Target roughly 1500–4000 words depending on the paper; longer is fine for dense theory.

Use exactly these headings:

```markdown
# <Title> — digest
<id> <version> · source: <tex|html|pdf> · built <YYYY-MM-DD>

## 1. Summary
One paragraph: problem, approach, main results, why it matters. Then one line: "Main claim:" in a
single sentence.

## 2. Prerequisites
Background the paper assumes, each with a one-line refresher and how it is used here.
(e.g. "Itô's lemma — used to derive the reverse SDE in §3.1".)

## 3. Notation
| Symbol | Meaning | Defined at |
Include every symbol used in main results. Translate custom macros from macros.tex
(e.g. `\E` → \mathbb{E}, `\ourmodel` → "GenCast"), listing macro and meaning.

## 4. Assumptions
Numbered A1, A2, … with the paper's own label if it has one ("A1 = Assumption 2.1"), location, and
one line on what it rules out. Flag **implicit** assumptions the paper relies on but does not state,
marked "(implicit)".

## 5. Main results
For each theorem/proposition/key equation/claim:
- **Name and location** (Thm 3.1, `thm:main`, §3.2)
- Statement (precise, in LaTeX)
- Depends on: assumptions (A-numbers) and lemmas
- Meaning in one sentence

## 6. Proof skeletons
For each main result: the key steps in order, with locations (appendix sections, equations).
Flag gaps, hand-waving, or steps that rely on unstated results as **[gap]**.

## 7. Method / algorithm
The method as steps or pseudocode, with the equations it uses. Hyperparameters and design
choices that matter.

## 8. Experiments
What is actually shown (datasets, baselines, metrics, key numbers, figure/table locations) vs. what
is claimed in the abstract/intro. Note missing ablations, baselines, or error bars.

## 9. Dependency graph
Text graph of how results depend on each other and on assumptions, e.g.
`A1, A2 → Lemma 2 → Thm 1 → Cor 1`;  `Lemma 3 (+A3) → Thm 2`.

## 10. Suspected inconsistencies or errors
Notation clashes, sign errors, unjustified steps, claims not supported by the experiments,
differences between versions. Say how confident you are in each. "None found" is a valid entry.

## 11. Section map
§ number → title → one line on content → line range in the source (from `lookup.py list section`).
This lets later sessions jump straight into the source.
```

Rules:
- Every item cites a location. Prefer the paper's printed numbers; add the label key in backticks
  when one exists.
- Write statements in LaTeX as in the paper; don't paraphrase a theorem when the exact statement
  matters.
- Do not pad. If the paper has no theorems, sections 5–6 cover the key equations/claims and the
  derivation of the objective instead.
