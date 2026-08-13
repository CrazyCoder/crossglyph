// A HalDisplay that is nothing but a framebuffer.
//
// One bit per pixel, MSB first -- the layout GfxRenderer::drawPixel writes and
// the simulator reads (crosspoint-simulator/src/HalDisplay.cpp:153).
//
// The panel-facing half of the interface (refresh waveforms, async display,
// deep sleep, the grayscale plane buffers) is stubbed out. The preview never
// presents anything: it renders the same text three times in the three render
// modes and reads the framebuffer back after each, because drawPixel writes to
// the framebuffer in every mode and the mode only decides which pixels are
// drawn. That is what makes the grayscale plumbing unnecessary here.
#pragma once
#include <cstdint>
#include <cstring>

class HalDisplay {
 public:
  enum RefreshMode { FULL_REFRESH, HALF_REFRESH, FAST_REFRESH };

  // The framebuffer lives in a function-local static rather than a member.
  //
  // As a member of an `inline HalDisplay display;` it came out null in
  // GfxRenderer's translation unit while being valid in api.cpp's -- so
  // GfxRenderer::begin() captured nullptr, every pixel was dropped, and the
  // only symptom was a blank image (the assert that would have caught it is
  // compiled out at -O2). A function-local static inside an inline function is
  // guaranteed to be one object across every translation unit, which is the
  // property actually needed here.
  static uint8_t* storage() {
    static uint8_t buffer[DISPLAY_WIDTH / 8 * DISPLAY_HEIGHT];
    return buffer;
  }

  // The *panel*, which is landscape-native: X4 and X4 Pro are 800x480, X3 is
  // 792x528 (crosspoint-simulator/src/EInkDisplay.h:28-32). The portrait
  // 480x800 page everyone talks about is the logical canvas GfxRenderer
  // produces by rotating onto this in its default Portrait orientation
  // (GfxRenderer.cpp:218 -- phyX = y, phyY = panelHeight - 1 - x).
  //
  // Getting these the wrong way round costs nothing visible: every coordinate
  // still lands inside the buffer, so nothing is clipped and nothing crashes;
  // the page is simply drawn somewhere else.
  static constexpr uint16_t DISPLAY_WIDTH = 800;
  static constexpr uint16_t DISPLAY_HEIGHT = 480;
  static constexpr uint16_t DISPLAY_WIDTH_BYTES = DISPLAY_WIDTH / 8;
  static constexpr uint32_t BUFFER_SIZE = DISPLAY_WIDTH_BYTES * DISPLAY_HEIGHT;

  void begin() {}
  void begin(bool) {}

  uint8_t* getFrameBuffer() const { return storage(); }
  void clearScreen(uint8_t color = 0xFF) const {
    std::memset(storage(), color, BUFFER_SIZE);
  }

  uint16_t getDisplayWidth() const { return DISPLAY_WIDTH; }
  uint16_t getDisplayHeight() const { return DISPLAY_HEIGHT; }
  uint16_t getDisplayWidthBytes() const { return DISPLAY_WIDTH_BYTES; }
  uint32_t getBufferSize() const { return BUFFER_SIZE; }

  bool isInverted() const { return false; }
  void setInverted(bool) {}
  bool toggleInverted() { return false; }

  // Lent in place, as on device: the allocation is never freed, so returning
  // it is a no-op. Only releaseFrameBufferForBuild uses this, which the
  // preview never calls.
  uint8_t* lendFrameBufferStorage(uint32_t* sizeOut) {
    if (sizeOut) *sizeOut = BUFFER_SIZE;
    return storage();
  }
  void returnFrameBufferStorage() {}

  // --- panel-facing: nothing to present to ---------------------------------
  void displayBuffer(RefreshMode = FAST_REFRESH, bool = false) {}
  void displayBufferAsync(RefreshMode = FAST_REFRESH) {}
  void waitRefreshComplete() {}
  bool supportsAsyncRefresh() const { return false; }
  void displayWindow(int, int, int, int) {}
  void refreshDisplay(RefreshMode = FAST_REFRESH, bool = false) {}
  void deepSleep() {}
  void drawImage(const uint8_t*, uint16_t, uint16_t, uint16_t, uint16_t,
                 bool = false) {}
  void drawImageTransparent(const uint8_t*, uint16_t, uint16_t, uint16_t,
                            uint16_t, bool = false) {}

  // --- grayscale: captured by re-rendering instead, see the header note ----
  bool combinesGrayscaleBase() const { return false; }
  void displayGrayscaleBase(RefreshMode = HALF_REFRESH, bool = false) {}
  void preconditionGrayscale() {}
  void preconditionGrayscale(uint16_t, uint16_t, uint16_t, uint16_t) {}
  void copyGrayscaleBuffers(const uint8_t*, const uint8_t*) {}
  void copyGrayscaleLsbBuffers(const uint8_t*) {}
  void copyGrayscaleMsbBuffers(const uint8_t*) {}
  void cleanupGrayscaleBuffers(const uint8_t*) {}
  void displayGrayBuffer(bool = false, RefreshMode = HALF_REFRESH) {}
  void grayscaleRevert() {}
  void writeGrayscalePlaneStrip(bool, const uint8_t*, int, int) {}
  bool supportsStripGrayscale() const { return false; }
  void presentIfNeeded() {}
  bool shouldQuit() const { return false; }
};

inline HalDisplay display;
