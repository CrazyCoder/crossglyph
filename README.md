# CrossGlyph

CrossGlyph tunes and converts fonts for e-readers that run
[CrossPoint](https://github.com/crosspoint-reader/crosspoint-reader) firmware.
It turns TTF and OTF files into `.cpfont` files that CrossPoint can load from an
SD card.

The browser preview uses the same text renderer as the firmware. Move a control
and the page redraws with the new font settings.

<p align="center">
  <a href="docs/images/tune.png"><img src="docs/images/tune.png" width="32%"
     alt="The Tune panel with font controls"></a>
  <a href="docs/images/preview.png"><img src="docs/images/preview.png" width="32%"
     alt="A rendered page inside a reader frame"></a>
  <a href="docs/images/export.png"><img src="docs/images/export.png" width="32%"
     alt="The Export panel with build settings"></a>
</p>

## Why use the converter

CrossPoint fonts are bitmap fonts. Each point size stores a separate picture of
every character. Each pixel uses one of four grey levels.

A font made for print or a high-resolution screen may look too light, too dark
or too crowded after that conversion. Small letters may lose thin strokes.
Kerning and ligatures that work in print may close gaps on an e-ink screen.

CrossGlyph lets you correct those problems before you copy the font to a card:

- **See the real result.** The preview draws the page with CrossPoint's own
  renderer.
- **Tune the letters.** Adjust darkness, stroke weight, hinting, line height,
  letter spacing, word spacing, kerning and ligatures.
- **Build a complete family.** Convert regular, bold, italic and bold italic at
  every point size you choose.
- **Use variable fonts.** Choose the text and bold weights. Optical size follows
  each point size during the build.
- **Choose character coverage.** Add scripts, symbols and fallback faces when
  the main family does not contain every character.
- **Prepare Arabic fonts.** CrossGlyph stores the joined forms that CrossPoint
  requests when it draws Arabic text.

The live preview replaces the slow cycle of building a font, copying it to a
card and opening a book after every change.

## Get started

1. [Download the latest release](https://github.com/CrazyCoder/crossglyph/releases/latest).
2. Extract it to a folder you can write to.
3. Copy your TTF or OTF files into the `fonts` folder.
4. On Windows, double-click `crossglyph.cmd`. On macOS or Linux, open a
   terminal in the extracted folder and run `./crossglyph.sh`.
5. Select your family in the browser.
6. Adjust the font in **Tune**.
7. Choose the point sizes and coverage in **Export**.
8. Press **Build**.
9. Copy the built family from `fonts/cpfonts` to `/fonts` on the reader's SD
   card.

The first launch downloads the program runtime into a cache. Later launches use
that cache. If the `fonts` folder is empty, the preview opens with the bundled
Literata family so you can explore the controls.

See [Getting started](docs/getting-started.md) for the complete first build.

## Font settings and page settings

**Font settings** change the files that CrossGlyph builds. They are the tuning
controls in **Tune** and the build choices in **Export**. The **size** control
chooses the preview size. The **sizes** boxes in Export choose the build sizes.
**Save** writes font settings to the family's config file. **Build** saves them
and creates the `.cpfont` files.

**Page settings** change only the page in the browser. They mirror CrossPoint
reading options such as margin, alignment, line spacing, hyphenation and night
mode. Use them to judge the font under the same conditions as a book.
**line height** in Tune changes the built font. **line spacing** in Page changes
only the preview.

## Documentation

| Task | Page |
|---|---|
| Build your first family in the browser | [Getting started](docs/getting-started.md) |
| Use the preview and understand its controls | [The browser preview](docs/preview.md) |
| Look up a font or config setting | [Font settings reference](docs/fonts.md) |
| Use commands and automation | [Command line](docs/cli.md) |
| Fix a visible problem | [Troubleshooting](docs/troubleshooting.md) |
| Update or roll back CrossGlyph | [Updating](docs/updating.md) |
| Run CrossGlyph in a container | [Docker](docs/docker.md) |
| Understand the implementation | [Internals](docs/internals.md) |

CrossGlyph is MIT licensed. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)
for bundled components and [CONTRIBUTING.md](CONTRIBUTING.md) to work on the
project.
