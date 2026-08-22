# Getting started

This guide builds one font family through the browser. At the end, the family
is ready to copy to a CrossPoint reader.

## Download CrossGlyph

1. Download the archive from the [latest release](https://github.com/CrazyCoder/crossglyph/releases/latest).
2. Extract it to a folder you can write to.

## Add a font family

Open the `fonts` folder beside the launcher. Copy the TTF or OTF files for your
family into it.

A typical family has these files:

```text
MyFont-Regular.ttf
MyFont-Bold.ttf
MyFont-Italic.ttf
MyFont-BoldItalic.ttf
```

CrossGlyph reads the family and style from the filenames. A regular face is
required. The other styles are optional.

You can also place a family in a subfolder. The filenames still decide its
family and styles. If CrossGlyph groups the files incorrectly, see
[Source files and styles](fonts.md#source-files-and-styles).

## Open the preview

Open the launcher in the extracted folder:

- On Windows, open `crossglyph.cmd`.
- On macOS or Linux, open `crossglyph.sh`.

The first launch downloads the runtime and dependencies into a cache. The
browser opens after the preview server is ready.

If the workspace has no font files, CrossGlyph opens the bundled Literata
family. Add your files, return to the browser and select your family from the
**font** list.

## Understand the page

Most users see a two-column layout. **Tune** and **Export** share a tabbed panel
on the left. The rendered page is on the right.

Wide screens show three columns by default. **Tune** is on the left, the
rendered page is in the middle and **Export** is on the right. Narrow screens
show one column. The selected panel comes first and the rendered page follows
it.

The controls keep the same names in every layout.

CrossGlyph has two kinds of settings:

- **Font settings** affect the built `.cpfont` files. They are in **Tune** and
  **Export**.
- **Page settings** affect only the browser preview. Open **Page** inside
  **Tune** to see them.

The **size** control at the top of **Tune** is also a preview choice. It lets you
judge one point size. The sizes that CrossGlyph builds are the boxes in
**Export**.

## Tune the font

1. Select your family from the **font** list.
2. Set **size** to a point size you read often.
3. Adjust **gamma** until the letters have the right darkness.
4. Adjust **weight** if thin strokes need more or less ink.
5. Check letter spacing, word spacing and line height.
6. Use the **?** buttons when a control name is unfamiliar.
7. Press **untuned** to compare your changes with the starting values.

The page redraws after each change. A curved arrow beside a control compares
that control with its saved value. Press the arrow again to return to your
current value.

Press **Save** when the font looks right. Save writes the font and export
settings to the family's config file.

## Match the reading page

Open **Page** in **Tune**. Set the margin, alignment, line spacing, hyphenation,
paragraph spacing, anti-aliasing and night mode to match the reading conditions
you want to test.

These settings are for comparison only. The browser remembers them for the next
visit, but Save and Build leave them out of the font config.

The hyphenation language describes the sample text. A book on the reader uses
the language stored in that book.

## Choose what to build

Open **Export**.

1. Check **name**. This is the family name shown by the reader.
2. Enter the point sizes under **sizes**.
3. Leave **Second family** empty unless you want another family entry with a
   different size list.
4. Choose the **coverage** needed by your books.
5. Turn on **bundled fallback faces** when the main family lacks characters you
   need.
6. Check **output**. The default is the workspace's `cpfonts` folder.

Coverage adds characters to the built files. More coverage increases file size
and build time. The preview reports text that the chosen coverage cannot draw.

## Build the family

Press **Build** to build the selected family. Press **Build all** to build every
family in the workspace.

Build saves the current font and export settings before it starts. You do not
need to press Save first.

CrossGlyph rebuilds the point sizes whose inputs changed. Hold Shift while
pressing a build button to rebuild every size.

The progress line reports the family and size being built. When the build
finishes, the output folder contains one family folder with one `.cpfont` file
per point size.

## Copy the family to the reader

1. Open `fonts/cpfonts`.
2. Copy the complete family folder to `/fonts` on the reader's SD card.
3. Eject the card safely and start the reader.
4. Select the family in CrossPoint's font settings.

You can use `/.fonts` instead of `/fonts` when you want to hide the family from
the file browser.

## Next steps

- [The browser preview](preview.md) explains every part of the page.
- [Font settings reference](fonts.md) explains the build settings and config
  keys.
- [Troubleshooting](troubleshooting.md) starts from the problem you can see.
- [Command line](cli.md) covers scripts, batch builds and automation.
