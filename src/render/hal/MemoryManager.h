// MemoryManager.h from the SDK (freeink-sdk/libs/hardware/MemoryManager),
// reduced to what the renderer calls.
//
// On the device, the renderer registers its glyph caches here so that layout
// can ask for them to be emptied when an allocation fails, and then try once
// more. The module's memory grows instead, so an allocation fails only when
// nothing is left at all. Nothing is registered and nothing is evicted.
#pragma once
#include <stddef.h>
#include <stdint.h>

#include <functional>

namespace freeink {

enum class MemPool : uint8_t { Internal, Psram, Default };

struct CacheSink {
  const char* name = nullptr;
  uint8_t priority = 128;
  std::function<size_t(size_t bytesRequested)> evict;
};

class MemoryManager {
 public:
  static MemoryManager& instance() {
    static MemoryManager manager;
    return manager;
  }

  int registerSink(const CacheSink&) { return 0; }
  size_t freeBytes(MemPool = MemPool::Default) const { return 0; }
  bool ensureFree(size_t, MemPool = MemPool::Default) { return false; }
};

}  // namespace freeink
