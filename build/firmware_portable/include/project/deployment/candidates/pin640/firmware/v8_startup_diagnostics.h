#ifndef V8_STARTUP_DIAGNOSTICS_H
#define V8_STARTUP_DIAGNOSTICS_H

#include <stdint.h>

/* Read these symbols in XSCT/Vitis to locate a board startup failure. */
typedef enum {
    V8_STARTUP_RESET = 0u,
    V8_STARTUP_MODEL_LOAD = 1u,
    V8_STARTUP_MODEL_READY = 2u,
    V8_STARTUP_DMA_INIT = 3u,
    V8_STARTUP_DMA_INIT_DONE = 4u,
    V8_STARTUP_DMA_RESET = 5u,
    V8_STARTUP_PL_PROBE = 6u,
    V8_STARTUP_PL_READY = 7u,
    V8_STARTUP_NETWORK_START = 8u,
    V8_STARTUP_READY = 9u
} V8StartupStage;

/* Error numbers are local to the stage currently reported above. */
enum {
    V8_STARTUP_ERROR_NONE = 0u,
    V8_STARTUP_ERROR_DMA_RESET = 1u,
    V8_STARTUP_ERROR_PL_PROBE = 2u,
    V8_STARTUP_ERROR_ABORT_CONTROL = 3u,
    V8_STARTUP_ERROR_CONTROL_ABORT_WRITE = 4u
};

extern volatile uint32_t v8_startup_stage;
extern volatile uint32_t v8_startup_error;

#endif
