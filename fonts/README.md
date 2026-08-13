# Your fonts go here

Put TTF or OTF files in this folder, then run the launcher in the folder above.
No configuration is needed to start: a folder of fonts is a family list.

Until there is a font in here, the preview opens on Literata, which ships with
the tool. It steps aside as soon as you add one of your own.

A family is a set of files sharing a stem: `NotoSans-Regular.ttf`,
`NotoSans-Bold.ttf`, `NotoSans-Italic.ttf`, `NotoSans-BoldItalic.ttf`. CrossGlyph
reads the style off the end of each filename, so a family named the way its
foundry named it needs no configuration.

Settings live in `conf`, one `<family>.conf` per family, with shared values in
`conf/all.conf`. That file ships commented out, so it sets nothing until you
edit it. The preview writes both for you when you press Save.

Built families land in `cpfonts`.
