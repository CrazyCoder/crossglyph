# Internals

This page is for contributors and maintainers. User workflows are in
[Getting started](getting-started.md), [The browser preview](preview.md) and
[Command line](cli.md).

## Conversion pipeline

CrossGlyph converts TTF and OTF faces into CrossPoint `.cpfont` files. The
converter is under `src/crossglyph/cpfont/`.

The converter is a fork of the code used by the CrossPoint font website.
`src/crossglyph/cpfont/UPSTREAM` records the pinned upstream revision. Review
upstream changes as source diffs because this fork deliberately changes the
conversion behavior.

The fork adds the controls exposed by CrossGlyph:

- gamma and grey-level thresholds;
- weight, slant and hinting modes;
- grayscale and mono rasterizing;
- stem darkening;
- line, letter and word spacing;
- kerning factors, ligatures and proportional figures;
- variable-font instances and optical sizing;
- ordered fallbacks and fixed-width spaces;
- Arabic presentation forms generated from a font's shaping rules.

`CPFONT_VERSION` and a hash of the converter are part of every build stamp. A
converter change therefore invalidates affected outputs.

## Font discovery

`src/crossglyph/fontconf.py` owns source discovery and config parsing.

Discovery walks the workspace recursively. It skips `conf`, `cpfonts`,
`fallbacks` and dot folders. The filename supplies the family stem and style.
Explicit style keys replace the discovered file for one slot.

The matcher also handles:

- common style words and short foundry suffixes;
- variable-font axis lists added by download sites;
- numbered foundry series before style words;
- an italic weight that follows a non-standard regular weight.

Tests in `tests/test_fontconf.py` define the accepted patterns. Add a case there
before changing discovery rules.

## Variable-font coordinates

`slot_coords()` in `fontconf.py` chooses coordinates for each style and point
size.

The regular and italic slots use the font's named regular instance when one
exists. Bold slots use the named bold instance. The fallback weights are 400
and 700, clamped to the axis range.

The optical-size axis follows the point size. An explicit coordinate in a style
key overrides automatic selection. The preview exposes text and bold weights,
but deliberately leaves optical size tied to the build size.

## Arabic forms

CrossPoint shapes Arabic text before glyph lookup. It requests presentation-form
codepoints. Many modern fonts store base letters and OpenType joining rules
instead of character-map entries for those forms.

`src/crossglyph/cpfont/arabic.py` mirrors the codepoint mapping used by the
firmware. The converter runs a face's shaping rules and stores the resulting
forms where CrossPoint looks for them. `tests/test_arabic.py` compares the table
with the firmware source and covers generated forms.

## Preview architecture

The preview server is in `src/crossglyph/preview/server.py`. Static HTML, CSS and
JavaScript are in `src/crossglyph/preview/static/`.

A render request follows this path:

1. The browser sends the family, point size, font tuning, page settings and
   sample text.
2. Python builds or reuses the temporary `.cpfont` data required by the page.
3. The render core lays out and draws the page.
4. The server returns the framebuffer and layout details.
5. The browser paints the framebuffer and optional reader frame.

The render core is CrossPoint drawing code compiled to WebAssembly. Releases
carry the built module under `src/crossglyph/render/`. The source checkout and
build tools are not required at runtime.

`tools/update-engine.py` updates the module from the pinned engine checkout.
`render.built-from.json` records the source revision.

## Browser state and font state

Font settings are stored in family config files. The browser sends them to the
server only when the user saves or builds.

Page, sample-text and device-preview choices are browser state. They are kept in
local storage and are not written to font configs. The preview point size is a
separate browser value because resetting Page must not change the size being
judged.

The responsive layout is measured in `static/js/device.js`. Wide screens show
Tune, the rendered page and Export as three columns. Most screens show two
columns with Tune and Export as tabs. Narrow screens stack the selected panel
above the rendered page.

## Build planning and stamps

`src/crossglyph/fontbuild.py` plans families and point sizes. Point sizes are
rasterized in separate worker processes up to the configured job limit.

Each family output contains `.crossglyph.json`. Its stamp includes source
content hashes, resolved settings, converter identity and one digest per size.
A normal build schedules only sizes whose digest changed.

The same file records provenance for the built family:

- CrossGlyph and FreeType versions;
- source filenames and hashes;
- variable-font coordinates;
- resolved settings and fallbacks;
- requested and drawable coverage;
- output filenames, sizes and glyph counts;
- Arabic forms synthesized during conversion.

Orphan cleanup removes generated families and sizes that the workspace no longer
produces. It leaves directories without a CrossGlyph stamp and keeps the last
output for a configured family whose source is temporarily unavailable.

## CrossPoint format limits

CrossPoint validates counts before allocating structures for an SD-card font.
The format limits include characters, consecutive character runs and kerning
entries.

Sparse coverage is the common run-limit problem. A broad fallback can fill gaps
and merge many runs. CrossGlyph estimates the counts before rasterizing and
refuses a build that CrossPoint would reject.

Keep user-facing remedies in [Troubleshooting](troubleshooting.md). Source
citations and boundary tests belong beside the limit calculations in
`fontbuild.py` and the relevant tests.

## Update layout

A native release has a root folder with launchers, user files, `current` and a
`versions` directory. `current` names the version used by the next launch.
Updates install a new version beside the active one and then change `current`.

User-owned workspace files and `update.conf` remain at the root. Managed
templates use conffile rules: an edited copy is kept and the release copy is
written with a `.new` suffix.

The browser and command line drive the same generator in
`src/crossglyph/upgrade.py`. It yields download, checksum, extraction and switch
steps. A local preview can hand its address to the new version and reload the
page after the replacement server answers.

Rollback selects the previous retained version and records the release that was
left. Automatic checks suppress that release until a newer one appears.

## Tests that protect the documentation

`tests/test_preview.py` checks three documentation contracts:

- every setting written by the panel appears in `docs/fonts.md`;
- labels that differ from config keys are mapped under
  **The same settings in the preview**;
- `docs/preview.md` uses browser labels instead of hidden config names.
