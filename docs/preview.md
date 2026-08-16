# The preview

<p align="center">
  <a href="images/preview.png"><img src="images/preview.png" width="50%"
     alt="A rendered page inside the white Xteink X4 frame, with the device preview controls below"></a>
</p>

```sh
./crossglyph.sh preview                    # the first family in the workspace
./crossglyph.sh preview --family notosans  # a family by name
./crossglyph.sh preview --font one.ttf     # a file that is in no family
./crossglyph.sh preview --no-open --host 0.0.0.0          # for a container
./crossglyph.sh preview --fonts ~/other-fonts             # another workspace
./crossglyph.sh preview --family notosans --png page.png  # one page, no server
```

Every rendered PNG carries `CrossGlyph X.Y.Z` in gray at the bottom right.
CrossGlyph adds the watermark after the device render, so it is not part of
the simulated framebuffer.

`--fonts` is the same flag `build` takes and answers the same question: which
folder holds the families. Unset, it is `$CROSSGLYPH_FONTS`, and unset again
it is the `fonts` folder beside the launcher.

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
one that came with the tool. Name it and it builds, and pressing **Save** on it
writes a `literata.conf` naming `dir`, after which it is a family like any
other and builds with the rest.

The server runs until it is killed, and it reads the Python once at startup, so
a change to the source needs a restart. On Windows, free the port first:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

## In the background

Tuning a font is a thing you come back to for days, and the terminal window
that is holding the server open is doing nothing else. So it can run without
one:

```sh
./crossglyph.sh start                 # start it, and open a browser on it
./crossglyph.sh start --port 8123 --no-open
./crossglyph.sh status                # what is running, and which version
./crossglyph.sh restart               # same address, same family
./crossglyph.sh stop
```

`start` takes every option `preview` takes, so `--family`, `--font`, `--host`
and `--port` mean the same things. It waits for the page to answer before it
says anything, so a start that failed says so here rather than opening a
browser on nothing, and the reason is in `preview.log` beside the launcher.

`status` asks the server rather than guessing from a process list, so what it
reports is what is actually serving:

```
preview on http://127.0.0.1:8000
  pid 41288, crossglyph X.Y.Z, up 2h
  fonts /home/you/crossglyph/fonts
  log /home/you/crossglyph/preview.log
```

The workspace and the pid come from the server rather than from what was
typed. `--fonts` and `$CROSSGLYPH_FONTS` both move the workspace, and the
process that serves is not always the one that was started: uv's venv python
launches the real interpreter, so a pid remembered at the spawn would be a
wrapper, and stopping it would leave the server holding the port.

A preview that has stopped answering while its process is still there is said
as one, since that is the state a stop has to be able to end:

```
a preview on http://127.0.0.1:8000 (pid 41288) is not answering.
`crossglyph stop` will kill it.
```

`preview.log` is written unbuffered, so it can be read while the server is
still up rather than filling in at the moment it exits.

`restart` takes what it is not told from the start it replaces: bare, it comes
back on the same address showing the same family, and `restart --port 9000`
moves only the port. It also picks up an update, since it resolves the version
to run at the moment it starts one. So `crossglyph update` and then
`crossglyph restart` is the whole of installing a release and running it, and
`status` names the version afterwards so there is no doubt which one answered.
Between the two, `status` says so as well:

```
  X.Y.Z is installed; a restart would run it
```

Starting one that is already running is not an error: it says where it is and
opens the browser, which is what you asked for. It refuses only when something
that is not CrossGlyph holds the port, or when a preview is running on a
different address than the one you named.

Stopping goes through the server rather than a signal, because Windows has
neither a SIGTERM nor a console for a detached process to receive Ctrl+Break
through. `POST /shutdown` is that request, and it answers a loopback client
only: a preview on `--host 0.0.0.0` serves its pages to the network and takes
a shutdown from nobody but the machine it runs on. There is no token, because
a token cannot help here. A browser elsewhere could only learn one if the page
carried it, and a page that carries it hands it to everyone who can load the
page.

## When the folder changes underneath it

The font folder is not only the app's to change. A font gets dropped into it,
a config gets edited in an editor, a docker volume gets a new file from
outside the container, all while the page is open.

Reaching the folder means leaving the window, so coming back to the page is
when it asks again: on tab focus it re-reads the folder, and a font added,
removed or retuned since the last look is in the picker. Nothing polls, so an
app nobody is looking at does no work at all, which is most of what a
background one does.

What you are tuning keeps its place through that. The picker does not move
under you, and unsaved knobs are never overwritten, since they are the only
thing on the page with nowhere else to live. When the open family's config
changes on disk:

- with nothing of yours in the panel, it follows the file and redraws
- with unsaved knobs, they stay, the page says the file changed, and the
  revert arrows compare against the file as it is now rather than as it was

A family whose files have gone falls back the way a fresh page would.

## What the controls do

Font controls (`gamma`, `weight`, `line_height`, the spacings, `kerning`,
`slant`, `thresholds`, `hinting`, `grayscale_hinting`, `mono`,
`stem_darkening`, `ligatures`, `figures`) rebuild the `.cpfont` behind the
page. Page controls (margin, alignment, hyphenation and the language its
patterns come from, line spacing, paragraph
spacing, antialiasing) are the reader's own settings, and they only
re-lay-out. The language list is every one the firmware carries patterns for;
on the device it comes from the book's own metadata instead. A control that
cannot apply is greyed rather than hidden, so hyphenating as Russian is not
offered while hyphenation is off.

`off` at the bottom of that list is a third state rather than a second way to
untick the box, and the difference shows on any text with a compound in it:

```
hyphenation off            was re-established after the
                           cost-benefit analysis of the
                           counter-example.

hyphenation on, off        was re-established after the cost-
                           benefit analysis of the counter-
                           example.
```

With hyphenation off the reader never breaks inside a word. With it on and no
language, it breaks at hyphens the text already carries and adds none of its
own -- exactly what the device does with a book whose language it does not
recognise, which is worth being able to look at. A language on top of that
adds its patterns.

The **Page** section folds, and starts folded. These are settings you match to
the device you are judging against once and then leave, where everything above
them is what a session is actually for. They are remembered in this browser, so
they survive a reload and every font you try; the fold is remembered with them.
A dot on the folded heading says one of them is not what the device ships with,
which is the same dot the rows carry, said for the section while the rows are
out of sight.

The font decides two of them. `ligatures` needs GSUB rules the converter can
read, and `figures` needs a `pnum` feature; a family with neither draws the
same page whichever way those are set, so both rows are greyed for it and say
which feature is missing. It is asked of every face, since a family whose
regular has ligatures and whose bold does not still has something to turn off.
A face that will not open is not greyed on, because that is a claim about a
font nobody could read.

`stem darkening` is greyed by the font and the `hinting` row together, which is
what makes it the confusing one. FreeType darkens in two engines, the Adobe CF2
interpreter that draws CFF and Type 1 faces and the auto-hinter, and each puts
a condition of its own on top: CF2 darkens a scaled load, the auto-hinter
darkens at a light target. So a TrueType family, which has no CF2 path, is
unmoved by the switch except at `hinting = light`, the one setting that hands
it to the auto-hinter. And nothing is moved under `hinting = auto`, which
targets normal hinting and reloads the glyph unscaled, failing both conditions
at once. Turn hinting and the row follows.

Only those two cases are greyed, so the switch may still do nothing where it is
left alone. A CFF face whose stems fall where the darkening curve rounds to
nothing is unmoved too, and that cannot be known without rasterizing the page
both ways. A face FreeType calls tricky never reaches the auto-hinter at all,
so `light` does nothing for it either. Both are left live, because greying a
switch that works is the one mistake worth avoiding here.

`grayscale hinting` and `mono` are greyed on facts of their own.
The first picks FreeType's other bytecode interpreter, so it is out of reach
for a face that has no bytecode to run: a CFF family, a TrueType family with no
instructions, and any family under `light`, `auto` or `none`, since the
auto-hinter draws those instead. The second leaves a pixel empty or full, so
while it is on there is no coverage in between for `gamma` or the thresholds to
act on and those two rows are greyed instead.

Night mode is the reader's inverted screen. The device draws the page exactly
as it does by day and complements the framebuffer on its way to the panel, so
what changes is which level each pixel lands on: paper and ink swap, and the
two greys swap with each other. That is a level complement rather than 255
minus a value, which would ask for greys this panel cannot make. It is worth
looking at a font both ways, since a face that is comfortable in black on
white can read heavy in white on black.

### Device preview

The **Device preview** under the page puts the rendered screen into an X3 or
X4 body. It starts folded. X4 is the default; choosing X3 redraws at its native
528 by 792 pixels instead of resizing the X4's 480 by 800 output. The body
color follows the page's light or dark appearance until you select black or
white. That choice is remembered independently from the page appearance. The
reader icon removes the body while keeping the selected screen proportions and
rounded corners.

**Paper** and **Ink** remap the panel's four levels without rebuilding the
font. Both run from 50% to 100% in the direction their labels imply: more paper
is lighter, and more ink is darker. Both default to 90%.

**Scale** has four meanings:

- **1:1 pixels** maps one reader pixel to one physical monitor pixel, accounting
  for the browser's device pixel ratio. It does not resample the screen.
- **Device size** uses the reader body's documented dimensions at 100%.
- **Fit** scales the selected body or bare screen into the available window.
- **Custom** applies 50% to 150% of the documented device size. It shows a
  100 mm ruler and the same slider and stepper controls as the numeric tuning
  knobs. Hold a physical ruler against the line and adjust until they match.
  Repeat this after moving the window to a monitor with a different scale.

These choices and the tone values are remembered in this browser. **Reset
device preview** restores the X4 frame, 1:1 pixels and 90% tones. It does not
change the font or its saved config.

To see what your tuning is doing, take it away: `untuned` at the top, the `\`
key, or press and hold the page itself. The size stays where it is, since that
is which size you are working at rather than tuning. Holding is a look and not
a change: whatever the toggle was set to is what comes back on release.

Size is a view setting. The browser remembers it for the next visit, but it is
not written to the family's config, and neither reset action changes it.

One knob at a time is the arrow beside it. It is a comparison rather than a
reset: your value is set aside and one press brings it back, so you can flick
between the two as often as it takes. Which value it offers depends on where
the knob stands. While the panel differs from the config, it offers the config,
which answers "undo what I just did to this row". Once they agree, which is
what saving makes true of every knob at once, it offers the stock value
instead, which answers "what does this font change". Leave a knob on stock and
it differs from the config again, so the arrow points back the other way. The
tooltip names which of the two it is holding.

Numeric axes of a variable font, such as `wdth`, use the same arrow. The
family's config is the first comparison, the default declared by the font is
the stock comparison, and **Untuned** shows that stock value. Weight pickers
remain face choices rather than one shared tuning axis.

A switch has no arrow. There is nothing to set aside when the value you are not
looking at is the other one, a click away on the box itself, so a checkbox
carries a mark instead: it says the row differs, and the tooltip says which way
the baseline has it.

**Reset font knobs**, in the foot of the card beside **Save**, puts the whole
section back, including the weight pickers of a variable family. Those go to
what the family declares, which is its config's weight if it has one and the
font's own named instance if it has not, rather than to the first entry in the
picker. The cross on the **Page** heading does the same for the section under
it.

The foot of the card is where **Save** is, rather than either panel, because it
writes the whole `.conf`: a coverage tick lights it exactly as a slider does.

The export panel holds what a build needs and a page does not: the name, the
sizes, the coverage intervals, the fallback families. What each of them means
is behind the **?** beside its label, since it is an answer you want once. Its
**Second family** section folds like **Page** does, since most families are one
family, and a dot on the folded heading says this one is not.

It has a column of its own beside the page while the window is wide enough for
three. Below that it folds in beside the font knobs, with **Tune** and
**Export** tabs above the panel deciding which of the two is showing, and the
page stays where it is either way. A build running behind the Export tab marks
it, since a build is minutes and the panel it reports in may not be the one
you are looking at.

**name** is what the family is called once it is built, which is the name the
reader picks from on a phone-sized screen rather than whatever the source files
are called. It reaches a filename, so letters, digits, `_` and
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
still adds something. Only what you chose is written to the config. **Save**
writes the lot back to the family's config, and Build then runs the same
build the command line runs.
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

A build also tidies the output folder against the workspace: a family you
renamed, dropped, or took the second size list off leaves a whole directory
behind, and the note says which ones went. Either button does it, since what
should be in that folder does not depend on which family you pressed Build on.
A family whose config still names it keeps what it built even when its face has
gone missing, and a directory the tool did not build is never touched.

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

The build writes a stamp beside the module holding the firmware it came from:
the repository, the branch and the commit. If a firmware checkout sits beside
this repository and has moved past that commit, the preview says so once and
draws anyway:

```
warning: the render core was built from crosspoint-reader develop 45caec3e76c2,
         and D:\...\crosspoint-reader-engine is now at 9f1c0a2b4d31.
         The preview draws with the older renderer until you rebuild it:
  bash D:\...\src\render\build.sh
```

An older renderer draws the page that older firmware drew, which is worth more
than no preview. The warning exists because whoever moved the checkout is the
one person who can rebuild the module, and it is said once per run rather than
once per redraw.

The checkout it compares against is `crosspoint-reader-engine` if there is one,
which is a clone kept for the engine and left on `develop`, and a plain
`crosspoint-reader` otherwise. That is what lets a working checkout be on any
branch without the preview having an opinion about it. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for keeping it current.

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

The **Text** card starts folded and remembers whether it is open. Its language
picker stays in the heading, so changing the specimen does not require opening
the text and its notes.

The picker holds one preset per language, and the page opens on one the browser
says you read. A specimen you cannot read says nothing about a font you are
choosing.

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

Your own text is in some language too, so Custom keeps a `hyphenate as` of its
own and brings it back with the words. Set one while Custom is showing and it
is remembered; go through a preset and return, and both the text and the
language you were reading it in come back. Changing `hyphenate as` while a
preset is showing is about that specimen and is not kept, and Custom with
nothing of its own recorded leaves whatever is showing alone.

On a first visit only, the browser's languages also pick `hyphenate as`,
English when none of them has patterns. That is a default rather than a
decision: it is not written down, and the cross on the **Page** heading goes
back to it.

If the family and its fallbacks have no glyph for something on the page, a line
under the box says how many characters that is. It is worth saying because the
device gives a glyph nobody has no width at all, so a paragraph of them is
blank space rather than a row of boxes, and a page with a hole in it looks
exactly like a page that failed to draw.

The remedy is under Export: **bundled fallback faces**, which is a dozen Noto
faces covering most scripts, and the **Fetch** button beside it when they are
not in the workspace yet. A fetch takes the page into account, so pressing
**Fetch** on a Japanese sample brings the 15.7 MB CJK face as well and turns
the box on,
rather than leaving you to work out which coverage would have asked for it. One
CJK face answers Japanese, Korean and both Chinese scripts. It is a slow
download, so the same bar the build uses says how far it has got, and the
button is out until it finishes.

## What this is not

The preview draws one page of sample text. It is not the reader: no chapters,
no pagination, no images, no tables, no footnotes. What it covers is what a
font decision depends on.
