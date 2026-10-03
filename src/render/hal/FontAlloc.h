// FontAlloc.h from the SDK's FreeInkFont
// (freeink-sdk/libs/font/FreeInkFont/include), on the plain heap.
//
// On the device these prefer PSRAM and fall back to the internal heap, which
// is what the SDK itself does on a host build. The browser has one heap, so
// they are malloc, realloc and free.
#pragma once
#include <stddef.h>
#include <stdlib.h>

static inline void* fiFontMalloc(size_t size) { return malloc(size); }
static inline void* fiFontRealloc(void* ptr, size_t size) {
  return realloc(ptr, size);
}
static inline void fiFontFree(void* ptr) { free(ptr); }
