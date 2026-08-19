"""Opening a FreeType face from a path FreeType cannot open itself.

Ours, not upstream's, though it sits in the fork's directory: the converter
opens faces and so do the page builder and the panel, and every one of them
can be handed a path FT_New_Face will not take.
"""
from __future__ import annotations

import os


def open_face(path):
    """A FreeType face for `path`, read through Python when FreeType cannot.

    freetype-py encodes the path as UTF-8 and hands the bytes to FT_New_Face,
    which opens them with the C library's `fopen`. On Windows that reads a
    byte string in the ANSI code page, so the two disagree over every
    character above ASCII: the name FreeType looks for is not the name on
    disk, and the face fails with FT_Err_Cannot_Open_Resource -- "cannot open
    resource" -- over a file Python itself reads without trouble. A Cyrillic
    or accented user name is enough, and the whole install sits under one.

    Reading the bytes avoids the encoding entirely. FT_New_Memory_Face draws
    from the buffer for the life of the face and freetype-py keeps a reference
    to it, so closing the handle here changes nothing.

    An ASCII path still goes to FreeType by name. A memory face costs a full
    read up front and holds the whole file resident for as long as it is open,
    where FreeType's own stream reads the tables it is asked for. The bundled
    CJK fallback is 15.7 MB, so the difference is worth keeping for the
    installs that never needed the detour.
    """
    import freetype

    path = os.fspath(path)
    if path.isascii():
        return freetype.Face(path)
    with open(path, "rb") as handle:
        return freetype.Face(handle)
