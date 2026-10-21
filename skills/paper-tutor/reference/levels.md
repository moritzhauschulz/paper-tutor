# Depth levels

One scale for every mode. The level sets how much mathematics you show, how much you assume, and how
hard questions are. Keep it stable within a session unless the user changes it; if answers show
the level is clearly wrong, suggest a change.

| Level | Explanations | Questions (quiz, explain+quiz) | Socratic targets |
|---|---|---|---|
| **1–2** | Abstract-level intuition. No equations. Analogies allowed. What problem, why it matters, what is new. | Conceptual recall: "What problem does the paper address?" "What is the main claim?" | "Why is the naive approach not good enough?" |
| **3–4** | Problem setup and main idea. Key equation(s) only, each explained term by term. No proofs. | "What does each term in Eq. (7) represent?" "Which quantity does the method optimise?" | "What would you need to know to solve this problem?" Leading the user to the key idea. |
| **5–6** | Full method with key equations. Assumptions stated. Results interpreted (what the numbers/plots actually show). | Derivation steps and interpretation: "Why does the loss reduce to Eq. (9) under Assumption 2?" "What does Fig. 3 show and not show?" | The user derives a step of the method, or explains why an assumption is needed. |
| **7–8** | Derivations of the main results, proof sketches, the role of each assumption, where the argument is delicate. | "Sketch why Thm 2 holds." "Which assumption fails if …?" "What breaks if the weighting λ(t) is constant?" | The user reconstructs a proof idea, or finds which assumption a step relies on. |
| **9–10** | Line-by-line proofs. Gaps and unstated assumptions flagged. Comparison to related work and alternative proof routes. | "Prove Lemma 4." "Find the gap in step 3 of the proof of Thm 2." "Generalise Prop. 1 to the non-stationary case." "Give a counterexample when Assumption 1 is dropped." | The user finds the gap, proposes an alternative route, or generalises a result. |

Guidelines:
- At levels ≥ 7, read the exact statement and proof (`lookup.py … show/proof`) before explaining
  or grading. Do not reconstruct proofs from memory.
- At levels ≤ 4, avoid symbols that were not introduced; define every symbol you use.
- Experimental papers with no theorems: high levels mean scrutinising the experimental design,
  baselines, ablations, statistical support for claims, and what is claimed vs. actually shown.
