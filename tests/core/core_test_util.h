/* SPDX-License-Identifier: MIT */
/* Shared helpers for the CPU-core black-box C tests (synthetic grids only). */
#ifndef NCI_CORE_TEST_UTIL_H
#define NCI_CORE_TEST_UTIL_H
#include "nci_api.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

extern int g_failures;
extern int g_checks;

#define CHECK(cond, ...)                                                        \
    do {                                                                        \
        g_checks++;                                                             \
        if (!(cond)) {                                                          \
            g_failures++;                                                       \
            fprintf(stderr, "%s:%d: CHECK(%s) failed: ", __FILE__, __LINE__,    \
                    #cond);                                                     \
            fprintf(stderr, __VA_ARGS__);                                       \
            fputc('\n', stderr);                                                \
        }                                                                       \
    } while (0)

int test_report(const char *name);

/* Grid with caller-owned buffers; all outputs pre-filled with sentinels. */
typedef struct {
    int64_t n[3];
    int64_t npts;
    int diag;
    double *rho, *rdg, *srho, *lam2, *grad, *hess;
    uint8_t *flags;
    nci_tile_stats_v1 stats;
    nci_tile_v1 tile;
} grid_t;

#define SENTINEL_BITS 0x5A5A5A5A5A5A5A5AULL
#define FLAG_SENTINEL 0xA5u

nci_options_v1 make_options(int mode, int threads, double rho_min, double neg_tol);
void grid_init(grid_t *g, int64_t nx, int64_t ny, int64_t nz, const double jinv[9],
               const int periodic[3], int diag);
void grid_free(grid_t *g);
void grid_fill_sentinels(grid_t *g);
int grid_outputs_untouched(const grid_t *g);
int64_t lin(const grid_t *g, int64_t i, int64_t j, int64_t k);
int grid_eval(void *ctx, grid_t *g, char *err, size_t errlen);
int eval_with(const nci_options_v1 *o, grid_t *g, char *err, size_t errlen);

/* Offsets of the 61-point stencil: {-2..2}^3 with at most two nonzero parts. */
int in_stencil61(int dx, int dy, int dz);

/* Expected bits 0-3 of every point, computed independently of the library. */
void expected_flags03(const grid_t *g, const int periodic[3], double rho_min,
                      uint8_t *out);

/* Checks flags/stats consistency and NaN/finite output rules for every point. */
void check_flag_semantics(const grid_t *g, const int periodic[3], double rho_min,
                          int status);

/* 3x3 helpers (row-major) in long double. */
void inv3(const long double a[9], long double out[9]);
void eig3_sym_closed(const long double h6[6], long double lam[3]);
long double rdg_const(void);

uint64_t bits_of(double x);
int same_bits(double a, double b);
double lcg_uniform(uint64_t *state);

#endif
