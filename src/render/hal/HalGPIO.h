// Deliberately empty.
//
// GfxRenderer.cpp includes <HalGPIO.h> but uses no symbol from it -- verified
// by grepping the translation unit for GPIO. and HalGPIO::. The real header
// drags in InputManager and Arduino's full surface, none of which a renderer
// needs, so the stub supplies nothing rather than pretending to.
//
// If a future firmware makes GfxRenderer actually touch GPIO, the build breaks
// here with an undefined symbol, which is the right way to find out.
#pragma once
