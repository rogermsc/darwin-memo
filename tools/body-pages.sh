#!/usr/bin/env bash
# Page count of the venue build's body -- the number a page limit applies to.
#
# The body is everything before the appendix, which starts its own page, so
# the count is exactly the page before the appendix's first heading. The
# venue build is two-column 10pt because that is the layout every limit in
# paper/submission-notes.md is written against; measuring the 11pt
# single-column preprint against a two-column limit compares the wrong
# things, which is how a 39-page body was once read as 39 pages over.
#
# Usage: tools/body-pages.sh [LIMIT]   -- exits non-zero if over LIMIT.
set -euo pipefail
LIMIT="${1:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
cd "$HERE/paper"
tectonic -X compile body.tex --outdir "$OUT" --keep-intermediates >/dev/null 2>&1
python3 - "$OUT/body.aux" "$LIMIT" <<'PY'
import re, sys

# LaTeX already knows which page the appendix landed on, and says so in the
# aux file. Reading it there beats grepping the rendered text for a heading
# that a retitled section would silently stop matching.
aux = open(sys.argv[1], encoding="utf-8").read()
found = re.search(r"\\newlabel\{sec:appendix\}\{\{[^}]*\}\{(\d+)\}", aux)
if not found:
    sys.exit("no page recorded for \\label{sec:appendix}; did the appendix move?")
body = int(found.group(1)) - 1
appendix = body + 1
print(f"venue body: {body} pages (appendix starts p{appendix})")
limit = sys.argv[2]
if limit and body > int(limit):
    sys.exit(f"body is {body} pages, over the {limit}-page limit")
PY
