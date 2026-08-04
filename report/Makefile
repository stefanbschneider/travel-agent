# Build the Phase 2 technical report. See README.md.
NAME    := fabiundstefan
MAXPAGES := 4

.PHONY: all clean check-pages

all: $(NAME).pdf

# bibtex runs even with no \cite yet (it is a no-op then); the two trailing passes settle
# references and the page count.
$(NAME).pdf: $(NAME).tex ijcai26.sty ijcai26.bib named.bst
	pdflatex -interaction=nonstopmode -halt-on-error $(NAME).tex
	-bibtex $(NAME)
	pdflatex -interaction=nonstopmode -halt-on-error $(NAME).tex
	pdflatex -interaction=nonstopmode -halt-on-error $(NAME).tex
	@$(MAKE) --no-print-directory check-pages

# The 4-page limit is a hard organizer rule, but a build that refuses to produce the PDF is the
# wrong way to enforce it: an over-long draft is much easier to cut down when you can read it.
# So this warns loudly and still leaves the PDF in place.
# pdflatex always reports "Output written on <file>.pdf (N pages, ...)" in the log, which needs
# no extra tooling; pdfinfo (poppler-utils) is the fallback when only the PDF is at hand.
check-pages:
	@pages=$$(sed -n 's/.*Output written on .*(\([0-9][0-9]*\) page.*/\1/p' $(NAME).log 2>/dev/null | tail -1); \
	if [ -z "$$pages" ]; then \
	  pages=$$(pdfinfo $(NAME).pdf 2>/dev/null | awk '/^Pages:/ {print $$2}'); \
	fi; \
	if [ -z "$$pages" ]; then \
	  echo "warning: could not determine the page count of $(NAME).pdf; check it by hand (max $(MAXPAGES))"; \
	elif [ "$$pages" -gt "$(MAXPAGES)" ]; then \
	  echo "WARNING: $(NAME).pdf is $$pages pages; the organizer limit is $(MAXPAGES)." >&2; \
	  echo "         The PDF was still written -- shorten it before submitting." >&2; \
	else \
	  echo "$(NAME).pdf: $$pages page(s), within the $(MAXPAGES)-page limit"; \
	fi

clean:
	rm -f $(NAME).aux $(NAME).log $(NAME).bbl $(NAME).blg $(NAME).out
