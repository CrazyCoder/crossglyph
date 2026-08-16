# Third party notices

CrossGlyph is MIT licensed. It carries the code below, under the licences
below.

## The render core

`src/crossglyph/render/render.wasm` is a compiled binary. It is built from
`src/render/api.cpp` in this repository together with these libraries from the
CrossPoint firmware, [crosspoint-reader](https://github.com/crosspoint-reader/crosspoint-reader):
`EpdFont`, `GfxRenderer`, `Utf8`, `MiniBidi`, `InflateReader` and the text and
hyphenation parts of `Epub`.

    MIT License
    Copyright (c) 2025 Dave Allie

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

The same binary links three libraries the firmware vendors. Their own licences
travel with their sources in that repository:

| library | licence |
|---|---|
| uzlib | zlib licence, copyright Paul Sokolovsky and Joergen Ibsen |
| miniz | MIT, copyright Rich Geldreich and Tenacious Software |
| MiniBidi | free use with attribution, copyright Arabeyes, Ahmad Khalifa |

## The .cpfont writer

`src/crossglyph/cpfont/convert.py` and `version.py` are a fork of
`scripts/font-builder/` in
[crosspoint-tools](https://github.com/crosspoint-reader/crosspoint-tools), the
repository behind the CrossPoint font website. `src/crossglyph/cpfont/UPSTREAM`
records the commit and what the fork adds.

    MIT License
    Copyright (c) 2025 SoFriendly

Full text as above, with that copyright line.

## The tool wrapper

`tools/tool-wrapper.sh`, `tools/tool-wrapper.cmd`, `tools/tool-wrapper.ps1` and
`tools/uv.cmd` download and verify a pinned uv. They derive from the tool
wrapper in the IntelliJ IDEA monorepo.

    Copyright 2000-2026 JetBrains s.r.o. and contributors
    Licensed under the Apache License, Version 2.0

Full text: https://www.apache.org/licenses/LICENSE-2.0

## The device frames

`src/crossglyph/preview/static/device/` contains geometry-normalized derivatives
of the official XTEINK X3 and X4 front renderings.

    Copyright XTEINK
    All rights reserved.

The device images are not licensed under CrossGlyph's MIT licence.

## The watermark bitmap

`src/crossglyph/preview/server.py` carries the glyphs needed to render the
version watermark from Spleen 6x12 2.2.0 by Frederic Cambus.

    Copyright (c) 2018-2026, Frederic Cambus
    All rights reserved.

    Redistribution and use in source and binary forms, with or without
    modification, are permitted provided that the following conditions are met:

      * Redistributions of source code must retain the above copyright
        notice, this list of conditions and the following disclaimer.

      * Redistributions in binary form must reproduce the above copyright
        notice, this list of conditions and the following disclaimer in the
        documentation and/or other materials provided with the distribution.

    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
    AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
    IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
    ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
    LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
    CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
    SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
    INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
    CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
    ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
    POSSIBILITY OF SUCH DAMAGE.

## The bundled family

`src/crossglyph/starter/` carries Literata 3.103 by TypeTogether, roman and
italic, so the preview has something to draw before anybody has put a font in
the workspace. It is redistributed unmodified, and `OFL.txt` sits beside the
two files.

    Copyright 2017 The Literata Project Authors
    (https://github.com/googlefonts/literata)
    Licensed under the SIL Open Font License, Version 1.1

## The fallback faces

The twelve Noto faces and the CJK faces are downloaded at run time and are not
redistributed here. They are licensed under the SIL Open Font License, and
`fetch-fallbacks` puts `OFL.txt` beside them.
