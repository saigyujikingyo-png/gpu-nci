/* SPDX-License-Identifier: MIT */
/* C/Fortran ABI v1 layout cross-check: the library's BIND(C) types (module
 * nci_abi) must agree with include/nci_api.h field by field. */
#include "nci_api.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

_Static_assert(sizeof(nci_options_v1) == 40, "options size");
_Static_assert(sizeof(nci_tile_v1) == 280, "tile size");
_Static_assert(sizeof(nci_tile_stats_v1) == 88, "stats size");
_Static_assert(offsetof(nci_options_v1, rho_min) == 24, "options padding");
_Static_assert(offsetof(nci_tile_v1, j_inv) == 152, "j_inv offset");
_Static_assert(offsetof(nci_tile_v1, periodic) == 224, "periodic offset");
_Static_assert(offsetof(nci_tile_v1, rho_capacity) == 240, "capacity offset");
_Static_assert(offsetof(nci_tile_stats_v1, bit_counts) == 32, "bit_counts offset");

void nci_test_fortran_layout(int64_t out[33], int32_t *nout);
void nci_test_fortran_echo(const nci_options_v1 *o, const nci_tile_v1 *t, nci_tile_stats_v1 *s,
                           int64_t vals[46], int32_t *nvals);

static int failures = 0;
#define EXPECT(c, ...)                                                          \
    do {                                                                        \
        if (!(c)) {                                                             \
            failures++;                                                         \
            fprintf(stderr, __VA_ARGS__);                                       \
            fputc('\n', stderr);                                                \
        }                                                                       \
    } while (0)

static int64_t dbits(double x) {
    int64_t v;
    memcpy(&v, &x, sizeof v);
    return v;
}

int main(void) {
    static const char *names[33] = {
        "sizeof(options)", "abi_version", "struct_bytes", "backend", "output_mode",
        "omp_threads", "reserved", "rho_min", "negative_tolerance", "sizeof(tile)",
        "abi_version", "struct_bytes", "global_n", "tile_start", "tile_count",
        "input_origin", "input_shape", "input_strides", "j_inv", "periodic", "reserved",
        "rho_capacity", "field_capacity", "flags_capacity", "grad_capacity", "hess_capacity",
        "sizeof(stats)", "total_points", "valid_points", "invalid_points", "numeric_failures",
        "bit_counts", "-"};
    const int64_t c_view[32] = {
        sizeof(nci_options_v1), offsetof(nci_options_v1, abi_version),
        offsetof(nci_options_v1, struct_bytes), offsetof(nci_options_v1, backend),
        offsetof(nci_options_v1, output_mode), offsetof(nci_options_v1, omp_threads),
        offsetof(nci_options_v1, reserved), offsetof(nci_options_v1, rho_min),
        offsetof(nci_options_v1, negative_tolerance), sizeof(nci_tile_v1),
        offsetof(nci_tile_v1, abi_version), offsetof(nci_tile_v1, struct_bytes),
        offsetof(nci_tile_v1, global_n), offsetof(nci_tile_v1, tile_start),
        offsetof(nci_tile_v1, tile_count), offsetof(nci_tile_v1, input_origin),
        offsetof(nci_tile_v1, input_shape), offsetof(nci_tile_v1, input_strides),
        offsetof(nci_tile_v1, j_inv), offsetof(nci_tile_v1, periodic),
        offsetof(nci_tile_v1, reserved), offsetof(nci_tile_v1, rho_capacity),
        offsetof(nci_tile_v1, field_capacity), offsetof(nci_tile_v1, flags_capacity),
        offsetof(nci_tile_v1, grad_capacity), offsetof(nci_tile_v1, hess_capacity),
        sizeof(nci_tile_stats_v1), offsetof(nci_tile_stats_v1, total_points),
        offsetof(nci_tile_stats_v1, valid_points), offsetof(nci_tile_stats_v1, invalid_points),
        offsetof(nci_tile_stats_v1, numeric_failures), offsetof(nci_tile_stats_v1, bit_counts)};
    int64_t f_view[33];
    int32_t nout = 0;
    nci_test_fortran_layout(f_view, &nout);
    EXPECT(nout == 32, "Fortran probe reported %d entries", (int)nout);
    for (int i = 0; i < 32 && i < nout; ++i)
        EXPECT(f_view[i] == c_view[i], "%s: Fortran %lld, C %lld", names[i],
               (long long)f_view[i], (long long)c_view[i]);

    nci_options_v1 o;
    nci_tile_v1 t;
    nci_tile_stats_v1 s;
    memset(&o, 0, sizeof o);
    memset(&t, 0, sizeof t);
    memset(&s, 0x77, sizeof s);
    o.abi_version = 11; o.struct_bytes = 12; o.backend = 13; o.output_mode = 14;
    o.omp_threads = 15; o.reserved = 16; o.rho_min = 0.125; o.negative_tolerance = -3.5;
    t.abi_version = 21; t.struct_bytes = 22;
    for (int d = 0; d < 3; ++d) {
        t.global_n[d] = ((int64_t)1 << 40) + 100 + d;
        t.tile_start[d] = -200 - d;
        t.tile_count[d] = 300 + d;
        t.input_origin[d] = -((int64_t)1 << 50) - d;
        t.input_shape[d] = 500 + d;
        t.input_strides[d] = 600 + d;
        t.periodic[d] = 70 + d;
    }
    for (int i = 0; i < 9; ++i) t.j_inv[i] = -1.0 / (i + 3.0);
    t.reserved = 80;
    t.rho_capacity = 900; t.field_capacity = 901; t.flags_capacity = 902;
    t.grad_capacity = 903; t.hess_capacity = INT64_MAX;
    int64_t expect[46], got[46];
    int n = 0;
    expect[n++] = o.abi_version; expect[n++] = o.struct_bytes; expect[n++] = o.backend;
    expect[n++] = o.output_mode; expect[n++] = o.omp_threads; expect[n++] = o.reserved;
    expect[n++] = dbits(o.rho_min); expect[n++] = dbits(o.negative_tolerance);
    expect[n++] = t.abi_version; expect[n++] = t.struct_bytes;
    for (int d = 0; d < 3; ++d) expect[n++] = t.global_n[d];
    for (int d = 0; d < 3; ++d) expect[n++] = t.tile_start[d];
    for (int d = 0; d < 3; ++d) expect[n++] = t.tile_count[d];
    for (int d = 0; d < 3; ++d) expect[n++] = t.input_origin[d];
    for (int d = 0; d < 3; ++d) expect[n++] = t.input_shape[d];
    for (int d = 0; d < 3; ++d) expect[n++] = t.input_strides[d];
    for (int i = 0; i < 9; ++i) expect[n++] = dbits(t.j_inv[i]);
    for (int d = 0; d < 3; ++d) expect[n++] = t.periodic[d];
    expect[n++] = t.reserved;
    expect[n++] = t.rho_capacity; expect[n++] = t.field_capacity; expect[n++] = t.flags_capacity;
    expect[n++] = t.grad_capacity; expect[n++] = t.hess_capacity;
    int32_t nvals = 0;
    nci_test_fortran_echo(&o, &t, &s, got, &nvals);
    EXPECT(nvals == n && n == 46, "echo returned %d values, expected %d", (int)nvals, n);
    for (int i = 0; i < n && i < nvals; ++i)
        EXPECT(got[i] == expect[i], "echo field %d: Fortran %lld, C %lld", i, (long long)got[i],
               (long long)expect[i]);
    EXPECT(s.total_points == 101 && s.valid_points == 102 && s.invalid_points == 103 &&
               s.numeric_failures == 104,
           "stats scalars written by Fortran");
    for (int b = 0; b < 7; ++b)
        EXPECT(s.bit_counts[b] == 200 + b, "stats.bit_counts[%d] = %lld", b,
               (long long)s.bit_counts[b]);
    printf("test_layout: options=%zu tile=%zu stats=%zu, %d failures\n", sizeof o, sizeof t,
           sizeof s, failures);
    return failures == 0 ? 0 : 1;
}
