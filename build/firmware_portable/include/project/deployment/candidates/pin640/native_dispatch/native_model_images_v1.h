#ifndef Z100_NATIVE_MODEL_IMAGES_V1_H
#define Z100_NATIVE_MODEL_IMAGES_V1_H
#include "native_platform_memory_v1.h"

/* Produced only by prepare_z100_native_model_embedding.py. Source images
 * remain immutable ordinary rodata, separate from the reserved destinations.
 * Session preparation independently verifies source and destination SHA256. */
extern const uint8_t zn_native_embedded_parameters_v1[3122432];
extern const uint8_t zn_native_embedded_parameters_v1_end[];
extern const uint8_t zn_native_embedded_directory_v1[5568];
extern const uint8_t zn_native_embedded_directory_v1_end[];
#endif
