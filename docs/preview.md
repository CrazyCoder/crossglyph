# The preview

```sh
./crossglyph.sh preview                    # the first family in the workspace
./crossglyph.sh preview --family notosans  # a family by name
./crossglyph.sh preview --font one.ttf     # a file that is in no family
./crossglyph.sh preview --no-open --host 0.0.0.0          # for a container
./crossglyph.sh preview --family notosans --png page.png  # one page, no server
```

`--family` takes a name from the workspace and resolves the four faces exactly
as a build does: from the family's own `.conf` if it has one, from `all.conf`
and the filenames if it does not, honouring any face pinned in either. A name
that matches nothing lists the families that are there. `--bold`, `--italic`
and `--bold-italic` work beside it and override that one face.

The picker at the top left switches families without a restart. The family
rides on each render request, and the build cache is keyed on the faces, so
going back to one you were just looking at is free. Started on a bare `--font`,
that file stays at the top of the list as a choice of its own, since it is no
family and cannot become one.

The picker always ends with Literata, which ships with the tool and is marked
`(bundled)`. Its faces are read where they are installed and nothing is copied
into the workspace. It is there so a first run has type to look at, and it
stays afterwards as somewhere to flip to: a face you know is good, at the size
and the knobs you are working at.

Being in the picker does not put it in your workspace. `crossglyph build` with
no arguments, and **Build all**, build the families in your folder and not the
one that came with the tool. Name it and it builds, and pressing Save on it
writes a `literata.conf` naming `dir`, after which it is a family like any
other and builds with the rest.

The server runs until it is killed, and it reads the Python once at startup, so
a change to the source needs a restart. On Windows, free the port first:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

## What the controls do

Font controls (`gamma`, `weight`, `line_height`, the spacings, `kerning`,
`slant`, `thresholds`, `hinting`, `stem_darkening`, `ligatures`, `figures`)
rebuild the `.cpfont` behind the page. Page controls (margin, alignment,
hyphenation and the language its patterns come from, line spacing, paragraph
spacing, antialiasing) are the reader's own settings, and they only
re-lay-out. The language list is every one the firmware carries patterns for;
on the device it comes from the book's own metadata instead. A control that
cannot apply is greyed rather than hidden, so hyphenating as Russian is not
offered while hyphenation is off.

Night mode is the reader's inverted screen. The device draws the page exactly
as it does by day and complements the framebuffer on its way to the panel, so
what changes is which level each pixel lands on: paper and ink swap, and the
two greys swap with each other. That is a level complement rather than 255
minus a value, which would ask for greys this panel cannot make. It is worth
looking at a font both ways, since a face that is comfortable in black on
white can read heavy in white on black.

To see what your tuning is doing, take it away: `untuned` at the top, the `\`
key, or press and hold the page itself. The size stays where it is, since that
is which size you are working at rather than tuning. Holding is a look and not
a change: whatever the toggle was set to is what comes back on release.

The export panel holds what a build needs and a page does not: the name, the
sizes, the coverage intervals, the fallback families.

The box beside the heading is what the family is called once it is built, which
is the name the reader picks from on a phone-sized screen rather than whatever
the source files are called. It reaches a filename, so letters, digits, `_` and
`-` are all it can keep: the rest is stripped on the way in and the box shows
what landed. Empty means the name the files already have. Two families may not
build under one name, since they would write over each other in the output
folder, so a name another family has taken is refused with a line saying which.
A second family counts as a name, being called after the first one. The picker
follows a rename as soon as it is saved, and so does any family falling back to
the one that moved.

The coverage presets overlap, and the row says so rather than leaving it to be
worked out: `reading` is the converter's `default` block and a good deal more,
so ticking it shows Default, Latin Extended, Symbols and Vietnamese as carried,
greyed and not yours to change while it is on. A preset you chose that another
of your choices already covers stays yours to untick, greyed with a note saying
it adds nothing. Greek and Cyrillic are never carried: `reading` has the main
blocks but not polytonic Greek or the Cyrillic Supplement, so ticking those
still adds something. Only what you chose is written to the config. Save writes the lot back to the
family's config, and Build then runs the same build the command line runs.
Save first, then build: the build reads the config from disk, so anything you
have not saved is not in it.

A build runs its sizes across a process pool, the same one the command line
uses, so a family with four sizes takes about as long as its slowest one rather
than all four end to end. They finish in whatever order they finish in.

A build reports as it goes, which matters because one with the fallbacks on
runs for minutes: the bar under the two buttons fills with the sizes done, and
the line under it names the family and size in hand, the count, and once there
is enough of the run to judge by, what is left. The sentence that stays when
it finishes says what was built, what was already current, and where it went,
with the bytes beside each count: a card has a fixed amount of room, and a
build is when somebody wants to know what a family costs on it. The two
numbers are separate because they answer different things, what this run
wrote and what the sizes it left alone already take up.

A build does the sizes whose inputs changed. Hold shift and it does the lot,
current or not, which is what you want when the inputs are the same and the
answer should not be: a converter that has moved on, or a face edited in
place. Both buttons say `Rebuild` for as long as the key is held.

A family that `all.conf` covers without naming has no file of its own. Saving
one writes a new `<family>.conf` rather than editing `all.conf`, which would
retune every family in the workspace.

## The render core

The page is not a reimplementation of the device's renderer. It is the
renderer: `EpdFont` and `GfxRenderer` from the firmware, compiled to
WebAssembly, driven from Python. Bytes in, bytes out, no syscalls.

That is what makes the preview honest. Everything that decides how a page looks
lives in those files: how a `.cpfont` is parsed, how a glyph is blitted at four
grey levels, where lines break, how justification distributes slack, how
hyphenation patterns apply. A Python reimplementation would agree with the
device until it did not, and the disagreement would be silent.

The module is `src/crossglyph/render/render.wasm`, about 530 KB, most of it the
compiled hyphenation tries for ten languages. It is committed, because a
release has no toolchain to build one with. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for rebuilding it.

### Freestanding, and why that is enforced

The module imports three WASI functions and nothing else:
`fd_close`, `fd_seek` and `fd_write`. libc links stdio unconditionally, so they
come along even though nothing calls them. They are standard, so any host can
satisfy them, and a browser needs no shim beyond an off the shelf one.

A test asserts that set exactly. A new import is a regression worth failing on,
because the browser version of this page has to load the same module with only
the Python wrapper replaced.

### Knowing when it is stale

The build writes a stamp beside the module holding the firmware commit it came
from. If a firmware checkout sits beside this repository and has moved past
that commit, the preview says so once and draws anyway:

```
warning: the render core was built from crosspoint-reader 45caec3e76c2, and
         D:\...\crosspoint-reader is now at 9f1c0a2b4d31.
         The preview draws with the older renderer until you rebuild it:
  bash D:\...\src\render\build.sh
```

An older renderer draws the page that older firmware drew, which is worth more
than no preview. The warning exists because whoever moved the checkout is the
one person who can rebuild the module, and it is said once per run rather than
once per redraw.

Without a checkout there is nothing to compare against, so nothing is claimed
and nothing is printed. That is the released case, and the reason the module
ships built. `$CROSSGLYPH_FIRMWARE` names a checkout somewhere other than
beside this repository.

An explicit path is taken at its word. `load_module(path)` skips the check,
because a caller naming a file has already said which one they mean.

## Speed

A control moves and the page redraws. Everything on that path is cached.

The workspace is walked once per family and the result held, so moving a slider
does not re-resolve the folder. Kerning is read from GPOS once per face, size
and figure setting, since parsing GPOS twice for the same font is most of the
cost of a rebuild. Rendered pages are cached on the whole request, so returning
to a setting you just left costs nothing.

The page coalesces its own requests. Dragging a slider issues one render at a
time and discards what is superseded, so a drag cannot queue thirty renders and
then serve them all.

First use of a family is slower than the rest, because that is where the folder
walk and the GPOS read happen. After that a control turn is tens of
milliseconds. The page prints the elapsed time under the image.

## The sample text

The picker over the text box holds one preset per language, and the page opens
on one the browser says you read. A specimen you cannot read says nothing about
a font you are choosing.

Each preset is the pangram the device itself shows under Settings > Font,
Article 1 of the Universal Declaration of Human Rights in that language, and a
short English paragraph so a font that has to carry both scripts can be judged
on both. Between them they exercise what a font decision depends on: tabular
figures, a justified line, a word long enough to hyphenate, and emphasis inside
running text. See `src/crossglyph/preview/samples.py`.

Custom is the first entry and holds whatever you type. Choosing a language
never costs you your own text, and switching back returns it; typing while a
preset is showing moves the picker to Custom under your hands. Both the choice
and your own text are remembered between sessions.

Choosing a preset moves `hyphenate as` with it when the core has patterns for
that language, and leaves it alone when it has none, so a Japanese specimen is
not quietly hyphenated as English.

On a first visit only, the browser's languages also pick `hyphenate as`,
English when none of them has patterns. That is a default rather than a
decision: it is not written down, and Reset page settings goes back to it.

If the family and its fallbacks have no glyph for something on the page, a line
under the box says how many characters that is. It is worth saying because the
device gives a glyph nobody has no width at all, so a paragraph of them is
blank space rather than a row of boxes, and a page with a hole in it looks
exactly like a page that failed to draw.

The remedy is under Export: **bundled fallback faces**, which is a dozen Noto
faces covering most scripts, and the Fetch button beside it when they are not
in the workspace yet. A fetch takes the page into account, so pressing Fetch on
a Japanese sample brings the 15.7 MB CJK face as well and turns the box on,
rather than leaving you to work out which coverage would have asked for it. One
CJK face answers Japanese, Korean and both Chinese scripts. It is a slow
download, so the same bar the build uses says how far it has got, and the
button is out until it finishes.

## What this is not

The preview draws one page of sample text. It is not the reader: no chapters,
no pagination, no images, no tables, no footnotes. What it covers is what a
font decision depends on.
