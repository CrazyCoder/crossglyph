"""Build a font, so a test that needs one does not need someone's font folder.

The suite already leans on `D:\\shared\\Xteink\\fontsrc` for the real thing --
tuning, hinting and kerning against actual outlines is the whole point of this
tool, and a synthetic face cannot stand in for that. What it can stand in for
is everything *structural*: which codepoints a face carries, whether it has a
GPOS kern pair, whether a fallback fills a hole. Those tests were reading
whatever fonts happened to be in that folder, which made them slow, and made
what they asserted depend on what had been dropped in there since.

A glyph here is a filled box, so a page drawn with one has ink on it and two
different builds differ. Everything is written to `tmp_path`; nothing is
committed, and nothing is read from outside the repo.
"""
from __future__ import annotations

import pathlib

# One em, and a box that sits on the baseline and fills most of it: real
# outlines, so FreeType rasterizes something and the page is not blank.
UPEM = 1000
BOX = ((80, 0), (520, 0), (520, 700), (80, 700))
ADVANCE = 600


def _glyph_name(codepoint: int) -> str:
    return f"u{codepoint:04X}"


def _draw(pen):
    pen.moveTo(BOX[0])
    for point in BOX[1:]:
        pen.lineTo(point)
    pen.closePath()
    return pen


def box_font(path: pathlib.Path, codepoints, *, kern=None, ligatures=None,
             figures: bool = False, cff: bool = False, family: str = "Probe",
             style: str = "Regular") -> pathlib.Path:
    """A font carrying exactly `codepoints`, each drawn as the same box.

    TrueType outlines unless `cff`, which writes the same boxes as CFF
    charstrings instead. Which of the two a face carries decides more than it
    looks: FreeType rasterizes them through different drivers, and stem
    darkening is one of the things only one of those does.

    The three optional features are written as real OpenType ones, because the
    tables are what the converter walks and this suite has to be able to
    produce them without asking the machine for a font that happens to have
    one.

    `kern` is {(left_codepoint, right_codepoint): units}, as GPOS `kern`.

    `ligatures` is {(codepoint, ...): codepoint}, as GSUB `liga`. Every
    codepoint named has to be in `codepoints`, output included: the converter
    reads the substitute back through the cmap, and a rule it cannot name that
    way is one it drops.

    `figures` adds a narrower alternate for each digit present and a GSUB
    `pnum` feature reaching it. The alternates deliberately have no cmap entry
    of their own, which is how a real face draws them and why the converter
    can only address them by glyph index.
    """
    from fontTools.feaLib.builder import addOpenTypeFeatures
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    codepoints = sorted(set(codepoints))
    names = [_glyph_name(code) for code in codepoints]

    box = _draw(TTGlyphPen(None)).glyph()
    empty = TTGlyphPen(None).glyph()

    # Unmapped alternates, which is what a proportional figure is: reachable
    # through the pnum lookup and by glyph index, and by nothing else.
    narrow = {f"{_glyph_name(code)}.pnum": code for code in codepoints
              if figures and 0x30 <= code <= 0x39}

    builder = FontBuilder(UPEM, isTTF=not cff)
    builder.setupGlyphOrder([".notdef", *names, *narrow])
    builder.setupCharacterMap(dict(zip(codepoints, names)))
    if cff:
        charstrings = {
            name: _draw(T2CharStringPen(ADVANCE, None)).getCharString()
            for name in (".notdef", *names, *narrow)}
        builder.setupCFF(f"{family}-{style}".replace(" ", ""), {},
                         charstrings, {})
    else:
        builder.setupGlyf({".notdef": empty,
                           **{name: box for name in (*names, *narrow)}})
    # A width of its own per alternate, rather than one narrow width for all
    # of them. "Tabular means every digit shares an advance" is the property
    # the feature exists to break, and a fixture whose proportional digits are
    # also uniform cannot tell a working substitution from a dropped one. The
    # one is the narrow digit, as it is in every face that draws these.
    builder.setupHorizontalMetrics(
        {**{name: (ADVANCE, 80) for name in (".notdef", *names)},
         **{name: (ADVANCE // 2 if code == 0x31 else ADVANCE * 3 // 4, 40)
            for name, code in narrow.items()}})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200,
                     usWinAscent=800, usWinDescent=200)
    builder.setupNameTable({"familyName": family, "styleName": style,
                            "psName": f"{family}-{style}".replace(" ", "")})
    builder.setupPost()

    blocks = []
    if kern:
        blocks.append(("kern", [
            f"pos {_glyph_name(left)} {_glyph_name(right)} {value};"
            for (left, right), value in kern.items()]))
    if ligatures:
        blocks.append(("liga", [
            "sub " + " ".join(_glyph_name(code) for code in sequence)
            + f" by {_glyph_name(output)};"
            for sequence, output in ligatures.items()]))
    if narrow:
        blocks.append(("pnum", [f"sub {name.removesuffix('.pnum')} by {name};"
                                for name in narrow]))
    if blocks:
        feature = path.with_suffix(".fea")
        feature.write_text("\n".join(
            f"feature {tag} {{\n" + "\n".join(f"    {rule}" for rule in rules)
            + f"\n}} {tag};\n" for tag, rules in blocks), encoding="utf-8")
        addOpenTypeFeatures(builder.font, str(feature))
        feature.unlink()

    builder.save(str(path))
    return path


#: Letters the joining fixture carries. Two dual-joining, which take all four
#: forms, and one right-joining, which takes two. Real codepoints, because
#: HarfBuzz picks its Arabic shaper from the character's own Unicode joining
#: property and would leave an invented one alone.
DUAL_JOINING = (0x0628, 0x062C)
RIGHT_JOINING = (0x0627,)
JOINING_LETTERS = DUAL_JOINING + RIGHT_JOINING

#: What each feature does to a letter, in the order a face declares them.
_JOINING_FEATURES = (("init", DUAL_JOINING), ("medi", DUAL_JOINING),
                     ("fina", JOINING_LETTERS))


def joining_font(path: pathlib.Path, *, decompose=(), family: str = "Probe",
                 style: str = "Regular") -> pathlib.Path:
    """A face that joins through GSUB and carries no presentation forms.

    This is the shape of font the synthesis exists for. Scheherazade New and
    ReadexPro both hold their joining rules and none of the Presentation
    Forms-B codepoints a CrossPoint device asks by, so a build that only reads
    the cmap finds nothing to draw for any of them.

    The form glyphs deliberately have no cmap entry, the way a real face leaves
    them, so they can only be reached by running the font's own rules.

    `decompose` names letters spelled as a mark plus a base, which is how
    Scheherazade spells the hamza alefs and how Noto spells most of its
    alphabet. Shaping one of those yields a run of two glyphs rather than one.
    Each form gets an advance of its own, so a composed glyph whose second
    piece was dropped is narrower than one that kept it.
    """
    from fontTools.feaLib.builder import addOpenTypeFeatures
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    codepoints = sorted({*JOINING_LETTERS, ord(" ")})
    names = [_glyph_name(code) for code in codepoints]
    forms = [f"{_glyph_name(code)}.{tag}"
             for tag, letters in _JOINING_FEATURES for code in letters]
    marks = [f"{_glyph_name(code)}.mark" for code in decompose]

    box = _draw(TTGlyphPen(None)).glyph()
    empty = TTGlyphPen(None).glyph()

    builder = FontBuilder(UPEM, isTTF=True)
    builder.setupGlyphOrder([".notdef", *names, *forms, *marks])
    builder.setupCharacterMap(dict(zip(codepoints, names)))
    builder.setupGlyf({".notdef": empty,
                       **{name: box for name in (*names, *forms, *marks)}})
    builder.setupHorizontalMetrics({
        **{name: (ADVANCE, 80) for name in (".notdef", *names)},
        # A width per form, so a form that resolved to the wrong glyph shows up
        # as a width and not only as a glyph id.
        **{name: (ADVANCE - 40 * index, 80) for index, name in enumerate(forms)},
        # A real mark carries no advance and is placed by GPOS. This one
        # advances, so a composed run that lost its second piece is measurably
        # narrower than one that kept it.
        **{name: (ADVANCE, 80) for name in marks}})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200,
                     usWinAscent=800, usWinDescent=200)
    builder.setupNameTable({"familyName": family, "styleName": style,
                            "psName": f"{family}-{style}".replace(" ", "")})
    builder.setupPost()

    # `script arab` rather than the default alone: HarfBuzz resolves an Arabic
    # run under the arab script tag, and a feature registered nowhere it looks
    # is a feature it never applies.
    blocks = [
        "languagesystem DFLT dflt;",
        "languagesystem arab dflt;",
    ]
    for tag, letters in _JOINING_FEATURES:
        rules = "\n".join(
            f"    sub {_glyph_name(code)} by {_glyph_name(code)}.{tag};"
            for code in letters)
        blocks.append(f"feature {tag} {{\n    script arab;\n{rules}\n}} {tag};")
    if marks:
        rules = "\n".join(
            f"    sub {_glyph_name(code)} by {_glyph_name(code)}.mark "
            f"{_glyph_name(code)};" for code in decompose)
        blocks.append(f"feature ccmp {{\n    script arab;\n{rules}\n}} ccmp;")

    feature = path.with_suffix(".fea")
    feature.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    addOpenTypeFeatures(builder.font, str(feature))
    feature.unlink()

    builder.save(str(path))
    return path


#: The default instance is deliberately the light end rather than 400, because
#: that is the case that matters: Merriweather defaults to Light, so a build
#: that takes the file as it comes ships a Light face labelled Regular.
VAR_AXIS = ("wght", 300, 300, 900)

#: Named as a real family names them, since discovery reads these names to
#: decide which coordinates a slot is built at.
VAR_INSTANCES = {"Light": 300, "Regular": 400, "Bold": 700, "Black": 900}


def variable_box_font(path: pathlib.Path, codepoints, *, family: str = "Probe",
                      style: str = "Regular", italic: bool = False,
                      instances=None, axis=None) -> pathlib.Path:
    """A variable TTF whose one axis makes the box wider as the weight rises.

    Enough of a variable font to be one: an fvar with named instances, and gvar
    deltas big enough that a build at 700 is visibly not a build at 300. That
    is what lets a test tell which instance was rasterized without measuring
    ink -- the advance itself moves.
    """
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib.tables.TupleVariation import TupleVariation

    tag, minimum, default, maximum = axis or VAR_AXIS
    instances = VAR_INSTANCES if instances is None else instances

    codepoints = sorted(set(codepoints))
    names = [_glyph_name(code) for code in codepoints]

    pen = TTGlyphPen(None)
    pen.moveTo(BOX[0])
    for point in BOX[1:]:
        pen.lineTo(point)
    pen.closePath()
    box = pen.glyph()
    empty = TTGlyphPen(None).glyph()

    builder = FontBuilder(UPEM, isTTF=True)
    builder.setupGlyphOrder([".notdef", *names])
    builder.setupCharacterMap(dict(zip(codepoints, names)))
    builder.setupGlyf({".notdef": empty, **{name: box for name in names}})
    builder.setupHorizontalMetrics(
        {name: (ADVANCE, 80) for name in (".notdef", *names)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200,
                     usWinAscent=800, usWinDescent=200)
    builder.setupNameTable({"familyName": family, "styleName": style,
                            "psName": f"{family}-{style}".replace(" ", "")})
    builder.setupPost()
    builder.setupFvar(
        axes=[(tag, minimum, default, maximum, "Weight")],
        instances=[{"location": {tag: value},
                    "stylename": name + (" Italic" if italic else "")}
                   for name, value in instances.items()])

    # One tuple per glyph at the heavy end: the two right-hand points move out,
    # so the box fattens with the weight and the advance grows with it. Four
    # contour points plus the four phantom points glyf variations carry.
    #
    # The region starts at the axis minimum rather than at the default, so
    # every weight between them differs -- otherwise a slot built at 400 and
    # one built at the font's own default would rasterize the same and a test
    # could not tell which of them ran. 600 units is coarse on purpose, for the
    # same reason: it has to survive being rounded to whole pixels at 13 pt.
    heavy = [(0, 0), (600, 0), (600, 0), (0, 0), (0, 0), (600, 0), (0, 0), (0, 0)]
    builder.setupGvar({
        name: [TupleVariation({tag: (0.0, 1.0, 1.0)}, heavy)] for name in names})

    builder.save(str(path))
    return path
