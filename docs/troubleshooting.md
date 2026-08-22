# Troubleshooting

Start with the result you can see. Messages in the browser and terminal include
the family or setting that caused the problem.

## My family is missing from the browser

Check that the regular TTF or OTF file is inside the font source folder. The
filename must contain a family name. A normal example is
`MyFont-Regular.ttf`.

Return to the browser after changing the folder. CrossGlyph refreshes the family
list when the tab receives focus.

The browser skips `conf`, `cpfonts`, `fallbacks`, dot folders and files that are
not TTF or OTF fonts.

## The styles are grouped incorrectly

CrossGlyph reads styles from filename endings such as Regular, Bold, Italic and
BoldItalic. A folder name does not define the family.

Rename unclear files or set `regular`, `bold`, `italic` and `bolditalic` in the
family config. See [Source files and styles](fonts.md#source-files-and-styles).

## A font control is greyed

The control cannot affect the selected font under the current settings. Read the
text beside it or press its **?** button.

Some controls need a particular outline format or hinting mode. For example,
grayscale hinting applies to hinted TrueType faces. Stem darkening applies only
to supported outline and hinting combinations.

## The preview and built font use different sizes

The **size** control in **Tune** selects the preview size. It does not add a size
to the build.

Open **Export** and set the boxes under **sizes**. Press a size label to preview
that exact build size.

## Page changes appear to alter the font

Margin, alignment, line spacing, hyphenation, paragraph spacing, anti-aliasing
and night mode change only the preview page. They can change line breaks and the
way the existing grey levels are painted.

Use **untuned** to compare font tuning while keeping the same Page settings.

## Characters are blank or replaced

Check the note below **Text**. It reports sample characters that the current
coverage and fallback choices cannot draw.

1. Open **Export**.
2. Select the required **coverage**.
3. Choose **fallback 1** or **fallback 2** when another workspace family has the
   missing characters.
4. Use **Fetch** and enable **bundled fallback faces** when the bundled set has
   them.

A coverage tick asks for a range. At least one selected face must contain each
character that you expect to see.

## Arabic text appears blank

Enable the **Arabic** coverage preset. CrossGlyph prepares the joined forms that
CrossPoint requests.

The main family or a fallback must contain Arabic letters and shaping rules.
Enable bundled fallback faces when your main family has no Arabic face.

## The build warns that a coverage range is empty

The selected faces supplied almost none of the characters in that coverage
preset. The built files can still be useful, so this is a warning by default.

Add a suitable fallback or remove the unused coverage tick. Automated builds
can use the command-line warning option when this should produce a nonzero exit
status.

## The build refuses the font because the reader would reject it

CrossPoint stores characters as consecutive runs. A large, sparse coverage can
exceed the run limit even when it contains fewer characters than another font.

Enable **bundled fallback faces** first. Their broad coverage fills gaps and can
reduce the run count. Otherwise choose a fallback that covers the selected
range more completely or remove that range.

CrossGlyph checks this before rasterizing and does not write a file that the
reader would reject.

## The reader keeps using its built-in font

Confirm that the complete built family folder is under `/fonts` or `/.fonts` on
the SD card. Keep the `.cpfont` filenames and folder together.

Check that the selected point size exists in the family. CrossPoint can only use
the sizes that were built.

Rebuild the family with the current CrossGlyph release and replace the folder on
the card. Current builds check the format limits before writing.

## Build finishes immediately after a source change

A normal build compares source contents and settings with the previous build.
Hold Shift while pressing **Build** or **Build all** to rebuild every size.

On the command line, use the force option described in
[Build fonts](cli.md#build-fonts).

## Build writes to the wrong folder

Check **output** in **Export**. The default is `cpfonts` inside the font
workspace.

For an isolated command-line workspace, set both the workspace and output
options. Changing only the workspace does not change the already resolved
default output folder.

## The preview will not start

Read `preview.log` beside the launcher. It contains setup and server errors.

A port may already be in use. Open the running preview, stop it or choose another
port. The commands are in [Background preview](cli.md#background-preview).

## An update does not complete

Keep the page open while the local preview restarts. If the replacement server
fails to appear, close CrossGlyph and open the launcher again.

Read `preview.log` for setup failures. See [Updating](updating.md) for files
preserved during an update and the command-line rollback path.
