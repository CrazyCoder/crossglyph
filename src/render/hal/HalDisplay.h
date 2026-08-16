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

  // One fixed allocation sized for the larger X3 framebuffer. Changing the
  // selected device changes only the active dimensions; the address stays
  // stable, which is what GfxRenderer expects after begin().
  static constexpr uint16_t X4_WIDTH = 800;
  static constexpr uint16_t X4_HEIGHT = 480;
  static constexpr uint16_t X3_WIDTH = 792;
  static constexpr uint16_t X3_HEIGHT = 528;
  static constexpr uint32_t MAX_BUFFER_SIZE =
      X3_WIDTH / 8 * X3_HEIGHT;
  // GfxRenderer uses these to initialize members before begin() replaces them
  // with the active geometry.
  static constexpr uint16_t DISPLAY_WIDTH = X4_WIDTH;
  static constexpr uint16_t DISPLAY_HEIGHT = X4_HEIGHT;
  static constexpr uint16_t DISPLAY_WIDTH_BYTES = DISPLAY_WIDTH / 8;
  static constexpr uint32_t BUFFER_SIZE =
      DISPLAY_WIDTH_BYTES * DISPLAY_HEIGHT;

  static uint8_t* storage() {
    static uint8_t buffer[MAX_BUFFER_SIZE];
    return buffer;
  }

  // Keep mutable geometry in function-local statics for the same reason as
  // the framebuffer: this inline HalDisplay is included by api.cpp and by the
  // firmware renderer. Member state has been observed to split between those
  // translation units in the wasm build, leaving the renderer on stale
  // dimensions with no error.
  static uint16_t& widthRef() {
    static uint16_t width = X4_WIDTH;
    return width;
  }
  static uint16_t& heightRef() {
    static uint16_t height = X4_HEIGHT;
    return height;
  }

  // The *panel* is landscape-native: X4 and X4 Pro are 800x480, X3 is
  // 792x528 (crosspoint-simulator/src/EInkDisplay.h:28-32). The portrait page
  // GfxRenderer exposes is the panel rotated into its default Portrait
  // orientation.
  void setGeometry(uint16_t width, uint16_t height) {
    widthRef() = width;
    heightRef() = height;
  }

  void begin() {}
  void begin(bool) {}

  uint8_t* getFrameBuffer() const { return storage(); }
  void clearScreen(uint8_t color = 0xFF) const {
    std::memset(storage(), color, getBufferSize());
  }

  uint16_t getDisplayWidth() const { return widthRef(); }
  uint16_t getDisplayHeight() const { return heightRef(); }
  uint16_t getDisplayWidthBytes() const { return widthRef() / 8; }
  uint32_t getBufferSize() const {
    return static_cast<uint32_t>(getDisplayWidthBytes()) * heightRef();
  }

  bool isInverted() const { return false; }
  void setInverted(bool) {}
  bool toggleInverted() { return false; }

  // Lent in place, as on device: the allocation is never freed, so returning
  // it is a no-op. Only releaseFrameBufferForBuild uses this, which the
  // preview never calls.
  uint8_t* lendFrameBufferStorage(uint32_t* sizeOut) {
    if (sizeOut) *sizeOut = getBufferSize();
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
  // (turnOffScreen, lut, factoryMode), as lib/hal/HalDisplay.h has it. The
  // last two arrived with the factory grayscale LUT for cover images; nothing
  // here shows one, but the signature has to match or GfxRenderer will not
  // compile against this stub.
  void displayGrayBuffer(bool = false, const unsigned char* = nullptr,
                         bool = false) {}
  void grayscaleRevert() {}
  void writeGrayscalePlaneStrip(bool, const uint8_t*, int, int) {}
  bool supportsStripGrayscale() const { return false; }
  void presentIfNeeded() {}
  bool shouldQuit() const { return false; }

};

inline HalDisplay display;
