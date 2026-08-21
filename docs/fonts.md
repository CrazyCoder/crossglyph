# Building fonts

A build turns your TTF or OTF files into `.cpfont` files, one for each point
size. A `.cpfont` holds a picture of every character at that size, in the four
greys the screen draws, along with the tables that space pairs of letters and
join `fi` into one shape. The device cannot scale type itself, which is why
each size is a separate file.

Three words run through this page. A family is what you pick on the device,
such as NotoSans. A style is one of its four slots: regular, bold, italic and
bold italic. A face is the file that fills a slot.

Settings live in one `<family>.conf` per family, in the workspace's `conf`
folder. Plain `key = value`, no section header, `#` and `;` start comments.
Every key is optional, and the shortest useful config is empty. The preview
writes the same files, so nothing here belongs to the command line alone.

```sh
./crossglyph.sh build             # everything that changed
./crossglyph.sh build --list      # what each config resolves to, building nothing
./crossglyph.sh build notosans    # one family, by config name or family name
./crossglyph.sh build --force     # ignore the stamps
```

## all.conf, the shared defaults

A file named `all.conf` in `conf` is not a family, and is not required. It
starts absent: `all.conf.example` beside it is a commented list of every key
it can hold, to copy when you want one. The preview writes `all.conf` too,
when you save a family it covers without naming.

It holds settings shared by every family in the workspace. A `<family>.conf`
inherits from it and states only what it does differently, and a family with no
config at all is built from it alone. Delete it and nothing changes.

Discovery does not depend on it either. Drop the four style files in the
workspace and they build on the next run, taking their name from the
filenames alone.

Subfolders are walked, so a family that arrives as a folder can stay one. The
folder is organization and nothing else. A face is known by its filename
wherever it sits, so `serif/Charis-Bold.ttf` is Charis' bold exactly as
`Charis-Bold.ttf` at the root would be. A folder holding `Regular.ttf` and
`Bold.ttf` builds two families called Regular and Bold, and neither takes the
folder's name. Rename the files. The folder name is never read.

Four folders are left alone. `conf` holds configs, `cpfonts` holds builds, and
`fallbacks` holds the Noto faces that fill holes in other families without
being families themselves. Anything beginning with a dot belongs to something
else.

`all.conf` cannot set `name`, `family`, or the explicit style and fallback file
keys. Each of those names one specific family or file, so they are rejected
there.

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
fallback_order = NotoSerif, bundled
space_glyphs   = yes
thresholds     = 4 8 12
hinting        = normal
regular        = NotoSans-Regular.ttf
bold           = NotoSans-Bold.ttf
italic         = NotoSans-Italic.ttf
bolditalic     = NotoSans-BoldItalic.ttf
```

#### What the family is, and which files it is made of

| key | default | meaning |
|---|---|---|
| `name` | the discovered family | family name on the device, and the filename prefix. Non-alphanumerics are stripped |
| `family` | the config filename | the stem to match source files against, when it differs from the filename. `name` does not affect it |
| `dir` | the workspace root | where to look for the font files |
| `regular` `bold` `italic` `bolditalic` | auto-discovered | name a file explicitly, relative to `dir`. `file.ttf@wght=600` pins a [variable font's](#variable-fonts) coordinates |

#### What gets built

| key | default | meaning |
|---|---|---|
| `sizes` | `12 14 16 18` | point sizes to build. Fractions are allowed, see below |
| `sizes_mod` | none | more point sizes. They join this family when `mod_suffix` is empty, and build `<name><mod_suffix>` otherwise |
| `mod_suffix` | `Mod` | what the second family's name ends with. Set to nothing and `sizes_mod` joins the first family instead |
| `out` | `cpfonts` | in `all.conf` only: where builds go, resolved against the workspace |

#### Which characters go in

| key | default | meaning |
|---|---|---|
| `intervals` | `reading` | preset names, comma separated. `reading` already contains `default`, `latin-ext`, `symbols` and `vietnamese`, and the panel shows those as carried rather than as ticks of yours. `intervals =` with nothing after it is the narrowest build there is, since `base` is carried whatever this says |
| `ranges` | none | raw `(0xAAAA-0xBBBB)` ranges, appended to `intervals` |
| `space_glyphs` | `yes` | add the fixed width spaces (U+2000 to U+200A, U+205F, U+3000) |
| `space_width_XXXX` | per Unicode | override one fixed width space as a fraction of an em: `space_width_2006 = 0.25` |

#### Where a missing character comes from

| key | default | meaning |
|---|---|---|
| `fallbacks` | `no` | append the bundled Noto families, and the pan-CJK face when `intervals` names a CJK script. A face you have not fetched is skipped, and the build says which, along with any preset that drew nothing. See [When a tick draws nothing](#when-a-tick-draws-nothing) |
| `fallback_order` | none | the fallback families and their order, comma separated. `bundled` stands for the set above. Behind the two keys below, which are always in front. Inert while `fallbacks` is `no`, since there is no chain to order. See [Which face a fallback lends](#which-face-a-fallback-lends) |
| `fallback_regular` `fallback2_regular` | none | your own fallback families, ahead of the bundled ones |
| `fallback_dir` | `fallbacks` | in `all.conf` only: a Noto set shared between workspaces |

#### How a glyph is drawn

| key | default | meaning |
|---|---|---|
| `gamma` | `1.0` | curve applied to glyph coverage before it is quantized, `1 - (1 - coverage)ᵞ`, so above 1 darkens. The most useful single control, see [Tuning how glyphs look](#tuning-how-glyphs-look) |
| `thresholds` | `4 8 12` | the three 4-bit cut points for grey levels 1, 2 and 3. Any ascending triple within 1 to 15. `3 6 10` is the set the built-in fonts use, and the preview offers it, `4 8 12` and `2 5 9` |
| `weight` | `0` | outline emboldening in pixels. Advance widths do not move, so text gets heavier at the same spacing |
| `slant` | `0` | shear as a tangent. `0.25` is about 14 degrees, for synthesizing an oblique a family lacks |
| `hinting` | `normal` | `normal`, `light` (vertical only, softer), `none`, or `auto` (FreeType's auto-hinter, worth trying when a font looks muddy at small sizes) |
| `grayscale_hinting` | `no` | run FreeType's interpreter version 35, which fits stems on both axes rather than hinting for a subpixel display. Only reaches a TrueType face carrying bytecode, under `hinting = normal` and with `mono` off. See [Tuning how glyphs look](#tuning-how-glyphs-look) |
| `mono` | `no` | rasterize each glyph as one bit per pixel, with FreeType's dropout control, instead of thresholding coverage. The font then draws in two levels whatever the reader's anti-aliasing setting is. See [Tuning how glyphs look](#tuning-how-glyphs-look) |
| `stem_darkening` | `no` | FreeType stem darkening. Narrow: a CFF or OTF face under any hinting but `auto`, and a TrueType face only under `hinting = light`. See [Tuning how glyphs look](#tuning-how-glyphs-look) |

#### How the text is spaced

| key | default | meaning |
|---|---|---|
| `line_height` | the font's own | line pitch. `1.15` is em relative, `0.9x` is a multiple of the font's own, `26px` is absolute. See [Line spacing](#line-spacing) |
| `letter_spacing` | `0` | tracking in pixels, added to every glyph's advance. Stored at 1/16 px, and negatives tighten |
| `word_spacing` | `0` | added to the space on top of `letter_spacing`, as CSS word-spacing is |
| `kerning` | `yes` | GPOS kerning: `yes`, `no`, or a factor such as `0.5`. A face kerned for print often over-tightens at 12 or 13 px |
| `ligatures` | `yes` | GSUB ligatures. `fi` and `fl` often blur into one blob at four grey levels |
| `figures` | `default` | `proportional` applies the font's GSUB `pnum` feature, so a `1` stops being padded to the width of a `0`. See [Proportional figures](#proportional-figures) |

The four explicit style keys are the exact equivalent of the four upload slots
on the CrossPoint font website. Auto-discovery is a convenience on top of them.
When it guesses wrong, name the files.

### The same settings in the preview

The preview writes these keys, and it labels them for a reader. Most of the
tuning controls carry the key's own words, so only the ones that differ are
here:

| in the preview | in a `.conf` |
|---|---|
| **name**, under Export | `name` |
| the four **sizes** boxes, and **more sizes** | `sizes` |
| **second family**, its sizes and its **suffix** | `sizes_mod`, `mod_suffix` |
| the **coverage** ticks | `intervals` |
| **extra ranges** | `ranges` |
| **bundled fallback faces** | `fallbacks` |
| **fallback 1**, **fallback 2** | `fallback_regular`, `fallback2_regular` |
| **mono rasterizing** | `mono` |
| **output** | `out`, in `all.conf` |
| **use the font's own**, beside line height | `line_height` left unset |
| the **text** and **bold** pickers, on a variable family | `regular` and the rest, with `@wght=` on them |

Some keys have no control. `dir`, `family`, `space_glyphs`, `space_width_XXXX`,
`fallback_order` and `fallback_dir` are settings you write in the file, and the
preview reads them and builds accordingly. `fallback_order` is the one you are
most likely to want: see
[Which face a fallback lends](#which-face-a-fallback-lends).

The preview writes the `.conf` before every build, so pressing **Build**
saves first. Whatever is on screen gets built.

## Sizes

CrossPoint's **Settings > Reader > Font Size** lists every size the active
family carries, one entry each. It is a point size that is stored and shown,
not an abstract small, medium or large slot.

`sizes_mod` is more sizes from the same faces. Where they land depends on
`mod_suffix`:

```ini
sizes      = 12 14 16 18
sizes_mod  = 13 15 17 19
mod_suffix =                 # one family, NotoSans, at all eight sizes
```

```ini
sizes      = 12 14 16 18
sizes_mod  = 13 15 17 19     # two, NotoSans and NotoSansMod
```

An absent `mod_suffix` is the default `Mod`, and a `mod_suffix` set to nothing
is the choice. Nothing on the device limits how many sizes one family carries,
so a second family is for when two entries in the font list suit you better
than one entry with a long list of sizes under it. Merged, the two lists write
one set of files, so two sizes that land on the same label are refused across
both.

Three sizes belong to the interface rather than to the page. Its own fonts are
8, 10 and 12 pt, measured at the 150 DPI this converter works in, and where the
interface has to draw CJK it borrows the selected family at the matching size
(`kUiFontSizes` in `SdCardFontSystem.cpp`). A default build carries 12 already,
so a CJK family wants the other two added:

```ini
sizes = 8 10 12 14 16 18
```

Without them a CJK book title has nothing to draw with in the menus, since the
reader only sets up the borrowing for a size the family actually carries. It
tests the family for Han, Hiragana, Katakana and Hangul first and skips the
whole arrangement when it finds none, so a Latin or Cyrillic family needs no
extra sizes and pays nothing for these. The website appends 8 and 10 to a CJK
build for you. Here they are yours to list, since a size list of any length is
yours to write.

### Fractional point sizes

`sizes` takes fractions such as `13.5`, and each one is a real rasterization at
that size. At 150 DPI a point is 2.08 px/em, so consecutive whole sizes are
about 10% apart at reading sizes: 13 pt sets `advanceY` 31 and 13.5 pt sets 32,
a step you cannot otherwise reach.

The filename carries the rounded label and never the size itself. The device
parses the size out of the filename with `strtol` into a `uint8_t`
(`SdCardFontRegistry.cpp:85`), so a fractional size could not be named there.
Nothing reads a point size out of the file, so `sizes = 13.5` writes
`Family_14.cpfont`, and the device offers "14" while rendering 13.5 pt glyphs.
Rounding is half up. `--list` and the line each size prints as it is built both
name the label when it differs from the size, so you can see which file a build
is about to write, or has just written:

```
  -> Family: 13.5 (ships as 14) 16
  Family 13.5 (ships as 14) (0.4 MB, 354 glyphs, 3s)
```

Two sizes that round to the same label would overwrite each other, so they are
refused: `sizes = 13.5 14` is an error.

The separator here is a comma or a space, which makes a decimal comma two
sizes. `sizes = 13,25` builds 13 pt and 25 pt, and nothing can tell that apart
from a request for exactly those two. Write the fraction with a dot. The
website's size boxes hold one size each and do read a comma as a decimal point,
because there the two cannot be confused.

## Coverage

Coverage is the list of characters that go into the file. Every character has a
number that identifies it, called a codepoint, and a preset such as `greek` is
a named set of those numbers. Anything you leave out is not in the font, and
the device draws nothing at all where it appears.

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

CrossPoint picks it and then looks that shape up by a separate codepoint,
because the device has no room for the rule engine a font's own joining rules
need. Fonts split into two camps on this. Older ones store every shape under
its own codepoint, and that is what the device expects. Newer ones, including
most good Arabic faces today, store one shape plus the rules, so the device
finds nothing where it looks. Scheherazade New and ReadexPro are in the second
camp, and they drew a page of blanks, or of replacement boxes wherever the
build had one to draw.

So the rules are run here instead, once, while the font is built, and each
resulting shape is stored where the device will ask for it. This is automatic.
There is no setting, and it works with any Arabic face. Some faces spell a
letter as a base plus a separate mark, which is how the alef with hamza and the
alef with madda are usually drawn; those pieces are combined into one picture
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

A face named in **fallback 1** (`fallback_regular`) is repaired the same way,
so a Latin family
that borrows its Arabic from one still gets joined text.

The built family records what it repaired, under `synthesized` in
`.crossglyph.json`, so a font never carries shapes that nothing in the
workspace explains.

A single glyph cannot exceed 255 pixels on either side, because that is what
the `.cpfont` format has room for. One glyph in practice reaches it: the
bismillah at U+FDFD, an entire phrase drawn as one ornament rather than a
letter. In Noto Sans Arabic it is 244 pixels wide at 12 pt and passes the
limit at about 12.6, so every ordinary reading size above 12 pt drops it. The
build says so, naming the codepoint and the size it measured, and carries on.
A glyph the device could not store draws nothing there either way, and one
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

### Which face a fallback lends

A fallback is a family and not a file. For each style, an entry lends its own
face for that style where the folder has one, and its regular face otherwise.
So a symbol borrowed into a bold run is drawn from the bold face when there is
one to draw it from.

The fetched set carries NotoSans in four styles and every other family in one.
Noto publishes a bold for some of them and an italic for NotoSans alone, so the
rest would be a megabyte each for a slot they cannot fill. Anything you add to the fallbacks folder yourself is picked up the same
way: drop `NotoSerif-Bold.ttf` beside a `NotoSerif-Regular.ttf` that a config
names, and the bold style starts using it.

`fallback_order` names the families and the order they are asked in:

```ini
fallbacks      = yes
fallback_order = NotoSerif, bundled
```

Three rules cover the key. The list is the chain. `bundled` stands for the
fetched set. A face appears once, at its first position. Leave `bundled` out
and the list is the whole chain. Write it that way to drop a family from the
set, or to reorder the set itself.

`fallbacks = yes` above it is not decoration. `fallbacks` is what turns the
chain on, and with it off there is nothing for `fallback_order` to order.

The two families you pick in the panel are always in front of all of it, so a
config never has to account for them. Naming one of them in `fallback_order`
as well changes nothing: it is already in the chain, and the second mention is
a repeat.

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

Each width can be overridden per family, as a fraction of an em. An em is the
font's own design square, the box every character is drawn inside, so a width
written this way scales with the point size. Use it when the typographic
default reads wrong at your size:

```ini
space_width_2006 = 0.25    # widen the dialogue dash space from 1/6 em
```

The widths are settable and the set of codepoints in the table is fixed. U+00A0
and U+202F are rewritten into a plain space before layout, so the device never
asks a font for them, and a codepoint outside the table is rejected out loud.

The face itself is generated, and it is an input to a build and never something
to put on a card. It lives in the temporary directory, named for a digest of
the widths in it, and a build makes it if it is not already there. A width
edited here therefore produces a different file, and nothing lands in the
folder you copy across.

## Tuning how glyphs look

Every pixel on the reader's screen is white, black or one of two greys, and
nothing else. FreeType draws a character in far more shades than that, so each
pixel has to be squashed down into one of the four. A face gains or loses its
character in that step, and `gamma` and `thresholds` are the two controls over
it.

In order: FreeType renders the outline as coverage, meaning how much of each
pixel the letter actually sits on, at 150 DPI, so 13 pt is 27.08 px/em, which
is to say the design square comes out 27 pixels across. `gamma` bends that
coverage, the result is rounded to 16 steps, then `thresholds` cuts those steps
into the four levels the device stores.

### Gamma

`gamma` is the darkness control. Raise it and the page inks more heavily; lower
it and a face that sets too black at small sizes lightens off.

A useful `gamma` runs 0.3 to 4.0. That is the range crengine offers for the
same curve, and it computes the curve the same way: `255 - ((255 - i)/255) **
gamma * 255`, in `Tools/GammaGen/gammagen.pl`. The exponent bends how much
white is left behind. A bigger number therefore gives a darker page, where
plain gamma arithmetic on the ink would lighten it.

crengine ships that range as 48 fixed steps, and their spacing is the useful
part: 0.05 up to 0.95, then 0.98, 1.00, 1.02, 1.05, then 0.05 again to 1.5,
0.1 to 3.2, and 0.2 to the top. They crowd where the eye can tell one from the
next and spread out where it cannot. Here the knob is a plain number stepping
by 0.05, that scale's finest step, so any of crengine's levels can be typed in
and the ones between them work as well. What it does is not uniform across that range. Up to about 2 it darkens.
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

### Thresholds

A threshold is the point where a pixel stops being one grey and becomes the
next one darker. There are three of them, because there are three levels above
white, and where you put them decides how much of the page comes out solid
black rather than grey.

**All three are yours to set, and the panel offers two of them by name.** Any
ascending triple within 1 to 15 is accepted, so `5 9 13` is as valid as the
default. The panel's **thresholds** row lists three, each a step darker than the last:
default (4, 8, 12), darkened (3, 6, 10) as the built-in fonts have it, and
darkest (2, 5, 9). Write your own triple in the `.conf` and the row grows
an entry for it, `custom (5, 9, 13)`, so loading a family never quietly rounds
its tuning to one of the three.

The first cut spreads the ink, and it is the only one that survives the reader
turning anti-aliasing off. Measured over a mixed Cyrillic
and Latin page at 13 pt, the three sets ink 3.62%, 3.93% and 4.22% of the
screen. Going darker than that stops being legible before it stops being
possible, which is why the list ends where it does.

Which of the three cut points matters depends on the reader's
**Settings > Text > Anti-Aliasing** switch. With it on, all three are live and
the page is drawn from two grey planes. With it off, `GfxRenderer` paints every
non-zero level solid black (`GfxRenderer.cpp:449`), so only the first threshold
has any effect and lowering it fattens the text.

Measured at 13 pt over a mixed Cyrillic and Latin sample of 5838 inked pixels.
Mean coverage does not move: thresholds redistribute what FreeType already
produced, and change none of it:

| thresholds | mean coverage | level 0 | 1 | 2 | 3 (black) |
|---|---|---|---|---|---|
| `4 8 12` (default) | 6.03 | 2950 | 608 | 414 | 1866 |
| `3 6 10` (the built-in fonts') | 6.03 | 2866 | 234 | 689 | 2049 |

### Weight, slant and the hinting knobs

`weight`, `slant`, `hinting`, `grayscale_hinting` and `stem_darkening` act
earlier, on the outline itself, so they change the coverage that then gets
squashed into four levels.

Hinting is the one to understand first. A letter's outline rarely lands on
whole pixels, so an upright stem can straddle two of them and come out as two
pale columns instead of one dark one. Hinting nudges the outline onto the grid
so that stops happening. A font can carry its own hinting instructions, and
FreeType can also work them out for itself, which is what `auto` asks for.

Three of these are worth a note.

`weight` uses `FT_Outline_Embolden`, which fattens the outline and leaves the
advance width alone. Text gets heavier at unchanged spacing. That is right at
reading sizes, and it is no substitute for a real bold face.

### Stem darkening

Stem darkening thickens the strokes a little, to make up for how thin type
looks once it is drawn small. `stem_darkening` is narrower than its name
suggests, and where it applies depends on `hinting` as much as on the font.
FreeType has the code in two engines, and each adds a condition on top of the
setting. The Adobe CF2 interpreter, which draws CFF and Type 1 faces, darkens a
scaled load. The auto-hinter darkens at a light target. So a CFF or OTF face
moves under any hinting but `auto`, while a TrueType face has no CF2 path and
moves only at `hinting = light`, the one setting that hands it to the
auto-hinter. Under `auto` neither format moves: it targets normal hinting, and
the auto-hinter reloads the glyph unscaled, failing both conditions at once.

The two are not the same size either. Through CF2 the effect is slight, well
under a percent of the set pixels; through the light auto-hinter it is
substantial. That was measured over 132 faces on FreeType 2.13. The preview
greys the switch when the pair you have chosen is one of the cases that cannot
move, and leaves the rest live without promising anything: a CFF face whose
stems fall where the darkening curve rounds to nothing is unmoved as well, and
nothing short of rasterizing both ways would know.

### Grayscale hinting

A font's own hinting instructions are a small program, and FreeType has two
interpreters that can run one. `grayscale_hinting` picks the one written for
grey screens instead of colour ones.

The default is version 40, which FreeType calls roughly equivalent to
DirectWrite ClearType. It hints vertically only, because on a subpixel display
snapping a stem sideways costs more than it buys. Version 35 fits both axes,
and FreeType documents it as supporting grayscale and black and white
rasterizing only. That is all this device does. A stem then lands on a pixel
instead of straddling two and being drawn twice in grey. Measured over 303
hinted faces it leaves 3.8% fewer midtone pixels, and a third fewer on a face
like DejaVu.

It is narrow in the same way `stem_darkening` is, for a different reason: it
reaches a face only while that face's own bytecode draws it. A CFF family has
none. A TrueType family with no glyph instructions goes to the auto-hinter
anyway, and so does any family under `light`, `auto` or `none`. So this is a
`hinting = normal` control on a TrueType face, and the preview greys the row
everywhere else.

`mono` takes it as well, for a reason of its own. FreeType turns backward
compatibility off whenever the raster is monochrome, which its own source
calls falling back to version 35 behaviour, and that behaviour is the whole
difference between the two interpreters. So under `mono = yes` both settings
draw the same glyph, and the row greys there too.

### Mono rasterizing

`mono` builds a font with no greys in it at all: every pixel comes out black
or white. What decides each one changes too.

Normally the converter takes FreeType's coverage and cuts it at the three
thresholds, and the reader with anti-aliasing off then paints every non-white
level solid black: a pixel a quarter covered goes black, which at 12px fattens
strokes into each other. With `mono` on, FreeType rasterizes at one bit per
pixel and decides each one with dropout control instead, a rule that keeps a
stroke too thin to land on a pixel from vanishing altogether. Measured on
DejaVu Serif at 12px that is a third less ink, and none of the ink that was
holding the letters open.

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

Line pitch is the distance from one line of text down to the next. It is stored
in the font, and the device does not decide it. `getLineHeight()` is `advanceY`
from the `.cpfont` times a compression factor (`GfxRenderer.cpp:2005`), and for
SD card fonts that factor is 0.95, 1.00 or
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
place the baseline inside the line, and underline, strikethrough, ruby and
superscript offsets are all measured from them (`TextBlock.cpp:185-219`). Set
the pitch below what those two span and consecutive lines can collide. The
build says so and carries on, because tight leading is sometimes the point:

```
warning: line_height 8px is under the 29px this font's ascender and
descender span, so consecutive lines may overlap
```

That warning is raised only for a pitch you asked for. A font whose own
declared band exceeds its own pitch is not unusual: NotoSans has a negative
`lineGap`, spanning 35 px against a 34 px pitch, and those are worst case
bounds that adjacent lines rarely both reach.

## When the reader will not load the font

A font can build cleanly and still be one the reader refuses. There is nothing
to see when it happens: the family appears in **Settings > Reader > Font**, you
select it, and the reader goes on drawing in its own font at 12, 14, 16 and 18
however many sizes you built. Nothing says the font was rejected.

CrossGlyph checks for this. The panel says so under the coverage boxes while
you are still ticking them, and a build refuses to write a file that cannot
load.

### What the reader counts

A `.cpfont` does not store a list of characters. It stores **runs of
consecutive characters**, because that is far smaller: `A` to `Z` is one entry
holding a start and an end, not twenty-six entries. CrossPoint loads at most
4096 of these runs per style, along with 65,536 characters and 4096 kerning
entries a side (`SdCardFont.cpp`, where the comment gives the reason as
rejecting malformed files before allocating memory for them).

A file over any of those limits is refused whole, and the three steps that
follow are the ones you cannot see:

- `SdCardFontSystem::ensureLoaded()` fails to load the family and calls
  `clearSdFontFamily()`, which empties the setting naming it.
- `readerFontPointSizes()` sees an empty name and returns the built-in ladder,
  `{12, 14, 16, 18}`.
- The family is still in the list, because the list comes from scanning the
  folder names on the card and never opens a file.

So the font looks installed and behaves as though you had never built it.

### Why a font ends up with too many runs

Gaps. A font that covers a range completely is one run. A font missing
characters in the middle of that range splits it in two, and a font that
covers a range in scattered patches costs one run for every patch.

A sparse fallback does exactly this. Pointing **fallback 1**
(`fallback_regular` in a config) at a language-specific CJK face and ticking
the CJK presets asks for tens of
thousands of characters from a face that has a few thousand of them, scattered.
Measured on one such build:

| coverage | runs | |
|---|---|---|
| as built | 4390 | refused |
| the same, minus `cjk-tc` | 4194 | refused |
| minus `cjk-tc` and `hangul` | 4192 | refused |
| the same, with `fallbacks = yes` | 64 | loads |
| no CJK presets at all | 123 | loads |

**Unticking presets is the move that does not work.** Two presets came off and the
count moved by 198. The count is not about how much you asked for. A build with 43,588 characters in it loads while one with
17,546 does not, when the second one gets them in pieces.

### What to do about it

**Turn on bundled fallback faces** (`fallbacks = yes`). The bundled set
includes a pan-CJK face
that covers those blocks completely, so the holes your own fallback leaves are
filled and the runs on either side of each hole join up. That is the 4390 to 64
row above, and it is the same characters either way.

The box is off by default (`fallbacks = no`), and that keeps a first build
small and self-contained. It also costs you this. With the set off, whatever
you put in **fallback 1** is the only face behind your family, gaps and all.

Failing that, put a face in **fallback 1** that covers the range you ticked
without gaps, or untick the range.

### Where you are told

- **In the panel**, under the coverage boxes, as soon as a tick pushes the
  count over. It carries the count, the limit, and what the same coverage would
  cost with the bundled faces on when that is under the limit.
- **On the command line**, once per family before the build starts, with the
  same figures. Those sizes are not built and the exit code is 1.
- **In a build either way**, since the converter refuses to write a file over
  any of the three limits. That check runs before any character is rasterized.
  It costs a second, where finding out on the device costs a card swap.

## When a tick draws nothing

A coverage preset can come out empty. Tick Greek on a Latin-only family with
the fallbacks off and the font builds, the glyph count moves not at all, and
the Greek codepoints you asked for are simply absent. The build says so,
once per family, under that family's sizes:

```
  Bitter 13 (0.4 MB, 3812 glyphs, 2s)
  Bitter 16 (0.6 MB, 3812 glyphs, 2s)
  Bitter: nothing in this build draws thai or bengali.
    NotoSansThai-Regular.ttf is in the fallbacks folder and this build did
    not open it.
    Set `fallbacks = yes`, or put `bundled` back in `fallback_order`.
```

Three answers, and the build works out which one applies. A face sitting in
the fallbacks folder that this build never opened is named by filename, and
either `fallbacks = no` or a `fallback_order` without `bundled` in it puts a
family there. A folder short of faces sends you to `crossglyph fetch-fallbacks`,
and to `fallbacks = yes` as well where the family is not reading the set
anyway. A complete folder that still draws nothing leaves **fallback 1** and
dropping the tick.

A family that produced no file at all leaves coverage out. Every size failed.
That is the line to read, and a note about an empty range would sit on top of
it.

Falling short does not raise it. Partial is the ordinary state, since a preset
covers codepoints no font assigns: against a fetched set Greek resolves at 92%
and Japanese at 99%, and with the set off an ordinary face covers about a
quarter of `reading`. A warning on those would fire on nearly every build.

The line comes when a tick drew under 2% of the characters in its block, which
is a little wider than nothing on purpose. A preset spans more than the script
it is named for: `cjk-sc` includes the fullwidth punctuation, and every Latin
serif measured for this draws one of the codepoints `arabic` spans. Testing
for an exact zero passed all of those, so a family with no Arabic and no CJK in
it said nothing at all. Where a tick drew a handful rather than none the line
says "almost nothing" instead.

A run with nothing left to build says it too. The fonts are on the card and the
range they cannot draw is as empty as it was, so a gate that only saw what this
run wrote would pass on the second attempt whatever it said on the first.

**The exit code stays 0.** A build that wrote usable fonts succeeded. The
empty range is a fault in the config, and the run carried the config out. Pass
`--fail-on-warning` to return 1 instead, for any warning the build raises. The
gate comes after the writing, so every `.cpfont` the run planned is on the disk
either way.

In the preview the same warning appears under the build buttons, worded as the
controls on the panel. It names the tick, and offers the box or the Fetch
button where one of those is the answer.

## Letter and word spacing

An advance is how far the pen moves along after drawing a character.
`letter_spacing` and `word_spacing` adjust those the way `line_height` adjusts
the gap between lines, at build time and in the file. Both are in pixels,
stored at 1/16 px, and both accept negatives. Word spacing stacks
on letter spacing exactly as CSS does, and the device takes the word gap from
the font's own U+0020 glyph (`GfxRenderer.cpp:1880`). A little positive
tracking often reads better on e-ink than on a screen.

## Kerning and ligatures

Kerning pulls particular pairs of letters closer, so the A and the V in "AV"
tuck under each other instead of leaving a hole. A ligature replaces a pair
with one drawn shape, which is how a well set `fi` avoids a collision between
the f's hood and the dot on the i. Both come from tables the font carries,
named GPOS and GSUB, and the build reads them and writes the answers in.

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
own family. That is how a Roboto SemiCondensed folder carrying every weight the
foundry ships narrows to the four faces you want.

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

The zip from the Google Fonts website writes the same list a second way, as
`GoogleSans-VariableFont_GRAD,opsz,wght.ttf` with the italic as
`GoogleSans-Italic-VariableFont_GRAD,opsz,wght.ttf`. That one comes off too.
Both spellings give one family with four slots, and neither needs a config.

What marks the suffix as generated is the shape of what follows the word: an
axis tag is four characters, so `Foundry-VariableFont_Display.ttf` keeps its
whole name and is a family in its own right.

### The italic follows the roman's weight

The website drops every extra weight italic such as `MediumItalic`, which is
right when one would fight a plain `Italic` for the slot, and wrong when the
family's roman is itself an extra weight. A family whose roman is
`Name-Medium` pairs with `Name-MediumItalic`, and leaves the lighter
`Name Italic` alone. A family whose roman is `Name-Regular` is unaffected.

### A foundry's series number is not part of the family

Linotype numbers the styles: 65 Medium, 66 Medium Italic, 75 Bold, 76 Bold
Italic, where the first digit is the weight and the second says upright or
italic. The number sits in the stem, so a file that keeps it strips to a
family nothing else shares, and the four never meet. Only a whole number
between the family and a tail of nothing but style words is dropped. That keeps
the rule off a name where the number is the family: `Roboto_Condensed_300` has
no style tail, so it stays a family in its own right.

### Terse suffixes

A terse suffix has no separator: `b` or `bd` bold, `i` or `it` italic,
`bi`, `bdi` or `bdit` bold italic, and `z` bold italic, the one Microsoft's
own core fonts ship (`georgiaz.ttf`, `verdanaz.ttf`, `CALIBRIZ.TTF`). A bare trailing letter is read as a style only when a file
named for the plain family sits beside it. Otherwise `Bodoni.ttf` would be the
italic of a family called `Bodon`. A spelled out suffix always outranks a terse
one.

Fonts whose names carry a version number, such as
`TerminusTTFWindows-Bold-4.49.3.ttf`, share no stem with their siblings and
need the explicit keys.

## Variable fonts

A variable font is not one face but a range of them in a single file. What
varies is set by its axes, each one a dial the designer left open: `wght` runs
from thin to heavy, and `opsz` adjusts the drawing for the size it will be read
at. A family shipping two such files fills all four slots:

| slot | file | built at |
|---|---|---|
| regular | `Merriweather[opsz,wdth,wght].ttf` | `wght 400` |
| bold | `Merriweather[opsz,wdth,wght].ttf` | `wght 700` |
| italic | `Merriweather-Italic[opsz,wdth,wght].ttf` | `wght 400` |
| bold italic | `Merriweather-Italic[opsz,wdth,wght].ttf` | `wght 700` |

A slot is built at the instance the font names, and never at the file's
default. That distinction decides what ships. Merriweather's default instance
is `wght 300`, its Light, so a build that takes the file as it comes ships a
Light face and calls it Regular. Rasterizing "Handgloves" at 13 pt gives 836 dark pixels from
the default, 1043 at the named Regular and 1337 at Bold.

A font that names no instance for a slot falls back to the CSS weights, 400 and
700, clamped to what its axis offers. A `wght` axis stopping at 500 builds its
bold there. A font whose axis has no room above its default has no bold in it
at all, and the slot is left empty instead of filled with the same glyphs
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
directory is removed too. Any build does this, including a build of one
family. The output folder should hold what the workspace produces, and that
does not depend on which family you happened to ask for.

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
  "freetype": "X.Y.Z",
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
  "fallbacks": {"regular": ["NotoSans-Regular.ttf", …],
                "bold": ["NotoSans-Bold.ttf", …], …},
  "coverage": {"reading": {"asked": 2887, "assigned": 2819, "drawable": 2819},
               "greek": {"asked": 400, "assigned": 368, "drawable": 368},
               "thai": {"asked": 128, "assigned": 87, "drawable": 0}},
  "files": {"12": {"file": "Bitter_12.cpfont", "bytes": 1162006,
                   "glyphs": 3095}}
}
```

Every setting, including the ones no config set. Defaults move between
versions, so a record of the departures alone would reproduce a different font
later, and neither copy could say which one shipped.

`freetype` is the version of FreeType that drew the glyphs, read from the
library itself rather than from the Python package that loads it.

Some of it serves a reader instead of a rebuild. `sha256` settles whether the
face you have is the face this was made from, where a version string is a claim
and a filename is a label. `licence_url` and `designer` answer the first two
questions a font somebody handed you raises. `glyphs` says what is in it
without opening anything.

`instance` records which face of a variable file a slot was drawn at. Without
it a reproduction of a Merriweather build comes back visibly lighter and
nothing explains why. `instance_name` sits beside it, because "Medium" is what
you would search for and `wght 500` is what you would have to translate it into
first. The `subfamily` cannot stand in: on a variable file it describes the
default instance, which is Thin for Bitter and not the face that was built.

`point_size` appears for a fractional size, because the filename cannot hold
one. The device parses the label with `strtol`, so a family built at 13.5 ships
as `_14`.

`fallbacks` is per style, since a chain lends its bold face to the bold style
where it has one. Which file a glyph was borrowed from is not one answer for
the whole family, and the record is what a reproduction reads.

### The coverage block

`coverage` holds what each ticked token asked for against what the faces
between them could supply. `settings` records the tokens, so that is the ask
and this is the answer. A zero here is the state the build warns about.

Judge `drawable` against `assigned` and never against `asked`. A preset is
written as whole blocks and blocks have holes: Thai spans 128 codepoints and
Unicode assigns 87 of them, so a face carrying every Thai character reaches 68%
of the block and 100% of the characters in it. Tifinagh caps at 74% the same
way and Hebrew at 82%.

`drawable` counts what the faces have. What the converter packed is a narrower
number, decided per style, and reaching it would cost a second pass over every
glyph. The `glyphs` count under `files` is the packed answer for one size.

### Repaired faces

A `synthesized` block appears above `fallbacks` when a face needed repairing,
and says how much. `"synthesized": {"arabic_forms": 125}` is a build of
Scheherazade New, which stores joining rules in place of joined shapes.
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

## How long a build takes

Sizes are rasterized in parallel, one process each. The default is a worker per
core less one, so the machine stays usable while a build runs, and there is a
ceiling on top of that, so a machine with a great many cores does not start a
process for each. `-j` changes it. One size on its own skips the pool, since
starting an interpreter to do a job this process could have done costs more
than the job. The converter's own progress output is captured and shown only on
failure, because a dozen concurrent streams interleave into nonsense.

The preview's Build button runs the same pool, so both take about the same
time. A family of several sizes finishes in a fraction of what those sizes cost
one after another.

## Which converter this drives

The website at `https://crosspointreader.com/fonts` does not run the firmware's
font script. It runs a fork of it, and `src/crossglyph/cpfont/` is a fork of
that:

| | firmware | website | here |
|---|---|---|---|
| path | `lib/EpdFont/scripts/` | `scripts/font-builder/` | forked from the website's |
| base coverage | none implicit | `base` always injected | as the website |
| presets | `ascii`, `latin1`, `cjk`, `builtin`, `punctuation` | `default`, `arabic`, `thai`, `bengali`, `cjk-sc`, `cjk-tc`, `cjk-jp` | as the website |
| fallbacks | one per style | two user families and the bundled Noto set | the same set, resolved per style and in an order a config can set, plus the space font and the pan-CJK face on demand |
| sizes | whole points | four whole points, with 8 and 10 appended to a CJK build | as many as you like, `13.5` included, and a second family at other sizes |
| variable fonts | the file's default instance | the file's default instance | the instance the designer named for the slot, `opsz` following the size, coordinates pinnable per slot |
| quantizer | fixed | `--darken-aa`, one darker preset | `gamma`, and `thresholds` as any ascending triple from a config or either of two presets in the panel |
| outline and pixel grid | `--force-autohint` | `--force-autohint` | `weight`, `slant`, `hinting` in four modes, `grayscale_hinting`, `mono`, `stem_darkening` |
| metrics | the font's own | the font's own | `line_height` in three units, `letter_spacing`, `word_spacing` |
| pair tables | always on | always on | `kerning` as a factor, `ligatures` off, `figures = proportional` |

The knobs in the last four rows are what the fork is for. One of them came
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
