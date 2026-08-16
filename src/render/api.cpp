// The C API of the render core.
//
// Freestanding by construction: bytes in, bytes out, no syscalls. One stray
// printf would import fd_write and cost the browser phase a WASI shim, so the
// build asserts that this module imports nothing at all -- see
// tests/test_render_core.py::test_the_module_is_freestanding.
//
// Design notes live in
// docs/superpowers/plans/2026-08-11-font-lab-render-core.md.
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include <EpdFontFamily.h>
#include <Epub/ParsedText.h>
#include <Epub/blocks/BlockStyle.h>
#include <Epub/blocks/TextBlock.h>
#include <Epub/hyphenation/Hyphenator.h>
#include <GfxRenderer.h>
#include <SdCardFont.h>

#include "HalDisplay.h"
#include "HalStorage.h"

namespace {

SdCardFont g_font;
bool g_loaded = false;
GfxRenderer g_renderer(display);

/// The one font id the preview uses.
constexpr int kFontId = 0;

/// The regular style's metrics, or nullptr when nothing is loaded.
const EpdFontData* fontData() {
  if (!g_loaded) return nullptr;
  const EpdFont* font = g_font.getEpdFont(EpdFontFamily::REGULAR);
  return font ? font->data : nullptr;
}

/// The lines of the last laid-out paragraph, kept so the host can read the
/// breaks back without a second layout pass.
std::vector<std::shared_ptr<TextBlock>> g_lines;

/// Layout options, defaulting to what the device actually ships
/// (CrossPointSettings.h:217, 241, 246): justified, extra paragraph spacing
/// on, hyphenation off.
///
/// Worth stating because two of the three are the opposite of what looks
/// natural, and the pair interacts: extra paragraph spacing is also what
/// turns the first-line indent *off* (ParsedText.cpp:588-602), so an
/// out-of-the-box page has gaps between paragraphs and no indents. A preview
/// that started from the prettier combination would be tuning against a page
/// the reader never shows until its owner goes and changes two settings.
CssTextAlign g_alignment = CssTextAlign::Justify;
bool g_hyphenation = false;
bool g_extraParagraphSpacing = true;

/// One style byte per word, or nullptr for all-regular. The host splits words
/// exactly as addWords does -- on ' ', empties dropped, newlines separating
/// paragraphs without consuming a byte -- so this cursor stays in step across
/// the whole page.
///
/// The length is carried too, and a word past the end falls back to regular:
/// that contract lives on both sides of the wasm boundary, and if the two ever
/// disagree a page set in the wrong faces is a better failure than reading off
/// the end of the buffer.
const uint8_t* g_styles = nullptr;
int g_stylesLength = 0;
int g_styleIndex = 0;

EpdFontFamily::Style nextStyle() {
  if (!g_styles || g_styleIndex >= g_stylesLength) {
    ++g_styleIndex;
    return EpdFontFamily::REGULAR;
  }
  return static_cast<EpdFontFamily::Style>(g_styles[g_styleIndex++]);
}

/// Feed the engine one space-separated word at a time. addWord does the NFC,
/// CJK and RTL splitting itself -- do not pre-split beyond spaces.
/// Mirrors TextSettingsPreview.cpp:41-53.
void addWords(ParsedText& parsed, const char* utf8) {
  std::string word;
  for (const char* p = utf8;; ++p) {
    if (*p == ' ' || *p == '\0') {
      if (!word.empty()) {
        parsed.addWord(word, nextStyle());
        word.clear();
      }
      if (*p == '\0') break;
    } else {
      word.push_back(*p);
    }
  }
}

/// Page geometry, in logical page pixels. Defaults are the reader's: the
/// panel's own viewable insets plus CrossPointSettings' SCREEN_MARGIN_MIN
/// (CrossPointSettings.h:249, EpubReaderActivity.cpp:1195-1199). The status
/// bar is deliberately not modelled -- it is chrome, not type.
constexpr int kScreenMargin = 5;
int g_screenMargin = kScreenMargin;
int g_marginLeft = 0, g_marginTop = 0, g_marginRight = 0, g_marginBottom = 0;
float g_lineCompression = 1.0f;
bool g_marginsResolved = false;

void applyMargins() {
  int top = 0, right = 0, bottom = 0, left = 0;
  g_renderer.getOrientedViewableTRBL(&top, &right, &bottom, &left);
  g_marginTop = top + g_screenMargin;
  g_marginRight = right + g_screenMargin;
  g_marginBottom = bottom + g_screenMargin;
  g_marginLeft = left + g_screenMargin;
  g_marginsResolved = true;
}

void resolveMargins() {
  if (!g_marginsResolved) applyMargins();
}

/// Lay one paragraph out into `into`. A ParsedText consumes its words
/// (ParsedText.cpp:665-670), so this builds a fresh one every time.
void layoutInto(std::vector<std::shared_ptr<TextBlock>>& into,
                const char* utf8, int width) {
  BlockStyle style;
  style.alignment = g_alignment;
  style.textAlignDefined = true;  // honour the knob; RTL is still auto-detected
  ParsedText parsed(g_extraParagraphSpacing, g_hyphenation, false, style);
  addWords(parsed, utf8);
  parsed.layoutAndExtractLines(
      g_renderer, kFontId, static_cast<uint16_t>(width),
      [&into](std::shared_ptr<TextBlock> line, uint32_t) {
        into.push_back(std::move(line));
      });
}

}  // namespace

extern "C" {

/// Bind the renderer to the framebuffer. Must run before anything is drawn:
/// GfxRenderer::begin() is what fills in frameBuffer and the panel dimensions
/// (GfxRenderer.cpp:120), and without it every pixel is clipped against a
/// zero-sized panel -- silently, with a blank image as the only symptom.
///
/// Idempotent, and called by rc_font_load, so the host never has to think
/// about it.
int rc_init() {
  static bool started = false;
  if (!started) {
    display.begin();
    g_renderer.begin();
    started = true;
  }
  return 1;
}

/// Select the reader geometry. The framebuffer allocation does not move;
/// GfxRenderer::begin() only refreshes its dimensions and write stride.
/// 0 is X4/X4 Pro (800x480 panel), 1 is X3 (792x528 panel).
int rc_set_device(int device_id) {
  rc_init();
  uint16_t width = 0;
  uint16_t height = 0;
  if (device_id == 0) {
    width = HalDisplay::X4_WIDTH;
    height = HalDisplay::X4_HEIGHT;
  } else if (device_id == 1) {
    width = HalDisplay::X3_WIDTH;
    height = HalDisplay::X3_HEIGHT;
  } else {
    return 0;
  }
  if (display.getDisplayWidth() == width &&
      display.getDisplayHeight() == height) {
    return 1;
  }
  display.setGeometry(width, height);
  g_renderer.begin();
  g_marginsResolved = false;
  g_lines.clear();
  return 1;
}

/// Parse a .cpfont from memory. The bytes are borrowed for the lifetime of the
/// font, so the caller must keep them alive -- which the Python side does by
/// leaving them in the module's own linear memory.
int rc_font_load(const uint8_t* data, int length) {
  rc_init();
  // Unregister before loading, not after a successful one: a failed load has
  // to leave nothing behind either. rc_probe_text_width and
  // rc_probe_line_height go straight to the renderer with no g_loaded check,
  // so a family left registered against a font whose bytes the host has since
  // freed would be read through. Passing a null image is how the host says
  // "drop it" (RenderModule.release).
  g_renderer.removeFont(kFontId);
  rc::setFontImage(data, static_cast<uint32_t>(length));
  g_loaded = g_font.load("<memory>");
  if (!g_loaded) return 0;
  // insertFont is a map::insert, so it is a *no-op* for a fontId already
  // present and only logs about it (GfxRenderer.cpp:176-181) -- and our
  // LOG_ERR is a no-op stub, so it says nothing at all. Hence the removeFont
  // above: the host reloads a font per render into a module it keeps for the
  // life of the process, and without it the family captured by the *first*
  // load would stick forever, drawing every later italic in roman glyphs.
  //
  // Both registrations are needed: insertFont gives the renderer the family to
  // measure and draw with, registerSdCardFont lets it reach back into the lazy
  // loader for glyphs that are not in the mini table yet.
  g_renderer.insertFont(kFontId, EpdFontFamily(g_font.getEpdFont(0),
                                               g_font.getEpdFont(1),
                                               g_font.getEpdFont(2),
                                               g_font.getEpdFont(3)));
  g_renderer.registerSdCardFont(kFontId, &g_font);
  return 1;
}

int rc_font_advance_y() {
  const EpdFontData* data = fontData();
  return data ? data->advanceY : 0;
}

int rc_font_ascender() {
  const EpdFontData* data = fontData();
  return data ? data->ascender : 0;
}

int rc_font_descender() {
  const EpdFontData* data = fontData();
  return data ? data->descender : 0;
}

/// Fetch the glyphs for this text into RAM. Returns how many could not be
/// found (0 on full success), as SdCardFont::prewarm does.
///
/// This is not an optimisation, it is a precondition: SdCardFont keeps the
/// glyph table on storage and builds an in-RAM mini table of only what has been
/// asked for (SdCardFont.cpp:1085). Nothing can be drawn before it is warmed.
int rc_font_prewarm(const char* utf8) {
  if (!g_loaded) return -1;
  return g_font.prewarm(utf8);
}

/// What the renderer thinks the panel is. Zero means begin() never ran, which
/// makes drawPixel's bounds check reject every pixel silently.
int rc_probe_panel_width() { rc_init(); return g_renderer.getScreenWidth(); }
int rc_probe_panel_height() { rc_init(); return g_renderer.getScreenHeight(); }

/// getWriteRows() is _stripActive ? _stripRows : panelHeight, so this says
/// which branch getWriteTarget took: panelHeight means the normal path, 0
/// means the renderer thinks a grayscale strip is active and every pixel is
/// being culled against a zero-height band.
int rc_probe_write_rows() { rc_init(); return g_renderer.getWriteRows(); }

/// The renderer's write target versus the buffer we hand back to the host.
/// If these differ, drawing lands somewhere nobody reads.
int rc_probe_write_target() {
  rc_init();
  return static_cast<int>(reinterpret_cast<uintptr_t>(
      g_renderer.getWriteTarget()));
}
int rc_probe_framebuffer_ptr() {
  rc_init();
  return static_cast<int>(reinterpret_cast<uintptr_t>(
      display.getFrameBuffer()));
}

/// Draw one pixel through the renderer, to separate "the text path found
/// nothing" from "the pixel path writes nowhere".
int rc_probe_pixel(int x, int y) {
  rc_init();
  display.clearScreen(0xFF);
  g_renderer.setRenderMode(GfxRenderer::BW);
  g_renderer.drawPixel(x, y, true);
  return 1;
}

/// The renderer's own view of the registered font, for diagnosing a blank
/// render: this goes through fontMap, so 0 means insertFont did not take.
int rc_probe_line_height() { return g_renderer.getLineHeight(kFontId); }

/// Width the renderer measures for a string, in pixels. 0 for text it cannot
/// draw, which distinguishes "no glyphs" from "drew somewhere invisible".
int rc_probe_text_width(const char* utf8) {
  return g_renderer.getTextWidth(kFontId, utf8);
}

/// The logical page you draw into: 480x800 portrait. GfxRenderer rotates this
/// onto the landscape panel, so these are not the framebuffer's dimensions.
int rc_screen_width() { rc_init(); return g_renderer.getScreenWidth(); }
int rc_screen_height() { rc_init(); return g_renderer.getScreenHeight(); }

/// The framebuffer's own layout: 800x480, one bit per pixel, MSB first. The
/// host has to un-rotate this to get the page back (phyX = y,
/// phyY = panelHeight - 1 - x, from GfxRenderer.cpp:218).
int rc_panel_width() { return display.getDisplayWidth(); }
int rc_panel_height() { return display.getDisplayHeight(); }
int rc_framebuffer_size() { return display.getBufferSize(); }
const uint8_t* rc_framebuffer() { return display.getFrameBuffer(); }

/// Draw text into the framebuffer in one render mode, and leave it there.
///
/// `mode` is GfxRenderer::RenderMode: 0=BW, 1=GRAYSCALE_LSB, 2=GRAYSCALE_MSB.
/// The caller renders the same text once per mode and reads the framebuffer
/// back each time; composing the three planes into grey levels is the host's
/// job, exactly as HalDisplay.cpp:195 does it in the simulator.
///
/// `clear` is the byte to fill with first: 0xFF (white) for the BW pass, 0x00
/// for the grey planes, which mark rather than paint.
int rc_render(const char* utf8, int x, int y, int mode, int clear) {
  if (!g_loaded) return 0;
  // Warming is a precondition, not an optimisation: the glyph table lives in
  // the file and only prewarm puts glyphs in RAM (SdCardFont.cpp:1085).
  g_font.prewarm(utf8);
  display.clearScreen(static_cast<uint8_t>(clear));
  g_renderer.setRenderMode(static_cast<GfxRenderer::RenderMode>(mode));
  g_renderer.drawText(kFontId, x, y, utf8);
  return 1;
}

/// Glyphs currently in RAM, summed from the mini interval table.
///
/// Deliberately *not* the font's coverage: that lives in the file header and is
/// what fontbuild.style_metrics reports. This counts what prewarm has fetched,
/// which is the number that says whether the lazy path is working.
int rc_font_cached_glyphs() {
  const EpdFontData* data = fontData();
  if (!data || !data->intervals) return 0;
  int total = 0;
  for (uint32_t i = 0; i < data->intervalCount; ++i) {
    total += static_cast<int>(data->intervals[i].last -
                              data->intervals[i].first + 1);
  }
  return total;
}


/// Lay out and draw a whole page. Paragraphs are separated by '\n'. Returns
/// the number of lines drawn, which is fewer than the text holds when the page
/// filled up.
///
/// `mode` and `clear` are the render core's: 0=BW 1=GRAYSCALE_LSB
/// 2=GRAYSCALE_MSB, cleared to 0xFF for the BW pass and 0x00 for the planes.
/// Call it once per mode and compose the framebuffers, exactly as with
/// rc_render.
int rc_page_render(const char* utf8, const uint8_t* styles, int styles_length,
                   int mode, int clear) {
  if (!g_loaded) return -1;
  rc_init();
  resolveMargins();
  g_styles = styles;
  g_stylesLength = styles ? styles_length : 0;
  g_styleIndex = 0;
  // prewarm's default styleMask is 0x0F (SdCardFont.h:46), so every face the
  // font carries is warmed already -- styles need nothing extra here.
  g_font.prewarm(utf8);
  display.clearScreen(static_cast<uint8_t>(clear));
  g_renderer.setRenderMode(static_cast<GfxRenderer::RenderMode>(mode));

  const int width = g_renderer.getScreenWidth() - g_marginLeft - g_marginRight;
  const int bottom = g_renderer.getScreenHeight() - g_marginBottom;
  const int measured = g_renderer.getLineHeight(kFontId, g_lineCompression);
  // A font whose line height comes back 0 would otherwise stack every line
  // on the one before it, 1px apart, all the way to the bottom margin.
  // Negative, not 0: the host cannot tell "drew nothing" from "could not
  // draw" otherwise, and a blank page is exactly the plausible-looking wrong
  // answer this module exists to avoid.
  if (measured <= 0) return -1;
  const int advance = measured;
  const int paragraphGap = g_extraParagraphSpacing ? advance / 2 : 0;
  if (width <= 0) return -1;

  int y = g_marginTop;
  int drawn = 0;
  std::string paragraph;
  for (const char* p = utf8;; ++p) {
    if (*p != '\n' && *p != '\0') {
      paragraph.push_back(*p);
      continue;
    }
    if (!paragraph.empty()) {
      std::vector<std::shared_ptr<TextBlock>> lines;
      layoutInto(lines, paragraph.c_str(), width);
      for (const auto& line : lines) {
        // The advance, not the ascender. getTextHeight returns the ascender
        // (GfxRenderer.cpp:2019-2026), and testing against that fits a line
        // the device would push to the next page -- its rule is
        // `nextY + getLineHeight(...) > viewportHeight`
        // (ChapterHtmlSlimParser.cpp:1675-1684). With advanceY 31 against an
        // ascender of 21, a third of margin/size combinations gained a line
        // the reader never shows, with its descenders in the bottom margin.
        if (y + advance > bottom) return drawn;
        line->render(g_renderer, kFontId, g_marginLeft, y);
        y += advance;
        ++drawn;
      }
      y += paragraphGap;
      paragraph.clear();
    }
    if (*p == '\0') break;
  }
  return drawn;
}

/// Lay one paragraph out at `width` pixels. Returns the number of lines, or
/// -1 with no font loaded. The lines stay readable via rc_layout_line until
/// the next call.
int rc_layout_paragraph(const char* utf8, int width) {
  if (!g_loaded) return -1;
  rc_init();
  // A diagnostic entry point: it always measures the roman.
  g_styles = nullptr;
  g_stylesLength = 0;
  g_styleIndex = 0;
  // Warming is a precondition, not an optimisation: layout measures glyph
  // advances, and SdCardFont has none in RAM until asked (SdCardFont.cpp:1085).
  g_font.prewarm(utf8);
  g_lines.clear();
  layoutInto(g_lines, utf8, width);
  return static_cast<int>(g_lines.size());
}

/// The words of one laid-out line, space-joined, into a caller's buffer.
/// Returns bytes written, or -1 for an index that was never laid out.
int rc_layout_line(int index, char* out, int cap) {
  if (index < 0 || index >= static_cast<int>(g_lines.size()) || cap <= 0) {
    return -1;
  }
  const TextBlock& line = *g_lines[index];
  int written = 0;
  for (uint16_t i = 0; i < line.wordCount(); ++i) {
    const int length = static_cast<int>(line.wordTextLen(i));
    if (i > 0 && written < cap) out[written++] = ' ';
    for (int j = 0; j < length && written < cap; ++j) {
      out[written++] = line.wordText(i)[j];
    }
  }
  return written;
}

/// Every layout knob at once, so a page is never drawn with half a spec.
///
/// margin      the reader's screenMargin, 5..40, added to the panel's own
///             viewable insets (EpubReaderActivity.cpp:1195-1199)
/// alignment   CssTextAlign: 0 Justify, 1 Left, 2 Center, 3 Right
/// hyphenation whether words may split across lines. Off is not merely "no
///             hyphens": it changes where every line breaks.
/// line_compression_x100  95 tight / 100 normal / 110 wide, the device's own
///             values for SD card fonts (CrossPointSettings.cpp:268-280)
///
/// Anti-aliasing is deliberately not here. It decides how many passes the
/// *host* runs, not how the module lays a page out -- see rc_page_render.
int rc_page_set_spec(int margin, int alignment, int hyphenation,
                     int extra_paragraph_spacing, int line_compression_x100) {
  rc_init();
  g_screenMargin = margin;
  applyMargins();
  g_alignment = static_cast<CssTextAlign>(alignment);
  g_hyphenation = hyphenation != 0;
  g_extraParagraphSpacing = extra_paragraph_spacing != 0;
  g_lineCompression = static_cast<float>(line_compression_x100) / 100.0f;
  return 1;
}

/// Back to what the device ships with (CrossPointSettings.h:217, 239-246):
/// SCREEN_MARGIN_MIN, justified, hyphenation off, extra paragraph spacing on,
/// normal line spacing.
int rc_page_reset_spec() {
  return rc_page_set_spec(kScreenMargin,
                          static_cast<int>(CssTextAlign::Justify), 0, 1, 100);
}

/// Which language's Liang patterns to hyphenate with -- "ru", "en", "de" and
/// the rest of lib/Epub/Epub/hyphenation/generated/.
///
/// The reader sets this from the book's own OPF metadata
/// (Section.cpp:410), and Section is not in this module -- so without this
/// call the hyphenator has no patterns and silently finds no breaks at all.
/// It is a knob here rather than a constant because hyphenation is
/// language-specific and the sample text is whatever you paste in.
int rc_page_set_language(const char* language) {
  Hyphenator::setPreferredLanguage(language ? language : "");
  return 1;
}

// Exercises the C++ standard library, which is the part a bare clang cannot
// build without a wasm sysroot. Kept as a build canary rather than deleted:
// if the toolchain ever loses libc++, this fails before anything subtler does.
int rc_probe_sum(const uint8_t* data, int length) {
  std::vector<uint8_t> copy(data, data + length);
  int total = 0;
  for (uint8_t value : copy) total += value;
  return total;
}

int rc_abi_version() { return 1; }

}  // extern "C"
