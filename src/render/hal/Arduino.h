// The two Arduino-isms the font code reaches for, stubbed.
//
// SdCardFont gets these transitively through the real HalStorage.h on device;
// our stub includes this for the same reason.
#pragma once
#include <cassert>  // GfxRenderer.cpp uses assert(); on device Arduino.h brings it
#include <cstdint>

/// Always zero. SdCardFont uses millis() only to fill stats_.prewarmTotalMs --
/// no control flow depends on it (SdCardFont.cpp:748, 843, 969, 1063) -- and a
/// real clock would mean a clock_time_get import, which is exactly what we are
/// avoiding. Elapsed times come out as 0; nothing reads them here.
inline unsigned long millis() { return 0; }

/// Likewise zero. FontDecompressor uses micros() only for its own timing
/// counters (FontDecompressor.cpp:144-219).
inline unsigned long micros() { return 0; }

class EspClass {
 public:
  /// Generous and constant. This gates the mini-data retention cache
  /// (SdCardFont.cpp:121): reporting plenty means nothing is evicted, which is
  /// what a preview wants and what a desktop host can afford.
  uint32_t getFreeHeap() const { return 8u * 1024 * 1024; }
  uint32_t getMaxAllocHeap() const { return 8u * 1024 * 1024; }

  /// Traps rather than returns. There is nothing to restart in a wasm module,
  /// and the one caller (GfxRenderer.cpp:170) reaches this only when the
  /// framebuffer has gone missing -- carrying on from there would render
  /// garbage and call it a preview. __builtin_trap compiles to `unreachable`,
  /// so this costs no host import.
  [[noreturn]] void restart() const { __builtin_trap(); }
};

inline EspClass ESP;
