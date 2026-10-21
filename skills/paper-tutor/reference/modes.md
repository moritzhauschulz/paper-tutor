# Modes in detail

| Mode | Who does the thinking | Goal | Graded? |
|---|---|---|---|
| explain | you explain, user asks | cover material efficiently | no |
| explain+quiz | you explain a chunk, then user answers | learn and check as you go | yes |
| socratic | user, guided by your questions | build understanding themselves | no (misconceptions logged) |
| quiz | user, unaided | test and reinforce | yes |

Chunk size scales with level: about a section at L1–3, a subsection or a single result at L4–6,
a single result or derivation step at L7+.

## explain

- Order: follow the paper's logic, not necessarily its section order (setup → main idea →
  method → results → limitations), unless the user asked for a specific part.
- Each chunk: what it says, why it matters, where it is (cite), and one sentence on how it connects
  to the previous chunk.
- End each chunk with a short offer: continue / deeper on X / switch to questions. Do not ask
  test questions in this mode.
- Log `covered` after each chunk, and `open` when the user raises something you could not resolve.

## explain+quiz (interleaved)

1. Explain one chunk as in *explain*.
2. Ask one question on exactly that chunk, matched to the level. (A second one only if the chunk was
   large or the first answer was a lucky guess.)
3. Grade (rubric below), give feedback with the location in the paper, log with
   `--mode explain+quiz`.
4. If the answer was correct, move on. If it was partial or wrong, re-explain the specific misunderstanding from a
   different angle (example, picture, special case, contrast), then ask one retry (a rephrased
   or simpler variant; log it with `--retry-of <qid of the first attempt>`). Move on after the retry
   either way; the miss stays in the log for re-quiz.

## socratic

The questions are the teaching. You never state the target insight.

1. **Pick a target** from the digest: one result, step, assumption or design choice, sized to the
   level. Tell the user the topic, not the answer: "Let's work out why the weighting in Eq. 7 is the
   right one."
2. **Start where the user is.** First question: what do they already think or know about it?
3. **Each turn: one question**, the smallest step forward from the user's last answer. Good forms:
   - "What would happen if …?" (special or limiting case)
   - "How does that square with …?" (surface a contradiction in their own reasoning)
   - "What do you need to know to decide that?"
   - "Can you check that against Eq. (n)?" (send them to the source)
4. **Do not correct directly.** When the user says something wrong, ask a question that lets them
   see the problem. Log it as a `misconception` (it becomes a re-quiz item).
5. **Hints**: only after the user is stuck twice on the same step. Give the smallest useful hint
   and log `hint`. After four stuck turns on one step, offer a choice: one more hint, or you explain
   this step (that one step only, then you continue with questions).
6. **Finish** when the user states the insight in their own words. Confirm it, sharpen it if needed,
   connect it to the paper's location, and log `insight` with their formulation.
7. Then offer the next target, a switch to quiz to consolidate, or a break.

Socratic sessions are slower; one or two targets per session is normal. Don't hurry the user toward the answer.

## quiz

No teaching before the answer. Formats:

- **questions** (default): one question, wait, grade, feedback, log, next. Mix question types
  according to the level table. Draw from sections the user has covered unless asked otherwise.
  If the answer is wrong, you may offer a hint and one follow-up (`--followup`), or move on.
- **teach-back** (`quiz teach-back`): name a result or concept; the user explains it in their own
  words at the current level. Grade it on (a) accuracy, (b) completeness, including the
  assumptions it needs, and (c) precision appropriate to the level. Feedback lists what was
  missing or wrong, with locations. Log with `--format teach-back`.
- **re-quiz**: take the weak items from `status.py` (each has a qid). Ask a rephrased variant, not
  the verbatim question, so the user cannot answer from memory. Log with `--retry-of <qid>`. For
  misconception items, ask a question that would expose the misconception if it is still there.

## Grading rubric (all graded modes)

- **correct**: the core idea is right and there are no substantive errors. Minor slips in notation
  do not count against it.
- **partial**: right direction but a key step, condition or assumption is missing, or there is a
  real but local error.
- **wrong**: the core idea is wrong or missing, including "I don't know".

Be honest, not generous: grades drive what gets re-quizzed. Feedback is 1–4 sentences, names what
was right, what was missing, and the paper location, and gives the correct answer when the grade
is not *correct*.
