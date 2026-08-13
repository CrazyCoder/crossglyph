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

While the workspace has no fonts in it, the picker offers Literata, which ships
with the tool and is marked `(bundled)`. Its faces are read where they are
installed and nothing is copied into the workspace. It is there so a first run
has type to look at, and it steps aside as soon as you add a font of your own.
Saving it first writes a `literata.conf` naming `dir`, which is what keeps it
in the list after that.

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

The export panel holds what a build needs and a page does not: the sizes, the
coverage intervals, the fallback families. Save writes the lot back to the
family's config, and Build then runs the same build the command line runs.
Save first, then build: the build reads the config from disk, so anything you
have not saved is not in it.

A build reports as it goes, which matters because one with the fallbacks on
runs for minutes: the bar under the two buttons fills with the sizes done, and
the line under it names the family and size in hand, the count, and once there
is enough of the run to judge by, what is left. The sentence that stays when
it finishes says what was built, what was already current, and where it went.

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

## What this is not

The preview draws one page from one paragraph of sample text. It is not the
reader: no chapters, no pagination, no images, no tables, no footnotes. What it
covers is what a font decision depends on.

The sample text is pangrams and typography test lines, chosen for what they
exercise: tabular figures, a justified line, a word long enough to hyphenate,
and both Cyrillic and Latin. Replace it with your own in the text box, which is
remembered between sessions.
