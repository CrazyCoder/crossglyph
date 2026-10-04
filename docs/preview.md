# The browser preview

The preview shows a page as CrossPoint draws it. Font controls rebuild the
preview font. Page controls lay out the page again. Both changes appear in the
browser as soon as they are ready.

<p align="center">
  <a href="images/preview.png"><img src="images/preview.png" width="80%"
     alt="The Export panel beside a rendered page in the two-column layout"></a>
</p>

For a first build, follow [Getting started](getting-started.md). This page is a
reference for the browser interface. Command-line options are in
[Command line](cli.md).

## Layout

Most screens use two columns. **Tune** and **Export** are tabs in the left
column. The rendered page and its viewing tools are in the right column.

Wide screens use three columns by default:

1. **Tune** on the left
2. the rendered page in the middle
3. **Export** on the right

Narrow screens use one column. **Tune** and **Export** remain tabs. The selected
panel appears above the rendered page.

The layout changes automatically with the browser width. It does not change
what a control does.

## What affects the built font

The page contains settings with different purposes:

| Part of the page | Purpose | Saved in the font config | Affects Build |
|---|---|---:|---:|
| **Tune** font controls | Change glyphs and font metrics | Yes | Yes |
| **Export** | Choose the files to build | Yes | Yes |
| **size** at the top of Tune | Choose the preview size | No | No |
| **Page** | Match CrossPoint reading settings | No | No |
| **Device preview** | Change the reader frame and display appearance | No | No |
| **Text** | Choose the sample text | No | No |

This distinction is important. **Page** can make the same font wrap and look
different, but it does not alter the `.cpfont` files.

## Choose a family

The **font** list at the top of the page contains the families found in the font
source folder. It also contains the bundled Literata family.

The four style markers beside the list show which faces are available. The
sample text uses bold and italic where it can, so missing styles are easy to
spot.

Return to the browser after adding, removing or editing font files. CrossGlyph
checks the folder when the tab receives focus and refreshes the family list.

## Choose the preview size

The **size** control selects the point size used by the rendered page. It is a
viewing choice. The browser remembers it.

The point sizes that Build creates are under **sizes** in **Export**. Changing
the preview size does not add that size to the build.

Use several preview sizes while tuning. Thin strokes, spacing and hinting can
behave differently at each size.

## Tune the font

The main controls in **Tune** change the font that Build will create.

| Control | What it changes |
|---|---|
| **gamma** | Overall ink coverage. Raise it to darken the letters. |
| **weight** | Stroke thickness without changing the requested point size. |
| **line height** | Distance from one line of text to the next. |
| **letter spacing** | Extra space after each character. |
| **word spacing** | Extra space added to normal spaces. |
| **kerning** | How strongly the font adjusts selected letter pairs. |
| **slant** | Adds an artificial slant when a style needs one. |
| **thresholds** | How the rendered coverage is divided into four grey levels. |
| **hinting** | How outlines are fitted to the pixel grid. |
| **grayscale hinting** | Uses the TrueType interpreter intended for grey pixels. |
| **mono rasterizing** | Builds black-and-white glyphs instead of four-level glyphs. |
| **stem darkening** | Thickens eligible outlines before rasterizing them. |
| **ligatures** | Joins sequences such as `fi` when the font provides that form. |
| **figures** | Chooses the font's default digits or proportional digits. |

A **?** button beside a control opens a short explanation. A greyed control
cannot affect the selected font under the current settings. The reason appears
with the control.

### Variable fonts

A variable family shows **text** and **bold** weight lists near the top of
**Tune**. They choose the weight used for the regular and bold styles.

Optical size is not a panel control. When a variable font has an optical-size
axis, CrossGlyph sets it from each point size being built.

## Compare changes

Use **untuned** at the top of the page to show the font without the current Tune
changes. The preview size stays the same. You can also press and hold the
rendered page for the same comparison.

A curved arrow beside one control compares only that control with its saved
value. Press it again to return to the value you were testing.

**Reset font knobs** restores all Tune controls to their default values. It does
not change Page, Text or Device preview settings.

## Check how sharp the strokes are

In the strip at the foot of the page, beside the render time, the page shows
its **Grid Fit**:
the score in large type, how much the last change moved it in a small pill
such as **+22**, and the score for each direction, **X** and **Y**.

The screen is a grid of pixels, and each pixel shows one of four levels of
grey. A straight stroke that lands exactly on whole pixels is black to its
edges. One that lands between pixels gets a column of grey beside it, and on an
e-ink screen that grey reads as blur. Grid Fit counts that grey along the
straight strokes of the text on the page, from 0 to 100. **X** is the upright
strokes, such as the stems of `n` and `l`. **Y** is the flat ones, such as the
bar of `e` or the top of `T`.

It measures sharpness, not whether the font looks good. Curves need their grey
to look smooth, so they are not counted.

- The pill is how much the last change moved the score: filled for a rise,
  dashed for a fall. It compares two pages of the same text, so changing the
  text starts again.
- The score is for the text on the page, weighted by how often each letter
  appears. A few lines of ordinary prose give a steady score. With too few
  letters it is marked **few letters**.
- Press the score to see it for each style on the page.
- With **mono rasterizing** there is no grey, so there is no score.

Point size changes Grid Fit more than most controls do: a quarter of a point
can move a stem onto whole pixels or off them. **Fit to grid** under
[Export](#fit-sizes-to-the-pixel-grid) searches for those sizes for you.

## Match the reading page

Open **Page** near the bottom of **Tune**. These controls reproduce page choices
that CrossPoint applies while reading:

- **margin** changes the space around the text;
- **alignment** chooses justified, left, centered or right-aligned text;
- **line spacing** applies the reader's tight, normal or wide spacing;
- **word spacing** sets each space as a share of the font's own, from 50 to
  200%, as the reader's own Word spacing setting does;
- **character spacing** adds or removes up to 2 pixels between letters, as the
  reader's Character spacing setting does;
- **hyphenate as** chooses patterns for the sample text;
- **hyphenation** turns those patterns on or off;
- **paragraph spacing** adds space between paragraphs;
- **anti-aliasing** changes how the four font levels are painted;
- **night mode** inverts the finished page.

Page settings affect only the browser preview. Save and Build leave them out of
the font config. The browser remembers them so you can keep testing fonts with
the same reading setup.

Tune has a **word spacing** and a **letter spacing** of its own. Those are
built into the font, so every reader of it gets them. The two in Page are a
reader's own settings, applied on top of the font, and only that reader sees
them.

A real book supplies its own language metadata. Set **hyphenate as** to the
language of the sample text you pasted into the preview.

**Reset page settings** returns the section to its starting values.

<p align="center">
  <a href="images/tune.png"><img src="images/tune.png" width="80%"
     alt="The Tune panel beside a rendered page, with Page and Device preview settings open"></a>
</p>

## Change the sample text

Open **Text** below the rendered page. Choose one of the supplied samples or
select **Custom** and paste your own text.

Use text that represents the books you read. Include bold, italic, digits,
punctuation and any scripts that matter to you. The note below the text reports
characters that the current coverage or fallback choices cannot draw.

The browser remembers custom text and the selected sample. Text is a preview
input and is not stored in the font config.

## Use the device preview

Open **Device preview** below the rendered page. It can show the page inside one
of the reader frames included with CrossGlyph or as a bare screen.

The controls include:

- **scale** chooses one screen pixel per monitor pixel, a physical-size view or
  a fit-to-column view;
- **zoom** enlarges the page to show each of the reader's pixels, and **grid**
  draws lines between them (see below);
- **paper** changes the displayed paper brightness;
- **ink** changes the displayed ink strength;
- **warm** and **tint** adjust the screen cast;
- the copy button copies the preview as a PNG;
- holding Shift while pressing the copy button downloads the PNG.

These are viewing settings. They do not change the font or its config. The
browser remembers them.

<p align="center">
  <a href="images/preview-text.png"><img src="images/preview-text.png" width="65%"
     alt="The Device preview and Text settings open"></a>
</p>

### Zoom in on the pixels

**zoom** enlarges the page so you can see how each of the reader's pixels
lands. The level counts screen pixels: at 10×, each reader pixel is a block
10 screen pixels wide. Every block is the same size, so a stroke two pixels
wide always looks twice as wide as one. From 6× up, a **grid** marks the
edges between pixels. It tints the pixels it crosses rather than covering
them, so ink stays dark and paper stays light, and it grows clearer as you
zoom in. Untick **grid** to hide it. While you zoom, the page fills the
whole panel it sits on, and the reader frame is hidden.

- Drag the page to move around it.
- Press and hold without moving to see the page untuned, as you can when
  zoom is off.
- Hold Alt and turn the wheel to zoom in or out around the pointer. The wheel
  alone scrolls the window as usual.
- Double-click to zoom in on a spot, and double-click again to see the whole
  page.
- Click the page, then use + and − to change the zoom, the arrow keys to move
  one pixel (Shift and an arrow for ten), and Esc to turn zoom off.
- Hold Z to let the zoomed page fill the whole browser window, and let go to
  see the controls again. This works straight after moving a slider, so you
  can change a setting and look at the result without clicking anything.
  While Z is held, the wheel alone zooms in and out.

The button beside **+** moves the zoom into a window of its own. Put it next
to the browser or on another screen, and size it as you like: it shows the
page as you change settings, and the panel goes back to the whole page.

- In the window, drag to move around, turn the wheel to zoom, and use the
  same keys as above. Zooming out stops at 2×, and Esc turns zoom off and
  closes the window.
- Double-click the whole page in the panel to move the window's view to that
  spot.
- The copy button copies what the window shows.
- Press the button again, or close the window, to bring the zoom back to the
  panel. The next window opens where the last one was.
- If nothing opens, the browser blocked the window: allow pop-ups for the
  preview's address.

The zoom and the place you are looking at stay put when you change a setting,
so you can watch the same letters as the page redraws.

While zoomed, the copy button copies what you see at the zoom's own size: at
10×, each reader pixel is 10 by 10 pixels in the image, with the grid if it
is showing. Hold Shift to download instead, and Alt to take the whole page.

## Save font settings

**Save** writes the Tune and Export settings to the selected family's config
file. It becomes available when those settings differ from the saved values.

Save writes the values shown on the page. Finish any comparison before saving
if you want to keep the value you were testing.

A family discovered from filenames may not have its own config file yet. Save
creates one for that family instead of changing the shared settings for every
family.

## Choose export settings

**Export** controls what Build writes:

- **name** is the family name shown by the reader;
- **sizes** lists up to eight point sizes to build;
- **suffix** makes sizes 5 to 8 a second family entry;
- **Fit to grid** suggests sizes that look sharper on the device;
- **coverage** chooses character ranges;
- **extra ranges** adds raw Unicode ranges;
- **bundled fallback faces** adds the downloaded Noto families after your own
  faces;
- **fallback 1** and **fallback 2** choose workspace families that fill missing
  characters first;
- **output** shows where the built family is written.

Select a size box to see the page at the size it holds. The box the page is
showing is marked. This changes only the preview, not the font.

A size can be a fraction, such as 13.25. The reader's list shows whole sizes,
so it ships under the whole number it rounds to. Hold the pointer over a box to
see that name. If two sizes round to the same number, a warning under the
boxes says so, since they cannot both be built.

The boxes are two rows of four. With the **suffix** empty, all of them belong
to this family and the reader lists every size. Fill in the suffix and sizes 5
to 8 build a second family entry, named with the suffix, which is clearer when
you want two entries in the reader's font list instead of one long size list.
The suffix stays greyed out until one of sizes 5 to 8 holds a size, since there
is nothing for it to name before then.

Coverage controls which characters are placed in the files. More coverage
creates larger files and takes longer to build. Fallback faces fill characters
that the main family lacks.

<p align="center">
  <a href="images/export.png"><img src="images/export.png" width="55%"
     alt="The complete Export panel with sizes, coverage, fallbacks and build controls"></a>
</p>

## Fit sizes to the pixel grid

**Fit to grid**, a folded section under the sizes in **Export**, suggests point
sizes whose straight strokes land more cleanly on the screen's pixels. It
scores the text on the page with the current Tune settings, as
[Grid Fit](#check-how-sharp-the-strokes-are) does.

1. Put a few lines of the kind of text you read on the page.
2. Open **Fit to grid**. With **My sizes** selected, the sizes in your boxes
   are listed beside it, in both rows. Press **Find sizes**, which counts the
   sizes as it scores them.
3. Press a value in the **Size** or **Suggested** column to show the page at
   that size. Press the other one to compare.
4. Untick any suggestion you do not want in the **Use** column. The box at
   the top of the column ticks or clears all of them at once.
5. Press **Apply**. The suggestions go into the size boxes.
6. Press **Save** or **Build** to keep them.

Each suggestion keeps the number the reader shows in its Font Size list, and
stays within half a point of that number. A box that holds 13.75 ships as 14,
as any fractional size does.

The **Grid Fit** column shows the score a suggestion would have, and **Gain**
how much higher that is than the size now, such as `+11`. Gain is empty when
the size is already the best. Hold the pointer over a score to see the score
now. A suggestion is ticked when it gains at least a few points. A suggestion
your box already holds is ticked and greyed out, since there is nothing to
change. You can change the ticks after **Apply** and press it again: a box
you untick goes back to the size it held at the search. **Apply** leaves
alone any box you have changed since the search. **Undo** puts back what
Apply wrote, and keeps any box you have edited since.

To choose new sizes instead, select **Range** and set where it **starts**, the
**step** between sizes (1, 2 or 3 points) and how many **sizes**, from 1 to 8.
The sizes it will try are listed beside **Range**, such as "Tries 12, 14, 16,
18". A range starts at 10, with a step of 1 and 8 sizes.
Press **Find sizes**. The sizes fill the boxes in order, the first row then the
second.

To put the range's sizes in the boxes as they are, with no search, press
**Fill boxes** beside the list. It writes them in order and empties the boxes
after them. Use it to fill a family's sizes in one press, or to go back to
whole sizes after you have saved suggested ones. **Undo** takes it back until
you save, even after you search the filled sizes and apply suggestions to
them: it goes back to the sizes you had before Fill boxes.

A range is the family's new list of sizes. Each ticked size is kept, including
one the boxes already hold, so untick a size to leave it out, such as the one
with the worst score. **Apply** writes the ticked sizes in order, with no gaps,
and empties the boxes after them. **Undo** brings every box back. If you type
in a size box after the search, Apply writes nothing and asks you to search
again. When a range changes how many sizes the family has, the section says
what Apply would leave, such as "After Apply: one family of 6 sizes". Apply
only changes the
boxes: nothing is built until you press **Build**. With the **suffix** filled
in, the second row is a second family instead.

Fit to grid does not change the suffix. Choosing another family drops the
suggestions, since they were found for the last one. Switching between **My
sizes** and **Range** drops them too, and **Undo** stays for anything Apply has
already written.

## Build

**Build** builds the selected family. **Build all** builds every family in the
font source folder.

Both buttons save the Tune and Export settings before starting. CrossGlyph
builds the point sizes whose inputs changed. Hold Shift to rebuild every size.

The progress line names the current family and size. Warnings and failures
appear below the buttons. See [Troubleshooting](troubleshooting.md) for the
common messages.
