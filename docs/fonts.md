# Font settings reference

This page describes settings that affect a built font. Most users can set them
in the browser. Config files provide shared defaults, settings without a browser
control and automated builds.

Page settings are separate. Margin, alignment, line spacing, hyphenation,
anti-aliasing and night mode change only the browser preview. `line_height`
changes a metric stored in the built font. **line spacing** under Page remains
preview-only.

For a guided build, start with [Getting started](getting-started.md). Commands
are in [Command line](cli.md).

## Browser names and config names

The browser uses labels that describe what the reader sees. Config files use
stable key names. Most labels match their keys after spaces replace underscores.
The exceptions are listed here.

### The same settings in the preview

| In the preview | In a `.conf` file |
|---|---|
| **name** | `name` |
| **sizes** | `sizes` |
| **more sizes** in the first family | additional values in `sizes` |
| **Second family** sizes | `sizes_mod` |
| **suffix** | `mod_suffix` |
| **coverage** | `intervals` |
| **extra ranges** | `ranges` |
| **bundled fallback faces** | `fallbacks` |
| **fallback 1** | `fallback_regular` |
| **fallback 2** | `fallback2_regular` |
| **mono rasterizing** | `mono` |
| **output** | `out` in `all.conf` |
| **use the font's own** beside line height | leave `line_height` unset |
| **text** and **bold** for a variable family | style keys with `@wght=` coordinates |

The config-only keys are `family`, `dir`, `fallback_order`, `fallback_dir`,
`space_glyphs` and `space_width_XXXX`.

## Config files

Config files are in `fonts/conf` by default. A family config is named
`<family>.conf`.

The format is `key = value`. It has no section headers. Lines beginning with
`#` or `;` are comments. Every key is optional.

CrossGlyph can discover a family from its filenames and build it without a
config. Pressing **Save** creates a family config when one is needed.

### Shared defaults

`all.conf` holds settings shared by every family. It is optional. Copy
`all.conf.example` when you want a commented starting point.

A family config inherits from `all.conf` and overrides the keys it names. A
discovered family with no config also uses the shared defaults.

Keep keys that identify one family or file in family configs. This includes
`name`, `family`, `regular`, `bold`, `italic`, `bolditalic`,
`fallback_regular` and `fallback2_regular`.

## Source files and styles

CrossGlyph searches the workspace and its subfolders for TTF and OTF files. It
skips `conf`, `cpfonts`, `fallbacks` and folders whose names begin with a dot.

It reads the style from the filename. These names form one family:

```text
MyFont-Regular.ttf
MyFont-Bold.ttf
MyFont-Italic.ttf
MyFont-BoldItalic.ttf
```

The regular face is required. The other styles are optional. CrossGlyph also
understands common names such as Roman, Book, Medium and Oblique.

The folder name does not become the family name. Rename unclear files or use
the explicit style keys when discovery selects the wrong face.

| Key | Default | Meaning |
|---|---|---|
| `family` | Config filename | Family text matched against source filenames. |
| `dir` | Workspace root | Folder to search for source files. |
| `regular` | Discovered | Exact regular source file. |
| `bold` | Discovered | Exact bold source file. |
| `italic` | Discovered | Exact italic source file. |
| `bolditalic` | Discovered | Exact bold italic source file. |
| `name` | Discovered family | Family and output folder name. Unsupported filename characters are removed. |

Paths are resolved from `dir`.

## Point sizes and output

CrossPoint loads one bitmap font file for each point size. The reader lists the
sizes carried by the selected family.

| Key | Default | Meaning |
|---|---|---|
| `sizes` | `12 14 16 18` | Point sizes in the main family. Fractions are allowed. |
| `sizes_mod` | Empty | A second list of point sizes from the same faces. |
| `mod_suffix` | `Mod` | Suffix for the second family. Leave it empty to merge both lists. |
| `out` | `cpfonts` | Output folder. This key belongs in `all.conf`. |

A fractional point size is rasterized at its exact value. Its filename uses the
nearest whole-number label. CrossGlyph refuses two sizes that would write the
same filename.

Example with a second family:

```ini
sizes = 12 13.5 15 17
sizes_mod = 14 16 18
mod_suffix = Large
```

Leave `mod_suffix` empty to put both size lists under one family name.

## Character coverage

Coverage selects the characters stored in the built files. Every build includes
basic Latin text and punctuation. The default `reading` preset adds ranges used
by common reading text, including broader Latin, Cyrillic, Greek and symbols.

| Key | Default | Meaning |
|---|---|---|
| `intervals` | `reading` | Comma-separated coverage presets. An empty value keeps base coverage. |
| `ranges` | Empty | Extra Unicode ranges such as `(0x2900-0x29FF)`. |
| `space_glyphs` | `yes` | Add fixed-width Unicode spaces. |
| `space_width_XXXX` | Unicode width | Override one fixed-width space as a fraction of an em. |

Example:

```ini
intervals = reading, arabic
ranges = (0x2900-0x29FF)
```

More coverage increases file size and build time. A preset adds only characters
that one of the selected faces can draw.

Arabic coverage also prepares the joined forms that CrossPoint requests. This
supports modern Arabic fonts that store joining rules in OpenType tables.

## Fallback faces

A fallback supplies a character missing from the main family. CrossGlyph checks
the main family, the two user fallbacks and then the enabled bundled faces.

| Key | Default | Meaning |
|---|---|---|
| `fallback_regular` | Empty | First user fallback family. |
| `fallback2_regular` | Empty | Second user fallback family. |
| `fallbacks` | `no` | Add the downloaded bundled Noto faces. |
| `fallback_order` | Built-in order | Comma-separated order. Use `bundled` for the bundled set. |
| `fallback_dir` | `fallbacks` | Folder holding bundled faces. This key belongs in `all.conf`. |

The user fallback keys name files relative to `dir`. A fallback lends its bold
or italic face when that style exists. Its regular face supplies other styles.

In the browser, use **Fetch** beside **bundled fallback faces**. The command-line
method is in [Command line](cli.md#download-bundled-fallbacks).

## Font tuning

These settings change the glyph images or font metrics.

| Key | Default | Meaning |
|---|---|---|
| `gamma` | `1.0` | Ink curve. Values above 1 darken the font. |
| `thresholds` | `4 8 12` | Cut points for the three non-white levels. |
| `weight` | `0` | Stroke change in pixels. Negative values make strokes lighter. |
| `slant` | `0` | Artificial slant. `0.25` is about 14 degrees. |
| `hinting` | `normal` | `normal`, `light`, `none` or `auto`. |
| `grayscale_hinting` | `no` | Use the TrueType interpreter intended for grey output. |
| `mono` | `no` | Rasterize glyphs as black and white. |
| `stem_darkening` | `no` | Apply FreeType stem darkening when supported. |
| `line_height` | Font value | Line pitch. A number is em-relative, `0.9x` scales the font value and `26px` is absolute. |
| `letter_spacing` | `0` | Pixels added to every character advance. |
| `word_spacing` | `0` | Pixels added to a space after letter spacing. |
| `kerning` | `yes` | `yes`, `no` or a factor such as `0.5`. |
| `ligatures` | `yes` | Use OpenType ligatures such as `fi`. |
| `figures` | `default` | `default` or `proportional`. |

Start with gamma. It changes darkness without changing the outline. Use weight
when the strokes need to become thicker or thinner. Check several point sizes
before saving.

Hinting fits outlines to the pixel grid. **normal** uses the font's instructions,
**light** changes vertical fitting, **none** disables hinting and **auto** uses
FreeType's auto-hinter. The browser greys controls that cannot affect the
selected font and explains why.

Mono rasterizing changes the built glyphs. The Page section's anti-aliasing
switch changes only how the preview paints the existing font levels.

## Variable fonts

A variable font stores a range of designs in one file. CrossGlyph chooses the
regular and bold weights from named instances in the font. It uses the common
400 and 700 weights when no suitable names exist.

The browser exposes the text and bold weights. Optical size follows each build
size automatically and is not a browser control.

A config can pin design coordinates after a style filename:

```ini
regular = MyVariable[wght,opsz].ttf@wght=500
bold = MyVariable[wght,opsz].ttf@wght=750
```

Separate several axes with commas. An explicit optical-size coordinate replaces
the automatic size for that style.

## Rebuilds and metadata

A normal build rebuilds only point sizes whose source files or settings changed.
Hold Shift while pressing a browser build button to rebuild every size. The
command line uses `--force`.

Removing a size removes its generated file. CrossGlyph leaves output folders it
did not create.

Each built family contains `.crossglyph.json`. It records the resolved settings,
source file hashes, variable-font coordinates, fallbacks, coverage and generated
files. CrossPoint does not read this file.

For implementation details, see [Internals](internals.md).
