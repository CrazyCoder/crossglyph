# CrossGlyph

Build fonts for an e-reader running
[CrossPoint](https://github.com/crosspoint-reader/crosspoint-reader), and tune
them against the renderer that will draw them.

CrossPoint reads fonts as `.cpfont` files: glyph bitmaps at two bits per pixel,
rasterized for one point size, with kerning and ligature tables baked in. The
device has no rasterizer, so every size is a separate build. CrossGlyph turns a
folder of TTF or OTF files into those files.

It also opens a preview in your browser. The page is drawn by the firmware's
own renderer, compiled to WebAssembly, so what you see is what the device
draws. Every setting is a control, and the page redraws as you move it.

## Quick start

1. Unpack the release somewhere you can write to.
2. Put your TTF or OTF files in the `fonts` folder beside the launcher.
3. Run `crossglyph.cmd` on Windows, or `./crossglyph.sh` on macOS and Linux.

The launcher fetches [uv](https://docs.astral.sh/uv/) on first use, which then
fetches Python and the dependencies. Nothing is installed system wide, and the
whole of it lives in a cache directory you can delete. A browser opens on the
first family it finds.

To build every family in the workspace, with no page in between:

```sh
./crossglyph.sh build
```

Windows on ARM is the one platform without ready-made wheels: `freetype-py`
publishes none, so uv tries to compile it and needs a build toolchain.

## The workspace

The folder the launcher opens holds four things:

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

A family needs no config at all. Drop four files in, name them the way their
foundry did, and `all.conf` covers them. Write a `<family>.conf` when one
family needs settings of its own. See [docs/fonts.md](docs/fonts.md) for every
key, and for what the tuning controls actually do.

## Getting the fonts onto the device

Copy a built family folder from `cpfonts` into `/fonts` on the SD card, or into
`/.fonts` to keep it out of the file browser. The device scans both at boot,
and the family then appears under **Settings > Reader > Font**.

The point sizes offered are the ones you built. A family built at 12, 14 and 16
offers three of them.

## Fallback faces

CrossPoint draws nothing for a codepoint no font in the chain has, so a family
that lacks an arrow leaves a gap where it should be. Twelve Noto faces fill
those holes, covering Hebrew, Armenian, Georgian, Ethiopic, Cherokee, Tifinagh,
Coptic, mathematics, symbols and emoji.

They are OFL licensed and unmodified, so they are downloaded rather than
shipped here:

```sh
./crossglyph.sh fetch-fallbacks
```

That is 3.4 MB, and it puts `OFL.txt` beside them. A CJK face is another
15.7 MB and comes only when a config asks for a CJK script. The preview offers
the same thing as a button. Set `fallbacks = no` in a config to build without
them, which is a factor of twelve smaller for a narrow face.

## What is here

| | |
|---|---|
| `src/crossglyph/` | the converter, the workspace rules and the preview server |
| `src/crossglyph/cpfont/` | the `.cpfont` writer, forked from the tool behind the CrossPoint website |
| `src/crossglyph/render/` | the firmware's renderer, compiled to WebAssembly, and the Python that drives it |
| `src/render/` | the C++ and the build script that produce that module |
| `docs/` | [fonts.md](docs/fonts.md) for building, [preview.md](docs/preview.md) for the renderer |

CrossGlyph is MIT licensed. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)
for the code it carries, and [CONTRIBUTING.md](CONTRIBUTING.md) to work on it.
