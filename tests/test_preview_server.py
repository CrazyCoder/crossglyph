"""The HTTP shim: knobs in as JSON, a PNG out."""
import io
import json
import pathlib

import pytest

import fontpaths

from crossglyph import render

SRC = fontpaths.truetype()
needs = pytest.mark.skipif(
    not render.WASM_PATH.is_file() or SRC is None,
    reason="needs a render core and CROSSGLYPH_TEST_FONT")
#: For the tests that build their own fonts: only the core has to be there.
needs_core = pytest.mark.skipif(
    not render.WASM_PATH.is_file(), reason="needs a render core")


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
    from PIL import Image, ImageChops

    response = client.post("/render", json={"size": 13})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    page = Image.open(io.BytesIO(response.content))
    assert page.size == (480, 800)
    corner = page.crop((page.width // 2, page.height - 30,
                        page.width, page.height))
    assert ImageChops.difference(
        corner, Image.new("L", corner.size, 255)).getbbox(), \
        "the generated PNG has no watermark in its bottom-right corner"


def test_the_watermark_names_the_running_version_and_respects_night_mode():
    from PIL import Image, ImageChops

    from crossglyph import version
    from crossglyph.preview import server
    from crossglyph.render import image

    assert server.WATERMARK == f"CrossGlyph {version.installed()}"
    assert server.WATERMARK_MASK.mode == "1"
    assert server.WATERMARK_MASK.size == (6 * len(server.WATERMARK), 12)
    all_digits = "CrossGlyph 0123456789"
    assert server._watermark_mask(all_digits).size == (6 * len(all_digits), 12)

    paper = Image.new("L", (480, 800), image.WHITE)
    day = server._watermark(paper.copy())
    changed = ImageChops.difference(paper, day).getbbox()
    assert changed is not None
    left, top, right, bottom = changed
    mask_left = paper.width - server.WATERMARK_INSET - \
        server.WATERMARK_MASK.width
    mask_top = paper.height - server.WATERMARK_INSET - \
        server.WATERMARK_MASK.height
    assert mask_left <= left < right <= mask_left + server.WATERMARK_MASK.width
    assert mask_top <= top < bottom <= mask_top + server.WATERMARK_MASK.height
    day_levels = {value for value, count in enumerate(day.histogram()) if count}
    assert day_levels == {image.DARK, image.WHITE}

    black = Image.new("L", paper.size, image.BLACK)
    night = server._watermark(black.copy(), inverted=True)
    assert ImageChops.difference(black, night).getbbox() is not None
    night_levels = {
        value for value, count in enumerate(night.histogram()) if count
    }
    assert night_levels == {image.BLACK, image.LIGHT}


@needs
def test_the_render_endpoint_uses_a_light_watermark_in_night_mode(client):
    from PIL import Image

    from crossglyph.preview import server
    from crossglyph.render import image

    response = client.post(
        "/render", json={"size": 13, "page": {"inverted": True}})
    assert response.status_code == 200
    page = Image.open(io.BytesIO(response.content))
    mask_x, mask_y = next(
        (x, y)
        for y in range(server.WATERMARK_MASK.height)
        for x in range(server.WATERMARK_MASK.width)
        if server.WATERMARK_MASK.getpixel((x, y)))
    left = page.width - server.WATERMARK_INSET - server.WATERMARK_MASK.width
    top = page.height - server.WATERMARK_INSET - server.WATERMARK_MASK.height
    assert page.getpixel((left + mask_x, top + mask_y)) == image.LIGHT


def test_png_output_carries_the_watermark(tmp_path, monkeypatch):
    from PIL import Image, ImageChops

    from crossglyph.preview import server

    source = tmp_path / "font.ttf"
    source.touch()
    output = tmp_path / "page.png"
    monkeypatch.setattr(server, "_sources", {0: source})
    monkeypatch.setattr(server, "set_font_source", lambda *a, **k: None)
    seen = {}
    monkeypatch.setattr(server, "build_font", lambda *a, **k: b"font")
    monkeypatch.setattr(
        server, "preview_page",
        lambda *a, **k: seen.setdefault("spec", k["spec"]) and
        Image.new("L", (528, 792), 255))
    monkeypatch.setattr(server, "axes_for", lambda *a, **k: ())

    assert server.main(["--font", str(source), "--device", "x3",
                        "--png", str(output)]) == 0
    page = Image.open(output)
    assert ImageChops.difference(
        page, Image.new("L", page.size, 255)).getbbox()
    assert seen["spec"].device == "x3"


@needs
def test_the_page_spec_reaches_the_render(client):
    tight = client.post("/render",
                        json={"size": 13, "page": {"line_spacing": "tight"}})
    wide = client.post("/render",
                       json={"size": 13, "page": {"line_spacing": "wide"}})
    assert tight.content != wide.content


@needs
def test_the_device_selects_native_page_geometry(client):
    from PIL import Image, ImageChops

    x3 = client.post("/render",
                     json={"size": 13, "page": {"device": "x3"}})
    x4 = client.post("/render",
                     json={"size": 13, "page": {"device": "x4"}})

    assert Image.open(io.BytesIO(x3.content)).size == (528, 792)
    assert Image.open(io.BytesIO(x4.content)).size == (480, 800)
    for name, response in (("X3", x3), ("X4", x4)):
        page = Image.open(io.BytesIO(response.content))
        content = page.crop((0, 0, page.width, page.height - 30))
        assert ImageChops.difference(
            content, Image.new("L", content.size, 255)).getbbox(), \
            f"{name} selected its geometry but drew no text"


@needs
def test_one_bit_rendering_reaches_the_render(client):
    """The knob a reader who keeps anti-aliasing off is tuning against."""
    from PIL import Image

    from crossglyph.preview import server

    response = client.post("/render",
                           json={"size": 13, "page": {"antialiased": False}})
    page = Image.open(io.BytesIO(response.content))
    left = page.width - server.WATERMARK_INSET - \
        server.WATERMARK_MASK.width
    top = page.height - server.WATERMARK_INSET - \
        server.WATERMARK_MASK.height
    right = left + server.WATERMARK_MASK.width
    bottom = top + server.WATERMARK_MASK.height
    framebuffer = (
        page.crop((0, 0, page.width, top)),
        page.crop((0, top, left, page.height)),
        page.crop((right, top, page.width, page.height)),
        page.crop((left, bottom, right, page.height)),
    )
    levels = {
        value
        for region in framebuffer
        for value, count in enumerate(region.histogram())
        if count
    }
    assert levels <= {0, 255}


#: Greek, which the family built below has none of and its fallback has.
GREEK = 0x3B1


def _forget_the_last_folder():
    """Every cache a render fills, so the next folder is read fresh.

    The build caches are keyed on paths the suite reuses across tests, so a
    stale entry would answer for the previous folder. The fingerprint goes
    with them: it is a module global, so the folder the last test built is
    what this one would be compared against.
    """
    from crossglyph.preview import server

    server.forget_families()
    server._workspace = None
    server.build_font_cached.cache_clear()
    server.resolved_fallbacks.cache_clear()


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
    _forget_the_last_folder()
    server.set_font_source(tmp_path / "Probe-Regular.ttf", family="Probe")
    yield "Filler"
    _forget_the_last_folder()
    server.set_font_source(SRC)


def test_the_family_list_is_read_from_the_folder_every_time(client,
                                                            two_families):
    """A guard rather than a fix: this list has never been remembered, and a
    font dropped into a docker volume shows up in it as soon as anything asks.
    What has to ask is the page, which does when its tab comes back."""
    from fontsmith import box_font

    from crossglyph import fontbuild

    def named():
        return {entry["name"]
                for entry in client.get("/defaults").json()["families"]}

    assert "Newcomer" not in named()
    box_font(fontbuild.SOURCE_DIR / "Newcomer-Regular.ttf", [0x20, 0x41],
             family="Newcomer")
    assert "Newcomer" in named()


def test_a_bold_run_is_offered_the_bold_fallback(tmp_path, monkeypatch):
    """The page has to agree with the build. A folder with NotoSans in four
    styles lends the bold one to bold and the regular one to regular."""
    from crossglyph import fontbuild
    from crossglyph.preview import server

    faces = tmp_path / fontbuild.FALLBACK_NAME
    faces.mkdir()
    for name in fontbuild.BUNDLED_FALLBACKS:
        (faces / name).write_bytes(b"")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    server._bundled_faces.cache_clear()

    offered = server.fallbacks_for(server.RenderRequest(
        text="a *b*", fallbacks=True, intervals="reading"))

    assert any(face.endswith("NotoSans-Bold.ttf")
               for face in offered[server.BOLD])
    assert not any(face.endswith("NotoSans-Bold.ttf")
                   for face in offered[server.REGULAR])
    assert any(face.endswith("NotoSans-Regular.ttf")
               for face in offered[server.REGULAR])


def test_the_page_follows_the_order_the_config_sets(tmp_path, monkeypatch):
    """`fallback_order` has no control on the page, so a render that ignored
    it would draw a chain the build does not use."""
    from fontsmith import box_font

    from crossglyph import fontbuild
    from crossglyph.preview import server

    faces = tmp_path / fontbuild.FALLBACK_NAME
    faces.mkdir()
    for name in fontbuild.BUNDLED_FALLBACKS:
        (faces / name).write_bytes(b"")
    box_font(tmp_path / "Probe-Regular.ttf", [0x20, 0x41], family="Probe")
    box_font(tmp_path / "MyIcons-Regular.ttf", [0x20, 0x2192],
             family="MyIcons")
    _conf(tmp_path).joinpath("probe.conf").write_text(
        "fallbacks = yes\nfallback_order = MyIcons, bundled\n",
        encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    _forget_the_last_folder()

    offered = server.fallbacks_for(server.RenderRequest(
        family="Probe", text="a", fallbacks=True, intervals="reading"))

    assert offered[server.REGULAR][0].endswith("MyIcons-Regular.ttf")


def test_a_family_with_no_face_for_a_style_lends_its_regular(tmp_path,
                                                             monkeypatch):
    """Noto publishes no italic for twelve of the thirteen, so this is the
    common case and not the corner."""
    from crossglyph import fontbuild
    from crossglyph.preview import server

    faces = tmp_path / fontbuild.FALLBACK_NAME
    faces.mkdir()
    for name in fontbuild.BUNDLED_FALLBACKS:
        (faces / name).write_bytes(b"")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    server._bundled_faces.cache_clear()

    offered = server.fallbacks_for(server.RenderRequest(
        text="a", fallbacks=True, intervals="reading"))

    assert any(face.endswith("NotoSansMath-Regular.ttf")
               for face in offered[server.ITALIC])


def test_the_page_is_told_how_many_faces_are_still_to_fetch(client, tmp_path,
                                                            two_families):
    """A folder fetched before the NotoSans styles were added has the faces an
    older version wanted, so presence alone would hide the button and leave
    nothing to press."""
    from crossglyph import fontbuild

    faces = tmp_path / fontbuild.FALLBACK_NAME
    faces.mkdir()
    for name in fontbuild.fetch_plan():
        if name in fontbuild.NOTOSANS_STYLES:
            continue
        (faces / name).write_bytes(b"")

    payload = client.get("/defaults").json()

    assert payload["fallbacks"].endswith(fontbuild.FALLBACK_NAME)
    assert payload["fallbacks_missing"] == len(fontbuild.NOTOSANS_STYLES)


def test_the_folder_listing_is_not_something_a_browser_may_keep(client,
                                                                two_families):
    """The page asks this again precisely because the answer changes. A copy
    held from before a font arrived would go on answering the old way through
    every reload, which is the page's own modules' problem and the same fix."""
    assert client.get("/defaults").headers["cache-control"] == "no-store"


def test_a_config_edited_by_hand_reaches_the_next_render(client, two_families):
    """What a family resolves to *is* remembered, and it is what the next page
    is drawn with. Left cached, an edit in an editor shows in the picker while
    the image beside it goes on being built from the file as it was."""
    from crossglyph import fontbuild
    from crossglyph.preview import server

    assert server.family_config("Probe").tuning.gamma == 1.0
    (_conf(fontbuild.SOURCE_DIR) / "probe.conf").write_text(
        "gamma = 1.6\n", encoding="utf-8")
    assert server.family_config("Probe").tuning.gamma == 1.0, \
        "resolved once and kept, which is the thing being fixed"

    client.get("/defaults")             # the page's tab has come back
    assert server.family_config("Probe").tuning.gamma == 1.6


def test_a_plain_page_load_is_a_rescan_too(client, two_families):
    """The page fetches /defaults on load as well as when its tab comes back,
    so a reload is the other way in and has to pick the folder up too. One
    endpoint does both, which is what makes that true rather than a second
    thing to remember."""
    from fontsmith import box_font

    from crossglyph import fontbuild
    from crossglyph.preview import server

    client.get("/defaults")                         # the page, loaded
    server.family_config("Probe")
    box_font(fontbuild.SOURCE_DIR / "Probe-Bold.ttf", [0x20, 0x41],
             family="Probe", style="Bold")
    assert "bold" not in server.family_config("Probe").styles

    client.get("/defaults")                         # the page, reloaded
    assert "bold" in server.family_config("Probe").styles


def test_the_bundled_faces_are_watched_as_well(client, two_families):
    """They are not families and never reach the picker, but a build fills
    holes from them, so a set that appears changes what a page is drawn with
    while no font and no config has moved."""
    from fontsmith import box_font

    from crossglyph import fontbuild
    from crossglyph.preview import server

    before = server.workspace_stamp()
    bundled = fontbuild.SOURCE_DIR / fontbuild.FALLBACK_NAME
    bundled.mkdir()
    box_font(bundled / fontbuild.ANCHOR_FACE, [0x20, 0x41], family="NotoSans")
    assert server.workspace_stamp() != before


def test_a_fetched_fallback_set_is_not_answered_for_out_of_the_old_cache():
    """Which faces a build would fill from is worked out once and kept. Left
    alone, a set fetched under a running app was invisible to every render
    after it: the answer from when there was nothing there kept coming back."""
    from crossglyph.preview import server

    server._bundled_faces.cache_clear()
    server._bundled_faces("nowhere", "base")
    assert server._bundled_faces.cache_info().currsize == 1
    server.forget_families()
    assert server._bundled_faces.cache_info().currsize == 0


def test_a_folder_that_has_not_moved_keeps_what_it_resolved(client,
                                                            two_families):
    """The fingerprint earns its walk here: forgetting on every ask would make
    each return to the tab re-read every config in the folder."""
    from crossglyph.preview import server

    client.get("/defaults")
    server.family_config("Probe")                   # fills the cache
    before = server._config_cached.cache_info().currsize
    client.get("/defaults")
    assert server._config_cached.cache_info().currsize == before


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
def test_the_page_can_ask_for_another_family(client, two_families):
    """The picker's whole point: changing which font is set should not mean
    restarting the app, so the family rides on the request rather than being
    process state.

    The fixture's two, not whatever the workspace happens to hold. A folder
    with one family in it ran none of this and said nothing about it.
    """
    pages = [client.post("/render", json={"size": 13, "family": name})
             for name in ("Probe", "Filler")]
    assert all(page.status_code == 200 for page in pages)
    assert pages[0].content != pages[1].content, \
        "Probe and Filler drew the same page"


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
    names = [entry["name"] for entry in response["families"]]
    assert set(names) == {"Probe", "Filler", "Literata"}
    # The bundled family comes after the workspace's own, since it is somewhere
    # to flip to rather than one of yours.
    assert names[-1] == "Literata"
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


@pytest.mark.parametrize(
    ("device", "suffix", "size", "hole", "margin"),
    [
        ("x4", "", (1118, 1820), (118, 105, 989, 1551), 8),
        ("x3", "", (1209, 1820), (132, 123, 1077, 1544), 8),
        # The 1:1 pair, whose aperture is the panel's own size so that scale
        # draws them untouched. Rendered rather than resampled, so they get
        # every check the tall ones get: an edge that was resized would fail
        # the bezel test below rather than pass it softly.
        ("x4", "-1to1", (612, 996), (64, 57, 542, 849), 4),
        ("x3", "-1to1", (671, 1011), (73, 68, 598, 858), 4),
    ],
)
def test_device_frames_carry_normalized_geometry(
        client, device, suffix, size, hole, margin):
    """The frames are rendered from the official models by fb2xt, which emits
    the geometry from the same run that produced the pixels. What matters here
    is that the shipped file still agrees with what the preview was told."""
    from PIL import Image, ImageStat

    for color in ("black", "white"):
        response = client.get(f"/device/{device}-{color}{suffix}.png")
        assert response.status_code == 200
        frame = Image.open(io.BytesIO(response.content)).convert("RGBA")
        assert frame.size == size
        left, top, right, bottom = hole
        alpha = frame.getchannel("A")
        assert alpha.getpixel(((left + right) // 2, (top + bottom) // 2)) == 0

        # The bezel must not change colour as it meets the hole. The frames this
        # replaced left three columns of screen material there, at 195 to 203
        # against a bezel of 13, which showed as grey lines down each side of a
        # night-mode page. Those columns were fully opaque, so asking about
        # alpha here would have passed on the very frames that were broken.
        green = frame.getchannel("G")
        middle = (top + bottom) // 2
        for edge, outward in ((left - 1, -1), (right, 1)):
            reference = green.getpixel((edge + outward * 15, middle))
            for offset in (1, 2, 3, 4):
                beside = green.getpixel((edge + outward * offset, middle))
                assert abs(beside - reference) <= 20, (
                    f"the bezel jumps from {reference} to {beside} as it meets "
                    f"the aperture, which is the grey line this pipeline removed")

        # The body is fitted to the canvas margin, which is what fixes the
        # frame's size; anti-aliasing puts the silhouette within a pixel of it.
        opaque = alpha.point(lambda value: 255 if value >= 128 else 0).getbbox()
        assert opaque is not None
        assert opaque[0] == pytest.approx(margin, abs=2)
        assert opaque[1] == pytest.approx(margin, abs=2)
        assert opaque[2] == pytest.approx(size[0] - margin, abs=2)
        assert opaque[3] == pytest.approx(size[1] - margin, abs=2)

        # A band across the top bezel, as a share of the frame rather than a
        # count of pixels: the same 25 to 100 that sits in flat bezel on an
        # 1820-tall frame reaches the curved top edge on a 996-tall one, and
        # reads several levels dark for it.
        band = (round(size[1] * 25 / 1820), round(size[1] * 100 / 1820))
        body = frame.crop((size[0] // 4, band[0], size[0] * 3 // 4, band[1]))
        red, green, blue = ImageStat.Stat(body.convert("RGB")).mean
        tone = (red + green + blue) / 3
        expected = (10, 22) if color == "black" else (210, 230)
        assert expected[0] <= tone <= expected[1]
        # Measured off the device on white paper in shade: green highest, then
        # red, then blue. A warm greenish white, not the cool one this asserted
        # before anybody measured it.
        assert green >= red >= blue, \
            "the frame lost the tint measured off the device"


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
    """Every named control associated with the *knob* form.

    The specimen text and reader model use ``form="knobs"`` from outside the
    form's box. Browsers include them in ``form.elements`` just like controls
    nested inside it. The export panel is a second form and stays out.
    """
    import re

    from crossglyph.preview import server

    page = (server.STATIC / "index.html").read_text(encoding="utf-8")
    inside = page[page.index('<form id="knobs">'):page.index("</form>")]
    tags = re.findall(r"<(?:input|select|textarea)\b[^>]*>", inside)
    tags += [
        tag for tag in re.findall(r"<(?:input|select|textarea)\b[^>]*>", page)
        if 'form="knobs"' in tag
    ]
    found = {}
    for tag in tags:
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
    assert names == {"name", "size1", "size2", "size3", "size4", "size_more",
                     "mod1", "mod2", "mod3", "mod4", "mod_more", "mod_suffix",
                     "ranges", "fallbacks", "fallback1", "fallback2",
                     "out"}, names

    # A box is not a key: the four steps and the row past them join into one
    # `sizes`, and the second family's four into `sizes_mod`. So what has to
    # line up with the server is what the page builds out of them.
    source = (server.STATIC / "js" / "export.js").read_text(encoding="utf-8")
    body = source[source.index("function exportSettings()"):]
    posted = set(re.findall(r"^\s*(\w+):", body[:body.index("\n}")], re.M))
    assert posted == {"name", "sizes", "sizes_mod", "mod_suffix", "intervals",
                      "ranges", "fallbacks", "fallback1", "fallback2"}, posted


def test_a_family_says_which_feature_knobs_it_can_answer(tmp_path, monkeypatch):
    """Turning ligatures off on a face with no ligature rules draws the
    identical page. The panel greys those knobs, so it has to be told."""
    from fontsmith import box_font

    from crossglyph import fontbuild
    from crossglyph.preview import server

    box_font(tmp_path / "Plain-Regular.ttf", range(0x20, 0x7F), family="Plain")
    box_font(tmp_path / "Rich-Regular.ttf",
             list(range(0x20, 0x7F)) + [0xFB01], family="Rich",
             ligatures={(0x66, 0x69): 0xFB01}, figures=True)
    (_conf(tmp_path) / "all.conf").write_text("sizes = 12\n", encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    server.forget_families()
    entries = {f["name"]: f["features"] for f in server.families()}

    assert entries["Plain"] == {"ligatures": False, "figures": False}
    assert entries["Rich"] == {"ligatures": True, "figures": True}


def test_a_feature_any_face_carries_keeps_its_knob(tmp_path, monkeypatch):
    """A family whose bold has no ligatures but whose regular does still
    draws a different page with the switch off."""
    from fontsmith import box_font

    from crossglyph import fontbuild
    from crossglyph.preview import server

    box_font(tmp_path / "Mixed-Regular.ttf",
             list(range(0x20, 0x7F)) + [0xFB01], family="Mixed",
             ligatures={(0x66, 0x69): 0xFB01})
    box_font(tmp_path / "Mixed-Bold.ttf", range(0x20, 0x7F), family="Mixed",
             style="Bold")
    (_conf(tmp_path) / "all.conf").write_text("sizes = 12\n", encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    server.forget_families()
    entry = next(f for f in server.families() if f["name"] == "Mixed")

    assert entry["faces"] == ["bold", "regular"], entry["faces"]
    assert entry["features"]["ligatures"] is True


def test_a_face_replaced_under_the_preview_is_asked_again(tmp_path, monkeypatch):
    """The whole workspace is walked for both of these on the way to the
    picker, so both are cached. A font swapped in place has to move both
    answers, the way it moves which instances a variable file offers."""
    from fontsmith import box_font

    from crossglyph import fontbuild
    from crossglyph.preview import server

    face = tmp_path / "Swap-Regular.ttf"
    box_font(face, range(0x20, 0x7F), family="Swap")
    (_conf(tmp_path) / "all.conf").write_text("sizes = 12\n", encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    server.forget_families()
    assert server.face_features(face) == frozenset()
    assert server.face_outlines(face) == "truetype"

    # Same path, another font: ligature rules it did not have, and drawn by
    # the other of FreeType's two engines.
    box_font(face, list(range(0x20, 0x7F)) + [0xFB01], family="Swap",
             ligatures={(0x66, 0x69): 0xFB01}, cff=True)
    assert server.face_features(face) == frozenset({"ligatures"})
    assert server.face_outlines(face) == "cff"


def test_a_family_says_whether_its_own_bytecode_draws_it(tmp_path):
    """Grayscale hinting picks between two bytecode interpreters, so the panel
    needs to know there is bytecode. fontsmith draws outlines and writes no
    instructions, which is the same case as the bundled Literata: TrueType, and
    fitted by the auto-hinter whichever interpreter is set."""
    import fontpaths
    from fontsmith import box_font

    from crossglyph.preview import server

    plain = box_font(tmp_path / "Plain-Regular.ttf", range(0x41, 0x5B),
                     family="Plain")
    cff = box_font(tmp_path / "Curvy-Regular.otf", range(0x41, 0x5B),
                   family="Curvy", cff=True)
    assert server.face_hinting(plain) == (False, False)
    assert server.face_hinting(cff) == (False, False)
    # A face nobody can read claims nothing, so nothing is greyed on it.
    missing = tmp_path / "Gone-Regular.ttf"
    assert server.face_hinting(missing) == (True, True)

    real = fontpaths.truetype()
    if real is not None:
        bytecode, _tricky = server.face_hinting(real)
        assert bytecode, f"{real.name} carries no bytecode, so it is the " \
                         f"wrong face for the tests that assume one"


def test_a_family_says_which_engine_draws_it(tmp_path, monkeypatch):
    """Stem darkening lives in FreeType's CF2 interpreter and in the
    auto-hinter, and which one draws a face depends on its outlines, so the
    page needs them to say whether the switch can do anything."""
    from fontsmith import box_font

    from crossglyph import fontbuild
    from crossglyph.preview import server

    box_font(tmp_path / "Quill-Regular.ttf", range(0x41, 0x5B), family="Quill")
    box_font(tmp_path / "Inky-Regular.otf", range(0x41, 0x5B), family="Inky",
             cff=True)
    # One family drawn by both engines, which no single rule speaks for.
    box_font(tmp_path / "Mixed-Regular.ttf", range(0x41, 0x5B), family="Mixed")
    box_font(tmp_path / "Mixed-Bold.otf", range(0x41, 0x5B), family="Mixed",
             style="Bold", cff=True)
    (_conf(tmp_path) / "all.conf").write_text("sizes = 12\n", encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    server.forget_families()
    outlines = {f["name"]: f["outlines"] for f in server.families()}

    assert outlines["Quill"] == "truetype"
    assert outlines["Inky"] == "cff"
    assert outlines["Mixed"] == "mixed"


def test_every_greyable_knob_is_a_knob_the_page_has():
    """The reasons are keyed by control name, and a name the markup does not
    carry is a row that silently never greys."""
    import re

    from crossglyph.preview import server

    source = (server.STATIC / "js" / "dom.js").read_text(encoding="utf-8")
    block = source[source.index("FEATURE_REASON = {"):]
    named = set(re.findall(r"^  (\w+):", block[:block.index("\n};")], re.M))
    assert named == set(server.FEATURE_KNOBS), named
    assert named <= set(_controls()), "greyed a knob the page does not have"

    # Every knob this module reaches for outright, which the table above does
    # not cover: stem darkening is greyed by a rule of its own, and reads the
    # hinting row to decide. Renaming either in the markup would leave that
    # rule quietly doing nothing.
    reached = set(re.findall(r"form\.elements\.(\w+)", source))
    assert reached <= set(_controls()), reached - set(_controls())
    assert {"stem_darkening", "hinting", "grayscale_hinting", "mono"} <= reached, \
        reached


def test_the_mark_beside_a_switch_can_be_hovered():
    """Everything it says past "this row differs" is in its tooltip, and an
    element taken out of hit testing has no hover for one to appear on. It sits
    in the arrow's column, which must stay inert -- but the row under it is a
    div rather than a label now, so nothing happens on the way past and the
    mark does not have to be excluded to be harmless.
    """
    import re

    from crossglyph.preview import server

    css = (server.STATIC / "style.css").read_text(encoding="utf-8")
    rule = re.search(r"\.mark\s*\{([^}]*)\}", css)
    assert rule, ".mark has no rule at all"
    assert "pointer-events" not in rule.group(1), \
        "the mark is out of hit testing, so its tooltip can never be shown"


def test_no_compare_arrow_sits_inside_a_label():
    """A press anywhere inside a label toggles the control it names, so an
    arrow within one is two actions on one click -- and the row's every empty
    gap, the arrow's column included, becomes a switch with nothing drawn on
    it. The stylesheet has always said so; this is what holds the markup to it.

    The probe cannot: it builds its own controls and never reads this file.
    """
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    for opened in re.finditer(r"<label\b[^>]*>", html):
        end = html.index("</label>", opened.end())
        assert "class=\"revert\"" not in html[opened.end():end], \
            f"a revert arrow sits inside {opened.group(0)}"


def test_every_fold_has_a_heading_that_opens_it():
    """fold.js collects its toggles by `data-fold`, and the stylesheet folds
    `#<name>-settings`. A heading that lost the attribute is a section nothing
    can open, and nothing else notices: the markup is still valid, the section
    is still hidden, and the press does nothing at all. That shipped once.
    """
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    css = (server.STATIC / "style.css").read_text(encoding="utf-8")

    folded = set(re.findall(r'data-folds~="(\w+)"\]\)\s*#(\w+)-settings', css))
    assert folded, "the stylesheet folds nothing"
    for name, section in sorted(folded):
        assert name == section, \
            f"the fold named {name} hides #{section}-settings"
        assert f'id="{name}-settings"' in html, f"#{name}-settings is not there"
        toggle = re.search(rf'<button[^>]*data-fold="{name}"[^>]*>', html)
        assert toggle, f"nothing carries data-fold=\"{name}\", so it cannot open"
        assert f'aria-controls="{name}-settings"' in toggle.group(0), \
            f"the {name} heading does not say what it controls"



def test_folded_text_keeps_the_sample_picker_in_its_heading():
    """The picker remains usable while the text and its notes are hidden."""
    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    island = html.index('id="textbox"')
    toggle = html.index('id="text-toggle"', island)
    picker = html.index('id="sample"', toggle)
    settings = html.index('id="text-settings"', picker)
    textarea = html.index("<textarea", settings)

    assert island < toggle < picker < settings < textarea


def test_what_boot_reads_is_what_the_modules_write():
    """boot.js restores both of these before the first paint, and a module
    writes each one after a press. Two files per key, and the failure when they
    drift is silent: the choice is still saved, nothing reads it back, and the
    page opens on the default every time.
    """
    import re

    from crossglyph.preview import server

    js = server.STATIC / "js"
    boot = (js / "boot.js").read_text(encoding="utf-8")
    for module, name in (("theme.js", "THEME"), ("fold.js", "FOLDS")):
        source = (js / module).read_text(encoding="utf-8")
        key = re.search(rf'{name} = "([^"]+)"', source)
        assert key, f"{module} names no key for {name}"
        assert f'"{key.group(1)}"' in boot, \
            f"boot.js does not read {key.group(1)}, which {module} writes"


def test_each_panel_commits_from_its_own_foot():
    """A bar under a card is what commits what is in it, and each panel has
    one: Save under the knobs, Build under the export panel. Neither press
    belongs inside the form it acts on -- a save writes the whole .conf, the
    export half included, and a build is the one thing on the page that changes
    height while you watch it, which only a foot can absorb.
    """
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    knobs = html[html.index('<form id="knobs">'):html.index("</form>")]
    for part in ('id="save"', 'id="saved"'):
        assert part not in knobs, f"{part} is inside the knobs panel"

    foot = re.search(r'<div id="savebar">(.*?)</div>', html, re.S)
    assert foot, "there is no save bar"
    for part in ('id="save"', 'id="saved"'):
        assert part in foot.group(1), f"{part} is not in the save bar"

    opened = html.index('<form id="export">')
    export = html[opened:html.index("</form>", opened)]
    build = html[html.index('<div id="buildbar">'):]
    for part in ('id="build"', 'id="build-all"', 'id="built"',
                 'class="bar"'):
        assert part not in export, f"{part} is inside the export panel"
        assert part in build, f"{part} is not in the build bar"


def test_hiding_save_on_the_export_tab_never_touches_its_hidden_property():
    """save.js sets `hidden` on that button to mean "this family has no .conf
    to write to", and buildFamilies reads it to decide whether to save before a
    run. A tab switch that set the same property to take the button off screen
    would quietly stop builds writing the file the build then reads, which
    looks exactly like a change that did nothing.

    So the export tab hides it in the stylesheet, and save.js stays the only
    place that assigns it.
    """
    from crossglyph.preview import server

    css = (server.STATIC / "style.css").read_text(encoding="utf-8")
    assert ':root[data-panel="export"] #savebar { display: none; }' in css, \
        "the export tab does not hide the save bar"

    js = server.STATIC / "js"
    assigns = {path.name for path in js.glob("*.js")
               if "saveButton.hidden =" in path.read_text(encoding="utf-8")}
    assert assigns == {"save.js"}, \
        f"saveButton.hidden is assigned outside save.js: {assigns - {'save.js'}}"


def test_the_build_bar_is_a_rule_until_it_runs():
    """It is drawn in the foot whether or not anything is running, so that a
    build changes what the foot says and never how tall it is. Two things carry
    that: the rule is in the document from the first paint rather than hidden,
    and it starts aria-hidden, since a progressbar sitting at no value all day
    is a control that is not there.
    """
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    build = html[html.index('<div id="buildbar">'):]
    bar = re.search(r"<div class=\"bar\"[^>]*>", build, re.S)
    assert bar, "the build bar has no rule"
    assert "hidden" not in bar.group(0).replace("aria-hidden", ""), \
        "the build's rule starts out of the document"
    assert 'aria-hidden="true"' in bar.group(0), \
        "the build's rule starts as a progressbar rather than as a rule"

    css = (server.STATIC / "style.css").read_text(encoding="utf-8")
    # The foot is made of --rule, so a bar in that tone is one nobody can see.
    assert "#buildbar .bar { margin-top: .6rem; background: var(--line); }" \
        in css, "the build's rule is not drawn against its own foot"


def test_the_line_the_build_bar_rests_on_can_never_take_a_second():
    """The reserved line opens on a word about the two presses, because an
    empty one reads as a line that failed to fill. It is its own element and
    not the note's first value: the note wraps, since an error arrives with its
    own lines, and this one must stay one line however wide the reader's UI
    font draws it. So it is cut short instead, and it goes for good once the
    panel has something of its own to say.
    """
    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    build = html[html.index('<div id="buildbar">'):]
    assert '<div class="rest">' in build, "the reserved line rests on nothing"

    css = (server.STATIC / "style.css").read_text(encoding="utf-8")
    rest = css[css.index("#build-status .rest {"):]
    rest = rest[:rest.index("}")]
    assert "white-space: nowrap" in rest and "text-overflow: ellipsis" in rest, \
        "the resting line can wrap to a second line and grow the foot"
    assert "#build-status:has(#built:not(:empty)) .rest" in css, \
        "the resting line outlives the first thing the panel has to say"


def test_the_breakpoints_fit_what_they_lay_out():
    """The no-script page shows three columns above a width, two below it and
    one below that. Once the device module has measured the reader it may keep
    two columns below the fallback breakpoint, but both fixed widths must
    remain safe before that script runs.

    Neither of the other suites can see the stylesheet. The module probe does
    cover the measured one/two-column decision, while this check ties its
    states to CSS and verifies the fallback arithmetic.
    """
    import re

    from crossglyph.preview import server

    css = (server.STATIC / "style.css").read_text(encoding="utf-8")
    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    device_js = (server.STATIC / "js" / "device.js").read_text(
        encoding="utf-8")
    for columns in ("one", "two"):
        assert f':root[data-preview-columns="{columns}"] body' in css
    assert "root.dataset.previewColumns" in device_js

    def rem(pattern: str, text: str) -> float:
        found = re.search(pattern, text)
        assert found, pattern
        return float(found.group(1)) * 16

    three_at = max(float(w) for w in re.findall(r"min-width:\s*(\d+)px", css))
    # The narrowest width it folds at is where two columns stop fitting, and a
    # max-width query names the last width that still folds.
    two_at = min(float(w) for w in re.findall(r"max-width:\s*(\d+)px", css)) + 1
    panel = rem(r"#knobs \{\s*\n?\s*width: ([\d.]+)rem", css)
    # Both side columns are counted at this one width below, so the export
    # column has to actually be it. It is set on the wrapper rather than on the
    # card, since the card and its foot have to stay the same width as each
    # other, which puts it out of reach of the pattern above.
    assert rem(r"#exportcol \{ width: ([\d.]+)rem", css) == panel, \
        "the export column is not the width the arithmetic below assumes"
    gap = rem(r"column-gap: ([\d.]+)rem", css)
    padding = rem(r"body \{\s*\n\s*margin: 0; padding: ([\d.]+)rem", css)
    stage = rem(r"#stage \{[^}]*padding: ([\d.]+)rem", css)
    sheet = float(re.search(r'id="device-page" width="(\d+)"', html).group(1))
    geometries = re.findall(
        r"native:\s*\{width:\s*(\d+).*?"
        r"frame:\s*\{width:\s*(\d+).*?"
        r"aperture:\s*\{[^}]*width:\s*(\d+)",
        device_js, re.DOTALL)
    assert geometries
    widest_surface = max(float(frame) * float(native) / float(aperture)
                         for native, frame, aperture in geometries)
    # The stage's border adds to its two paddings. The canvas's declared width
    # is narrower than the widest visible frame, but remains part of the
    # contract.
    page_column = max(sheet, widest_surface) + 2 * stage + 2

    # A media query counts the scrollbar as width the layout does not get, and
    # this page always has one. A breakpoint with less headroom than that fires
    # while what is below it still cannot fit.
    scrollbar = 17
    for what, at, needs in (
            ("three columns", three_at,
             2 * panel + page_column + 2 * gap + 2 * padding),
            ("two columns", two_at, panel + page_column + gap + 2 * padding)):
        assert at >= needs + scrollbar, \
            (f"{what} need {needs:.0f}px and the layout goes to them at "
             f"{at:.0f}px, which a scrollbar eats into")


def test_every_asset_the_page_asks_for_is_one_the_server_will_serve():
    """A stylesheet, a script or an icon the route refuses is a 404 the page
    never mentions: the browser asks quietly and draws without it. The route
    serves an allowlist of suffixes, so adding a file of a new kind to the
    markup is exactly when that goes wrong.
    """
    import re

    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    refs = set(re.findall(r'(?:href|src)="([^"#:]+)"', html))
    assert "favicon.svg" in refs, "the page asks for no icon"

    client = TestClient(server.app)
    for ref in sorted(refs):
        assert (server.STATIC / ref).is_file(), f"{ref} is not in static/"
        assert client.get(f"/{ref}").status_code == 200, \
            f"the server will not serve {ref}"


def test_common_device_controls_remain_available_while_folded():
    """The folded island keeps its common choices and hides only advanced ones."""
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    preview = html.index('id="device-preview"')
    settings = html.index('<div id="device-settings">', preview)
    folded = html[preview:settings]
    for control in ("device-model", "device-color", "device-frame-shown"):
        assert f'id="{control}"' in folded, control
    for control in ("device-scale", "device-paper", "device-ink"):
        assert f'id="{control}"' not in folded, control

    frame = re.search(
        r'<label class="device-frame-toggle".*?</label>', folded, re.S)
    assert frame is not None
    assert "<svg " in frame.group()
    assert 'aria-label="Show reader frame"' in frame.group()



def test_device_numeric_controls_use_the_shared_stepper():
    """Device percentages get the same range, field and two buttons as knobs."""
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    controls = {
        "device-paper": ("50", "100"),
        "device-ink": ("50", "100"),
        "device-calibration-range": ("50", "150"),
        "device-warm": ("-12", "12"),
        "device-tint": ("-8", "8"),
    }
    for control, (minimum, maximum) in controls.items():
        assert f'data-slider-for="{control}"' in html
        assert html.count(f'data-for="{control}"') == 2
        field = re.search(
            rf'<input class="mono" id="{control}"[^>]+>', html)
        assert field is not None, control
        assert 'type="number"' in field.group()
        assert f'min="{minimum}"' in field.group()
        assert f'max="{maximum}"' in field.group()

    assert '<option value="custom">custom</option>' in html
    assert 'id="device-calibrate"' not in html


def test_the_ruler_is_cut_off_rather_than_scrolled():
    """The line is measured from its left tick outwards, so the far end is not
    somewhere you go looking. A scrollbar would take a row of the panel and move
    the line while it was being read against a physical ruler.

    Two files have to agree on the class for the clipping to happen at all, and
    renaming it in one of them would silently bring the scrollbar back.
    """
    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    css = (server.STATIC / "style.css").read_text(encoding="utf-8")
    assert 'class="device-ruler-clip"' in html
    rule = css[css.index(".device-ruler-clip {"):]
    rule = rule[:rule.index("}")]
    assert "overflow: hidden" in rule, rule


def test_every_numeric_device_knob_carries_a_reset_arrow():
    """Each of these has a default that is a number you would otherwise have to
    remember and retype. Scale is the one control without an arrow: it is a
    dropdown already showing every value it has.
    """
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    carried = set(re.findall(r'data-device-reset="([^"]+)"', html))
    assert carried == {"device-paper", "device-ink", "device-warm",
                       "device-tint", "device-calibration-range"}, carried
    # Hidden until the value differs, which is the page's job to decide.
    for control in sorted(carried):
        arrow = re.search(
            rf'<button[^>]*data-device-reset="{control}"[^>]*>', html, re.S)
        assert arrow is not None, control
        assert "hidden" in arrow.group(), control
        assert 'class="revert"' in arrow.group(), control


def test_the_copy_button_says_what_shift_does():
    """One button for two things, so the one it is not doing has to be findable.
    The page settles that the same way Build does when it says Rebuild: the
    press names both, and the icon changes while the key is held.
    """
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    button = re.search(r'<button[^>]*id="device-copy".*?</button>', html, re.S)
    assert button is not None
    title = re.search(r'title="([^"]+)"', button.group())
    assert title is not None
    assert "Shift" in title.group(1), title.group(1)
    # Both icons, and the download one starts hidden.
    assert 'class="as-copy"' in button.group()
    assert 'class="as-download"' in button.group()
    assert re.search(r'class="as-download"[^>]*hidden', button.group())
    # Beside the frame toggle, in the row that is open when the fold is shut.
    preview = html.index('id="device-preview"')
    settings = html.index('<div id="device-settings">', preview)
    assert 'id="device-copy"' in html[preview:settings]


def test_the_device_panel_reads_top_to_bottom():
    """Custom scale belongs under the dropdown that turns it on, not below the
    two tone rows that have nothing to do with it. Warm and tint come after
    paper and ink, in a block of their own so the rule between them is the one
    .device-tones already draws.
    """
    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    order = [html.index(mark) for mark in (
        'id="device-scale"', 'id="device-calibration"',
        'id="device-paper"', 'id="device-ink"',
        'id="device-warm"', 'id="device-tint"')]
    assert order == sorted(order), order
    assert html.count('<div class="device-tones">') == 2


def test_the_frame_tint_filter_is_declared_in_display_levels():
    """The knobs hand the frame an offset in levels, so the filter has to work
    in the space those levels are in. A filter interpolates in linear light
    unless it is told otherwise, which would bend every offset by the transfer
    curve and turn a two-level shift into something else entirely.
    """
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    filt = re.search(r'<filter id="frame-tint".*?</filter>', html, re.S)
    assert filt is not None
    assert 'color-interpolation-filters="sRGB"' in filt.group()
    for channel in "rgb":
        assert f'id="frame-tint-{channel}"' in filt.group(), channel
        assert filt.group().count('type="linear"') == 3


def test_a_checkbox_knob_is_marked_rather_than_given_an_arrow():
    """The arrow sets a value aside so you can flick back to it. A switch has
    nothing to set aside -- the value it is not showing is the other one, one
    click away on the box itself -- so an arrow there is a second control for
    the same flip, plus a set-aside state that survives neither the flip nor a
    reload. The mark says the same thing and offers no press.
    """
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    rows = re.findall(r'<div class="row check">(.*?)</div>', html, re.S)
    assert len(rows) >= 7, len(rows)
    for row in rows:
        name = re.search(r'name="(\w+)"', row)
        assert 'class="revert"' not in row, f"{name.group(1)} still has an arrow"
        assert f'data-mark="{name.group(1)}"' in row, f"{name.group(1)} has no mark"


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
    the converter's, from rasterize_font_style, not the family builder's.
    Catching the wrong one left a 500 traceback where a 422 belongs."""
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


def test_the_figures_knob_reaches_the_page(tmp_path):
    """The knob is honestly inert on a face with no pnum feature, so this
    needs one that draws proportional figures -- built here rather than taken
    off the machine, which asked for "a CFF face" and got three failures from
    any CFF face that happens not to draw them."""
    from fastapi.testclient import TestClient
    from fontsmith import box_font

    from crossglyph.preview import server

    face = box_font(tmp_path / "Prop-Regular.ttf",
                    [ord(ch) for ch in "0123456789 the quick brown fox"],
                    figures=True, cff=True, family="Prop")
    try:
        server.set_font_source(face)
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

    assert entry["export"]["name"] == "Alto", "the name box would open blank"
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

    # An empty box is the absence of the key rather than the key set to
    # nothing: written down, it comes back as "CustomFont" and the second
    # family builds under that.
    _save_export("Alto", sizes_mod="13 15", mod_suffix="")
    assert _alto_says(scratch, "mod_suffix") is None
    entry = next(f for f in server.families() if f["name"] == "Alto")
    assert entry["export"]["mod_suffix"] == "Mod"


def _alto_says(scratch, key):
    """What alto.conf sets a key to, or None. Its `name` line arrived with the
    fixture's own padding, which a substring match would not survive."""
    from crossglyph import fontconf

    return fontconf.read_values(_conf(scratch) / "alto.conf").get(key)


def test_a_family_builds_under_the_name_it_is_given(scratch):
    """What a family is called on the device is a choice, not whatever its
    files happen to be called: a source family can be MerriweatherSans-
    Condensed and the reader's Font list is a phone-sized screen."""
    from crossglyph.preview import server

    response = _save_export("Alto", name="Alt")
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Alt"
    assert _alto_says(scratch, "name") == "Alt"

    entry = next(f for f in server.families() if f["name"] == "Alt")
    assert entry["export"]["name"] == "Alt", "the name box would open blank"
    assert entry["conf"] == "alto.conf", \
        "the file is named after the family, not after what it builds as"

    # And back. A name the family would take anyway is not worth a line, and
    # the old one no longer addresses anything -- so the save that removes it
    # has to find the family by the key that never moves.
    assert _save_export("Alt", name="Alto").json()["name"] == "Alto"
    assert _alto_says(scratch, "name") is None


def test_a_name_that_could_not_be_a_filename_comes_back_stripped(scratch):
    """It reaches a .cpfont filename, so the converter strips it to what one
    can hold. The page is told what landed rather than left showing what was
    typed."""
    response = _save_export("Alto", name="My Font!")
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "MyFont"
    assert _alto_says(scratch, "name") == "MyFont"

    # An empty box is "whatever the files are called", not a name of its own --
    # which is the one answer sanitize_name cannot give, since it makes up
    # "CustomFont" for a string with nothing usable in it.
    assert _save_export("Alto", name="  ").json()["name"] == "Alto"


def test_two_families_may_not_build_under_one_name(scratch):
    """They would write over each other size by size in the build folder, and
    nothing downstream could tell them apart afterwards."""
    response = _save_export("Alto", name="Ledger")
    assert response.status_code == 422
    assert "Ledger" in response.text
    assert "Ledger" not in \
        (_conf(scratch) / "alto.conf").read_text(encoding="utf-8"), \
        "a refused rename still touched the file"


def test_the_second_family_a_config_builds_takes_its_name_too(scratch):
    """`sizes_mod` builds <name><mod_suffix> from the same faces, so a config
    holds two names in the output folder rather than one. Landing on the
    second is the same overwrite as landing on the first."""
    assert _save_export("Ledger", sizes_mod="9 10").status_code == 200

    response = _save_export("Alto", name="LedgerMod")
    assert response.status_code == 422
    assert "LedgerMod" in response.text, response.text
    assert _alto_says(scratch, "name") == "Alto", \
        "a refused rename still touched the file"

    # And the other way round: this config's own second family is a name it
    # did not have before, and it can land on somebody just as squarely.
    response = _save_export("Alto", name="Ledg", sizes_mod="9 10",
                            mod_suffix="er")
    assert response.status_code == 422, response.text
    assert "Ledger" in response.text


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
    made = tmp_path / "cpfonts" / family / f"{family}_12.cpfont"
    assert made.is_file()
    # The bytes are the file's own, not an estimate: these go on a card with a
    # fixed amount of room, and a build is when somebody wants to know.
    written = made.stat().st_size
    assert steps[1] == {"event": "size", "family": family, "size": 12,
                        "done": 1, "total": 1, "bytes": written}
    assert steps[-1]["out"] == str(tmp_path / fontbuild.OUTPUT_NAME)
    assert steps[-1]["bytes"] == written
    assert steps[-1]["families"] == [
        {"name": family, "bytes": written, "current_bytes": 0, "sizes": [12],
         "built": [12], "skipped": [], "failed": [], "removed": [],
         "error": None}]

    # And again, with nothing to do: what it wrote is zero, and what is already
    # there is the same file. A run that built nothing still has an answer to
    # how much is on the card.
    again = _steps(TestClient(server.app).post("/build", json={}))
    assert again[-1]["bytes"] == 0
    assert again[-1]["current_bytes"] == written
    assert again[-1]["families"][0]["skipped"] == [12]

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


def _two_families(tmp_path, monkeypatch, extra=""):
    from fontsmith import box_font

    from crossglyph import fontbuild

    box_font(tmp_path / "Alpha-Regular.ttf", range(0x20, 0x7F), family="Alpha")
    box_font(tmp_path / "Beta-Regular.ttf", range(0x20, 0x7F), family="Beta")
    (_conf(tmp_path) / "all.conf").write_text(
        "sizes = 12\nintervals = base\nfallbacks = no\nspace_glyphs = no\n"
        + extra, encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    return tmp_path / fontbuild.OUTPUT_NAME


def test_a_build_drops_the_families_no_config_produces(tmp_path, monkeypatch):
    """A family that stops being one -- renamed, or gone the way georgiaz went
    when it became the bold italic of georgia -- otherwise leaves a whole
    directory behind that per-size pruning never looks at, and the simulator
    would go on staging it.

    Any build, not only a build of everything: what the output folder should
    hold is what the workspace produces, which does not depend on which family
    you happened to press Build on.
    """
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    out = _two_families(tmp_path, monkeypatch)
    client = TestClient(server.app)

    built = _steps(client.post("/build", json={}))
    assert built[-1]["event"] == "done", built
    assert (out / "Alpha").is_dir() and (out / "Beta").is_dir()

    (tmp_path / "Beta-Regular.ttf").unlink()
    named = _steps(client.post("/build", json={"family": "Alpha"}))
    assert named[0]["removed"] == ["Beta"], named[0]
    assert named[-1]["removed"] == ["Beta"], "the summary lost it"
    assert not (out / "Beta").exists()
    assert (out / "Alpha").is_dir(), "the family that still exists went too"


def test_a_rename_takes_the_directory_it_used_to_build_into(tmp_path, monkeypatch):
    """What the panel's name box does, end to end: the old name is not a
    family any more, so the fonts under it are not either."""
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    out = _two_families(tmp_path, monkeypatch)
    client = TestClient(server.app)
    _steps(client.post("/build", json={}))
    assert (out / "Alpha").is_dir()

    assert _save_export("Alpha", name="Alfa", sizes="12").status_code == 200
    steps = _steps(client.post("/build", json={"family": "Alfa"}))
    assert steps[0]["removed"] == ["Alpha"], steps[0]
    assert (out / "Alfa").is_dir() and not (out / "Alpha").exists()
    assert (out / "Beta").is_dir(), "a rename took an unrelated family with it"


def test_a_family_whose_face_went_missing_keeps_what_it_built(tmp_path, monkeypatch):
    """Its config still claims the name, and a config that cannot resolve
    today produces nothing -- which is the one reason its output could not be
    rebuilt, and so the worst reason to delete it."""
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    out = _two_families(tmp_path, monkeypatch)
    (_conf(tmp_path) / "beta.conf").write_text("family = Beta\n", encoding="utf-8")
    client = TestClient(server.app)
    _steps(client.post("/build", json={}))
    assert (out / "Beta").is_dir()

    (tmp_path / "Beta-Regular.ttf").unlink()
    steps = _steps(client.post("/build", json={"family": "Alpha"}))
    assert steps[0]["removed"] == [], steps[0]
    assert (out / "Beta").is_dir()


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
    assert _entry("Optic")["files"]["regular"] == "Optic[opsz].ttf"


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


def test_saving_preserves_a_hidden_optical_size_override(
        variable_source, tmp_path):
    import fontsmith
    from fastapi.testclient import TestClient

    from crossglyph.cpfont.tuning import Tuning
    from crossglyph.preview import server

    _second_axis(fontsmith.variable_box_font(
        tmp_path / "OpticWeight[wght,opsz].ttf", range(0x41, 0x5B),
        family="OpticWeight"), tag="opsz", low=7, default=12, high=72)
    config_path = _conf(variable_source) / "opticweight.conf"
    config_path.write_text(
        "family = OpticWeight\n"
        "regular = OpticWeight[wght,opsz].ttf@opsz=12\n",
        encoding="utf-8")
    body = {key: Tuning().as_dict()[key] for key in server.SAVED_KEYS}
    body.pop("line_height", None)

    answer = TestClient(server.app).post(
        "/save", json={"family": "OpticWeight", "tuning": body,
                       "axes": {"text": 400, "bold": 700}})

    assert answer.status_code == 200, answer.text
    written = config_path.read_text(encoding="utf-8")
    assert "regular = OpticWeight[wght,opsz].ttf@opsz=12" in written
    assert server.family_config("OpticWeight").axis_overrides["regular"] == {
        "opsz": 12.0}
    assert _entry("OpticWeight")["files"]["regular"] == (
        "OpticWeight[wght,opsz].ttf at opsz 12, wght 400")


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


@pytest.fixture
def free_address(monkeypatch):
    """Nothing listening on the address these tests pretend to serve on.

    They stub uvicorn, so none of them binds anything, but main() asks whether
    the address is free before it claims it. On a machine with a preview of
    its own running, port 8000 is not, and the refusal is the whole point of
    the ask.
    """
    from crossglyph import daemon

    monkeypatch.setattr(daemon, "taken", lambda host, port: False)


def test_the_preview_opens_on_a_family_when_nothing_says_which(two_families,
                                                               free_address,
                                                               monkeypatch):
    """A tester who unpacked the zip runs the launcher and nothing else, so
    the page has to arrive on whatever is in the workspace."""
    from crossglyph.preview import server

    served = {}

    class Uvicorn:
        """uvicorn.Server, which main() builds itself so /shutdown can ask it."""

        def __init__(self, config):
            served["config"] = config

        def run(self):
            served["state"] = server._restart_state
            served["ran"] = True

    monkeypatch.setattr("uvicorn.Server", Uvicorn)
    assert server.main(["--no-open"]) == 0
    assert served["ran"] and served["config"].host == "127.0.0.1"
    assert server._family in {"Probe", "Filler"}
    assert "--family" in served["state"].rest
    assert served["state"].port == 8000
    assert server._restart_state is None


def test_ctrl_c_stops_the_preview_without_a_traceback(two_families,
                                                       free_address,
                                                       monkeypatch):
    """Uvicorn re-raises its captured SIGINT after shutting down cleanly."""
    from crossglyph.preview import server

    class Uvicorn:
        def __init__(self, _config):
            pass

        def run(self):
            raise KeyboardInterrupt

    monkeypatch.setattr("uvicorn.Server", Uvicorn)
    assert server.main(["--no-open"]) == 0


def test_a_held_address_is_answered_before_anything_is_claimed(two_families,
                                                                monkeypatch,
                                                                capsys):
    """`crossglyph start` and then a bare `crossglyph` is the way into this.
    Left to uvicorn it is a line of errno with the word bind in it, printed
    after this command has already said "preview on ..." for a preview that
    never started."""
    from crossglyph import daemon
    from crossglyph.preview import server

    monkeypatch.setattr(daemon, "taken", lambda host, port: True)
    monkeypatch.setattr(daemon, "probe",
                        lambda host, port, **k: {"version": "0.1.2"})
    monkeypatch.setattr("uvicorn.Server",
                        lambda config: pytest.fail("built a server anyway"))

    assert server.main(["--no-open"]) == 1

    said = capsys.readouterr()
    assert "already running on" in said.err
    assert "preview on" not in said.out


@pytest.mark.parametrize(
    ("arguments", "wanted"),
    [(["--no-open"], "0.0.0.0"),
     (["--no-open", "--host", "192.0.2.1"], "192.0.2.1")])
def test_the_preview_host_uses_the_environment_unless_flagged(
        two_families, free_address, monkeypatch, arguments, wanted):
    """An image can set one safe container default without changing the local
    default or stopping an explicit address from winning."""
    from crossglyph.preview import server

    served = {}

    class Uvicorn:
        def __init__(self, config):
            served["config"] = config

        def run(self):
            pass

    monkeypatch.setenv("CROSSGLYPH_HOST", "0.0.0.0")
    monkeypatch.setattr("uvicorn.Server", Uvicorn)
    assert server.main(arguments) == 0
    assert served["config"].host == wanted


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

    marked = {entry["name"] for entry in server.families() if entry["bundled"]}
    assert marked == {"Literata"}, "a font of yours is being called bundled"


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
    five of them: the three CJK ones and Korean, which do not break words that
    way, and Arabic, which justifies by stretching the joins between letters
    rather than by breaking a word in two. A preset whose language the page
    *can* hyphenate but does not offer would be one the picker could never
    follow."""
    import re

    from crossglyph.preview import server

    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    picker = re.search(r'<select id="language".*?</select>', html, re.S)
    offered = set(re.findall(r'<option value="(\w*)"', picker.group(0)))

    unhyphenated = {tag for tag in _samples() if tag not in offered}
    assert unhyphenated == {"ar", "ja", "ko", "zh-Hans", "zh-Hant"}, \
        unhyphenated


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
    named = {"ar": "arabic", "en": "english", "fi": "finnish", "fr": "french",
             "de": "german", "it": "italian", "pl": "polish", "ru": "russian",
             "es": "spanish", "sv": "swedish", "uk": "ukrainian"}
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


def test_the_fetch_streams_its_progress_and_reads_the_page(tmp_path, monkeypatch):
    """The button drives a bar from these lines, and the text on the page is
    what asks for a CJK face when no coverage box has."""
    import contextlib
    import io
    import json

    from fastapi.testclient import TestClient

    from crossglyph import fontbuild
    from crossglyph.preview import server

    @contextlib.contextmanager
    def serve(*_args, **_kwargs):
        yield io.BytesIO(b"x" * 64)

    monkeypatch.setattr("urllib.request.urlopen", serve)
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)

    answer = TestClient(server.app).post(
        "/fallbacks", json={"intervals": "reading", "text": "すべての人間は"})
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("application/x-ndjson")

    steps = [json.loads(line) for line in answer.text.splitlines() if line.strip()]
    assert steps[0]["event"] == "plan"
    assert steps[-1]["event"] == "done"
    assert steps[-1]["where"].endswith(fontbuild.FALLBACK_NAME)

    started = [step["name"] for step in steps if step["event"] == "start"]
    assert any("CJK" in name for name in started), \
        "a Japanese page fetched nothing that could draw it"
    assert fontbuild.FALLBACK_LICENCE in started, "the OFL requires it"


def test_the_update_endpoint_says_what_this_install_is(client):
    from crossglyph import install, version

    said = client.get("/update").json()
    assert version.parse(said["version"]) is not None
    assert said["kind"] in install.KINDS
    assert said["can_self_update"] is install.can_self_update(said["kind"])
    # The sentence, already decided: the page renders what it is given rather
    # than working out for itself when there is one to show.
    assert said["notice"] == install.notice(said["kind"],
                                            bool(said["available"]),
                                            offering=True)


def test_an_installed_release_waiting_for_a_restart_is_said(client,
                                                            monkeypatch):
    """This process goes on being the version it started as, so a check it
    makes after an update finds the release already on the disk and calls it
    new. What a restart would run is the answer to that, and it is read off
    the disk rather than remembered: a reload, a second browser and an update
    done from the command line are all told the same thing.
    """
    from crossglyph.preview import server

    from crossglyph import install, updates

    monkeypatch.setattr(server.updates, "load_state",
                        lambda root: updates.State(1000.0, "9.9.9", None))
    monkeypatch.setattr(server.layout, "current", lambda root: "9.9.9")
    said = client.get("/update").json()
    assert said["pending"] == "9.9.9"
    # The release is still the newest one there is, and still worth naming.
    assert said["available"] == "9.9.9"
    # But nothing says how to fetch what has already been fetched: the notice
    # is the one for an install with nothing to install.
    assert said["notice"] == install.notice(said["kind"], False,
                                            offering=True)


def test_a_release_it_can_install_itself_is_not_also_told_the_command(
        client, monkeypatch):
    """The page puts an Update button on this very line, so the sentence
    beside it would say only what the button already does."""
    from crossglyph.preview import server

    from crossglyph import install, updates

    monkeypatch.setattr(server.updates, "load_state",
                        lambda root: updates.State(1000.0, "9.9.9", None))
    monkeypatch.setattr(server.install, "detect", lambda root: install.ZIP)
    said = client.get("/update").json()
    assert said["available"] == "9.9.9"
    assert said["can_self_update"] is True
    assert said["notice"] == ""


def test_nothing_is_pending_while_what_runs_is_what_is_current(client,
                                                               monkeypatch):
    from crossglyph import version
    from crossglyph.preview import server

    monkeypatch.setattr(server.layout, "current",
                        lambda root: version.installed())
    assert client.get("/update").json()["pending"] is None
    # A checkout has no `current` at all, which is the ordinary case here.
    monkeypatch.setattr(server.layout, "current", lambda root: None)
    assert client.get("/update").json()["pending"] is None


def test_the_firmware_commit_travels_with_the_version(client, monkeypatch):
    """Two installs on the same version can carry different renderers, so the
    commit is part of the answer rather than a detail."""
    from crossglyph.preview import server

    monkeypatch.setattr(server.stamp, "build_stamp", lambda: "45caec3e76c2")
    assert client.get("/update").json()["firmware"] == "45caec3e76c2"


def test_a_core_with_no_stamp_reports_null_rather_than_a_guess(client,
                                                               monkeypatch):
    from crossglyph.preview import server

    monkeypatch.setattr(server.stamp, "build_stamp", lambda: None)
    assert client.get("/update").json()["firmware"] is None


def test_the_update_endpoint_carries_what_the_check_found(client, monkeypatch):
    from crossglyph import updates
    from crossglyph.preview import server

    monkeypatch.setattr(server.updates, "load_state",
                        lambda root: updates.State(1000.0, "9.9.9", None))
    said = client.get("/update").json()
    assert said["latest"] == "9.9.9"
    assert said["available"] == "9.9.9"
    assert said["checked_at"] == 1000.0
    assert said["error"] is None


def test_reading_the_state_never_fetches(client, monkeypatch):
    """GET is the page rendering what is already known. The thread at startup
    and the button are the only two things that ask."""
    from crossglyph.preview import server

    def forbidden(*args, **kwargs):
        raise AssertionError("GET /update went to the network")

    monkeypatch.setattr(server.updates, "check", forbidden)
    assert client.get("/update").status_code == 200


def test_a_forced_check_asks_and_answers(client, monkeypatch):
    from crossglyph import updates
    from crossglyph.preview import server

    asked = []

    def check(root, **kw):
        asked.append(kw)
        return updates.State(2000.0, "9.9.9", None)

    monkeypatch.setattr(server.updates, "check", check)
    monkeypatch.setattr(
        server.updates, "load_state",
        lambda root: updates.State(0.0, None, None))
    said = client.post("/update/check").json()
    assert asked and asked[0]["force"] is True
    assert said["latest"] == "9.9.9"


def test_a_container_check_reports_how_to_update(client, monkeypatch):
    from crossglyph import install, updates
    from crossglyph.preview import server

    state = updates.State(2000.0, "9.9.9", None)
    monkeypatch.setattr(
        server.updates, "check", lambda root, **kwargs: state)
    monkeypatch.setattr(
        server.updates, "load_state",
        lambda root: updates.State(0.0, None, None))
    monkeypatch.setattr(
        server.install, "detect", lambda root: install.CONTAINER)
    monkeypatch.setattr(server.version, "installed", lambda: "0.1.0")

    said = client.post("/update/check").json()

    assert said["available"] == "9.9.9"
    assert said["can_self_update"] is False
    assert said["notice"] == "Pull the new image to update."


def test_a_page_load_stays_quiet_about_a_release_that_was_turned_down(
        client, monkeypatch):
    """A load is the tool raising the subject, which is the nagging a
    rollback exists to stop."""
    from crossglyph import updates
    from crossglyph.preview import server

    monkeypatch.setattr(server.updates, "load_state",
                        lambda root: updates.State(2000.0, "9.9.9", None,
                                                   rejected="9.9.9"))
    said = client.get("/update").json()

    assert said["latest"] == "9.9.9"
    assert said["available"] is None
    assert said["turned_down"] is False


def test_but_the_button_names_it_and_offers_it(client, monkeypatch):
    """The same distinction the command line draws: pressing Check now is a
    person asking, and the answer includes why it had not been mentioned."""
    from crossglyph import updates
    from crossglyph.preview import server

    state = updates.State(2000.0, "9.9.9", None, rejected="9.9.9")
    monkeypatch.setattr(server.updates, "check", lambda root, **kw: state)
    monkeypatch.setattr(server.updates, "load_state", lambda root: state)
    said = client.post("/update/check").json()

    assert said["available"] == "9.9.9"
    assert said["turned_down"] is True


def test_a_forced_check_that_fails_says_so_rather_than_erroring(client,
                                                                monkeypatch):
    """A 500 would show the page nothing to explain. The failure is the
    answer, so it travels in the body."""
    from crossglyph import updates
    from crossglyph.preview import server

    monkeypatch.setattr(server.updates, "check",
                        lambda root, **kw: updates.State(1.0, None, "no route"))
    monkeypatch.setattr(server.updates, "load_state",
                        lambda root: updates.State(1.0, None, "no route"))
    said = client.post("/update/check")
    assert said.status_code == 200
    assert said.json()["error"] == "no route"


def test_the_page_is_told_when_checking_is_off(client, monkeypatch):
    from crossglyph import updateconf
    from crossglyph.preview import server

    monkeypatch.setattr(server.updateconf, "settings",
                        lambda root: updateconf.Settings(False, 24.0, 1))
    assert client.get("/update").json()["checking_off"] is True


# --- applying -------------------------------------------------------------


def steps(client, monkeypatch, *given):
    from crossglyph.preview import server

    monkeypatch.setattr(server, "_update_phase", "idle")
    monkeypatch.setattr(server.upgrade, "steps",
                        lambda root, *a, **kw: iter(given))
    said = client.post("/update", json={})
    assert said.status_code == 200
    return [json.loads(line) for line in said.text.splitlines() if line]


def test_applying_streams_a_line_at_a_time(client, monkeypatch):
    """The same shape /build and /fallbacks answer with, so the page reads it
    with the reader it already has."""
    said = steps(client, monkeypatch,
                 {"event": "plan", "version": "9.9.9", "bytes": 1600000,
                  "notes_url": "https://example.invalid/", "converting": False},
                 {"event": "step", "got": 1600000, "bytes": 1600000},
                 {"event": "done", "version": "9.9.9", "kept": [], "staged": [],
                  "converting": False, "where": "versions/9.9.9"})
    assert [step["event"] for step in said] == ["plan", "step", "done"]
    assert said[-1]["restarting"] is False


def test_a_local_update_hands_the_running_preview_to_the_new_version(
        monkeypatch):
    from crossglyph import daemon
    from crossglyph.preview import server
    from fastapi.testclient import TestClient

    state = daemon.State(
        pid=1234, host="127.0.0.1", port=8123,
        rest=["--family", "notosans"], version="0.3.0", started=1.0)
    handed = []
    monkeypatch.setattr(server, "_update_phase", "idle")
    monkeypatch.setattr(server, "_handoff_process", None)
    monkeypatch.setattr(server, "_handoff_failed", False)
    monkeypatch.setattr(server, "_restart_state", state)
    monkeypatch.setattr(
        server.upgrade, "steps",
        lambda root: iter(({
            "event": "done", "version": "9.9.9", "kept": [], "staged": [],
            "converting": False, "where": "versions/9.9.9"},)))
    monkeypatch.setattr(
        server.daemon, "handoff_command",
        lambda root, target: ["new-python", "-m", "crossglyph"])

    class Started:
        def poll(self):
            return None

    def handoff(root, target, saved):
        handed.append((root, target, saved))
        return Started()

    monkeypatch.setattr(server.daemon, "handoff", handoff)

    with TestClient(server.app, client=("127.0.0.1", 55555)) as client:
        said = [json.loads(line) for line in
                client.post("/update", json={}).text.splitlines() if line]
        repeated = [json.loads(line) for line in
                    client.post("/update", json={}).text.splitlines() if line]
        status = client.get("/update").json()

    assert said[-1]["restarting"] is True
    assert said[-1]["restart_log"].endswith(server.daemon.LOG_NAME)
    assert repeated == [{
        "event": "error",
        "error": "an update is already running or waiting for CrossGlyph "
                 "to restart.",
    }]
    assert status["handoff"] == "starting"
    assert handed == [(server.install.root(), "9.9.9", state)]


def test_a_cross_origin_form_cannot_apply_an_update(client, monkeypatch):
    from crossglyph.preview import server

    called = []
    monkeypatch.setattr(server, "_update_phase", "idle")
    monkeypatch.setattr(
        server.upgrade, "steps", lambda root: called.append(root) or iter(()))

    answer = client.post(
        "/update",
        headers={
            "Origin": "https://attacker.invalid",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        content="submit=update",
    )

    assert answer.status_code == 422
    assert called == []


def test_a_second_request_cannot_overlap_an_update(monkeypatch):
    import threading

    from crossglyph.preview import server
    from fastapi.testclient import TestClient

    entered = threading.Event()
    finish = threading.Event()
    first = []
    monkeypatch.setattr(server, "_update_phase", "idle")

    def applying(_root):
        entered.set()
        assert finish.wait(timeout=5)
        yield {"event": "error", "error": "first request finished"}

    monkeypatch.setattr(server.upgrade, "steps", applying)

    def post_first():
        first.append(TestClient(server.app).post("/update", json={}))

    worker = threading.Thread(target=post_first)
    worker.start()
    try:
        assert entered.wait(timeout=5)
        second = TestClient(server.app).post("/update", json={})
    finally:
        finish.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert "already running" in second.text
    assert "first request finished" in first[0].text


def test_update_state_reports_a_failed_handoff(client, monkeypatch):
    from crossglyph.preview import server

    class Finished:
        def poll(self):
            return 1

    monkeypatch.setattr(server, "_handoff_process", Finished())
    monkeypatch.setattr(server, "_handoff_failed", False)

    assert client.get("/update").json()["handoff"] == "failed"


def test_a_refusal_is_the_first_line_rather_than_a_status(client, monkeypatch):
    """What the page has to show is the sentence, and a status code is not
    one."""
    said = steps(client, monkeypatch,
                 {"event": "error", "error": "this install cannot update "
                                             "itself. Run git pull to update."})
    assert "git pull" in said[0]["error"]


def test_the_endpoint_does_not_decide_who_may_apply(client, monkeypatch):
    """upgrade.steps resolves the kind and refuses as its first step, before
    it opens the network. A second gate here is a second thing to keep in
    step with the first."""
    from crossglyph.preview import server

    seen = []
    monkeypatch.setattr(server, "_update_phase", "idle")
    monkeypatch.setattr(server.upgrade, "steps",
                        lambda root, *a, **kw: seen.append(root) or iter(()))
    client.post("/update", json={})
    assert seen == [server.install.root()]


# --- the page shows what the build would carry -----------------------------


def _joining(tmp_path):
    import fontsmith
    return fontsmith.joining_font(tmp_path / "joining.ttf")


@needs_core
def test_coverage_the_build_would_drop_is_dropped_from_the_page(tmp_path):
    """The page and the device have to agree, or a family looks finished here
    and reaches the reader unreadable.

    Unticking a range used to leave the render byte for byte the same, because
    a preview build is sized to the text rather than to the coverage. It is
    still sized to the text; it is now also held to what a build of that
    coverage would carry.
    """
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    server._sources.clear()
    server._sources[0] = _joining(tmp_path)
    client = TestClient(server.app)
    arabic_text = "\u0628\u0628\u0628 abc"

    carried = client.post("/render", json={"text": arabic_text, "size": 16,
                                           "intervals": "base,arabic"})
    dropped = client.post("/render", json={"text": arabic_text, "size": 16,
                                           "intervals": "base"})
    assert carried.status_code == dropped.status_code == 200
    assert carried.content != dropped.content, \
        "unticking a range the text uses has to change the page"
    assert carried.headers["x-uncovered"] == "0"
    assert int(dropped.headers["x-uncovered"]) > 0
    assert dropped.headers["x-coverage-fix"] == "arabic"


@needs_core
def test_a_panel_that_has_not_said_its_coverage_draws_everything(tmp_path):
    """Absent is not the same as nothing ticked.

    The export panel sends its coverage once it has read a family's config,
    and a family with no config never sends one. Guessing empty there would
    blank every non-Latin page before anybody touched a control.
    """
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    server._sources.clear()
    server._sources[0] = _joining(tmp_path)
    client = TestClient(server.app)
    body = {"text": "\u0628\u0628\u0628 abc", "size": 16}

    silent = client.post("/render", json=body)
    everything = client.post("/render", json={**body, "intervals": "base,arabic"})
    assert silent.headers["x-uncovered"] == "0"
    assert silent.content == everything.content


def test_the_named_fix_is_a_preset_that_would_actually_carry_them():
    from crossglyph.preview import presets_covering

    assert presets_covering(frozenset({0x0628, 0x0645})) == ("arabic",)
    assert presets_covering(frozenset({0x0410})) == ("cyrillic",)
    assert presets_covering(frozenset()) == ()
    # Nothing in any preset: said as nothing rather than as a wrong tick.
    assert presets_covering(frozenset({0xE000})) == ()


@needs_core
def test_a_range_being_typed_into_does_not_fail_the_page(tmp_path):
    """The field holds half a range for as long as it takes to type one.

    Resolving the whole spec answered `(0x06` with a 422 and a line on the log,
    four times on the way to a range that is fine, while the page redrew on
    every keystroke.
    """
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    server._sources.clear()
    server._sources[0] = _joining(tmp_path)
    client = TestClient(server.app)
    body = {"text": "\u0628\u0628\u0628 abc", "size": 16, "intervals": "base"}

    for half in ["(", "(0x", "(0x06", "(0x0600-", "nonsense"]:
        answer = client.post("/render", json={**body, "ranges": half})
        assert answer.status_code == 200, f"{half!r} took the page down"
        # Not in force yet, so the page is narrowed by the ticks alone.
        assert int(answer.headers["x-uncovered"]) > 0, half

    whole = client.post("/render", json={**body, "ranges": "(0x0600-0x06FF)"})
    assert whole.status_code == 200
    assert whole.headers["x-uncovered"] == "0", \
        "a range that parses has to take effect"


def test_naming_a_preset_is_cheap_on_a_page_with_nothing_wrong():
    """Asked on every render, so the usual answer costs nothing to reach.

    Expanding every preset to compare it spent three and a half milliseconds a
    keystroke listing a CJK block nobody had asked about.
    """
    import time

    from crossglyph.preview import presets_covering

    start = time.perf_counter()
    for _ in range(50):
        assert presets_covering(frozenset()) == ()
    assert (time.perf_counter() - start) / 50 < 0.001


def test_a_codepoint_no_preset_carries_names_none_rather_than_raising():
    """Reached from a render, so an answer of "nothing" cannot be an exception.

    Private use, and any block the presets do not name.
    """
    from crossglyph.preview import presets_covering

    assert presets_covering(frozenset({0xE000})) == ()
    # Mixed: the one that is carried is still named, the other is dropped.
    assert presets_covering(frozenset({0xE000, 0x0628})) == ("arabic",)


@needs_core
def test_fallbacks_without_a_coverage_still_render(tmp_path):
    """Coverage is optional on a render and the fallback ticks are not tied
    to it, so the two arrive apart and the pair has to hold.

    Making coverage nullable put a None into the split that decides whether a
    CJK face was asked for, which is an AttributeError and a 500 out of a
    request nobody has to send wrongly to make.
    """
    from fastapi.testclient import TestClient

    from crossglyph.preview import server

    server._sources.clear()
    server._sources[0] = _joining(tmp_path)
    client = TestClient(server.app)
    answer = client.post("/render", json={"text": "abc", "size": 16,
                                          "fallbacks": True})
    assert answer.status_code in (200, 503), answer.text


@needs_core
def test_a_workspace_under_a_non_ascii_path_still_draws(tmp_path, monkeypatch):
    """The install sits under the user's own name, and plenty of those carry
    a character above ASCII. FreeType opens a path through the C library's
    `fopen`, which on Windows reads it in the ANSI code page while freetype-py
    hands it UTF-8, so no face in such a folder opens by name. Reached from
    here it is the whole panel: the first render answers "cannot open
    resource", and no knob on the page changes that."""
    from fastapi.testclient import TestClient
    from fontsmith import box_font

    from crossglyph import fontbuild
    from crossglyph.preview import server

    workspace = tmp_path / "Сергей"
    workspace.mkdir()
    box_font(workspace / "Probe-Regular.ttf", [*range(0x20, 0x7F)],
             family="Probe")
    (_conf(workspace) / "all.conf").write_text("fallbacks = no\n",
                                               encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", workspace)
    _forget_the_last_folder()
    server.set_font_source(workspace / "Probe-Regular.ttf", family="Probe")
    try:
        answer = TestClient(server.app).post(
            "/render", json={"size": 13, "family": "Probe", "text": "Hello"})
        assert answer.status_code == 200, answer.text
    finally:
        _forget_the_last_folder()
        server.set_font_source(SRC)


# --- what a failed render says ----------------------------------------------


def _fault_of(answer):
    """The kind and the sentence, as the page reads them off a render."""
    return answer.headers.get("x-fault"), answer.json()["detail"]


@needs_core
def test_a_malformed_font_is_not_called_a_setting(tmp_path, monkeypatch):
    """A file in the folder that is not a font. fontTools reads the face
    before the rasterizer does, so this arrives as the converter's own
    FontBuildError, which already names the file and says what to try."""
    from fastapi.testclient import TestClient
    from fontsmith import box_font

    from crossglyph import fontbuild
    from crossglyph.preview import server

    face = tmp_path / "Probe-Regular.ttf"
    box_font(face, range(0x20, 0x7F), family="Probe")
    (_conf(tmp_path) / "all.conf").write_text("fallbacks = no\n",
                                              encoding="utf-8")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    _forget_the_last_folder()
    server.set_font_source(face, family="Probe")
    try:
        face.write_bytes(b"not a font at all")
        answer = TestClient(server.app).post(
            "/render", json={"size": 13, "family": "Probe", "text": "Hi"})
        kind, why = _fault_of(answer)
        assert answer.status_code == 422
        assert kind == "font"
        assert "Probe-Regular.ttf" in why, why
        assert "FT_Exception" not in why, \
            "freetype-py's wrapper reached the page"
    finally:
        _forget_the_last_folder()
        server.set_font_source(SRC)


def test_a_family_that_is_gone_is_not_called_a_setting(tmp_path, monkeypatch):
    """A remembered choice whose files have moved. Nothing on the panel was
    refused, so the headline the page picks must not say a setting was.

    Its own folder, because the answer to "no such family" depends on what
    else is in the one being read: a config in there that cannot be resolved
    is reported ahead of the name that was asked for, and rightly.
    """
    from fastapi.testclient import TestClient
    from fontsmith import box_font

    from crossglyph import fontbuild
    from crossglyph.preview import server

    box_font(tmp_path / "Probe-Regular.ttf", [0x20, 0x41], family="Probe")
    monkeypatch.setattr(fontbuild, "SOURCE_DIR", tmp_path)
    _forget_the_last_folder()
    try:
        answer = TestClient(server.app).post(
            "/render", json={"size": 13, "family": "Nonesuch"})
        kind, why = _fault_of(answer)
        assert answer.status_code == 422
        assert kind == "family"
        # Cased as the picker looks it up, and it lists what is there instead.
        assert "nonesuch" in why.lower() and "Probe" in why, why
    finally:
        _forget_the_last_folder()
        server.set_font_source(SRC)


@needs
def test_a_knob_the_converter_will_not_take_is_a_setting(client):
    """The one case the old single headline was right about, kept."""
    answer = client.post("/render",
                         json={"size": 13, "page": {"alignment": "sideways"}})
    assert answer.status_code == 422
    assert _fault_of(answer)[0] == "setting"


def test_freetype_saying_nothing_about_the_file_is_told_which(tmp_path):
    """The other way a font fault arrives, and the reason _unreadable exists.
    FreeType reports what went wrong and never which file it was reading, so
    "cannot open resource" on its own is a sentence about nothing in
    particular.

    Reached when FreeType refuses a face fontTools could read, which the
    malformed case above never is. A fallback in the chain is as likely to be
    the one it refused as the family's own face, so every face the build was
    given is named and none is claimed to be the culprit.
    """
    import freetype

    from crossglyph.preview import server

    folder = tmp_path / "Сергей"
    faces = {0: folder / "Probe-Regular.ttf", 2: folder / "Probe-Italic.ttf"}
    kind, why = server._fault(freetype.FT_Exception(1), faces)

    assert kind == "font"
    assert "FT_Exception" not in why, "freetype-py's wrapper reached the page"
    assert why.startswith("cannot open resource."), why
    assert "one of Probe-Italic.ttf, Probe-Regular.ttf" in why, why
    assert str(folder) in why, why
    # One face, and nothing is hedged: there is only one file it can be.
    single = server._fault(freetype.FT_Exception(1), {0: faces[0]})[1]
    assert "one of" not in single, single
    assert "Probe-Regular.ttf" in single, single
    # Nothing resolved yet, so there is nothing to name and it says only what
    # FreeType said.
    assert server._fault(freetype.FT_Exception(1), None)[1] == (
        "cannot open resource")


def test_freetype_words_carrying_brackets_come_through_whole():
    """The wrapper is one bracket off each end. str.strip() takes characters
    and not an affix, so a message ending in a bracket of its own loses that
    one too and comes out unbalanced."""
    from crossglyph.preview import server

    class Odd(Exception):
        def __str__(self):
            return "FT_Exception:  (invalid argument (size))"

    assert server._freetype_said(Odd()) == "invalid argument (size)"
    # Nothing shaped like the wrapper at all, so there is nothing to unwrap.
    assert server._freetype_said(ValueError("plain")) == "plain"


def test_a_reason_the_converter_exits_with_reaches_the_page():
    """The converter exits where a library would raise, so its reason is the
    exit's own argument. A bare exit code carries none, and the panel has to
    say something for that too."""
    from crossglyph.preview import server

    assert server._fault(SystemExit("this font needs 261 pixels a line"),
                         None) == ("converter",
                                   "this font needs 261 pixels a line")
    kind, why = server._fault(SystemExit(1), None)
    assert kind == "converter"
    assert why.startswith("the converter rejected"), why


@needs
def test_an_unknown_coverage_preset_says_which_one(client):
    """The other exit on this path. Its list of what it would have taken is
    the answer to the question the reader is about to ask."""
    answer = client.post("/render", json={"size": 13, "intervals": "klingon"})
    kind, why = _fault_of(answer)
    assert answer.status_code == 422
    assert kind == "converter"
    assert "klingon" in why and "cyrillic" in why, why
