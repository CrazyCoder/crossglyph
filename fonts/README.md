# Your fonts go here

Put TTF or OTF files in this folder, then run the launcher in the folder above.
No configuration is needed to start: a folder of fonts is a family list.

Until there is a font in here, the preview opens on Literata, which ships with
the tool. It stays in the picker afterwards as something to compare against,
and it is not built unless you ask for it by name or press Save on it.

A family is a set of files sharing a stem: `NotoSans-Regular.ttf`,
`NotoSans-Bold.ttf`, `NotoSans-Italic.ttf`, `NotoSans-BoldItalic.ttf`. CrossGlyph
reads the style off the end of each filename, so a family named the way its
foundry named it needs no configuration.

Settings live in `conf`, one `<family>.conf` per family, with shared values in
`conf/all.conf`. Both are yours and both start absent: copy
`conf/all.conf.example` when you want the shared file, or press Save in the
preview, which writes either for you.

Built families land in `cpfonts`.
