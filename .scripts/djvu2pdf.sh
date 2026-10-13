#!/bin/sh

# convert DjVu -> searchable PDF, keeping the DjVu text (OCR) layer and bookmarks
# usage:  djvu2pdf.sh  <file.djvu> [output.pdf]
# needs dpsprep (install: uv tool install dpsprep); without it, falls back to
# ddjvu, whose PDF has page images only (no text layer, not searchable)

set -eu

i="$1"
o="${2:-$(basename "$i" .djvu).pdf}"
echo "------------ converting $i to PDF ----------------"
echo "[ writing output to $o ] "

if command -v dpsprep >/dev/null 2>&1; then
    dpsprep "$i" "$o"
else
    echo "dpsprep not found: the PDF will have NO text layer (install: uv tool install dpsprep)" >&2
    ddjvu -format=pdf -quality=85 -verbose "$i" "$o"
fi
