/* SPDX-License-Identifier: MIT */
#include "core_test_util.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

int g_failures = 0;
int g_checks = 0;

int test_report(const char *name) {
    printf("%s: %d checks, %d failures\n", name, g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}

uint64_t bits_of(double x) {
    uint64_t u;
    memcpy(&u, &x, sizeof u);
    return u;
}

int same_bits(double a, double b) { return bits_of(a) == bits_of(b); }

double lcg_uniform(uint64_t *state) {
    *state = *state * 6364136223846793005ULL + 1442695040888963407ULL;
    return (double)(*state >> 11) * (1.0 / 9007199254740992.0);
}

nci_options_v1 make_options(int mode, int threads, double rho_min, double neg_tol) {
    nci_options_v1 o;
    memset(&o, 0, sizeof o);
    o.abi_version = NCI_ABI_VERSION;
    o.struct_bytes = (int32_t)sizeof o;
    o.backend = NCI_CPU;
    o.output_mode = mode;
    o.omp_threads = threads;
    o.reserved = 0;
    o.rho_min = rho_min;
    o.negative_tolerance = neg_tol;
    return o;
}

static void *xmalloc(size_t bytes) {
    void *p = malloc(bytes ? bytes : 1);
    if (!p) {
        fprintf(stderr, "test allocation of %zu bytes failed\n", bytes);
        exit(2);
    }
    return p;
}

void grid_init(grid_t *g, int64_t nx, int64_t ny, int64_t nz, const double jinv[9],
               const int periodic[3], int diag) {
    memset(g, 0, sizeof *g);
    g->n[0] = nx;
    g->n[1] = ny;
    g->n[2] = nz;
    g->npts = nx * ny * nz;
    g->diag = diag;
    size_t n = (size_t)g->npts;
    g->rho = xmalloc(n * sizeof(double));
    g->rdg = xmalloc(n * sizeof(double));
    g->srho = xmalloc(n * sizeof(double));
    g->lam2 = xmalloc(n * sizeof(double));
    g->flags = xmalloc(n);
    if (diag) {
        g->grad = xmalloc(3 * n * sizeof(double));
        g->hess = xmalloc(6 * n * sizeof(double));
    }
    for (size_t p = 0; p < n; ++p) g->rho[p] = 1.0;

    nci_tile_v1 *t = &g->tile;
    memset(t, 0, sizeof *t);
    t->abi_version = NCI_ABI_VERSION;
    t->struct_bytes = (int32_t)sizeof *t;
    for (int d = 0; d < 3; ++d) {
        t->global_n[d] = g->n[d];
        t->tile_start[d] = 0;
        t->tile_count[d] = g->n[d];
        t->input_origin[d] = 0;
        t->input_shape[d] = g->n[d];
        t->periodic[d] = periodic[d];
    }
    t->input_strides[0] = ny * nz;
    t->input_strides[1] = nz;
    t->input_strides[2] = 1;
    memcpy(t->j_inv, jinv, 9 * sizeof(double));
    t->reserved = 0;
    t->rho_capacity = g->npts;
    t->field_capacity = g->npts;
    t->flags_capacity = g->npts;
    t->grad_capacity = diag ? 3 * g->npts : 0;
    t->hess_capacity = diag ? 6 * g->npts : 0;
    grid_fill_sentinels(g);
}

void grid_free(grid_t *g) {
    free(g->rho);
    free(g->rdg);
    free(g->srho);
    free(g->lam2);
    free(g->flags);
    free(g->grad);
    free(g->hess);
    memset(g, 0, sizeof *g);
}

static void fill_bits(double *a, size_t n) {
    uint64_t s = SENTINEL_BITS;
    for (size_t i = 0; i < n; ++i) memcpy(&a[i], &s, sizeof s);
}

static int all_bits(const double *a, size_t n) {
    for (size_t i = 0; i < n; ++i)
        if (bits_of(a[i]) != SENTINEL_BITS) return 0;
    return 1;
}

void grid_fill_sentinels(grid_t *g) {
    size_t n = (size_t)g->npts;
    fill_bits(g->rdg, n);
    fill_bits(g->srho, n);
    fill_bits(g->lam2, n);
    if (g->diag) {
        fill_bits(g->grad, 3 * n);
        fill_bits(g->hess, 6 * n);
    }
    memset(g->flags, FLAG_SENTINEL, n);
    memset(&g->stats, 0x5A, sizeof g->stats);
}

int grid_outputs_untouched(const grid_t *g) {
    size_t n = (size_t)g->npts;
    if (!all_bits(g->rdg, n) || !all_bits(g->srho, n) || !all_bits(g->lam2, n)) return 0;
    if (g->diag && (!all_bits(g->grad, 3 * n) || !all_bits(g->hess, 6 * n))) return 0;
    for (size_t i = 0; i < n; ++i)
        if (g->flags[i] != FLAG_SENTINEL) return 0;
    const unsigned char *s = (const unsigned char *)&g->stats;
    for (size_t i = 0; i < sizeof g->stats; ++i)
        if (s[i] != 0x5A) return 0;
    return 1;
}

int64_t lin(const grid_t *g, int64_t i, int64_t j, int64_t k) {
    return (i * g->n[1] + j) * g->n[2] + k;
}

int grid_eval(void *ctx, grid_t *g, char *err, size_t errlen) {
    size_t n = (size_t)g->npts;
    double *copy = xmalloc(n * sizeof(double));
    memcpy(copy, g->rho, n * sizeof(double));
    int st = nci_eval_tile_f64_v1(ctx, &g->tile, g->rho, g->rdg, g->srho, g->lam2,
                                  g->diag ? g->grad : NULL, g->diag ? g->hess : NULL,
                                  g->flags, &g->stats, err, errlen);
    CHECK(memcmp(copy, g->rho, n * sizeof(double)) == 0, "input density was modified");
    free(copy);
    return st;
}

int eval_with(const nci_options_v1 *o, grid_t *g, char *err, size_t errlen) {
    void *ctx = NULL;
    char cerr[256];
    int st = nci_context_create_v1(o, &ctx, cerr, sizeof cerr);
    CHECK(st == NCI_OK && ctx != NULL, "context creation failed: %d %s", st, cerr);
    if (st != NCI_OK) return -1;
    st = grid_eval(ctx, g, err, errlen);
    int ds = nci_context_destroy_v1(ctx, cerr, sizeof cerr);
    CHECK(ds == NCI_OK, "destroy failed: %d %s", ds, cerr);
    return st;
}

int in_stencil61(int dx, int dy, int dz) {
    if (dx < -2 || dx > 2 || dy < -2 || dy > 2 || dz < -2 || dz > 2) return 0;
    return (dx != 0) + (dy != 0) + (dz != 0) <= 2;
}

void expected_flags03(const grid_t *g, const int periodic[3], double rho_min, uint8_t *out) {
    const int64_t *n = g->n;
    for (int64_t i = 0; i < n[0]; ++i)
        for (int64_t j = 0; j < n[1]; ++j)
            for (int64_t k = 0; k < n[2]; ++k) {
                int64_t idx[3] = {i, j, k};
                uint8_t f = 0;
                for (int d = 0; d < 3; ++d)
                    if (!periodic[d] && (idx[d] < 2 || idx[d] > n[d] - 3)) f |= NCI_BOUNDARY;
                double c = g->rho[lin(g, i, j, k)];
                if (!(c > 0.0))
                    f |= NCI_NONPOSITIVE_RHO;
                else if (c <= rho_min)
                    f |= NCI_LOW_RHO;
                for (int dx = -2; dx <= 2; ++dx)
                    for (int dy = -2; dy <= 2; ++dy)
                        for (int dz = -2; dz <= 2; ++dz) {
                            if (!in_stencil61(dx, dy, dz)) continue;
                            int64_t q[3] = {i + dx, j + dy, k + dz};
                            int inside = 1;
                            for (int d = 0; d < 3; ++d) {
                                if (periodic[d])
                                    q[d] = ((q[d] % n[d]) + n[d]) % n[d];
                                else if (q[d] < 0 || q[d] >= n[d])
                                    inside = 0;
                            }
                            if (inside && g->rho[lin(g, q[0], q[1], q[2])] < 0.0)
                                f |= NCI_STENCIL_INVALID;
                        }
                out[lin(g, i, j, k)] = f;
            }
}

void check_flag_semantics(const grid_t *g, const int periodic[3], double rho_min, int status) {
    size_t n = (size_t)g->npts;
    uint8_t *exp03 = xmalloc(n);
    expected_flags03(g, periodic, rho_min, exp03);
    int64_t bits[7] = {0}, valid = 0;
    int bad03 = 0, badnan = 0, badvalid = 0;
    for (size_t p = 0; p < n; ++p) {
        uint8_t f = g->flags[p];
        for (int b = 0; b < 7; ++b)
            if (f & (1u << b)) bits[b]++;
        if ((f & 31u) == 0) valid++;
        if ((f & 0x80u) || (f & 15u) != exp03[p]) {
            if (bad03++ < 5)
                fprintf(stderr, "  point %zu: flags 0x%02x, expected bits0-3 0x%02x\n", p, f,
                        exp03[p]);
        }
        if ((f & 31u) != 0) {
            int ok = isnan(g->rdg[p]) && isnan(g->srho[p]) && isnan(g->lam2[p]);
            if (f & NCI_POINT_NUMERIC_FAILURE) {
                /* numeric failure: never combined with bits 0-3, 5 or 6 */
                ok = ok && f == NCI_POINT_NUMERIC_FAILURE && exp03[p] == 0;
            } else {
                ok = ok && (f & 0x70u) == 0;
                if (g->diag)
                    for (int c = 0; c < 3; ++c) ok = ok && isnan(g->grad[3 * p + c]);
                if (g->diag)
                    for (int c = 0; c < 6; ++c) ok = ok && isnan(g->hess[6 * p + c]);
            }
            if (!ok && badnan++ < 5)
                fprintf(stderr, "  point %zu: invalid point outputs/bits wrong (flags 0x%02x)\n",
                        p, f);
        } else {
            double r = g->rho[p], l = g->lam2[p], s = g->srho[p];
            int ok = (f & NCI_LAMBDA_SCI_UNCERTAIN) && isfinite(g->rdg[p]) && g->rdg[p] >= 0.0 &&
                     isfinite(l) && isfinite(s);
            if (l > 0.0)
                ok = ok && same_bits(s, r);
            else if (l < 0.0)
                ok = ok && same_bits(s, -r);
            else
                ok = ok && same_bits(s, 0.0);
            if (fabs(l) <= 1e-12) ok = ok && (f & NCI_LAMBDA_NUM_UNCERTAIN);
            if (g->diag) {
                for (int c = 0; c < 3; ++c) ok = ok && isfinite(g->grad[3 * p + c]);
                for (int c = 0; c < 6; ++c) ok = ok && isfinite(g->hess[6 * p + c]);
                double hf = 0.0;
                for (int c = 0; c < 6; ++c) hf += g->hess[6 * p + c] * g->hess[6 * p + c];
                hf = sqrt(hf);
                if (fabs(l) > 1e-9 * (1.0 + hf)) ok = ok && !(f & NCI_LAMBDA_NUM_UNCERTAIN);
            }
            if (!ok && badvalid++ < 5)
                fprintf(stderr, "  point %zu: valid point semantics wrong (flags 0x%02x)\n", p, f);
        }
    }
    CHECK(bad03 == 0, "%d points with wrong bits 0-3", bad03);
    CHECK(badnan == 0, "%d invalid points with wrong outputs", badnan);
    CHECK(badvalid == 0, "%d valid points with wrong outputs", badvalid);
    CHECK(g->stats.total_points == g->npts, "total_points %lld", (long long)g->stats.total_points);
    CHECK(g->stats.valid_points == valid, "valid_points %lld vs %lld",
          (long long)g->stats.valid_points, (long long)valid);
    CHECK(g->stats.invalid_points == g->npts - valid, "invalid_points %lld",
          (long long)g->stats.invalid_points);
    CHECK(g->stats.numeric_failures == bits[4], "numeric_failures %lld vs %lld",
          (long long)g->stats.numeric_failures, (long long)bits[4]);
    for (int b = 0; b < 7; ++b)
        CHECK(g->stats.bit_counts[b] == bits[b], "bit_counts[%d] %lld vs %lld", b,
              (long long)g->stats.bit_counts[b], (long long)bits[b]);
    CHECK(bits[6] == valid, "bit 6 must be set exactly on numerically valid points");
    int expect_status = bits[4] > 0 ? NCI_NUMERIC_FAILURE : (valid == 0 ? NCI_INVALID_INPUT : NCI_OK);
    CHECK(status == expect_status, "status %d, expected %d", status, expect_status);
    free(exp03);
}

void inv3(const long double a[9], long double o[9]) {
    long double c00 = a[4] * a[8] - a[5] * a[7];
    long double c01 = a[5] * a[6] - a[3] * a[8];
    long double c02 = a[3] * a[7] - a[4] * a[6];
    long double det = a[0] * c00 + a[1] * c01 + a[2] * c02;
    o[0] = c00 / det;
    o[1] = (a[2] * a[7] - a[1] * a[8]) / det;
    o[2] = (a[1] * a[5] - a[2] * a[4]) / det;
    o[3] = c01 / det;
    o[4] = (a[0] * a[8] - a[2] * a[6]) / det;
    o[5] = (a[2] * a[3] - a[0] * a[5]) / det;
    o[6] = c02 / det;
    o[7] = (a[1] * a[6] - a[0] * a[7]) / det;
    o[8] = (a[0] * a[4] - a[1] * a[3]) / det;
}

/* Closed-form (trigonometric) eigenvalues, ascending; independent of Jacobi. */
void eig3_sym_closed(const long double h[6], long double lam[3]) {
    long double xx = h[0], yy = h[1], zz = h[2], xy = h[3], xz = h[4], yz = h[5];
    long double p1 = xy * xy + xz * xz + yz * yz;
    if (p1 == 0.0L) {
        long double d[3] = {xx, yy, zz}, t;
        if (d[0] > d[1]) { t = d[0]; d[0] = d[1]; d[1] = t; }
        if (d[1] > d[2]) { t = d[1]; d[1] = d[2]; d[2] = t; }
        if (d[0] > d[1]) { t = d[0]; d[0] = d[1]; d[1] = t; }
        lam[0] = d[0]; lam[1] = d[1]; lam[2] = d[2];
        return;
    }
    long double q = (xx + yy + zz) / 3.0L;
    long double p2 = (xx - q) * (xx - q) + (yy - q) * (yy - q) + (zz - q) * (zz - q) + 2.0L * p1;
    long double p = sqrtl(p2 / 6.0L);
    long double b00 = (xx - q) / p, b11 = (yy - q) / p, b22 = (zz - q) / p;
    long double b01 = xy / p, b02 = xz / p, b12 = yz / p;
    long double detb = b00 * (b11 * b22 - b12 * b12) - b01 * (b01 * b22 - b12 * b02) +
                       b02 * (b01 * b12 - b11 * b02);
    long double r = detb / 2.0L;
    if (r < -1.0L) r = -1.0L;
    if (r > 1.0L) r = 1.0L;
    long double phi = acosl(r) / 3.0L;
    long double pi = acosl(-1.0L);
    lam[2] = q + 2.0L * p * cosl(phi);
    lam[0] = q + 2.0L * p * cosl(phi + 2.0L * pi / 3.0L);
    lam[1] = 3.0L * q - lam[0] - lam[2];
}

long double rdg_const(void) {
    long double pi = acosl(-1.0L);
    return 2.0L * cbrtl(3.0L * pi * pi);
}
