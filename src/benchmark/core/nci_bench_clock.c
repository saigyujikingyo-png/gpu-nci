/* SPDX-License-Identifier: MIT */
/* Private P1 benchmark clock (src/benchmark/core/README.md): CLOCK_MONOTONIC
 * in nanoseconds, -1 when clock_gettime fails or the value is not a valid,
 * representable timestamp. Compiled only into the benchmark object
 * collections. No global state, no I/O. */
#define _POSIX_C_SOURCE 199309L
#include <stdint.h>
#include <time.h>

int64_t nci_bench_monotonic_ns(void);

int64_t nci_bench_monotonic_ns(void)
{
  struct timespec ts;
  if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
    return -1;
  }
  if (ts.tv_sec < 0 || ts.tv_nsec < 0 || ts.tv_nsec > 999999999L) {
    return -1;
  }
  if ((int64_t)ts.tv_sec > (INT64_MAX - (int64_t)ts.tv_nsec) / INT64_C(1000000000)) {
    return -1;
  }
  return (int64_t)ts.tv_sec * INT64_C(1000000000) + (int64_t)ts.tv_nsec;
}
