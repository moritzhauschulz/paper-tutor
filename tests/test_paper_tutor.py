"""Offline tests. Run: python3 -I tests/test_paper_tutor.py"""

import gzip
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "paper-tutor" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import common  # noqa: E402
import fetch_paper  # noqa: E402
import refs  # noqa: E402
import texindex  # noqa: E402

MAIN_TEX = r"""\documentclass{article}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}[section]
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem{assumption}{Assumption}
\newcommand{\E}{\mathbb{E}}
\DeclareMathOperator{\KL}{KL}
\numberwithin{equation}{section}
\begin{document}
\section{Introduction}\label{sec:intro}
% \input{ignored}
We study $\E[X]$.
\input{sections/setup}
\section{Results}
\begin{theorem}[Main bound]\label{thm:main}
Under Assumption~\ref{ass:a}, $\KL(p\|q) \le 1$.
\end{theorem}
\begin{proof}
Combine \eqref{eq:one} and \eqref{eq:two}.
\end{proof}
\begin{figure}
\includegraphics[width=\linewidth]{figs/plot}
\caption{Loss curves, see \S\ref{sec:intro}.}\label{fig:loss}
\end{figure}
\appendix
\section{Proofs}
\begin{lemma}\label{lem:aux} A lemma. \end{lemma}
\end{document}
"""

SETUP_TEX = r"""\subsection{Setup}\label{sec:setup}
\begin{assumption}\label{ass:a} Bounded. \end{assumption}
\begin{equation}\label{eq:zero} a = b \end{equation}
\begin{align}
x &= 1 \label{eq:one}\\
y &= 2 \nonumber\\
z &= 3 \label{eq:two}
\end{align}
"""


def make_tree(root):
    (root / "sections").mkdir(parents=True)
    (root / "figs").mkdir()
    (root / "main.tex").write_text(MAIN_TEX)
    (root / "sections" / "setup.tex").write_text(SETUP_TEX)
    (root / "figs" / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "main.bbl").write_text("\\begin{thebibliography}{1}\n\\bibitem{ho20} J. Ho. DDPM. "
                                   "arXiv:2006.11239, 2020.\n\\end{thebibliography}\n")


def tar_bytes(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestIds(unittest.TestCase):
    def test_parse(self):
        cases = {
            "2312.15796": ("2312.15796", None),
            "2312.15796v2": ("2312.15796", "v2"),
            "arXiv:2312.15796": ("2312.15796", None),
            "https://arxiv.org/abs/2312.15796v2": ("2312.15796", "v2"),
            "https://arxiv.org/pdf/2312.15796v1.pdf": ("2312.15796", "v1"),
            "https://arxiv.org/html/2312.15796v3": ("2312.15796", "v3"),
            "math/0601001": ("math/0601001", None),
            "math.AG/0601001v2": ("math.AG/0601001", "v2"),
            "hep-th/9901001": ("hep-th/9901001", None),
            "math_0601001": ("math/0601001", None),
            "0704.0001": ("0704.0001", None),
        }
        for s, want in cases.items():
            self.assertEqual(common.parse_arxiv(s), want, s)
        self.assertIsNone(common.parse_arxiv("paper.pdf"))
        self.assertIsNone(common.parse_arxiv("https://openreview.net/pdf?id=abc"))

    def test_safe_id(self):
        self.assertEqual(common.safe_id("math/0601001"), "math_0601001")
        self.assertEqual(common.safe_id("../../etc"), "etc")


class TestExtraction(unittest.TestCase):
    def test_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as t:
            data = gzip.decompress(tar_bytes({"ok.tex": b"x", "../evil.tex": b"x",
                                              "/abs.tex": b"x", "a/../../b.tex": b"x"}))
            dest = Path(t) / "out"
            skipped = fetch_paper.safe_extract(data, dest)
            self.assertEqual(sorted(skipped), sorted(["../evil.tex", "/abs.tex", "a/../../b.tex"]))
            self.assertTrue((dest / "ok.tex").exists())
            self.assertFalse((Path(t) / "evil.tex").exists())

    def test_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as t:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tf:
                info = tarfile.TarInfo("link")
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                tf.addfile(info)
            skipped = fetch_paper.safe_extract(buf.getvalue(), Path(t) / "o")
            self.assertEqual(skipped, ["link"])

    def test_unpack_kinds(self):
        with tempfile.TemporaryDirectory() as t:
            kind, _ = fetch_paper.unpack_source(tar_bytes({"main.tex": b"\\documentclass{x}"}), Path(t) / "a")
            self.assertEqual(kind, "tex")
            kind, _ = fetch_paper.unpack_source(gzip.compress(b"\\documentclass{article}\n"), Path(t) / "b")
            self.assertEqual(kind, "tex")
            self.assertTrue((Path(t) / "b" / "main.tex").exists())
            kind, _ = fetch_paper.unpack_source(b"%PDF-1.5 ...", Path(t) / "c")
            self.assertEqual(kind, "pdf")


class TestTex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "src"
        make_tree(self.root)
        (self.root / "notmain.tex").write_text("\\section{x}")

    def tearDown(self):
        self.tmp.cleanup()

    def test_find_main_and_flatten(self):
        main = texindex.find_main(self.root)
        self.assertEqual(main.name, "main.tex")
        flat, unresolved = texindex.flatten(main, self.root)
        self.assertIn("\\subsection{Setup}", flat)
        self.assertEqual(unresolved, [])
        self.assertIn("% \\input{ignored}", flat)

    def test_index_numbers(self):
        flat, _ = texindex.flatten(self.root / "main.tex", self.root)
        idx = texindex.build_index(flat, src_root=self.root)
        labs = {lab["key"]: lab for lab in idx["labels"]}
        self.assertEqual(labs["sec:intro"]["display"], "§1")
        self.assertEqual(labs["sec:setup"]["display"], "§1.1")
        self.assertEqual(labs["ass:a"]["display"], "Assumption 1")
        self.assertEqual(labs["eq:zero"]["display"], "Eq. (1.1)")
        self.assertEqual(labs["eq:one"]["display"], "Eq. (1.2)")
        self.assertEqual(labs["eq:two"]["display"], "Eq. (1.3)")  # middle row is \nonumber
        self.assertEqual(labs["thm:main"]["display"], "Theorem 2.1")
        self.assertEqual(labs["thm:main"]["title"], "Main bound")
        self.assertEqual(labs["lem:aux"]["display"], "Lemma A.1")
        self.assertEqual(labs["fig:loss"]["display"], "Figure 1")
        self.assertEqual(idx["figures"][0]["images"], "figs/plot.png")
        self.assertIn("Loss curves", idx["figures"][0]["caption"])
        self.assertEqual(idx["proofs"][0]["of"], "thm:main")
        self.assertTrue(any("\\KL" in m for m in idx["macros"]))
        self.assertEqual([s["num"] for s in idx["sections"]], ["1", "1.1", "2", "A"])

    def test_refs_resolve(self):
        flat, _ = texindex.flatten(self.root / "main.tex", self.root)
        idx = texindex.build_index(flat, src_root=self.root)
        d = Path(self.tmp.name)
        texindex.write_indexes(d, idx)
        r = refs.load(d)
        self.assertEqual(refs.resolve("Thm 2.1", r)[0]["key"], "thm:main")
        self.assertEqual(refs.resolve("Theorem 2.1", r)[0]["key"], "thm:main")
        self.assertEqual(refs.resolve("Eq. (1.3)", r)[0]["key"], "eq:two")
        self.assertEqual(refs.resolve("(1.2)", r)[0]["key"], "eq:one")
        self.assertEqual(refs.resolve("§1.1", r)[0]["num"], "1.1")
        self.assertEqual(refs.resolve("Fig. 1", r)[0]["key"], "fig:loss")
        self.assertEqual(refs.section_of("Thm 2.1", r), "2")
        self.assertEqual(refs.section_of("§A", r), "A")


class TestEndToEnd(unittest.TestCase):
    """Local-directory fetch, logging and status through the real CLIs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "PAPER_TUTOR_HOME": str(Path(self.tmp.name) / "store")}
        self.src = Path(self.tmp.name) / "mypaper"
        make_tree(self.src)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, script, *args):
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *args],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r.stdout

    def test_flow(self):
        out = json.loads(self.run_cli("fetch_paper.py", str(self.src), "--title", "Test paper"))
        self.assertEqual(out["status"], "fetched")
        self.assertEqual(out["source_type"], "tex")
        self.assertEqual(out["n_results"], 3)
        pid = out["id"]
        d = Path(out["paper_dir"])
        self.assertTrue((d / "refs.bbl").exists())

        self.run_cli("log.py", "start", pid, "--mode", "explain", "--level", "6")
        self.run_cli("log.py", "event", pid, "--kind", "covered", "--where", "§1", "--text", "setup")
        self.run_cli("log.py", "event", pid, "--kind", "switch", "--text", "socratic", "--where", "Thm 2.1")
        self.run_cli("log.py", "event", pid, "--kind", "misconception", "--where", "Thm 2.1",
                     "--text", r"thinks $\KL$ is symmetric")
        q = self.run_cli("log.py", "quiz", pid, "--level", "6", "--where", "Eq. (1.2)", "--q", r"Why $x=1$?",
                         "--answer", "dunno", "--grade", "wrong", "--feedback", "see (1.2)")
        qid = q.split()[3].rstrip(":")
        self.run_cli("log.py", "quiz", pid, "--level", "6", "--where", "Eq. (1.2)", "--q", "retry",
                     "--answer", "because", "--grade", "correct", "--feedback", "ok", "--retry-of", qid)
        end = self.run_cli("log.py", "end", pid)
        self.assertIn("explain → socratic", end)
        self.assertIn("1/2 correct", end)

        recs = [json.loads(x) for x in (d / "quiz.jsonl").read_text().splitlines()]
        self.assertEqual(recs[0]["grade"], "misconception")
        self.assertIn(r"\KL", recs[0]["q"])

        status = self.run_cli("status.py", pid)
        self.assertIn("1 weak items", status)  # the retried item no longer counts
        self.assertIn("§2 Results", status)
        self.assertIn("next unstarted section: §A", status)
        self.assertIn("Digest: missing", status)

        show = self.run_cli("lookup.py", pid, "show", "Thm 2.1")
        self.assertIn("Main bound", show)
        proof = self.run_cli("lookup.py", pid, "proof", "thm:main")
        self.assertIn("Combine", proof)
        cite = self.run_cli("lookup.py", pid, "cite", "ho20")
        self.assertIn("2006.11239", cite)
        self.assertIn("Test paper", (Path(self.env["PAPER_TUTOR_HOME"]) / "index.md").read_text())

    def test_html_to_text_keeps_math(self):
        html = (b'<html><body><h2 class="ltx_title">Intro</h2><p class="ltx_p">Let '
                b'<math alttext="\\alpha_t" display="inline"><mi>a</mi></math> be.</p>'
                b'<script>x</script></body></html>')
        txt = fetch_paper.html_to_text(html)
        self.assertIn("$\\alpha_t$", txt)
        self.assertIn("## Intro", txt)
        self.assertNotIn("x\n", txt.replace("Let", ""))


if __name__ == "__main__":
    unittest.main(verbosity=1)
