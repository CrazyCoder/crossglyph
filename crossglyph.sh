#!/bin/sh
# Run CrossGlyph, fetching uv on first use. With no arguments it opens the
# preview in a browser.
root="$(cd "$(dirname "$0")" && pwd)"
exec "$root/tools/uv.cmd" run --project "$root" crossglyph "$@"
