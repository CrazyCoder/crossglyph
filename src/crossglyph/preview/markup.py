"""`*bold*` and `_italic_` in the sample text, as a style per word.

The layout engine takes a style per word (ParsedText::addWord), so emphasis is
per word here too: a mark that opens mid-word still styles the whole word.
That is a limit of this markup, not of the engine.

The word count has to match the engine's exactly -- each paragraph split on
single spaces, empties dropped, a newline separating paragraphs without
consuming a style -- because the module indexes these bytes by word as it lays
the page out. One byte out of step and every following word wears the wrong
face, which reads as a random emphasis bug rather than an off-by-one.
"""
from __future__ import annotations

#: Style bits, as EpdFontFamily::Style numbers them: 1 bold, 2 italic, 3 both.
BOLD, ITALIC = 1, 2

MARKS = {"*": BOLD, "_": ITALIC}


def parse(text: str) -> tuple[str, bytes]:
    """Split marked-up text into plain text and one style byte per word."""
    out, styles = [], bytearray()
    style, word_style, in_word = 0, 0, False

    for index, char in enumerate(text):
        bit = MARKS.get(char)
        if bit is not None and _is_intraword_underscore(text, index):
            bit = None                # some_variable_name is not emphasis
        if bit is not None:
            # The closing branch has to come first. A closing mark has no
            # partner *ahead* of it, so asking _has_partner about it would say
            # no and emit it as literal text -- leaving the run styled to the
            # end of the paragraph, with a stray asterisk in the middle of it.
            if style & bit:
                style ^= bit
                continue
            if _has_partner(text, index):
                style |= bit
                continue
            # Otherwise it is a stray mark, and falls through as literal text.

        if char in (" ", "\n"):
            if in_word:
                styles.append(word_style)
                in_word = False
        elif not in_word:
            in_word, word_style = True, style
        else:
            word_style |= style
        out.append(char)

    if in_word:
        styles.append(word_style)
    return "".join(out), bytes(styles)


def _is_intraword_underscore(text: str, index: int) -> bool:
    """An underscore with letters or digits on both sides.

    `some_variable_name` is a name, not emphasis. Without this it becomes
    *somevariablename* and, worse, the stray opener swallows the next real
    `_italic_` in the paragraph -- text mangled in two places at once. The
    same rule Markdown uses, and only for `_`: a `*` inside a word is rare
    enough in prose to leave alone.
    """
    if text[index] != "_":
        return False
    before = text[index - 1] if index else ""
    after = text[index + 1] if index + 1 < len(text) else ""
    return before.isalnum() and after.isalnum()


def _has_partner(text: str, index: int) -> bool:
    """Whether the mark at `index` is closed later in the same paragraph.

    An unmatched mark is a typo in a text box, not an instruction: showing it
    as an asterisk beats swallowing the rest of the page.

    The candidate has to be eligible itself, or the guarantee is hollow: in
    `_open and some_var here` the leading underscore would find the one inside
    `some_var`, open on it, and then that one would be skipped as intraword --
    leaving the run open to the end of the paragraph, which is the exact
    failure this is here to prevent.
    """
    mark = text[index]
    end = text.find("\n", index + 1)
    stop = len(text) if end < 0 else end
    return any(text[i] == mark and not _is_intraword_underscore(text, i)
               for i in range(index + 1, stop))
