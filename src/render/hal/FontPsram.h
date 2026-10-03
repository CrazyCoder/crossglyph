// FontPsram.h from the SDK's FreeInkFont
// (freeink-sdk/libs/font/FreeInkFont/include), on the plain heap.
//
// On the device these put font buffers in PSRAM when the board has it. The
// browser has one heap, so the vector is an ordinary one and the arrays are
// nothrow new[], which keeps the contract the firmware relies on: nullptr on
// failure, never an exception.
#pragma once
#include <cstddef>
#include <new>
#include <vector>

namespace freeink {
namespace font {

template <typename T>
using PsramVector = std::vector<T>;

template <typename T>
T* psramNewArray(std::size_t n) {
  return new (std::nothrow) T[n ? n : 1];
}

template <typename T>
void psramDeleteArray(T* p) {
  delete[] p;
}

}  // namespace font
}  // namespace freeink
