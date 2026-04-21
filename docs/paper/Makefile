# Makefile for building the Veritas paper.
#
#   make          — compile veritas.pdf via latexmk (recommended)
#   make simple   — compile with pdflatex directly (fallback)
#   make clean    — remove build artifacts (keeps veritas.pdf)
#   make distclean— remove build artifacts AND veritas.pdf

PAPER = veritas

.PHONY: all simple clean distclean

all: $(PAPER).pdf

$(PAPER).pdf: $(PAPER).tex
	@command -v latexmk >/dev/null 2>&1 && \
	  latexmk -pdf -interaction=nonstopmode -halt-on-error $(PAPER).tex || \
	  { echo "latexmk not found — try 'make simple' (requires pdflatex)"; exit 1; }

simple: $(PAPER).tex
	pdflatex -interaction=nonstopmode -halt-on-error $(PAPER).tex
	pdflatex -interaction=nonstopmode -halt-on-error $(PAPER).tex

clean:
	rm -f $(PAPER).aux $(PAPER).log $(PAPER).out $(PAPER).toc \
	      $(PAPER).bbl $(PAPER).blg $(PAPER).fls $(PAPER).fdb_latexmk \
	      $(PAPER).synctex.gz

distclean: clean
	rm -f $(PAPER).pdf
