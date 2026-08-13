#!/bin/bash
# Build the render core to a freestanding .wasm.
#
# Run under MSYS2:
#   c:/tools/msys64/usr/bin/env.exe MSYSTEM=MINGW64 \
#     c:/tools/msys64/usr/bin/bash.exe -lc 'bash <repo>/src/render/build.sh'
#
# The module is committed, because a release has no toolchain to build one
# with. The stamp beside it records the firmware commit it came from.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FW="${FW:-$ROOT/../crosspoint-reader}"
EMSDK="${EMSDK:-$ROOT/../emsdk}"
OUT="$ROOT/src/crossglyph/render"
OBJ="$ROOT/build/obj"

# emsdk ships .exe wrappers on Windows, extensionless scripts elsewhere.
EMCC="${EMCC:-$EMSDK/upstream/emscripten/emcc.exe}"
EMXX="${EMXX:-$EMSDK/upstream/emscripten/em++.exe}"
[ -f "$EMCC" ] || EMCC="$EMSDK/upstream/emscripten/emcc"
[ -f "$EMXX" ] || EMXX="$EMSDK/upstream/emscripten/em++"

[ -d "$FW" ] || { echo "firmware clone not found at $FW" >&2; exit 1; }
[ -f "$EMXX" ] || { echo "em++ not found at $EMXX" >&2; exit 1; }
mkdir -p "$OBJ"

# The stub HAL comes first, so our HalDisplay/HalStorage/HalGPIO/Logging/
# Arduino/BoardConfig headers shadow the firmware's.
INCS="-I$ROOT/src/render/hal \
  -I$FW/lib/EpdFont -I$FW/lib/GfxRenderer -I$FW/lib/Utf8 \
  -I$FW/lib/Memory -I$FW/lib/MiniBidi -I$FW/lib/Logging \
  -I$FW/lib/InflateReader -I$FW/lib/uzlib/src -I$FW/lib/miniz \
  -I$FW/lib/Epub -I$FW/lib/Serialization"

CXX_SRCS="$ROOT/src/render/api.cpp \
  $FW/lib/EpdFont/EpdFont.cpp \
  $FW/lib/EpdFont/EpdFontFamily.cpp \
  $FW/lib/EpdFont/SdCardFont.cpp \
  $FW/lib/EpdFont/FontDecompressor.cpp \
  $FW/lib/Utf8/Utf8.cpp \
  $FW/lib/GfxRenderer/GfxRenderer.cpp \
  $FW/lib/GfxRenderer/FontCacheManager.cpp \
  $FW/lib/MiniBidi/BidiUtils.cpp \
  $FW/lib/InflateReader/InflateReader.cpp \
  $FW/lib/Epub/Epub/ParsedText.cpp \
  $FW/lib/Epub/Epub/blocks/TextBlock.cpp \
  $FW/lib/Epub/Epub/hyphenation/Hyphenator.cpp \
  $FW/lib/Epub/Epub/hyphenation/HyphenationCommon.cpp \
  $FW/lib/Epub/Epub/hyphenation/LiangHyphenation.cpp \
  $FW/lib/Epub/Epub/hyphenation/LanguageRegistry.cpp"

# Compiled as C, not C++: em++ would force C++ on these and reject uzlib's
# implicit void* conversions (tinflate.c:559), which are legal C.
C_SRCS="$FW/lib/MiniBidi/minibidi.c \
  $FW/lib/uzlib/src/tinflate.c"

EXPORTS='["_malloc","_free","_rc_abi_version","_rc_probe_sum","_rc_init",
"_rc_font_load","_rc_font_advance_y","_rc_font_ascender","_rc_font_descender",
"_rc_font_prewarm","_rc_font_cached_glyphs",
"_rc_render","_rc_framebuffer","_rc_framebuffer_size",
"_rc_page_render","_rc_layout_paragraph","_rc_layout_line","_rc_page_set_spec","_rc_page_reset_spec","_rc_page_set_language",
"_rc_screen_width","_rc_screen_height","_rc_panel_width","_rc_panel_height",
"_rc_probe_line_height","_rc_probe_text_width","_rc_probe_pixel","_rc_probe_panel_width","_rc_probe_panel_height","_rc_probe_write_target","_rc_probe_framebuffer_ptr","_rc_probe_write_rows"]'

OBJS=""
for src in $CXX_SRCS; do
  obj="$OBJ/$(basename "$src" .cpp).o"
  # gnu++2a, not c++17: the firmware builds with it (platformio.ini:35) and
  # lib/Memory uses C++20 requires-clauses and std::is_unbounded_array_v.
  # Matching the firmware's standard removes a whole class of divergence.
  "$EMXX" -c "$src" $INCS -std=gnu++2a -O2 -fno-exceptions -fno-rtti -o "$obj"
  OBJS="$OBJS $obj"
done
for src in $C_SRCS; do
  obj="$OBJ/$(basename "$src" .c).c.o"
  "$EMCC" -c "$src" $INCS -O2 -o "$obj"
  OBJS="$OBJS $obj"
done

# -sPURE_WASI=1 is what keeps the module portable: without it the build imports
# env.emscripten_notify_memory_growth, an Emscripten-specific callback a
# non-Emscripten host would have to fake. With it the imports are three
# standard WASI stdio functions that libc links in and we never call --
# satisfied natively by wasmtime, and by any off-the-shelf shim in a browser.
#
# EXIT_RUNTIME is not set explicitly: emcc rejects that alongside
# STANDALONE_WASM, and --no-entry already makes this a reactor module.
# -sALLOW_MEMORY_GROWTH is not optional: freetype-wasm ships without it and the
# epdfont-converter had to binary-patch its memory section at install time to
# handle anything larger than a trivial Latin font.
"$EMXX" $OBJS \
  -sSTANDALONE_WASM=1 -sPURE_WASI=1 -sALLOW_MEMORY_GROWTH=1 --no-entry \
  -sEXPORTED_FUNCTIONS="$EXPORTS" \
  -o "$OUT/render.wasm"

# Record what this was built from, beside it. crossglyph.render.is_stale() reads
# this and refuses to load a module the firmware has moved past -- a preview
# drawn by the wrong renderer is worse than no preview.
#
# cygpath -m gives D:/... , which both this shell and the Windows Python that
# reads the stamp can hand to git. $FW itself is /d/... under MSYS2, and git
# invoked from Windows would read that as a relative path.
COMMIT="$(git -C "$FW" rev-parse HEAD 2>/dev/null || true)"
SOURCE="$FW"
command -v cygpath >/dev/null 2>&1 && SOURCE="$(cygpath -m "$FW")"
if [ -n "$COMMIT" ]; then
  # The commit and nothing else: the stamp is committed, and the path this was
  # built from belongs to one machine.
  printf '{"firmware": "%s"}\n' "$COMMIT" > "$OUT/render.built-from.json"
else
  # A firmware exported without .git has no commit to record. Writing an empty
  # one would read back as "no stamp", which counts as stale -- so every run
  # would rebuild and still be stale. Say so instead, once.
  echo "  note: $SOURCE has no git commit; staleness cannot be checked" >&2
  rm -f "$OUT/render.built-from.json"
fi

echo "built $OUT/render.wasm ($(stat -c%s "$OUT/render.wasm") bytes)"
echo "  from $SOURCE @ ${COMMIT:0:12}"
