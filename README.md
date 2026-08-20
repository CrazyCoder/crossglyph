# CrossGlyph

Tune a font for an Xteink reader running
[CrossPoint](https://github.com/crosspoint-reader/crosspoint-reader), and watch
the page redraw as you move each control. Changes appear as fast as your
machine can rebuild that part of the font, which is fast enough to keep turning
a knob and watching what happens.

These readers draw in four shades of grey and nothing else, so most fonts need
work before they read well on one. Without a preview, every guess costs a card
swap or an emulator run, which is why most people stop at the point size.

<p align="center">
  <a href="docs/images/tune.png"><img src="docs/images/tune.png" width="32%"
     alt="The Tune panel with font and page controls"></a>
  <a href="docs/images/preview.png"><img src="docs/images/preview.png" width="32%"
     alt="A rendered page inside the white Xteink X4 frame"></a>
  <a href="docs/images/export.png"><img src="docs/images/export.png" width="32%"
     alt="The Export panel with sizes, coverage, fallbacks and build controls"></a>
</p>

- **The reader's own renderer.** The firmware's drawing code, compiled to run
  in the browser, so the page shows what the device will draw and not an
  impression of it.
- **Controls for the letters.** How dark the type is (gamma, and the three grey
  cut points), how thick or thin the strokes are (weight, and stem darkening),
  a slant for a face with no italic of its own, how the outline is snapped onto
  the pixel grid (hinting, grayscale hinting, and a one-bit mode that drops the
  greys), the space between letters, words and lines, how hard pairs are pulled
  together (kerning), whether `fi` joins into one shape (ligatures), and
  whether digits are all one width. [docs/fonts.md](docs/fonts.md) explains
  what every one of them does to the type.
- **Controls for the page.** Margins, alignment, line and paragraph spacing,
  hyphenation and the language its rules come from, anti-aliasing and night
  mode, so the page you are judging is set up like the device you are judging
  it for.
- **The page inside the reader.** Drawn from XTEINK's own models, one screen
  pixel to one of your monitor's, shaded to match a real device and adjustable
  from there. One press copies it out as an image.
- **Variable fonts.** These carry a range of weights in a single file. Build
  one at the weight its designer named, or at any weight you pick. Left alone,
  Merriweather would hand you its Light as your Regular.
- **A family in seconds.** Regular, bold, italic and bold italic, at every
  point size you asked for, one process per size.
- **The bundled Noto faces on request**, so a missing arrow or Greek letter is
  not a hole in the page. Each one lends its own bold or italic to text set
  that way, where it has one.
- **Arabic comes out joined** with any face. A modern Arabic font carries the
  rules for how letters connect, and CrossGlyph runs them and builds the joined
  shapes in. The device has no room to do that itself.
- **Nothing installed system wide.** The launcher fetches uv, Python and the
  dependencies into a cache directory you can delete.

CrossGlyph turns TTF and OTF files into `.cpfont`, the format the device reads.
A `.cpfont` holds a picture of every letter at one point size, in the four
greys the screen has, along with the tables that space letter pairs and join
`fi` into one shape. The device cannot scale type itself, so each point size is
a separate file and a separate build.

## Quick start

1. Unpack the release somewhere you can write to.
2. Run `crossglyph.cmd` on Windows, or `./crossglyph.sh` on macOS and Linux.
3. Put your TTF or OTF files in the `fonts` folder beside the launcher.

The launcher fetches [uv](https://docs.astral.sh/uv/) on first use, which then
fetches Python and the dependencies. Nothing is installed system wide, and the
whole of it lives in a cache directory you can delete. A browser opens on the
first family it finds.

What you unpack holds the launcher, your `fonts` folder, and a `versions`
folder with the code in it. The launcher runs whichever version `current`
names, so a later release is added beside this one and never written over it.

CrossGlyph looks for a newer release about once a day and says so when there
is one. `crossglyph update`, or the button in the preview, installs it beside
the version you are on and leaves your fonts and your settings alone. A local
preview restarts on the new version and reloads the page; a command-line
update waits for you to close CrossGlyph and open it again.
`crossglyph update --rollback` goes back. Nothing is downloaded or installed
until you ask, and one line in `update.conf` turns the looking off. See
[docs/updating.md](docs/updating.md).

Step 3 is second on purpose: there is nothing to set up before the first run.
An empty workspace opens on Literata, which ships with the tool, so the page
has type on it while you decide what to tune. Add a font of your own and it
takes over.

To build every family in the workspace, with no page in between:

```sh
./crossglyph.sh build
```

To keep the preview running without a terminal window holding it open, there
is `start`, `status`, `restart` and `stop`. `start` opens a browser once the
page answers, `restart` comes back on the same address and picks up an update
if one has been installed, and `stop --port 8123` names a preview on another
address instead of the one this install started.
[docs/preview.md](docs/preview.md) has the rest.

Windows on ARM is the one platform without ready-made wheels: `freetype-py`
publishes none, so uv tries to compile it and needs a build toolchain.

## Docker

Docker can run the preview and command-line builds with only the `fonts`
workspace mounted from the host. On Windows:

```bat
crossglyph-docker.cmd
```

On macOS or Linux:

```sh
./crossglyph-docker.sh
```

The launcher waits for a healthy preview, then prints its browser address, the
mounted workspace and the commands for logs and shutdown. Add `--local` to
build from the unpacked release or checkout instead of pulling CrossGlyph's
published image. The image installs nothing on the host and publishes the
preview on `127.0.0.1` by default. [docs/docker.md](docs/docker.md) covers the
raw Compose commands, image tags, batch builds and remote hosting.

## The workspace

The `fonts` folder sits beside the launcher, outside `versions`, so an update
only ever adds to it: a file you edited is kept, with the new one written
beside it as `<name>.new`. It holds four things:

```
fonts/
  NotoSans-Regular.ttf   your font files, at the root
  NotoSans-Bold.ttf
  conf/                  one <family>.conf per family, and all.conf
  fallbacks/             the bundled Noto faces, once fetched
  cpfonts/               what gets built
```

`$CROSSGLYPH_FONTS` names another workspace, and so does `--fonts DIR`. Builds
land in `cpfonts` unless `out` in `all.conf` says otherwise.

A family needs no config at all. Drop the regular, bold, italic and bold italic
files in, name them the way their foundry did, and they build on the next run.
`all.conf` holds settings shared by every family. It is yours and starts
absent; copy `all.conf.example` beside it to start from a commented list of
every key. Write a `<family>.conf` when one family needs settings the others do
not. See [docs/fonts.md](docs/fonts.md) for every key, and for what the tuning
controls actually do.

## Getting the fonts onto the device

Copy a built family folder from `cpfonts` into `/fonts` on the SD card, or into
`/.fonts` to keep it out of the file browser. The device scans both at boot,
and the family then appears under **Settings > Reader > Font**.

The point sizes offered are the ones you built. A family built at 12, 14 and 16
offers three of them.

## Fallback faces

A codepoint is one character as the computer stores it, and CrossPoint draws
nothing at all for one that no font in the chain has. A family with no arrow in
it leaves a gap where the arrow should be. The bundled Noto faces fill those
gaps, covering Hebrew, Arabic, Thai, Bengali, Armenian, Georgian, Ethiopic,
Cherokee, Tifinagh, Coptic, mathematics, symbols and emoji.

They are OFL licensed and unmodified, so they are downloaded on request and
not shipped here:

```sh
./crossglyph.sh fetch-fallbacks
```

That is a few megabytes, and it puts `OFL.txt` beside them. The face for
Chinese, Japanese and Korean is a much larger download on its own, and it comes
only when something has asked for it: a config naming one of those scripts, or,
in the preview, text on the page that cannot be drawn without it. That one face
covers Chinese in both its written forms, Japanese and Korean, so there is no
choice to make between them.

The preview offers the same download as a button, with a bar, since it takes a
while. Bundled fallbacks are off by default, which keeps a first build
self-contained and makes a narrow face a fraction of the size. After fetching
them, turn on **bundled fallback faces** in the preview or set
`fallbacks = yes` in a config to fill codepoints the family lacks.

## What is here

| | |
|---|---|
| `src/crossglyph/` | the converter, the workspace rules and the preview server |
| `src/crossglyph/cpfont/` | the `.cpfont` writer, forked from the tool behind the CrossPoint website |
| `src/crossglyph/render/` | the firmware's renderer, compiled to WebAssembly, and the Python that drives it |
| `src/render/` | the C++ and the build script that produce that module |
| `src/crossglyph/starter/` | Literata, the family an empty workspace opens on |
| `docs/` | [fonts.md](docs/fonts.md) for building, [preview.md](docs/preview.md) for the renderer, [docker.md](docs/docker.md) for containers, [updating.md](docs/updating.md) for the update check |

CrossGlyph is MIT licensed. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)
for the code it carries, and [CONTRIBUTING.md](CONTRIBUTING.md) to work on it.
