# .latexmkrc : Writer manuscript workspace
# Resolves vendored venue templates from ./styles/ (set up by fetch_template.py in Phase 2).
# Default target: main.tex.

# TEXINPUTS resolution: include ./styles/ recursively, then default TeX path.
$ENV{'TEXINPUTS'} = './styles//:' . ($ENV{'TEXINPUTS'} || '');

# Default file (latexmk runs this if no argument given).
@default_files = ('main.tex');

# Standard latexmk options for nonstopmode + file-line-error + synctex.
# (render.sh wraps these as flags; defaults here apply when invoking latexmk directly.)
$pdf_mode = 1;
$pdflatex = 'pdflatex -interaction=nonstopmode -file-line-error -synctex=1 %O %S';

# Clean target removes intermediate files.
$clean_ext = 'aux bbl blg fdb_latexmk fls log out synctex.gz toc nav snm vrb';
