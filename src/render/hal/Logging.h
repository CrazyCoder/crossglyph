// The firmware's LOG_* macros, as no-ops.
//
// Not for tidiness: logPrintf reaches stdout, and pulling the printf machinery
// into the link would grow the module and add host imports for output nobody
// reads. Errors surface as return values through the C API instead.
#pragma once

#define LOG_ERR(...) ((void)0)
#define LOG_WRN(...) ((void)0)
#define LOG_INF(...) ((void)0)
#define LOG_DBG(...) ((void)0)
#define LOG_VRB(...) ((void)0)
