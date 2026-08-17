# Building fonts

One `<family>.conf` per family, in the workspace's `conf` folder. Plain
`key = value`, no section header, `#` and `;` start comments. Every key is
optional, and the shortest useful config is empty.

```sh
./crossglyph.sh build             # everything that changed
./crossglyph.sh build --list      # what each config resolves to, building nothing
./crossglyph.sh build notosans    # one family, by config name or family name
./crossglyph.sh build --force     # ignore the stamps
```

## all.conf, the shared defaults

A file named `all.conf` in `conf` is not a family, and is not required.

It holds settings shared by every family in the workspace: a `<family>.conf`
inherits from it and states only what it does differently, and a family with no
config at all is built from it. The workspace ships one with every line
commented out, so it sets nothing until you edit it. Delete it and nothing
changes.

Discovery does not depend on it either. Drop four files in the workspace and
they build on the next run, taking their name from the filenames.

Subfolders are walked, so a family that arrives as a folder can stay one. The
folder is organization and nothing else: a face is known by its filename
wherever it sits, so `serif/Charis-Bold.ttf` is Charis' bold exactly as
`Charis-Bold.ttf` at the root would be, and a folder of `Regular.ttf` and
`Bold.ttf` builds families called Regular and Bold rather than one named after
the folder. Rename the files, not the folder.

Four folders are left alone: `conf` holds configs, `cpfonts` holds builds,
`fallbacks` holds the Noto faces that fill holes in other families rather than
being families themselves, and anything beginning with a dot is somebody
else's.

It cannot set `name`, `family`, or the explicit style and fallback file keys.
Those name one specific family or file, so they are rejected there.

`--list` says where each family's settings came from:

```
NotoSans   <- notosans.conf
NotoSerif  <- all.conf (shared defaults, no config of its own)
```

## Every key

```ini
name           = NotoSans
family         = NotoSans
dir            = .
sizes          = 12 14 16 18
sizes_mod      = 13 15 17 19
mod_suffix     = Mod
intervals      = reading
ranges         = (0x2900-0x29FF),(0x2E00-0x2E7F)
fallbacks      = no
space_glyphs   = yes
thresholds     = 4 8 12
hinting        = normal
regular        = NotoSans-Regular.ttf
bold           = NotoSans-Bold.ttf
italic         = NotoSans-Italic.ttf
bolditalic     = NotoSans-BoldItalic.ttf
```

| key | default | meaning |
|---|---|---|
| `name` | the discovered family | family name on the device, and the filename prefix. Non-alphanumerics are stripped |
| `family` | the config filename | the stem to match source files against, when it differs from the filename. `name` does not affect it |
| `dir` | the workspace root | where to look for the font files |
| `sizes` | `12 14 16 18` | point sizes to build. Fractions are allowed, see below |
| `sizes_mod` | none | point sizes for a second family, `<name><mod_suffix>` |
| `mod_suffix` | `Mod` | suffix for that second family |
| `intervals` | `reading` | preset names, comma separated. `reading` already contains `default`, `latin-ext`, `symbols` and `vietnamese`, and the panel shows those as carried rather than as ticks of yours |
| `ranges` | none | raw `(0xAAAA-0xBBBB)` ranges, appended to `intervals` |
| `fallbacks` | `no` | append the thirteen bundled Noto faces, and the pan-CJK face when `intervals` names a CJK script. Fetch the faces before enabling it |
| `space_glyphs` | `yes` | add the fixed width spaces (U+2000 to U+200A, U+205F, U+3000) |
| `gamma` | `1.0` | curve applied to glyph coverage before it is quantized, `1 - (1 - coverage)ᵞ`, so above 1 darkens. The most useful single control, see [Tuning how glyphs look](#tuning-how-glyphs-look) |
| `thresholds` | `4 8 12` | the three 4-bit cut points for grey levels 1, 2 and 3. `3 6 10` is the darker set the built-in fonts use |
| `weight` | `0` | outline emboldening in pixels. Advance widths do not move, so text gets heavier at the same spacing |
| `slant` | `0` | shear as a tangent. `0.25` is about 14 degrees, for synthesizing an oblique a family lacks |
| `hinting` | `normal` | `normal`, `light` (vertical only, softer), `none`, or `auto` (FreeType's auto-hinter, worth trying when a font looks muddy at small sizes) |
| `grayscale_hinting` | `no` | run FreeType's interpreter version 35, which fits stems on both axes rather than hinting for a subpixel display. Only reaches a TrueType face carrying bytecode, under `hinting = normal`. See [Tuning how glyphs look](#tuning-how-glyphs-look) |
| `mono` | `no` | rasterize each glyph as one bit per pixel, with FreeType's dropout control, instead of thresholding coverage. The font then draws in two levels whatever the reader's anti-aliasing setting is. See [Tuning how glyphs look](#tuning-how-glyphs-look) |
| `stem_darkening` | `no` | FreeType stem darkening. Narrow: a CFF or OTF face under any hinting but `auto`, and a TrueType face only under `hinting = light`. See [Tuning how glyphs look](#tuning-how-glyphs-look) |
| `line_height` | the font's own | line pitch. `1.15` is em relative, `0.9x` is a multiple of the font's own, `26px` is absolute. See [Line spacing](#line-spacing) |
| `letter_spacing` | `0` | tracking in pixels, added to every glyph's advance. Stored at 1/16 px, and negatives tighten |
| `word_spacing` | `0` | added to the space on top of `letter_spacing`, as CSS word-spacing is |
| `kerning` | `yes` | GPOS kerning: `yes`, `no`, or a factor such as `0.5`. A face kerned for print often over-tightens at 12 or 13 px |
| `ligatures` | `yes` | GSUB ligatures. `fi` and `fl` often blur into one blob at four grey levels |
| `figures` | `default` | `proportional` applies the font's GSUB `pnum` feature, so a `1` stops being padded to the width of a `0`. See [Proportional figures](#proportional-figures) |
| `space_width_XXXX` | per Unicode | override one fixed width space as a fraction of an em: `space_width_2006 = 0.25` |
| `regular` `bold` `italic` `bolditalic` | auto-discovered | name a file explicitly, relative to `dir`. `file.ttf@wght=600` pins a [variable font's](#variable-fonts) coordinates |
| `fallback_regular` `fallback2_regular` | none | your own fallback families, ahead of the bundled ones |
| `out` | `cpfonts` | in `all.conf` only: where builds go, resolved against the workspace |
| `fallback_dir` | `fallbacks` | in `all.conf` only: a Noto set shared between workspaces |

The four explicit style keys are the exact equivalent of the four upload slots
on the CrossPoint font website. Auto-discovery is a convenience on top of them.
When it guesses wrong, name the files.

## Sizes

CrossPoint's **Settings > Reader > Font Size** lists every size the active
family carries, one entry each. It is a point size that is stored and shown,
not an abstract small, medium or large slot.

`sizes_mod` builds a second family from the same faces at another set of sizes,
so `NotoSans` at 12, 14, 16, 18 and `NotoSansMod` at 13, 15, 17, 19. It is a
way to keep two lists apart.

Two sizes are special. The built-in interface fonts render at 8, 10 and 12 pt,
and CJK text in the interface is drawn by borrowing the selected family at the
matching size. A CJK family therefore wants `sizes = 8 10 12 14 16 18`, or book
titles keep showing boxes. For Latin and Cyrillic this does not apply. The
website appends those two sizes to a CJK build for you; here they are yours to
list, since a size list of any length is yours to write.

### Fractional point sizes

`sizes` takes fractions such as `13.5`, and they are real rasterizations rather
than a rounding of the nearest whole size. At 150 DPI a point is 2.08 px/em, so
consecutive whole sizes are about 10% apart at reading sizes: 13 pt sets
`advanceY` 31 and 13.5 pt sets 32, a step you cannot otherwise reach.

The filename carries the rounded label, not the size. The device parses the
size out of the filename with `strtol` into a `uint8_t`
(`SdCardFontRegistry.cpp:85`), so a fractional size could not be named there.
Nothing reads a point size out of the file itself, so `sizes = 13.5` writes
`Family_14.cpfont`, and the device offers "14" while rendering 13.5 pt glyphs.
Rounding is half up. `--list` and the line each size prints as it is built both
name the label when it differs from the size, so the file a build is about to
write, or has just written, is never left to be worked out:

```
  -> Family: 13.5 (ships as 14) 16
  Family 13.5 (ships as 14) (0.4 MB, 354 glyphs, 3s)
```

Two sizes that round to the same label are refused rather than silently
overwriting each other, so `sizes = 13.5 14` is an error.

The separator here is a comma or a space, so a decimal comma is two sizes:
`sizes = 13,25` builds 13 pt and 25 pt, and nothing can tell it apart from
somebody asking for exactly that. Write the fraction with a dot. The website's
size boxes hold one size each and do read a comma as a decimal point, since
there the two cannot be confused.

## Coverage

`intervals` takes the same preset names as the website's checkboxes:

| checkbox | preset | | checkbox | preset |
|---|---|---|---|---|
| Reading (Fiction) | `reading` | | Bengali | `bengali` |
| Default (CrossPoint) | `default` | | Thai | `thai` |
| Latin Extended | `latin-ext` | | Hangul (Korean) | `hangul` |
| Greek | `greek` | | Chinese (Simplified) | `cjk-sc` |
| Cyrillic | `cyrillic` | | Chinese (Traditional) | `cjk-tc` |
| Vietnamese | `vietnamese` | | Japanese | `cjk-jp` |
| Hebrew | `hebrew` | | Symbols and Arrows | `symbols` |
| Arabic (Farsi, Urdu) | `arabic` | | IPA characters | `ipa-chars` |
| Armenian | `armenian` | | Georgian | `georgian` |
| Ethiopic | `ethiopic` | | Cherokee | `cherokee` |
| Tifinagh | `tifinagh` | | | |

`base`, which is ASCII plus General Punctuation, is added by the converter
itself and must not be listed. `reading` already covers `default` plus Greek,
Cyrillic, mathematics, arrows, box drawing, dashes and CJK quote marks.

### Arabic

Arabic is written joined up, like cursive, so a letter takes a different shape
depending on where it sits in a word: one at the start, another in the middle,
another at the end, another standing alone. A reader has to pick the right one.

CrossPoint picks it and then looks that shape up by a codepoint of its own,
because it has no room on the device for the rule engine a font's own joining
rules need. Fonts split into two camps on this. Older ones store every shape
under its own codepoint, which is what the device expects. Newer ones, and most
good Arabic faces today, store one shape plus the rules, and the device finds
nothing where it looks. Scheherazade New and ReadexPro are in the second camp,
and until this was handled they drew a page of blanks, or of replacement boxes
wherever the build had one of those to draw instead.

So the rules are run here instead, once, while the font is built, and each
resulting shape is stored where the device will ask for it. This is automatic:
there is no setting, and it works with any Arabic face. Where a face spells a
letter as a base plus a separate mark, which is how the alef with hamza and the
alef with madda are usually drawn, the pieces are combined into one picture
first.

The one thing to do yourself is put `arabic` in `intervals`, exactly as you
would for Greek or Cyrillic. It is the choice to carry Arabic at all, and it
costs file size, so it is not assumed.

```
intervals = reading, arabic
```

Note that `reading` on its own contains no Arabic whatsoever. A family built
with the default coverage draws nothing for an Arabic book, however good the
face is. Asking for the letters is enough, by preset or by a raw `ranges`
entry: the shapes they are drawn by follow from the letters and are added for
you.

A face named in `fallback_regular` is repaired the same way, so a Latin family
that borrows its Arabic from one still gets joined text.

The built family records what it repaired, under `synthesized` in
`.crossglyph.json`, so a font never carries shapes that nothing in the
workspace explains.

A single glyph cannot exceed 255 pixels on either side, because that is what
the `.cpfont` format has room for. One glyph in practice reaches it: the
bismillah at U+FDFD, an entire phrase drawn as one ornament rather than a
letter. In Noto Sans Arabic it is 244 pixels wide at 12 pt and passes the
limit at about 12.6, so every ordinary reading size above 12 pt drops it. The
build says so, naming the codepoint and the size it measured, and carries on:
a glyph the device could not store draws nothing there either way, and one
ornament is not worth failing a family over.

The honorific ligatures beside it, U+FDFA and U+FDFB, are nowhere near the
limit: 27 and 26 pixels at 12 pt, 40 and 38 at 18 pt. They are included at
every size.

### What actually decides the size

`fallbacks` is the dominant control, not `intervals`. Only codepoints some font
in the chain has are emitted, so with fallbacks off, listing a script your face
lacks is free. With them on, every interval you list is a request the Noto
faces will satisfy. Measured on a 297-codepoint Latin and Cyrillic face at
13 pt:

| `intervals` | `fallbacks` | glyphs | size |
|---|---|---|---|
| `reading,latin-ext,greek,cyrillic,symbols` | yes | 3328 | 1.2 MB |
| `reading,cyrillic` | yes | 3095 | 1.1 MB |
| `default,cyrillic` | yes | 1547 | 0.5 MB |
| `reading,latin-ext,greek,cyrillic,symbols` | no | 299 | 0.1 MB |

The last row is 286 glyphs from the face itself plus the thirteen spaces below.
Narrowing the intervals of a narrow font while fallbacks are on barely helps.
Turning fallbacks off is a factor of twelve. The build prints the glyph count
beside each size for this reason: a 300-codepoint font that builds to 3000
glyphs is being padded, and the byte size alone does not say so.

`default` is also a much cheaper request than `reading` when fallbacks are on,
because `reading` adds mathematics, arrows, box drawing, geometric shapes and
dingbats.

## The fixed width spaces

Every family gets a second, tiny fallback holding nothing but the fixed width
spaces, U+2000 to U+200A, U+205F and U+3000, with correct advance widths and no
outlines. It is independent of `fallbacks`, because it cannot pad a build:
thirteen glyphs, and only the ones the real face lacks are taken.

It is there because most reading faces have no glyph for U+2006 SIX-PER-EM
SPACE, which converters put after a dialogue dash. The firmware does not rescue
it: `ChapterHtmlSlimParser.cpp:1229` rewrites only U+00A0 and U+202F into a
space token, and everything else reaches `renderCharImpl`, which logs
`No glyph for codepoint 8198` and draws nothing. The space silently vanishes.

Each width can be overridden per family, as a fraction of an em, when the
typographic default reads wrong at your size:

```ini
space_width_2006 = 0.25    # widen the dialogue dash space from 1/6 em
```

Only the widths are settable, not which codepoints are in the table. U+00A0 and
U+202F are rewritten into a plain space before layout, so the device never asks
a font for them, and a codepoint outside the table is rejected rather than
silently ignored.

The face itself is generated, and it is an input to a build rather than
anything to put on a card: it lives in the temporary directory, named for a
digest of the widths in it, and a build makes it if it is not already there.
So a width edited here produces a different file rather than finding the old
one and using it, and nothing lands in the folder you copy across.

## Tuning how glyphs look

The device stores two bits per pixel, four levels, so every glyph passes
through a quantizer, and that is where a face gains or loses its character.
FreeType renders 8-bit coverage at 150 DPI, so 13 pt is 27.08 px/em. `gamma`
curves that coverage, it is truncated to 4 bits, then `thresholds` cuts it into
the four levels the device stores.

A useful `gamma` runs about 0.3 to 4.0, the range crengine offers for the same
curve. What it does is not uniform across that range. Up to about 2 it darkens.
Past 3 it darkens barely at all and mostly converts grey edges into solid
black, measured on a 13 px page:

| `gamma` | ink on the page | of which grey |
|---|---|---|
| 0.3 | 5.6% | |
| 1.0 | 8.3% | 34% |
| 2.0 | 9.8% | 24% |
| 3.0 | 10.5% | 13% |
| 4.0 | 10.8% | 11% |

So a high `gamma` keeps some antialiasing while pushing the page towards the
hard edges of 1-bit rendering, and a low one lightens a face that sets too
heavy at small sizes.

Which of the three cut points matters depends on the reader's
**Settings > Text > Anti-Aliasing** switch. With it on, all three are live and
the page is drawn from two grey planes. With it off, `GfxRenderer` paints every
non-zero level solid black (`GfxRenderer.cpp:449`), so only the first threshold
has any effect and lowering it fattens the text.

Measured at 13 pt over a mixed Cyrillic and Latin sample of 5838 inked pixels.
Mean coverage does not move, because thresholds redistribute what FreeType
already produced rather than changing it:

| thresholds | mean coverage | level 0 | 1 | 2 | 3 (black) |
|---|---|---|---|---|---|
| `4 8 12` (default) | 6.03 | 2950 | 608 | 414 | 1866 |
| `3 6 10` (the built-in fonts') | 6.03 | 2866 | 234 | 689 | 2049 |

`weight`, `slant`, `hinting`, `grayscale_hinting` and `stem_darkening` act
earlier, on the outline and on how FreeType fits it to the pixel grid, so they
change the coverage the quantizer then sees. Three of them are worth a note.

`weight` uses `FT_Outline_Embolden`, which fattens the outline without moving
the advance width. Text gets heavier at unchanged spacing, which is right at
reading sizes but is not a substitute for a real bold face.

`stem_darkening` is narrower than its name suggests, and where it applies
depends on `hinting` as much as on the font. FreeType has the code in two
engines, and each puts a condition of its own on top of the setting: the Adobe
CF2 interpreter, which draws CFF and Type 1 faces, darkens a scaled load, and
the auto-hinter darkens at a light target. So a CFF or OTF face moves under any
hinting but `auto`, and a TrueType face, having no CF2 path, moves only at
`hinting = light`, which is the one setting that hands it to the auto-hinter.
Under `auto` neither format moves: it targets normal hinting, and the
auto-hinter reloads the glyph unscaled, which fails both conditions at once.

The two are not the same size either. Through CF2 the effect is slight, well
under a percent of the set pixels; through the light auto-hinter it is
substantial. Measured over 132 faces on FreeType 2.13, and the preview greys
the switch when the pair you have chosen is one of the cases that cannot move.
It leaves the rest alone rather than promising anything, because a CFF face
whose stems fall where the darkening curve rounds to nothing is unmoved as
well, and nothing short of rasterizing both ways would know.

`grayscale_hinting` chooses which of FreeType's two TrueType bytecode
interpreters runs a font's own hinting. The default is version 40, which
FreeType calls roughly equivalent to DirectWrite ClearType and which hints
vertically only, since on a subpixel display snapping a stem sideways costs
more than it buys. Version 35 fits both axes, and FreeType documents it as
supporting grayscale and black and white rasterizing only, which is exactly
what this device has. A stem then lands on a pixel instead of straddling two
and being drawn twice in grey. Measured over 303 hinted faces it leaves 3.8%
fewer midtone pixels, and a third fewer on a face like DejaVu.

It is narrow in the same way `stem_darkening` is, and for a different reason:
it reaches a face only while that face's own bytecode is what draws it. A CFF
family has none, a TrueType family with no glyph instructions goes to the
auto-hinter anyway, and so does any family under `light`, `auto` or `none`. So
it is a `hinting = normal` control, on a TrueType face, and the preview greys
the row everywhere else.

`mono` changes what a pixel is decided by. Normally the converter takes
FreeType's coverage and cuts it at the three thresholds, and the reader with
anti-aliasing off then paints every non-white level solid black: a pixel a
quarter covered goes black, which at 12px fattens strokes into each other.
With `mono` on, FreeType rasterizes at one bit per pixel and decides each one
with dropout control instead. Measured on DejaVu Serif at 12px that is a third
less ink, and none of the ink that was holding the letters open.

It is not tied to the reader's setting. A font built this way draws in two
levels whatever the page is set to, which is the only way to see what it does
to a face without changing the page underneath it. It is a build rather than a
view, though: mono hinting rounds advances to whole pixels, so between 2 and 12
of 26 lowercase advances move and the text sets to different lines. `gamma` and
the thresholds have nothing to act on while it is on, and the preview greys
them.

It combines with every hinting mode, but `light` is a special case worth
knowing about. FreeType carries the hinting algorithm and the raster in the
same field, so asking for both in one call is not possible: a glyph is loaded
under light hinting and then rasterized bilevel in a second step. Light
hinting fits vertically only, on purpose, so the stems it leaves are not on
the pixel grid sideways. Made bilevel they come out a pixel wider here and
narrower there, where `hinting = normal` with `mono` gives you stems of one
width. That is a look, not a fault, and the two are worth comparing on a face
before choosing.

## Line spacing

Line pitch is stored in the font, not decided on the device. `getLineHeight()`
is `advanceY` from the `.cpfont` times a compression factor
(`GfxRenderer.cpp:2005`), and for SD card fonts that factor is 0.95, 1.00 or
1.10 for Tight, Normal and Wide, hardcoded to one family's table for every font
(`CrossPointSettings.cpp:268`). So Tight buys 5%, calibrated for a font you are
not using.

`advanceY` is whatever the font's `hhea` and `OS/2` tables declare, and fonts
disagree enormously. Measured across 686 faces at 13 pt, the tightest sits at
0.886 em and the loosest at 2.105, which is a 138% spread. The loosest font at
Tight still sits at 2.0 em.

`line_height` fixes it at build time, in whichever of three units suits the
question:

```ini
line_height = 1.15      # 1.15 times the em square, whatever the font claims
line_height = 0.9x      # 10% tighter than this font's own
line_height = 26px      # exactly 26 pixels
```

The em relative form is the one that makes families comparable. Set it once in
`all.conf` and every font lays out identically no matter what its tables say.
That is also CSS's unitless `line-height` semantics.

Only the pitch moves. `ascender` and `descender` are left alone, because they
place the baseline inside the line and are what underline, strikethrough, ruby
and superscript offsets are measured from (`TextBlock.cpp:185-219`). Set the
pitch below what those two span and consecutive lines can collide. The build
says so and carries on, since tight leading is sometimes exactly the point:

```
warning: line_height 8px is under the 29px this font's ascender and
descender span, so consecutive lines may overlap
```

That warning is raised only for a pitch you asked for. A font whose own
declared band exceeds its own pitch is not unusual: NotoSans has a negative
`lineGap`, spanning 35 px against a 34 px pitch, and those are worst case
bounds that adjacent lines rarely both reach.

`letter_spacing` and `word_spacing` adjust the horizontal advances the same
way. Both are in pixels, stored at 1/16 px, and both accept negatives. Word
spacing stacks on letter spacing exactly as CSS does, and the device takes the
word gap from the font's own U+0020 glyph (`GfxRenderer.cpp:1880`). A little
positive tracking often reads better on e-ink than on a screen.

## Kerning and ligatures

Both tables are baked into the `.cpfont` per style and cannot be turned off on
the device: kerning as a class matrix of int8 4.4 fixed point pixels, ligatures
as up to 255 pair to glyph entries.

`kerning` takes a factor rather than only a switch, because the useful setting
is usually partial. At 13 pt one unit of that fixed point pixel is a large
fraction of a stem, so a face kerned for print can over-tighten. `kerning = 0.5`
keeps the shape of the designer's pairs at half the amount. Scaling happens
before the class matrix is derived, so flattened pairs collapse into fewer
classes and the table gets smaller as well as gentler.

`ligatures = no` is worth trying on any face whose `fi` and `fl` look like a
blot at reading sizes. The four level quantizer is much less forgiving than a
laser printer.

Both also cost time. Each parses GPOS or GSUB with fontTools for every source
face, so turning them off speeds a rebuild up as well as changing the result.

## Proportional figures

Digits come in two width styles. Tabular pads every digit to a common width so
columns align, and it is the usual default. Proportional lets each take its
natural width, a `1` narrower than a `0`. Columns are what tabular is for, and
a book is prose, where the padding shows up as a gap around every narrow digit.

```ini
figures = proportional
```

This applies the font's GSUB `pnum` feature at rasterization time, so the
`.cpfont` carries the proportional outlines and advances under the digit
codepoints. The device is never aware of it. Kerning is read for the
substituted glyphs rather than the originals, so the digits do not keep the
tabular pairs.

It only moves a font that declares the feature, which is a real limitation
rather than a bug, the same shape as `ligatures` on a face with no ligature
pairs. Some faces substitute all ten digits, some a handful, most none at all.
The preview has it as the **figures** control, and the sample text carries
`111 118 181 811 1118` so the difference is visible rather than inferred.

## Auto-discovery

The rules come from the website's folder picker.

1. Every `.ttf` or `.otf` in `dir` is a candidate.
2. Its style is read from the end of the filename, `BoldItalic`, then `Bold`,
   then `Italic`, then `Regular`, where regular also matches `Normal`, `Book`,
   `Roman`, `Medium` and `Rg`. No match means regular.
3. Stripping that suffix leaves the family stem, which must equal `family`,
   case insensitively.

So `NotoSans-Regular.ttf` is the roman face, and
`Roboto_SemiCondensed-Light.ttf` strips to `Roboto_SemiCondensed-Light`, its
own family, which is how an
eighteen file Roboto SemiCondensed folder narrows to the four faces you want.

Where two files claim one slot, an explicit weight beats a bare stem and
`Regular` beats `Medium`. `--list` always prints the winner.

Four rules go beyond the website's.

### A variable font's axes are not part of its family name

Google Fonts ships `Merriweather[opsz,wdth,wght].ttf` and
`Merriweather-Italic[opsz,wdth,wght].ttf`. The bracketed axis list comes off
the stem before anything is matched. Left on, it survives the non-alphanumeric
strip as a family called `Merriweatheropszwdthwght`, and the italic, whose
suffix is no longer at the end of the stem, becomes a second one-face family
instead of that family's italic.

### The italic follows the roman's weight

The website drops every extra weight italic such as `MediumItalic`, which is
right when one would fight a plain `Italic` for the slot, and wrong when the
family's roman is itself an extra weight. A family whose roman is
`Name-Medium` pairs with `Name-MediumItalic` rather than with the lighter
`Name Italic`. A family whose roman is `Name-Regular` is unaffected.

### A foundry's series number is not part of the family

Linotype numbers the styles: 65 Medium, 66 Medium Italic, 75 Bold, 76 Bold
Italic, where the first digit is the weight and the second says upright or
italic. The number sits in the stem, so without dropping it each file strips
to a family of its own and the four never meet. Only a whole number between
the family and a tail of nothing but style words goes, which keeps the rule
off a name where the number is the family: `Roboto_Condensed_300` has no style
tail, so it stays its own family.

### Terse suffixes

The old convention has no separator: `b` or `bd` bold, `i` or `it` italic,
`bi`, `bdi` or `bdit` bold italic, and `z` bold italic, which is what
Microsoft's own core fonts ship (`georgiaz.ttf`, `verdanaz.ttf`,
`CALIBRIZ.TTF`). A bare trailing letter is read as a style only when a file
named for the plain family sits beside it. Otherwise `Bodoni.ttf` would be the
italic of a family called `Bodon`. A spelled out suffix always outranks a terse
one.

Fonts whose names carry a version number, such as
`TerminusTTFWindows-Bold-4.49.3.ttf`, share no stem with their siblings and
need the explicit keys.

## Variable fonts

A variable font is several faces in one file, so a family that ships two of
them ships four:

| slot | file | built at |
|---|---|---|
| regular | `Merriweather[opsz,wdth,wght].ttf` | `wght 400` |
| bold | `Merriweather[opsz,wdth,wght].ttf` | `wght 700` |
| italic | `Merriweather-Italic[opsz,wdth,wght].ttf` | `wght 400` |
| bold italic | `Merriweather-Italic[opsz,wdth,wght].ttf` | `wght 700` |

A slot is built at the instance the font names, not at the file's default. That
distinction is the whole point: Merriweather's default instance is `wght 300`,
its Light, so a build that takes the file as it comes ships a Light face and
calls it Regular. Rasterizing "Handgloves" at 13 pt gives 836 dark pixels from
the default, 1043 at the named Regular and 1337 at Bold.

A font that names no instance for a slot falls back to the CSS weights, 400 and
700, clamped to what its axis offers. A `wght` axis stopping at 500 builds its
bold there. A font whose axis has no room above its default has no bold in it
at all, and the slot is left empty rather than filled with the same glyphs
twice. A file for the slot always wins, because a drawn bold beats an
interpolated one.

`opsz` follows the size being built. The optical size axis exists to be set to
the size you are rendering at, so a four size build sets it four times, clamped
to the axis range. Merriweather's starts at 18 pt, so a 12 to 15 pt build
clamps to 18 at every size. A face whose range reaches down to 7 gets its true
text cut at each one.

To pin a slot's coordinates, put them after the filename:

```ini
# a family whose text weight is the one its designer called SemiBold
regular    = Merriweather[opsz,wdth,wght].ttf@wght=600
bold       = Merriweather[opsz,wdth,wght].ttf@wght=900
```

Several axes are comma separated (`@wght=600,opsz=24`), values are clamped to
the axis range, and an axis the font does not have is an error naming the ones
it does. An explicit `opsz` pin replaces automatic optical sizing and is kept
when the preview saves the family, even though the preview has no optical-size
control.

The coordinates are part of what decides a rebuild. Two slots sharing a file
have the same content hash, so without them, moving a weight would leave every
size looking current.

## Rebuilds

Only sizes whose inputs changed are rebuilt. Each family directory carries a
`.crossglyph.json` stamp holding one digest per size, covering the source
fonts' contents, the resolved settings, the converter and its `CPFONT_VERSION`.
Contents rather than timestamps, because fonts arrive by copy, download and
rsync, and all three hand back a fresh mtime for unchanged bytes.

A size disappears from the config and its `.cpfont` goes with it. A whole
family disappears, because you dropped `sizes_mod` or renamed it, and its
directory is removed too. Any build does this, not only a build of everything:
what the output folder should hold is what the workspace produces, which does
not depend on which family you happened to ask for.

Two things are never removed. A directory with no stamp of ours was not built
here, so anything you put in the output folder by hand is safe. And a family
whose config still names it keeps what it built even when it cannot build
today, because a face that has gone missing is the one reason its fonts could
not be replaced.

`--force` ignores the stamps. A failed size is left out of the stamp, so the
next run retries exactly that one.

## What a built family says about itself

The same `.crossglyph.json` carries a `built` block recording how the family
was made. A family folder is a thing people copy, onto a card, into a zip, or
to somebody who liked how it looked, and what travels with it is four
`.cpfont` files whose only metadata is a name and a size. This is the rest.

```json
"built": {
  "at": "2026-08-15T08:44:43Z",
  "by": "crossglyph X.Y.Z",
  "cpfont_format": 4,
  "config": "bitter.conf",
  "settings": {"gamma": 1.0, "hinting": "light", "figures": "proportional", …},
  "sources": {
    "regular": {"file": "Bitter[wght].ttf", "sha256": "ef2b9a71…",
                "name": "Bitter", "version": "Version 3.021",
                "designer": "Sol Matas, and Bitter project Authors",
                "licence_url": "https://openfontlicense.org",
                "instance": {"wght": 500.0}, "instance_name": "Medium"}
  },
  "fallbacks": ["NotoSans-Regular.ttf", …],
  "files": {"12": {"file": "Bitter_12.cpfont", "bytes": 1162006,
                   "glyphs": 3095}}
}
```

Every setting, not only the ones a config set. Defaults move between versions,
so a record of the departures alone would reproduce a different font later and
neither copy could say which one shipped.

Some of it is there for a reader rather than for a rebuild. `sha256` is what
says whether the face you have is the face this was made from, where a version
string is a claim and a filename is a label. `licence_url` and `designer` are
the first two questions a font someone handed you raises. `glyphs` answers
what is in it without opening anything. `instance` is which face of a variable
file a slot was drawn at, without which a reproduction of a Merriweather build
comes back visibly lighter and nothing says why, with `instance_name` beside
it, because "Medium" is what somebody searching for that face would type and
`wght 500` is what they would have to translate first. The `subfamily` cannot
stand in for it: on a variable file that describes the default instance, which
is Thin for Bitter and not what anybody built. And `point_size` appears for
a fractional size, because the filename cannot hold one: the device parses the
label with `strtol`, so a family built at 13.5 ships as `_14`.

A `synthesized` block appears above `fallbacks` when a face needed repairing,
and says how much: `"synthesized": {"arabic_forms": 125}` is a build of
Scheherazade New, which stores joining rules rather than joined shapes.
`arabic_forms` counts the shapes the build resolved by running a face's own
shaping instead of reading its character map, across every face it drew from,
the fallbacks included. A face that already carries those shapes contributes
nothing, so an Arabic build whose only Arabic face is the bundled Noto one has
no such block. Nothing switches the repair on, so without this line a `.cpfont`
holds glyphs at codepoints no source face carries and nothing in the workspace
says where they came from.

It is written when a build produces something, so a folder that is already
current keeps the record of the run that made it. Nothing reads it back yet.
It is written because the time to record how something was made is while you
still know.

Sizes are rasterized in parallel, one process each. The default is a worker per
core less one, so the machine stays usable while a build runs, and never more
than twelve however many cores there are. `-j` changes it. One size on its own
skips the pool, since starting an interpreter to do a job this process could
have done costs more than the job. The
converter's own progress output is captured and shown only on failure, because
a dozen concurrent streams interleave into nonsense.

The preview's Build button runs the same pool, so both take about the same
time: eight sizes of Literata are 17s one at a time and 3s across eight
workers.

## Which converter this drives

The website at `https://crosspointreader.com/fonts` does not run the firmware's
font script. It runs a fork of it, and `src/crossglyph/cpfont/` is a fork of
that:

| | firmware | website | here |
|---|---|---|---|
| path | `lib/EpdFont/scripts/` | `scripts/font-builder/` | forked from the website's |
| base coverage | none implicit | `base` always injected | as the website |
| presets | `ascii`, `latin1`, `cjk`, `builtin`, `punctuation` | `default`, `arabic`, `thai`, `bengali`, `cjk-sc`, `cjk-tc`, `cjk-jp` | as the website |
| fallbacks | one per style | two user families and thirteen bundled Noto | as the website, plus the space font and the pan-CJK face on demand |
| sizes | whole points | four whole points, with 8 and 10 appended to a CJK build | as many as you like, `13.5` included, and a second family at other sizes |
| variable fonts | the file's default instance | the file's default instance | the instance the designer named for the slot, `opsz` following the size, coordinates pinnable per slot |
| quantizer | fixed | `--darken-aa`, one darker preset | `gamma` and all three `thresholds` |
| outline and pixel grid | `--force-autohint` | `--force-autohint` | `weight`, `slant`, `hinting` in four modes, `grayscale_hinting`, `mono`, `stem_darkening` |
| metrics | the font's own | the font's own | `line_height` in three units, `letter_spacing`, `word_spacing` |
| pair tables | always on | always on | `kerning` as a factor, `ligatures` off, `figures = proportional` |

The fourteen in the last four rows are what the fork is for. One of them came
from upstream and the rest are new here: `figures` is the firmware's `--pnum`,
and that flag sits in the script for the built-in fonts, not in the SD card
script the other two columns are, so the website never had it either.

With default settings the fork produces byte identical output to the website's.

The converter is one layer of this. Everything the workspace puts around it is
also ours: [config files with shared defaults](#allconf-the-shared-defaults),
[discovery rules the website's picker does not have](#auto-discovery),
[the fixed width spaces](#the-fixed-width-spaces),
[content-hashed rebuild stamps and a process per size](#rebuilds), and the
[preview](preview.md), which draws a page with the firmware's own renderer
while you move a knob.

`uv run tools/refresh_cpfont.py` pulls upstream and prints a diff to merge by
hand. It never overwrites, since the fork has diverged deliberately.
`src/crossglyph/cpfont/UPSTREAM` records the pinned commit. The converter's
SHA-256 and its `CPFONT_VERSION` are part of every build stamp, so a merged
change rebuilds rather than leaving stale output behind.
