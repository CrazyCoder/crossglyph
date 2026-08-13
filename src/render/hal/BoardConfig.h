// The sliver of BoardConfig that GfxRenderer touches.
//
// The real header (freeink-sdk/libs/hardware/BoardConfig/include/BoardConfig.h)
// pulls in driver/gpio.h and esp_rom_sys.h, so it cannot be compiled off the
// device. GfxRenderer only ever reads BoardConfig::ACTIVE.viewableInsets, so
// that is all this supplies.
//
// Values are the SDK's own defaults (BoardConfig.h:599-604): the margin the
// panel's bezel hides, which the renderer keeps text out of.
#pragma once
#include <cstdint>

namespace BoardConfig {

struct ViewableInsets {
  uint8_t top = 9;
  uint8_t right = 3;
  uint8_t bottom = 3;
  uint8_t left = 3;
};

struct BoardProfile {
  ViewableInsets viewableInsets = {};
};

inline BoardProfile ACTIVE = {};

}  // namespace BoardConfig
