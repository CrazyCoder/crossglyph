# Your fonts go here

Put TTF or OTF files in this folder, then run the launcher in the folder above.

A family is a set of files sharing a stem: `NotoSans-Regular.ttf`,
`NotoSans-Bold.ttf`, `NotoSans-Italic.ttf`, `NotoSans-BoldItalic.ttf`. CrossGlyph
reads the style off the end of each filename, so a family named the way its
foundry named it needs no configuration.

Settings live in `conf`, one `<family>.conf` per family, with shared values in
`conf/all.conf`. The preview writes them for you when you press Save.

Built families land in `cpfonts`.
