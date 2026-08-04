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

# The 4-page limit is a hard organizer rule, so enforce it at build time rather than trusting a
# glance at the PDF.
check-pages:
	@pages=$$(grep -c '^/Type\s*/Page$$' $(NAME).pdf 2>/dev/null || true); \
	if [ -z "$$pages" ] || [ "$$pages" = "0" ]; then \
	  pages=$$(pdfinfo $(NAME).pdf 2>/dev/null | awk '/^Pages:/ {print $$2}'); \
	fi; \
	if [ -z "$$pages" ]; then \
	  echo "warning: could not determine the page count of $(NAME).pdf; check it by hand (max $(MAXPAGES))"; \
	elif [ "$$pages" -gt "$(MAXPAGES)" ]; then \
	  echo "error: $(NAME).pdf is $$pages pages; the organizer limit is $(MAXPAGES)" >&2; exit 1; \
	else \
	  echo "$(NAME).pdf: $$pages page(s), within the $(MAXPAGES)-page limit"; \
	fi

clean:
	rm -f $(NAME).aux $(NAME).log $(NAME).bbl $(NAME).blg $(NAME).out
