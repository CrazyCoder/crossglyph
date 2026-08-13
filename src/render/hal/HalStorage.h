// A HalStorage that serves one in-memory buffer for any path.
//
// SdCardFont reads its .cpfont lazily through Storage.openFileForRead
// (SdCardFont.cpp:515), which is the right design on a device with an SD card
// and a few hundred KB of RAM. Here the file is already in memory, so the whole
// HAL collapses to a cursor over a span -- and the module stays free of WASI
// file imports, which is what lets the same .wasm run in a browser.
#pragma once
#include <cstdint>
#include <cstring>

// The firmware's font code reaches ESP and millis() through this header on
// device, so the stub supplies them the same way.
#include "Arduino.h"

namespace rc {

inline const uint8_t* g_data = nullptr;
inline uint32_t g_length = 0;

/// Point the stub at the bytes to serve. Borrowed, not copied: the caller owns
/// them and must outlive the font.
inline void setFontImage(const uint8_t* data, uint32_t length) {
  g_data = data;
  g_length = length;
}

}  // namespace rc

class HalFile {
 public:
  // void*, like the real HalFile (lib/hal/HalStorage.h:86): Serialization.h
  // reads straight into a std::string's char buffer, and a uint8_t* parameter
  // rejects that.
  int read(void* out, size_t count) {
    if (!rc::g_data || pos_ >= rc::g_length) return 0;
    const uint32_t available = rc::g_length - pos_;
    const uint32_t take = count < available ? static_cast<uint32_t>(count)
                                            : available;
    std::memcpy(out, rc::g_data + pos_, take);
    pos_ += take;
    return static_cast<int>(take);
  }

  /// Present so TextBlock::serialize compiles. The preview never writes: page
  /// caching is Section's job, and Section is not in this module.
  size_t write(const void*, size_t count) { return count; }

  bool seekSet(uint32_t offset) {
    if (offset > rc::g_length) return false;
    pos_ = offset;
    return true;
  }

  uint32_t size() const { return rc::g_length; }
  void close() { pos_ = 0; }
  explicit operator bool() const { return rc::g_data != nullptr; }

 private:
  uint32_t pos_ = 0;
};

class HalStorageStub {
 public:
  /// The path is ignored: there is exactly one image, set by setFontImage.
  bool openFileForRead(const char*, const char*, HalFile& file) {
    if (!rc::g_data) return false;
    file.seekSet(0);
    return true;
  }

  bool exists(const char*) const { return rc::g_data != nullptr; }
  bool ready() const { return rc::g_data != nullptr; }
};

inline HalStorageStub Storage;
