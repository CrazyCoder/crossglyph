"""The HTTP shim: knobs in as JSON, a PNG out."""
import io
import pathlib

import pytest

import fontpaths

from crossglyph import render

SRC = fontpaths.truetype()
needs = pytest.mark.skipif(
    render.is_stale() or SRC is None,
    reason="needs a render core and CROSSGLYPH_TEST_FONT")
#: For the tests that build their own fonts: only the core has to be there.
needs_core = pytest.mark.skipif(
    render.is_stale(), reason="needs a current render core")


def _conf(workspace):
    """The workspace's config folder, created on first use."""
    from crossglyph import fontbuild

    directory = fontbuild.conf_dir(workspace)
    directory.mkdir(exist_ok=True)
    return directory


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    server.set_font_source(SRC)
    return TestClient(server.app)


@needs
def test_posting_knobs_returns_a_png(client):
    from PIL import Image

    response = client.post("/render", json={"size": 13})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(response.content)).size == (480, 800)


@needs
def test_the_page_spec_reaches_the_render(client):
    tight = client.post("/render",
                        json={"size": 13, "page": {"line_spacing": "tight"}})
    wide = client.post("/render",
                       json={"size": 13, "page": {"line_spacing": "wide"}})
    assert tight.content != wide.content


@needs
def test_one_bit_rendering_reaches_the_render(client):
    """The knob a reader who keeps anti-aliasing off is tuning against."""
    from PIL import Image

    response = client.post("/render",
                           json={"size": 13, "page": {"antialiased": False}})
    page = Image.open(io.BytesIO(response.content))
    levels = {value for value, count in enumerate(page.histogram()) if count}
    assert levels <= {0, 255}


#: Greek, which the family built below has none of and its fallback has.
GREEK = 0x3B1


@pytest.fixture
def two_families(tmp_path, monkeypatch):
    """A source folder of exactly two families, built for this test.

    What is being checked is the *relationship* -- one lacks a codepoint the
    other has -- and reading someone's font folder for two that happen to
    stand in that relation made the assertion depend on what was in it, and
    cost a walk of every family in it to find out.
    """
    from fontsmith import box_font

    from crossglyph import fontbuild
    from crossglyph.preview import server

    box_font(tmp_path / "Probe-Regular.ttf",
             [*range(0x20, 0x7F), *map(ord, "Привет, мир")], family="Probe")
    box_font(tmp_path / "Filler-Regular.ttf", [0x20, GREEK, 0x3B2],
             family="Filler")
    (_conf(tmp_path) / "all.conf").write_text("fallbacks = no\n", encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    # The build caches are keyed on paths this fixture reuses across tests, so
    # a stale entry would answer for the previous folder.
    server.forget_families()
    server.build_font_cached.cache_clear()
    server.useful_fallbacks.cache_clear()
    server.set_font_source(tmp_path / "Probe-Regular.ttf", family="Probe")
    yield "Filler"
    server.forget_families()
    server.build_font_cached.cache_clear()
    server.useful_fallbacks.cache_clear()
    server.set_font_source(SRC)


@needs_core
def test_a_chosen_fallback_family_reaches_the_page(client, two_families):
    """The panel's fallback pickers are build settings that now show: a
    codepoint the family lacks is drawn from the face the build would use,
    rather than being blank here and filled on the card."""
    greek = {"size": 13, "text": "α", "family": "Probe"}
    blank = client.post("/render", json=greek)
    filled = client.post("/render", json={**greek, "fallback1": two_families})
    assert blank.status_code == 200 and filled.status_code == 200, filled.text
    assert blank.content != filled.content, \
        "the fallback family drew nothing the family had not already drawn"


@needs_core
def test_the_fallbacks_are_off_the_path_when_the_family_covers_the_text(
        client, two_families):
    """Posted on every render, so they must cost nothing on the usual page --
    where every character is in the family and no fallback is opened at all."""
    body = {"size": 13, "text": "Привет", "family": "Probe"}
    plain = client.post("/render", json=body)
    offered = client.post("/render", json={**body, "fallback1": two_families})
    assert offered.status_code == 200, offered.text
    assert plain.content == offered.content


@needs
def test_a_tuning_knob_reaches_the_render(client):
    plain = client.post("/render", json={"size": 13})
    heavier = client.post("/render", json={"size": 13,
                                           "tuning": {"weight": 0.5}})
    assert plain.content != heavier.content


@needs
def test_a_bad_knob_is_a_client_error_not_a_crash(client):
    response = client.post("/render",
                           json={"size": 13, "page": {"alignment": "diagonal"}})
    assert response.status_code == 422
    assert "alignment" in response.text


@needs
def test_an_unknown_tuning_field_is_a_client_error(client):
    response = client.post("/render",
                           json={"size": 13, "tuning": {"nonsense": 1}})
    assert response.status_code == 422


@needs
def test_the_same_request_twice_is_served_from_the_cache(client):
    from crossglyph.preview import server

    server.build_font_cached.cache_clear()
    body = {"size": 13, "text": "Проверка"}
    client.post("/render", json=body)
    misses = server.build_font_cached.cache_info().misses
    client.post("/render", json=body)
    assert server.build_font_cached.cache_info().misses == misses, \
        "an identical request rasterized the font a second time"


def test_the_two_style_vocabularies_agree():
    """The faces come back keyed by fontconf's style names and are mapped
    through STYLE_IDS, which drops anything it does not know -- so a style
    fontconf grows that this table lacks would go missing from every preview
    without a word. The one assertion that catches that needs no font at all.
    """
    from crossglyph import fontconf
    from crossglyph.preview import server

    assert set(server.STYLE_IDS) == set(fontconf.STYLES)


def test_a_family_name_stands_in_for_its_face_paths():
    """Starting the app is the one place this tool asks for typing, and the
    face paths are most of it. The family's own .conf already knows them."""
    from crossglyph import fontbuild
    from crossglyph.preview import server

    families = [config.name for config in fontbuild.gather(fontbuild.SOURCE_DIR)[0]]
    if not families:
        pytest.skip("needs the local font source folder")

    faces = server.family_faces(families[0])
    assert "regular" in faces, f"{families[0]} resolved no regular face"
    assert all(path.is_file() for path in faces.values())


@needs
def test_the_page_can_ask_for_another_family(client):
    """The picker's whole point: changing which font is set should not mean
    restarting the app, so the family rides on the request rather than being
    process state."""
    from crossglyph.preview import server

    names = [entry["name"] for entry in server.families()]
    if len(names) < 2:
        pytest.skip("needs two families in the font source folder")

    pages = [client.post("/render", json={"size": 13, "family": name})
             for name in names[:2]]
    assert all(page.status_code == 200 for page in pages)
    assert pages[0].content != pages[1].content, \
        f"{names[0]} and {names[1]} drew the same page"


@needs
def test_a_family_the_folder_lost_is_a_client_error(client):
    """A remembered choice whose files have moved. The page falls back on its
    own, but a stale one that slips through must not be a 500."""
    response = client.post("/render", json={"size": 13, "family": "no-such"})
    assert response.status_code == 422
    assert "there is:" in response.text


@needs
def test_the_picker_is_told_what_there_is(two_families):
    """One walk of the folder answers both halves, so the page can say which
    faces a family will load without a request per entry."""
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    response = TestClient(server.app).get("/defaults").json()
    assert {entry["name"] for entry in response["families"]} == {"Probe", "Filler"}
    assert all(entry["faces"] for entry in response["families"])


def test_an_unknown_family_says_what_there_is():
    """The failure people hit is a misremembered name, so the answer has to be
    the list rather than 'not found'."""
    from crossglyph import fontbuild
    from crossglyph.preview import server

    if not fontbuild.SOURCE_DIR.is_dir():
        pytest.skip("needs the local font source folder")

    with pytest.raises(LookupError, match="there is:"):
        server.family_faces("no-such-family")


@needs
def test_the_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_the_page_and_its_modules_are_never_cached(client):
    """This is a tool you edit while it is running. A browser that keeps the
    modules serves them after the edit meant to fix them: the page runs the old
    code, the change reads as having done nothing, and the search moves to the
    wrong question. It costs nothing to say no here."""
    for path in ("/", "/js/app.js", "/style.css"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "no-store", path


@needs
def test_the_sample_text_is_offered_to_the_page(client):
    """The text box starts empty and falls back to the server's sample, so the
    page has to be able to show what that sample is."""
    from crossglyph import preview

    response = client.get("/defaults")
    assert response.status_code == 200
    assert response.json()["text"] == preview.SAMPLE_TEXT


def test_rendering_without_a_font_source_says_so():
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    server.set_font_source(None)
    try:
        response = TestClient(server.app).post("/render", json={"size": 13})
        assert response.status_code == 503
        assert "--font" in response.text
    finally:
        server.set_font_source(SRC)


# --- the knob panel -------------------------------------------------------


def _controls():
    """Every named control in the *knob* form, with the group it posts under.

    Scoped to that form: the export panel below the page is a second form with
    names of its own, and they answer to a different half of the server.
    """
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    html = html[html.index('<form id="knobs">'):html.index("</form>")]
    found = {}
    for tag in re.findall(r"<(?:input|select|textarea)\b[^>]*>", html):
        name = re.search(r'name="([^"]+)"', tag)
        if not name:
            continue
        group = re.search(r'data-group="([^"]+)"', tag)
        found[name.group(1)] = group.group(1) if group else "tuning"
    return found


def test_every_knob_on_the_page_is_one_the_server_takes():
    """A knob whose name is wrong does not fail -- it silently does nothing,
    which is indistinguishable from a knob that has no effect on this font.
    Cheaper to pin the names than to notice that by eye."""
    from crossglyph.cpfont.tuning import Tuning
    from crossglyph.preview import server

    fields = {
        "root": set(server.RenderRequest.model_fields),
        "page": set(server.PageKnobs.model_fields),
        "tuning": {f.name for f in __import__("dataclasses").fields(Tuning)},
        # The variable-font pickers are not fields of their own: the page
        # gathers them into `axes`, keyed by the slot each one drives.
        "axes": {f"axis_{slot}" for slot in server.WEIGHT_SLOTS},
    }
    for name, group in _controls().items():
        assert name in fields[group], \
            f"the page posts {name!r} under {group!r}, which takes no such field"


def test_the_page_offers_every_language_the_core_can_hyphenate():
    """The patterns are compiled into the render core, so a language the
    firmware carries and the page does not offer is one nobody can preview.

    Which is how the list fell four short: the page was written against the
    languages there were, and LanguageRegistry.cpp went on gaining them.
    Reading the registry rather than a copy of it is what keeps the next
    addition from being invisible here.
    """
    import re

    from crossglyph import render
    from crossglyph.preview import server

    registry = (render.FIRMWARE / "lib" / "Epub" / "Epub" / "hyphenation"
                / "LanguageRegistry.cpp")
    if not registry.is_file():
        pytest.skip(f"{registry} not found (no firmware checkout beside this one)")
    carried = set(re.findall(r'\{"\w+",\s*"(\w+)",\s*&\w+Hyphenator\}',
                             registry.read_text(encoding="utf-8")))
    assert carried, "read no languages out of the registry"

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    picker = re.search(r'<select id="language".*?</select>', html, re.S)
    offered = set(re.findall(r'<option value="(\w*)"', picker.group(0)))
    assert carried <= offered, f"the page cannot preview {carried - offered}"
    # And nothing the core would silently find no breaks for. Empty is the
    # page's own "off", which is a choice rather than a language.
    assert offered - carried == {""}, offered - carried


def test_the_export_panel_posts_what_the_server_reads():
    """The same trap as the knobs, one form down: a misspelt name here saves
    nothing rather than failing."""
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    html = html[html.index('<form id="export">'):]
    names = set(re.findall(r'<(?:input|select)\b[^>]*name="([^"]+)"', html))
    # `out` is all.conf's and posts to an endpoint of its own; the rest ride
    # along with a save, in the shape family_entry reports them.
    assert names == {"size1", "size2", "size3", "size4", "size_more",
                     "mod1", "mod2", "mod3", "mod4", "mod_more", "mod_suffix",
                     "ranges", "fallbacks", "fallback1", "fallback2",
                     "out"}, names

    # A box is not a key: the four steps and the row past them join into one
    # `sizes`, and the second family's four into `sizes_mod`. So what has to
    # line up with the server is what the page builds out of them.
    source = (server.STATIC / "js" / "export.js").read_text(encoding="utf-8")
    body = source[source.index("function exportSettings()"):]
    posted = set(re.findall(r"^\s*(\w+):", body[:body.index("\n}")], re.M))
    assert posted == {"sizes", "sizes_mod", "mod_suffix", "intervals",
                      "ranges", "fallbacks", "fallback1", "fallback2"}, posted


def test_the_page_offers_every_page_knob():
    """The other direction: a knob the server takes but the panel never shows
    is one nobody can turn."""
    from crossglyph.preview import server

    shown = {name for name, group in _controls().items() if group == "page"}
    assert shown == set(server.PageKnobs.model_fields)


ITALIC_SRC = fontpaths.italic()
needs_italic = pytest.mark.skipif(ITALIC_SRC is None,
                                  reason="set CROSSGLYPH_TEST_ITALIC to the italic face")


@needs
@needs_italic
def test_a_second_face_reaches_the_render():
    """The emphasis in the sample text has somewhere to go once the family
    has an italic, and nowhere before that."""
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    try:
        server.set_font_source(SRC)
        one = TestClient(server.app).post("/render", json={"size": 13})
        server.set_font_source(SRC, italic=ITALIC_SRC)
        two = TestClient(server.app).post("/render", json={"size": 13})
        assert one.content != two.content
        assert TestClient(server.app).get("/defaults").json()["faces"] == \
            ["italic", "regular"]
    finally:
        server.set_font_source(SRC)


@needs
def test_the_line_height_knob_reaches_the_page(client):
    """The converter's own interline knob: it changes advanceY in the .cpfont,
    so it is what ships on the card -- distinct from the reader's tight/normal/
    wide setting, which multiplies it at render time."""
    tight = client.post("/render",
                        json={"size": 13, "tuning": {"line_height": 1.0}})
    loose = client.post("/render",
                        json={"size": 13, "tuning": {"line_height": 2.0}})
    assert tight.status_code == loose.status_code == 200
    assert tight.content != loose.content


@needs
def test_omitting_the_line_height_keeps_the_fonts_own(client):
    """Absent means "whatever hhea says", which no slider position stands for.
    The panel deletes the field rather than inventing a number for it."""
    from crossglyph.preview import server

    absent = client.post("/render", json={"size": 13})
    explicit = client.post("/render",
                           json={"size": 13, "tuning": {"line_height": ""}})
    assert absent.content == explicit.content
    assert server._tuning((("line_height", ""),)).line_height is None


@needs
def test_a_line_height_with_a_unit_is_understood(client):
    """The same three forms the .conf parser takes, through the same parse:
    a bare number is a multiple of the em, `x` the font's own, `px` literal."""
    from crossglyph.preview import server

    assert server._tuning((("line_height", 1.4),)).line_height.mode == "em"
    assert server._tuning((("line_height", "1.4x"),)).line_height.mode == "scale"
    assert server._tuning((("line_height", "30px"),)).line_height.mode == "px"
    assert client.post("/render",
                       json={"size": 13,
                             "tuning": {"line_height": "30px"}}).status_code == 200


@needs
def test_a_nonsense_line_height_is_a_client_error(client):
    response = client.post("/render",
                           json={"size": 13, "tuning": {"line_height": "wide"}})
    assert response.status_code == 422
    assert "line_height" in response.text


@needs
def test_a_list_valued_tuning_knob_round_trips(client):
    """JSON has no tuples, so thresholds arrives as a list -- and a list in an
    lru_cache key raises TypeError, which surfaced as a 422 saying
    "unhashable type". thresholds is a documented knob."""
    default = client.post("/render", json={"size": 13})
    darkened = client.post("/render",
                           json={"size": 13, "tuning": {"thresholds": [3, 6, 10]}})
    assert darkened.status_code == 200, darkened.text
    assert darkened.content != default.content


@needs
def test_a_fractional_size_reaches_the_render(client):
    response = client.post("/render", json={"size": 13.5})
    assert response.status_code == 200
    assert response.content != client.post("/render", json={"size": 13}).content


def test_the_defaults_served_are_the_devices(client):
    """The panel and the API have to agree with CrossPointSettings, or the
    first page anyone sees is a layout the reader does not ship."""
    from crossglyph.preview import server

    knobs = server.PageKnobs()
    assert knobs.hyphenation is False
    assert knobs.extra_paragraph_spacing is True
    assert knobs.alignment == "justify"
    assert knobs.line_spacing == "normal"


@needs
def test_editing_the_text_reuses_the_font_when_the_alphabet_holds(client):
    """The cache is keyed on the coverage, not the text: typing another
    sentence in the same language asks for glyphs the last build already has,
    and paying 25 ms a keystroke for that would be the whole point missed."""
    from crossglyph.preview import server

    server.build_font_cached.cache_clear()
    client.post("/render", json={"size": 13, "text": "Проверка связи"})
    misses = server.build_font_cached.cache_info().misses
    client.post("/render", json={"size": 13, "text": "связи Проверка"})
    assert server.build_font_cached.cache_info().misses == misses, \
        "a text edit within the same alphabet rasterized the font again"

    client.post("/render", json={"size": 13, "text": "Проверка ζ"})
    assert server.build_font_cached.cache_info().misses == misses + 1, \
        "a character the build did not have was not rasterized"


@needs
def test_a_corrupt_face_is_a_client_error_not_a_traceback(tmp_path):
    """Two classes are called FontBuildError; the one this path can raise is
    the converter's (convert.py:321), not the family builder's. Catching the
    wrong one left a 500 traceback where a 422 belongs."""
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    broken = tmp_path / "broken.ttf"
    broken.write_bytes(b"not a font at all")
    server.set_font_source(broken)
    try:
        response = TestClient(server.app).post("/render", json={"size": 13})
        assert response.status_code == 422, response.text
    finally:
        server.set_font_source(SRC)


PNUM_SRC = fontpaths.cff()
needs_pnum = pytest.mark.skipif(PNUM_SRC is None,
                                reason="set CROSSGLYPH_TEST_OTF to a face with a pnum feature")


@needs_pnum
def test_the_figures_knob_reaches_the_page():
    """A synthesized face has no pnum feature, and the knob is honestly inert
    without one. This needs a face whose designer drew proportional figures,
    and the sample text carries enough digits to show the substitution."""
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    try:
        server.set_font_source(PNUM_SRC)
        client = TestClient(server.app)
        plain = client.post("/render", json={"size": 13})
        prop = client.post("/render", json={
            "size": 13, "tuning": {"figures": "proportional"}})
        assert plain.status_code == 200 and prop.status_code == 200
        assert plain.content != prop.content
    finally:
        server.set_font_source(SRC)


@needs
def test_an_unknown_figure_style_is_a_422(client):
    # Through the fixture, which sets the font source: without one the answer
    # is a 503 about the source and the knob is never looked at, so the test
    # passed or failed on whatever ran before it in the same process.
    response = client.post("/render", json={
        "size": 13, "tuning": {"figures": "oldstyle"}})
    assert response.status_code == 422, response.text
    assert "figures" in response.text


# --- saving back to the .conf ---------------------------------------------
# A scratch source folder, never the real one: these tests write configs.

SCRATCH_FONTS = ["Alto-Medium.otf", "Alto Bold.otf",
                 "Ledger.ttf", "Ledger Bold.ttf"]


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """A font source folder with two families, one of which has no .conf."""
    from crossglyph import fontbuild

    for name in SCRATCH_FONTS:
        (tmp_path / name).write_bytes(b"")
    (_conf(tmp_path) / "all.conf").write_text("gamma = 1.2\nkerning = 0.5\n",
                                       encoding="utf-8")
    (_conf(tmp_path) / "alto.conf").write_text(
        "# Alto.\nname   = Alto\nweight = 0.1\n", encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    return tmp_path


def _save(scratch, family, **tuning):
    """Post a save the way the panel does: every knob it owns, not a patch."""
    from fastapi.testclient import TestClient

    from crossglyph.cpfont.tuning import Tuning
    from crossglyph.preview import server

    showing = next((f["tuning"] for f in server.families()
                    if f["name"] == family), Tuning().as_dict())
    body = {key: showing[key] for key in server.SAVED_KEYS}
    body.update(tuning)
    # Absent is what "the font's own" posts, and the only key allowed to be.
    if body.get("line_height") is None:
        body.pop("line_height", None)
    return TestClient(server.app).post(
        "/save", json={"family": family, "tuning": body})


def test_the_panel_is_what_the_family_is_set_to(scratch):
    """all.conf underneath the family's own file, which is the build the card
    would get -- so it is where the knobs start."""
    from crossglyph.preview import server

    entry = next(f for f in server.families() if f["name"] == "Alto")
    assert entry["tuning"]["gamma"] == 1.2, "all.conf was not read"
    assert entry["tuning"]["weight"] == 0.1, "the family's own file was not"
    assert entry["conf"] == "alto.conf" and entry["derived"] is False


def test_saving_writes_only_what_differs_from_all_conf(scratch):
    """The point of all.conf is that changing it moves every family, which
    stops being true the moment each family repeats its values back."""
    response = _save(scratch, "Alto", gamma=1.2, weight=0.4)
    assert response.status_code == 200, response.text
    assert response.json()["moved"] == ["weight"]

    text = (_conf(scratch) / "alto.conf").read_text(encoding="utf-8")
    assert "weight = 0.4" in text
    assert "gamma" not in text, "a value all.conf already gives was restated"
    assert text.startswith("# Alto.\n"), "the file's own comment was lost"


def test_a_knob_returning_to_the_shared_value_loses_its_line(scratch):
    _save(scratch, "Alto", gamma=1.9)
    assert "gamma = 1.9" in (_conf(scratch) / "alto.conf").read_text(encoding="utf-8")

    response = _save(scratch, "Alto", gamma=1.2)
    assert response.json()["moved"] == ["gamma"]
    assert "gamma" not in (_conf(scratch) / "alto.conf").read_text(encoding="utf-8")


def test_a_family_with_no_config_gets_one_rather_than_all_conf(scratch):
    """Its config.path *is* all.conf, so the obvious write would retune every
    family in the folder."""
    before = (_conf(scratch) / "all.conf").read_text(encoding="utf-8")

    response = _save(scratch, "Ledger", gamma=1.7)
    assert response.status_code == 200, response.text
    assert response.json()["conf"] == "ledger.conf"
    assert (_conf(scratch) / "all.conf").read_text(encoding="utf-8") == before, \
        "the shared defaults were rewritten"
    assert "gamma = 1.7" in \
        (_conf(scratch) / "ledger.conf").read_text(encoding="utf-8")


def test_what_comes_back_is_what_the_file_now_says(scratch):
    """Read back rather than echoed: the panel's baseline has to be the file,
    or a value the writer declined to store would look saved."""
    saved = _save(scratch, "Alto", weight=0.4).json()["tuning"]
    from crossglyph.preview import server

    assert saved == next(f for f in server.families()
                         if f["name"] == "Alto")["tuning"]


def test_saving_an_unknown_family_is_a_client_error(scratch):
    response = _save(scratch, "no-such", gamma=1.5)
    assert response.status_code == 422
    assert "there is:" in response.text


def test_saving_a_knob_the_converter_would_refuse_is_a_client_error(scratch):
    response = _save(scratch, "Alto", figures="oldstyle")
    assert response.status_code == 422
    assert "figures" in response.text
    assert not (_conf(scratch) / "alto.conf").read_text(encoding="utf-8").count(
        "figures"), "a rejected save still touched the file"


# --- the export half ------------------------------------------------------


def test_the_panel_is_told_what_a_family_builds_as(scratch):
    from crossglyph.preview import server

    (_conf(scratch) / "alto.conf").write_text(
        "sizes = 12 13\nintervals = cyrillic\nfallbacks = no\n"
        "fallback_regular = Ledger.ttf\n", encoding="utf-8")
    entry = next(f for f in server.families() if f["name"] == "Alto")

    assert entry["export"]["sizes"] == "12 13"
    assert entry["export"]["intervals"] == "cyrillic"
    assert entry["export"]["fallbacks"] is False
    assert entry["export"]["fallback1"] == "Ledger", \
        "a fallback file is offered as the family it belongs to"
    assert entry["export"]["fallback2"] == ""


def _save_export(family, **export):
    from fastapi.testclient import TestClient

    from crossglyph.cpfont.tuning import Tuning
    from crossglyph.preview import server

    tuning = {key: Tuning().as_dict()[key] for key in server.SAVED_KEYS}
    tuning.pop("line_height", None)
    body = {"sizes": "12 14 16 18", "intervals": "reading", "ranges": "",
            "fallbacks": False, "fallback1": "", "fallback2": ""}
    body.update(export)
    return TestClient(server.app).post(
        "/save", json={"family": family, "tuning": tuning, "export": body})


def test_the_export_settings_save_beside_the_tuning(scratch):
    response = _save_export("Alto", sizes="10 12", intervals="cyrillic,greek",
                            ranges="(0x2900-0x29FF)")
    assert response.status_code == 200, response.text

    text = (_conf(scratch) / "alto.conf").read_text(encoding="utf-8")
    assert "sizes = 10 12" in text
    assert "intervals = cyrillic,greek" in text
    assert "ranges = (0x2900-0x29FF)" in text


def test_a_second_family_saves_with_the_suffix_that_names_it(scratch):
    """`sizes_mod` builds <name><mod_suffix> from the same faces, so the suffix
    is only worth writing beside sizes -- and only when it is not the one the
    family would be called anyway."""
    from crossglyph.preview import server

    response = _save_export("Alto", sizes_mod="13 15", mod_suffix="Alt")
    assert response.status_code == 200, response.text
    text = (_conf(scratch) / "alto.conf").read_text(encoding="utf-8")
    assert "sizes_mod = 13 15" in text
    assert "mod_suffix = Alt" in text

    entry = next(f for f in server.families() if f["name"] == "Alto")
    assert entry["export"]["sizes_mod"] == "13 15"
    assert entry["export"]["mod_suffix"] == "Alt", "the panel would open blank"

    # The default suffix is not worth a line, and neither is a suffix with no
    # second family to name.
    _save_export("Alto", sizes_mod="13 15", mod_suffix="Mod")
    assert "mod_suffix" not in (_conf(scratch) / "alto.conf").read_text(encoding="utf-8")
    _save_export("Alto", sizes_mod="", mod_suffix="Alt")
    text = (_conf(scratch) / "alto.conf").read_text(encoding="utf-8")
    assert "sizes_mod" not in text and "mod_suffix" not in text


def test_a_fallback_family_is_stored_as_its_regular_file(scratch):
    """The converter takes a file; the panel offers families, because that is
    the only sane way to pick one. The trip in has to land on the face."""
    response = _save_export("Alto", fallback1="Ledger")
    assert response.status_code == 200, response.text
    assert "fallback_regular = Ledger.ttf" in \
        (_conf(scratch) / "alto.conf").read_text(encoding="utf-8")

    _save_export("Alto", fallback1="")
    assert "fallback_regular" not in \
        (_conf(scratch) / "alto.conf").read_text(encoding="utf-8"), \
        "clearing the picker left the file behind"


def test_sizes_the_device_could_not_read_are_refused(scratch):
    """The label reaching the card is a uint8 the device parses with strtol
    (SdCardFontRegistry.cpp:85), so this is a 422 rather than a family that
    builds a file nothing loads."""
    response = _save_export("Alto", sizes="900")
    assert response.status_code == 422
    assert "255" in response.text


def test_where_builds_go_is_all_confs_business(scratch):
    from fastapi.testclient import TestClient

    from crossglyph import fontbuild
    from crossglyph.preview import server

    client = TestClient(server.app)
    answer = client.get("/defaults").json()
    assert answer["out"] == "", "all.conf says nothing about where builds go"
    assert answer["out_resolved"] == str(scratch / fontbuild.OUTPUT_NAME), \
        "and the default is beside the sources"

    response = client.post("/out", json={"out": "../elsewhere"})
    assert response.status_code == 200, response.text
    assert response.json()["out"] == str((scratch / ".." / "elsewhere").resolve())
    assert "out = ../elsewhere" in (_conf(scratch) / "all.conf").read_text(encoding="utf-8")

    client.post("/out", json={"out": ""})
    assert "out" not in (_conf(scratch) / "all.conf").read_text(encoding="utf-8")


def _steps(response):
    """The build's progress lines, as dicts."""
    import json

    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_building_writes_the_families_the_folder_declares(tmp_path, monkeypatch):
    """The whole point of the Build button: what crossglyph build would produce,
    from the same configs, without leaving the page."""
    import shutil

    from fastapi.testclient import TestClient

    from crossglyph import fontbuild
    from crossglyph.preview import server

    if SRC is None:
        pytest.skip("needs the local font source")
    shutil.copy(SRC, tmp_path / SRC.name)
    family = SRC.stem
    (_conf(tmp_path) / f"{family}.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = no\nspace_glyphs = no\n",
        encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)

    steps = _steps(TestClient(server.app).post("/build", json={}))
    assert [step["event"] for step in steps] == ["plan", "size", "done"], steps
    assert steps[0]["total"] == 1
    # Lowercase because the font file is: the family's capitalisation comes
    # from the filename rather than from the config's.
    assert steps[1] == {"event": "size", "family": family, "size": 12,
                        "done": 1, "total": 1}
    assert steps[-1]["out"] == str(tmp_path / fontbuild.OUTPUT_NAME)
    assert steps[-1]["families"] == [
        {"name": family, "sizes": [12], "built": [12], "skipped": [],
         "failed": [], "removed": [], "error": None}]
    assert (tmp_path / "cpfonts" / family / f"{family}_12.cpfont").is_file()

    again = _steps(TestClient(server.app).post("/build", json={}))
    assert again[0]["total"] == 0, "a second build redid the work"
    assert again[-1]["families"][0]["skipped"] == [12]


def test_a_build_says_where_it_has_got_to(tmp_path, monkeypatch):
    """Four families at four sizes with the fallbacks on is minutes. A button
    that says "building" for all of it is a hung one, as far as anybody
    watching can tell."""
    import shutil

    from fastapi.testclient import TestClient

    from crossglyph import fontbuild
    from crossglyph.preview import server

    if SRC is None:
        pytest.skip("needs the local font source")
    shutil.copy(SRC, tmp_path / SRC.name)
    family = SRC.stem
    (_conf(tmp_path) / f"{family}.conf").write_text(
        "sizes = 12 13\nintervals = base\nfallbacks = no\nspace_glyphs = no\n",
        encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)

    steps = _steps(TestClient(server.app).post("/build", json={}))
    assert [step["event"] for step in steps] == ["plan", "size", "size", "done"]
    assert [step.get("done") for step in steps if step["event"] == "size"] == [1, 2]
    assert all(step["total"] == 2 for step in steps if "total" in step), \
        "the count is known before the first font is rasterized"


def test_a_family_that_cannot_build_does_not_take_the_others_with_it(
        tmp_path, monkeypatch):
    """One bad face in a folder-wide build must not lose the rest of it, and
    the failure has to arrive as a line rather than as a status: by then the
    response has been going for minutes."""
    import shutil

    from fastapi.testclient import TestClient

    from crossglyph import fontbuild
    from crossglyph.preview import server

    if SRC is None:
        pytest.skip("needs the local font source")
    shutil.copy(SRC, tmp_path / SRC.name)
    family = SRC.stem
    (_conf(tmp_path) / f"{family}.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = no\nspace_glyphs = no\n",
        encoding="utf-8")
    (tmp_path / "Broken.ttf").write_bytes(b"not a font at all")
    (_conf(tmp_path) / "broken.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = no\nspace_glyphs = no\n",
        encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)

    steps = _steps(TestClient(server.app).post("/build", json={}))
    kinds = [step["event"] for step in steps]
    assert "failed" in kinds and kinds[-1] == "done", steps
    assert (tmp_path / "cpfonts" / family / f"{family}_12.cpfont").is_file(), \
        "the family that could build did not"
    done = steps[-1]["families"]
    assert any(one["error"] for one in done)
    assert any(one["built"] for one in done)


def test_building_everything_drops_the_families_no_config_produces(
        tmp_path, monkeypatch):
    """`crossglyph build` with no config named removes them, and Build all is that
    same command: a renamed family -- or one that stops being its own, the way
    georgiaz became the bold italic of georgia -- otherwise leaves a whole
    directory behind that the simulator would go on staging.
    """
    from fastapi.testclient import TestClient

    from fontsmith import box_font

    from crossglyph import fontbuild
    from crossglyph.preview import server

    box_font(tmp_path / "Alpha-Regular.ttf", range(0x20, 0x7F), family="Alpha")
    box_font(tmp_path / "Beta-Regular.ttf", range(0x20, 0x7F), family="Beta")
    (_conf(tmp_path) / "all.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = no\nspace_glyphs = no\n",
        encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    client = TestClient(server.app)

    built = _steps(client.post("/build", json={}))
    assert built[-1]["event"] == "done", built
    out = tmp_path / fontbuild.OUTPUT_NAME
    assert (out / "Alpha").is_dir() and (out / "Beta").is_dir()

    (tmp_path / "Beta-Regular.ttf").unlink()
    # Naming a family is not a build of everything: the others are simply not
    # under consideration, so nothing of theirs may be removed.
    named = _steps(client.post("/build", json={"family": "Alpha"}))
    assert named[0]["removed"] == [], named[0]
    assert (out / "Beta").is_dir(), "a build of one family deleted another"

    everything = _steps(client.post("/build", json={}))
    assert everything[0]["removed"] == ["Beta"], everything[0]
    assert everything[-1]["removed"] == ["Beta"], "the summary lost it"
    assert not (out / "Beta").exists()
    assert (out / "Alpha").is_dir(), "the family that still exists went too"


@needs
def test_the_quantizer_thresholds_reach_the_render(client):
    """Where the cut points between the four grey levels sit, which is what a
    face that sets too light on the panel needs moved."""
    plain = client.post("/render", json={"size": 13})
    darker = client.post("/render",
                         json={"size": 13, "tuning": {"thresholds": "3,6,10"}})
    assert darker.status_code == 200, darker.text
    assert plain.content != darker.content


@needs
def test_a_malformed_threshold_triple_is_a_client_error(client):
    response = client.post("/render",
                           json={"size": 13, "tuning": {"thresholds": "3,6"}})
    assert response.status_code == 422
    assert "thresholds" in response.text


def test_a_configs_own_triple_reaches_the_panel(scratch):
    """The knobs open at what the family is set to, and this is the one whose
    control is a list rather than a number: a triple the list does not offer
    has to arrive intact rather than as the default."""
    from crossglyph.preview import server

    (_conf(scratch) / "alto.conf").write_text("thresholds = 2,5,9\n", encoding="utf-8")
    entry = next(f for f in server.families() if f["name"] == "Alto")
    assert entry["tuning"]["thresholds"] == [2, 5, 9]


def test_saving_writes_the_thresholds_triple(scratch):
    from fastapi.testclient import TestClient

    from crossglyph.cpfont.tuning import Tuning
    from crossglyph.preview import server

    tuning = {key: Tuning().as_dict()[key] for key in server.SAVED_KEYS}
    tuning.pop("line_height", None)
    tuning["thresholds"] = "3,6,10"
    TestClient(server.app).post("/save", json={"family": "Alto",
                                               "tuning": tuning})
    assert "thresholds = 3,6,10" in \
        (_conf(scratch) / "alto.conf").read_text(encoding="utf-8")


def test_asking_for_bundled_fallbacks_without_them_says_where_to_get_them(
        scratch, monkeypatch):
    """They are large, unmodified and OFL, so this repo does not vendor them.
    Ticking the box without them is a state of the workspace: the answer says
    where it looked and how to fetch them, rather than being a traceback."""
    from fastapi.testclient import TestClient

    from crossglyph import fontbuild
    from crossglyph.preview import server

    (_conf(scratch) / "alto.conf").write_text("sizes = 12\nfallbacks = yes\n",
                                                encoding="utf-8")

    # A line rather than a status: the response starts before the first font
    # is built, so by the time this is known the headers are long gone.
    steps = _steps(TestClient(server.app).post("/build", json={"family": "Alto"}))
    assert steps[-1]["event"] == "error", steps
    assert "fetch-fallbacks" in steps[-1]["error"]
    assert str(scratch / "fallbacks") in steps[-1]["error"], \
        "the answer has to say where it looked"
    # And the way out that this reader has: the command is for a terminal they
    # are not in, and the button is three rows above the note they are reading.
    assert "Fetch" in steps[-1]["error"], \
        "the panel's own answer has to name the panel's own button"


# --- variable families ----------------------------------------------------

@pytest.fixture
def variable_source(tmp_path, monkeypatch):
    """A source folder holding one variable family and one static one."""
    import fontsmith
    from crossglyph import fontbuild

    fontsmith.variable_box_font(tmp_path / "Probe[wght].ttf", range(0x41, 0x5B))
    fontsmith.variable_box_font(tmp_path / "Probe-Italic[wght].ttf",
                                range(0x41, 0x5B), style="Italic", italic=True)
    fontsmith.box_font(tmp_path / "Plain-Regular.ttf", range(0x41, 0x5B),
                       family="Plain")
    (_conf(tmp_path) / "all.conf").write_text("sizes = 12\nfallbacks = no\n",
                                       encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    return tmp_path


def _entry(name):
    from crossglyph.preview import server
    return next(f for f in server.families() if f["name"] == name)


def test_a_static_family_offers_no_axis_controls(variable_source):
    assert _entry("Plain")["variable"] is None


def test_a_variable_family_offers_its_own_instances(variable_source):
    variable = _entry("Probe")["variable"]
    assert [i["name"] for i in variable["instances"]] == \
        ["Light", "Regular", "Bold", "Black"]
    # Where the two pickers stand: the instances the font names, not its default.
    assert variable["weights"] == {"text": 400.0, "bold": 700.0}


def test_a_face_with_nothing_but_an_optical_size_offers_no_controls(
        variable_source, tmp_path):
    """opsz follows the size being previewed, so a control for it would be a
    second and disagreeing way to say what size this is -- which leaves this
    face with nothing to offer, and an empty panel section is worse than none."""
    import fontsmith
    fontsmith.variable_box_font(tmp_path / "Optic[opsz].ttf", range(0x41, 0x5B),
                                family="Optic", axis=("opsz", 6, 12, 72),
                                instances={"Text": 12})
    assert _entry("Optic")["variable"] is None


def _second_axis(path, tag="wdth", low=75, default=100, high=125):
    """Add an axis the named instances do not vary, which is the case that
    decides whether the panel opens clean."""
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables._f_v_a_r import Axis

    font = TTFont(str(path))
    axis = Axis()
    axis.axisTag, axis.minValue = tag, low
    axis.defaultValue, axis.maxValue = default, high
    font["fvar"].axes.append(axis)
    # An instance has to carry a value for every axis, or fvar will not compile.
    # They all sit at the default, which is the point: no instance varies this
    # axis, so nothing but the default says where its slider starts.
    for instance in font["fvar"].instances:
        instance.coordinates[tag] = default
    font.save(str(path))
    return path


def test_a_slider_the_config_says_nothing_about_opens_where_it_sits(
        variable_source, tmp_path):
    """The row is built at the font's default for an axis no instance pins, so
    that is where the panel has to say the slider is. Reporting nothing leaves
    the page comparing its own slider against a value that is not there, and
    Save lit on a page nobody has touched."""
    import fontsmith
    _second_axis(fontsmith.variable_box_font(
        tmp_path / "Widey[wght,wdth].ttf", range(0x41, 0x5B), family="Widey",
        instances={"Thin": 300}))
    variable = _entry("Widey")["variable"]
    assert variable["other"] == {"wdth": 100.0},         "the slider's position has to be reported, default or not"
    assert [a["tag"] for a in variable["axes"]] == ["wght", "wdth"]


def test_an_axis_the_face_does_not_have_is_ignored(variable_source):
    """It would reach the rasterizer, which drops it, and then a save would
    write a config that will not parse -- an error about a font that is fine."""
    from crossglyph.preview import server

    config = server.family_config("Probe")
    assert server.panel_coords(config, "regular", None,
                               {"text": 400, "nope": 12}) == {"wght": 400.0}


def test_faces_named_on_the_command_line_still_get_their_instance(
        variable_source, tmp_path):
    """No config to consult, so there is no family to ask -- but a variable file
    named with --font would otherwise draw at its default instance, which is not
    its text weight."""
    from crossglyph.preview import server

    server.set_font_source(tmp_path / "Probe[wght].ttf")
    try:
        axes = dict(server.axes_for("", 13))
        assert axes[server.REGULAR] == (("wght", 400.0),)
    finally:
        server.set_font_source(None)


def test_the_panel_weights_reach_the_render(variable_source):
    from crossglyph.preview import server

    config = server.family_config("Probe")
    plain = server.axes_for("Probe", 13, {})
    heavier = server.axes_for("Probe", 13, {"text": 900})
    assert plain != heavier
    # The text weight moves the roman and the italic, and leaves bold alone.
    assert dict(heavier)[server.STYLE_IDS["regular"]] == (("wght", 900.0),)
    assert dict(heavier)[server.STYLE_IDS["italic"]] == (("wght", 900.0),)
    assert dict(heavier)[server.STYLE_IDS["bold"]] == (("wght", 700.0),)
    assert config.styles["regular"] != config.styles["italic"]


def test_a_weight_off_the_end_of_the_axis_is_clamped(variable_source):
    from crossglyph.preview import server

    axes = dict(server.axes_for("Probe", 13, {"text": 5000}))
    assert axes[server.STYLE_IDS["regular"]] == (("wght", 900.0),)


def test_saving_the_axes_pins_them_in_the_config(variable_source):
    from fastapi.testclient import TestClient

    from crossglyph.cpfont.tuning import Tuning
    from crossglyph.preview import server

    body = {key: Tuning().as_dict()[key] for key in server.SAVED_KEYS}
    body.pop("line_height", None)
    answer = TestClient(server.app).post(
        "/save", json={"family": "Probe", "tuning": body,
                       "axes": {"text": 500, "bold": 800}})
    assert answer.status_code == 200, answer.text
    written = (_conf(variable_source) / "probe.conf").read_text(encoding="utf-8")
    assert "regular = Probe[wght].ttf@wght=500" in written
    assert "bold = Probe[wght].ttf@wght=800" in written
    assert "italic = Probe-Italic[wght].ttf@wght=500" in written
    # And the family now builds at what was pinned.
    assert server.family_config("Probe").coords("regular") == {"wght": 500.0}


def test_only_the_axes_that_differ_are_written(variable_source, tmp_path):
    """A coordinate is an override laid over the font's own instance, so an
    axis the panel left where the font put it is not restated -- restating it
    freezes a value that should go on following the font."""
    import fontsmith
    from fastapi.testclient import TestClient

    from crossglyph.cpfont.tuning import Tuning
    from crossglyph.preview import server

    _second_axis(fontsmith.variable_box_font(
        tmp_path / "Widey[wght,wdth].ttf", range(0x41, 0x5B), family="Widey"))
    body = {key: Tuning().as_dict()[key] for key in server.SAVED_KEYS}
    body.pop("line_height", None)
    # The instance puts both at wght 400 / wdth 100; only the weight moves.
    answer = TestClient(server.app).post(
        "/save", json={"family": "Widey", "tuning": body,
                       "axes": {"text": 500, "bold": 700, "wdth": 100}})
    assert answer.status_code == 200, answer.text
    written = (_conf(variable_source) / "widey.conf").read_text(encoding="utf-8")
    line = next(one for one in written.splitlines()
                if one.startswith("regular ="))
    # The filename carries the axis list, so only what follows the @ is checked.
    assert line.split("@")[1] == "wght=500", line
    # And the family still builds at the width the font names.
    assert server.family_config("Widey").coords("regular") == {
        "wght": 500.0, "wdth": 100.0}


def test_the_automatic_pick_is_not_written_back(variable_source):
    """A slot sitting where discovery would put it anyway keeps no line, so the
    config goes on following the font rather than freezing today's answer."""
    from fastapi.testclient import TestClient

    from crossglyph.cpfont.tuning import Tuning
    from crossglyph.preview import server

    body = {key: Tuning().as_dict()[key] for key in server.SAVED_KEYS}
    body.pop("line_height", None)
    TestClient(server.app).post(
        "/save", json={"family": "Probe", "tuning": body,
                       "axes": {"text": 400, "bold": 700}})
    written = (_conf(variable_source) / "probe.conf").read_text(encoding="utf-8")
    assert "wght" not in written


# --- starting with no arguments -------------------------------------------


def test_the_preview_opens_on_a_family_when_nothing_says_which(two_families,
                                                               monkeypatch):
    """A tester who unpacked the zip runs the launcher and nothing else, so
    the page has to arrive on whatever is in the workspace."""
    from crossglyph.preview import server

    served = {}
    monkeypatch.setattr("uvicorn.run",
                        lambda app, **kw: served.update(kw))
    assert server.main(["--no-open"]) == 0
    assert served["host"] == "127.0.0.1"
    assert server._family in {"Probe", "Filler"}


def test_an_empty_workspace_opens_on_the_bundled_family(tmp_path, monkeypatch):
    """There is always a family to draw, so a first run draws one instead of
    stopping to say what to put in the folder."""
    from crossglyph import fontbuild
    from crossglyph.preview import server

    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    server.forget_families()
    assert server._first_family() == "Literata"


def test_an_install_missing_its_own_faces_says_both_places(tmp_path,
                                                           monkeypatch, capsys):
    """The one way to have nothing to draw is a copy of the tool that lost the
    family it ships, so the message names that folder as well as yours."""
    from crossglyph import fontbuild
    from crossglyph.preview import server

    empty = tmp_path / "no-starter"
    empty.mkdir()
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    monkeypatch.setattr(fontbuild, "STARTER_DIR", empty)
    server.forget_families()
    assert server.main(["--no-open"]) == 2
    said = capsys.readouterr().err
    assert str(tmp_path) in said and str(empty) in said


@needs_core
def test_a_render_draws_without_the_fallbacks_that_are_not_there(two_families):
    """The box is ticked by default and the faces are a download away, so a
    first run would otherwise show a blank page. What the family itself covers
    is what is being tuned, and the panel says they are not here a few rows
    under the box that asked for them."""
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    client = TestClient(server.app)
    body = {"size": 13, "family": "Probe", "intervals": "reading,cyrillic"}
    asked = client.post("/render", json={**body, "fallbacks": True})
    unasked = client.post("/render", json={**body, "fallbacks": False})

    assert asked.status_code == 200, asked.text
    assert asked.content == unasked.content, \
        "the page differs, so something was found to fall back to"


# --- the family that ships with the tool -----------------------------------


def test_an_empty_workspace_still_has_a_family_to_show(tmp_path, monkeypatch):
    """Unpack, run, see type. Nothing to install and nothing to find first."""
    from crossglyph import fontbuild
    from crossglyph.preview import server

    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    server.forget_families()
    entries = server.families()

    assert [entry["name"] for entry in entries] == ["Literata"]
    assert entries[0]["bundled"] is True
    # Two variable files behind four badges, so the page opens with a bold and
    # an italic to look at rather than one weight shown four times.
    assert entries[0]["faces"] == ["bold", "bold italic", "italic", "regular"]
    assert entries[0]["variable"], "the axis controls have nothing to show"


def test_a_font_of_your_own_is_never_marked_bundled(two_families):
    from crossglyph.preview import server

    assert [entry["bundled"] for entry in server.families()] == [False, False]


def test_saving_the_bundled_family_records_where_its_faces_are(tmp_path,
                                                               monkeypatch):
    """It is offered only while the workspace is empty, so a config that did
    not say `dir` would stop resolving the moment a font of your own landed."""
    from fontsmith import box_font

    from crossglyph import fontbuild, fontconf
    from crossglyph.preview import server

    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    server.forget_families()
    assert _save(None, "Literata", gamma=1.4).status_code == 200

    written = fontconf.read_values(fontbuild.conf_dir(tmp_path) / "literata.conf")
    assert written["dir"] == str(fontbuild.STARTER_DIR)
    assert written["family"] == "Literata"

    # And it goes on resolving once there is a font to prefer.
    box_font(tmp_path / "Probe-Regular.ttf", [ord("A")], family="Probe")
    server.forget_families()
    configs, errors = fontbuild.gather(tmp_path)
    assert errors == []
    assert {c.name for c in configs} == {"Literata", "Probe"}
    assert next(c for c in configs if c.name == "Literata").tuning.gamma == 1.4


# --- the sample text presets -----------------------------------------------


def _samples():
    from crossglyph.preview import SAMPLES

    return SAMPLES


def test_every_preset_marks_whole_words():
    """The invariant the module indexes by, on every text that ships.

    One byte out of step and every word after it wears the wrong face, which
    reads as a random emphasis bug rather than as an off-by-one.
    """
    from crossglyph.preview import markup

    for tag, sample in _samples().items():
        text, styles = markup.parse(sample.text)
        words = [w for para in text.split("\n") for w in para.split(" ") if w]
        assert len(words) == len(styles), f"{tag} is out of step"


def test_every_preset_shows_a_bold_and_an_italic():
    """A specimen with no emphasis in it says nothing about three of the four
    faces a family carries."""
    from crossglyph.preview import markup

    for tag, sample in _samples().items():
        _, styles = markup.parse(sample.text)
        worn = {bit for style in styles for bit in (markup.BOLD, markup.ITALIC)
                if style & bit}
        assert worn == {markup.BOLD, markup.ITALIC}, \
            f"{tag} never sets a bold or an italic"


def test_no_preset_leaves_a_mark_in_the_text():
    """An unclosed mark is drawn as an asterisk. On a shipped sample that is a
    typo on the page somebody is judging a font by."""
    from crossglyph.preview import markup

    for tag, sample in _samples().items():
        text, _ = markup.parse(sample.text)
        assert "*" not in text and "_" not in text, f"{tag} has a stray mark"


def test_the_two_presets_with_no_spaces_carry_no_marks():
    """Japanese and Chinese are written without spaces, and this markup styles
    a whole word at a time (markup.parse), so one mark inside a paragraph would
    set the entire paragraph -- and its closing mark, having letters on both
    sides, would be read as an underscore in a name and never close it. Their
    English paragraph carries the emphasis instead."""
    from crossglyph.preview import markup

    for tag in ("ja", "zh-Hans", "zh-Hant"):
        native = _samples()[tag].text.split("\n")[:-1]
        for line in native:
            assert "*" not in line and "_" not in line, \
                f"{tag} marks a paragraph the engine cannot split into words"
        # And the English tail does carry them, or the preset shows no italic.
        _, styles = markup.parse(_samples()[tag].text)
        assert set(styles) > {0}


def test_every_preset_is_long_enough_to_wrap():
    """One paragraph cannot show a first-line indent, paragraph spacing, or
    where the hyphenator would break a line."""
    for tag, sample in _samples().items():
        assert len(sample.text.split("\n")) >= 3, f"{tag} is one paragraph"


def test_every_preset_either_hyphenates_or_is_a_script_that_does_not():
    """A preset whose language the page cannot hyphenate is fine, and there are
    four of them. A preset whose language the page *can* hyphenate but does not
    offer would be one the picker could never follow."""
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    picker = re.search(r'<select id="language".*?</select>', html, re.S)
    offered = set(re.findall(r'<option value="(\w*)"', picker.group(0)))

    unhyphenated = {tag for tag in _samples() if tag not in offered}
    assert unhyphenated == {"ja", "ko", "zh-Hans", "zh-Hant"}, unhyphenated


def test_the_presets_say_the_same_as_the_device_does():
    """Each preset opens on the string the firmware itself shows under a font
    name, so the preview and the device agree on what a font's preview text is.

    Read out of the translations rather than copied here, because a wording
    somebody improves upstream should turn up as a failure and not as a
    divergence nobody notices.
    """
    import re

    from crossglyph import render

    translations = render.FIRMWARE / "lib" / "I18n" / "translations"
    if not translations.is_dir():
        pytest.skip(f"{translations} not found (no firmware checkout beside this one)")

    # The four CJK presets have no translation to read: the firmware carries
    # none, and their opening lines are named in samples.py.
    named = {"en": "english", "fi": "finnish", "fr": "french", "de": "german",
             "it": "italian", "pl": "polish", "ru": "russian", "es": "spanish",
             "sv": "swedish", "uk": "ukrainian"}
    for tag, stem in named.items():
        path = translations / f"{stem}.yaml"
        if not path.is_file():
            pytest.skip(f"{path} not found")
        found = re.search(r'^STR_FONT_PREVIEW_TEXT:\s*"(.*)"\s*$',
                          path.read_text(encoding="utf-8"), re.M)
        assert found, f"no preview string in {path.name}"
        opening = _samples()[tag].text.split("\n")[0]
        assert opening.rstrip(".") == found.group(1).strip().rstrip("."), \
            f"{tag} no longer opens on what the device shows"


def test_the_page_is_served_every_preset():
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    answered = TestClient(server.app).get("/defaults").json()["samples"]
    assert list(answered) == list(_samples()), "the order the picker uses"
    for tag, sample in _samples().items():
        assert answered[tag]["name"] == sample.name
        assert answered[tag]["text"] == sample.text
    # The endonym is what somebody scans the list for, so none may be blank.
    assert all(entry["name"].strip() for entry in answered.values())


@needs_core
def test_a_render_says_how_much_of_it_could_not_be_drawn(two_families):
    """A glyph nobody has takes no width on the device, so a paragraph of them
    is blank space rather than a row of boxes. Without a count on the answer,
    choosing a language the family cannot set looks exactly like a page that
    failed to draw, and the remedy is a fetch nobody knows to make."""
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    client = TestClient(server.app)
    body = {"size": 13, "family": "Probe", "fallbacks": False}

    covered = client.post("/render", json={**body, "text": "Привет, мир"})
    assert covered.status_code == 200, covered.text
    assert covered.headers["x-undrawn"] == "0"

    # Japanese against a family that has no Japanese in it, which is the shape
    # of a first run: a Latin family and a CJK sample.
    japanese = client.post("/render", json={**body, "text": "すべての人間は"})
    assert japanese.status_code == 200, japanese.text
    assert int(japanese.headers["x-undrawn"]) == len(set("すべての人間は"))


@needs_core
def test_a_fallback_that_covers_the_text_leaves_nothing_undrawn(two_families):
    """The count is what is missing after the fallbacks, not before them, or
    every page with a Greek letter on it would carry a warning."""
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    client = TestClient(server.app)
    body = {"size": 13, "family": "Probe", "text": "α", "fallbacks": False}

    alone = client.post("/render", json=body)
    assert alone.headers["x-undrawn"] == "1"
    filled = client.post("/render", json={**body, "fallback1": two_families})
    assert filled.headers["x-undrawn"] == "0"
