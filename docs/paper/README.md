# Veritas paper

This directory contains the LaTeX source of the Veritas paper.

- [`veritas.tex`](veritas.tex) — main paper (~8 printed pages).
- [`Makefile`](Makefile) — `make` produces `veritas.pdf`.

## Build

```bash
cd docs/paper
make                # requires latexmk + pdflatex (any TeX Live / MacTeX)
# or
make simple         # pdflatex-only fallback, runs twice for cross-refs
```

Install TeX if you don't have it:

- macOS: `brew install --cask mactex-no-gui` (or full MacTeX)
- Linux: `apt install texlive-full` or `dnf install texlive-scheme-full`
- Windows: [MiKTeX](https://miktex.org/) or [TeX Live](https://tug.org/texlive/)

## Cleanup

```bash
make clean          # removes *.aux, *.log, *.bbl, etc. — keeps the PDF
make distclean      # also removes veritas.pdf
```

## Companion markdown

A prose version of the same material (no figures, no theorem environments)
lives at [`docs/POSITION_PAPER.md`](../POSITION_PAPER.md) and renders
inline on GitHub.
