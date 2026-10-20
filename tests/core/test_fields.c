/* SPDX-License-Identifier: MIT */
/* Black-box field tests on small synthetic grids (<= 17^3): analytic FD4
 * exactness, exact discrete Fourier symbols on periodic axes, 61-point
 * dependency, negative-tail invalidation, low/zero densities, flags, stats,
 * thread determinism and numeric-failure reporting. */
#include "core_test_util.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

static const double RHO_MIN = 1e-8;

/* ---------- quartic polynomial on a skewed, left-handed grid ---------- */

static long double poly_rho(const long double r[3]) {
    long double x = r[0], y = r[1], z = r[2];
    return 2.0L + 0.10L * x - 0.20L * y + 0.05L * z + 0.30L * x * x - 0.10L * y * y +
           0.20L * z * z + 0.15L * x * y - 0.05L * x * z + 0.10L * y * z + 0.02L * x * x * x -
           0.03L * x * y * z + 0.04L * y * y * z - 0.01L * z * z * z + 0.010L * x * x * x * x -
           0.020L * y * y * y * y + 0.015L * x * x * z * z + 0.005L * x * y * y * y;
}

static void poly_grad_hess(const long double r[3], long double g[3], long double h[6]) {
    long double x = r[0], y = r[1], z = r[2];
    g[0] = 0.10L + 0.60L * x + 0.15L * y - 0.05L * z + 0.06L * x * x - 0.03L * y * z +
           0.04L * x * x * x + 0.03L * x * z * z + 0.005L * y * y * y;
    g[1] = -0.20L - 0.20L * y + 0.15L * x + 0.10L * z - 0.03L * x * z + 0.08L * y * z -
           0.08L * y * y * y + 0.015L * x * y * y;
    g[2] = 0.05L + 0.40L * z - 0.05L * x + 0.10L * y - 0.03L * x * y + 0.04L * y * y -
           0.03L * z * z + 0.03L * x * x * z;
    h[0] = 0.60L + 0.12L * x + 0.12L * x * x + 0.03L * z * z;
    h[1] = -0.20L + 0.08L * z - 0.24L * y * y + 0.03L * x * y;
    h[2] = 0.40L - 0.06L * z + 0.03L * x * x;
    h[3] = 0.15L - 0.03L * z + 0.015L * y * y;
    h[4] = -0.05L - 0.03L * y + 0.06L * x * z;
    h[5] = 0.10L - 0.03L * x + 0.08L * y;
}

/* J columns are the physical step vectors a, b, c (bohr). */
static const long double JSTEP[9] = {0.15L, 0.03L, -0.01L, 0.01L, 0.14L, 0.02L,
                                     -0.02L, 0.01L, -0.16L};

static void grid_position(const grid_t *g, int64_t i, int64_t j, int64_t k, long double r[3]) {
    long double q[3] = {(long double)i - 0.5L * (long double)(g->n[0] - 1),
                        (long double)j - 0.5L * (long double)(g->n[1] - 1),
                        (long double)k - 0.5L * (long double)(g->n[2] - 1)};
    for (int a = 0; a < 3; ++a)
        r[a] = JSTEP[3 * a] * q[0] + JSTEP[3 * a + 1] * q[1] + JSTEP[3 * a + 2] * q[2];
}

static void poly_grid(grid_t *g, int diag) {
    long double ji[9];
    double jd[9];
    inv3(JSTEP, ji);
    for (int i = 0; i < 9; ++i) jd[i] = (double)ji[i];
    const int fin[3] = {0, 0, 0};
    grid_init(g, 13, 12, 11, jd, fin, diag);
    for (int64_t i = 0; i < 13; ++i)
        for (int64_t j = 0; j < 12; ++j)
            for (int64_t k = 0; k < 11; ++k) {
                long double r[3];
                grid_position(g, i, j, k, r);
                g->rho[lin(g, i, j, k)] = (double)poly_rho(r);
            }
}

static void test_polynomial(void) {
    grid_t g;
    poly_grid(&g, 1);
    const int fin[3] = {0, 0, 0};
    nci_options_v1 o = make_options(NCI_DIAGNOSTIC, 4, RHO_MIN, 0.0);
    char err[256];
    int st = eval_with(&o, &g, err, sizeof err);
    CHECK(st == NCI_OK, "polynomial status %d: %s", st, err);
    check_flag_semantics(&g, fin, RHO_MIN, st);
    CHECK(g.stats.valid_points == 9 * 8 * 7, "interior count %lld", (long long)g.stats.valid_points);

    long double C = rdg_const();
    double eg = 0, eh = 0, el = 0, er = 0;
    int sign_bad = 0;
    for (int64_t i = 2; i < 11; ++i)
        for (int64_t j = 2; j < 10; ++j)
            for (int64_t k = 2; k < 9; ++k) {
                int64_t p = lin(&g, i, j, k);
                long double r[3], ge[3], he[6], le[3];
                grid_position(&g, i, j, k, r);
                poly_grad_hess(r, ge, he);
                eig3_sym_closed(he, le);
                for (int c = 0; c < 3; ++c) eg = fmax(eg, fabs((double)(g.grad[3 * p + c] - ge[c])));
                for (int c = 0; c < 6; ++c) eh = fmax(eh, fabs((double)(g.hess[6 * p + c] - he[c])));
                el = fmax(el, fabs((double)(g.lam2[p] - le[1])));
                long double gn = sqrtl(ge[0] * ge[0] + ge[1] * ge[1] + ge[2] * ge[2]);
                long double rho = poly_rho(r);
                long double s = gn / (C * powl(rho, 4.0L / 3.0L));
                er = fmax(er, fabs((double)((g.rdg[p] - s) / s)));
                if (fabsl(le[1]) > 1e-6L && (g.lam2[p] > 0) != (le[1] > 0)) sign_bad++;
            }
    printf("polynomial: max|dg|=%.3e max|dH|=%.3e max|dl2|=%.3e max rel dRDG=%.3e\n", eg, eh, el,
           er);
    CHECK(eg < 1e-11, "gradient error %.3e", eg);
    CHECK(eh < 1e-9, "Hessian error %.3e", eh);
    CHECK(el < 1e-9, "lambda2 error %.3e", el);
    CHECK(er < 1e-11, "RDG relative error %.3e", er);
    CHECK(sign_bad == 0, "%d lambda2 sign disagreements", sign_bad);
    grid_free(&g);
}

/* ---------- exact discrete Fourier symbols on periodic axes ---------- */

static long double symS(long double w) { return (8.0L * sinl(w) - sinl(2.0L * w)) / 6.0L; }
static long double symT(long double w) { return (15.0L - 16.0L * cosl(w) + cosl(2.0L * w)) / 6.0L; }

typedef struct {
    int ax1, ax2, m1, m2;
    long double amp, ph1, ph2;
} mode_t;

static const mode_t MODES[3] = {{0, 1, 1, 2, 0.40L, 0.3L, -0.7L},
                                {1, 2, 1, 3, -0.30L, 1.1L, 0.2L},
                                {0, 2, 3, 1, 0.25L, -0.4L, 0.9L}};

static void fourier_expected(const grid_t *g, int64_t idx[3], long double *rho, long double gq[3],
                             long double hq[3][3]) {
    *rho = 3.0L;
    memset(gq, 0, 3 * sizeof(long double));
    memset(hq, 0, 9 * sizeof(long double));
    long double pi = acosl(-1.0L);
    for (int m = 0; m < 3; ++m) {
        const mode_t *md = &MODES[m];
        long double w1 = 2.0L * pi * md->m1 / (long double)g->n[md->ax1];
        long double w2 = 2.0L * pi * md->m2 / (long double)g->n[md->ax2];
        long double u = w1 * (long double)idx[md->ax1] + md->ph1;
        long double v = w2 * (long double)idx[md->ax2] + md->ph2;
        long double A = md->amp;
        *rho += A * cosl(u) * cosl(v);
        gq[md->ax1] += -A * symS(w1) * sinl(u) * cosl(v);
        gq[md->ax2] += -A * symS(w2) * cosl(u) * sinl(v);
        hq[md->ax1][md->ax1] += -A * symT(w1) * cosl(u) * cosl(v);
        hq[md->ax2][md->ax2] += -A * symT(w2) * cosl(u) * cosl(v);
        long double mix = A * symS(w1) * symS(w2) * sinl(u) * sinl(v);
        hq[md->ax1][md->ax2] += mix;
        hq[md->ax2][md->ax1] += mix;
    }
}

static void test_fourier(const int periodic[3]) {
    static const double JI[9] = {2.0, 0.3, -0.1, 0.2, 2.5, 0.4, -0.3, 0.1, 1.8};
    grid_t g;
    grid_init(&g, 16, 10, 12, JI, periodic, 1);
    for (int64_t i = 0; i < 16; ++i)
        for (int64_t j = 0; j < 10; ++j)
            for (int64_t k = 0; k < 12; ++k) {
                int64_t idx[3] = {i, j, k};
                long double rho, gq[3], hq[3][3];
                fourier_expected(&g, idx, &rho, gq, hq);
                g.rho[lin(&g, i, j, k)] = (double)rho;
            }
    nci_options_v1 o = make_options(NCI_DIAGNOSTIC, 5, RHO_MIN, 0.0);
    char err[256];
    int st = eval_with(&o, &g, err, sizeof err);
    check_flag_semantics(&g, periodic, RHO_MIN, st);
    double eg = 0, eh = 0, el = 0;
    int64_t checked = 0;
    for (int64_t i = 0; i < 16; ++i)
        for (int64_t j = 0; j < 10; ++j)
            for (int64_t k = 0; k < 12; ++k) {
                int64_t p = lin(&g, i, j, k);
                if (g.flags[p] & 31u) continue;
                int64_t idx[3] = {i, j, k};
                long double rho, gq[3], hq[3][3], gr[3], hr[3][3], h6[6], le[3];
                fourier_expected(&g, idx, &rho, gq, hq);
                for (int a = 0; a < 3; ++a) {
                    gr[a] = 0;
                    for (int q = 0; q < 3; ++q) gr[a] += (long double)JI[3 * q + a] * gq[q];
                }
                for (int a = 0; a < 3; ++a)
                    for (int b = 0; b < 3; ++b) {
                        hr[a][b] = 0;
                        for (int q = 0; q < 3; ++q)
                            for (int s = 0; s < 3; ++s)
                                hr[a][b] += (long double)JI[3 * q + a] * hq[q][s] *
                                            (long double)JI[3 * s + b];
                    }
                h6[0] = hr[0][0]; h6[1] = hr[1][1]; h6[2] = hr[2][2];
                h6[3] = hr[0][1]; h6[4] = hr[0][2]; h6[5] = hr[1][2];
                eig3_sym_closed(h6, le);
                for (int c = 0; c < 3; ++c) eg = fmax(eg, fabs((double)(g.grad[3 * p + c] - gr[c])));
                for (int c = 0; c < 6; ++c) eh = fmax(eh, fabs((double)(g.hess[6 * p + c] - h6[c])));
                el = fmax(el, fabs((double)(g.lam2[p] - le[1])));
                checked++;
            }
    int64_t expect_valid = 1;
    for (int d = 0; d < 3; ++d) expect_valid *= periodic[d] ? g.n[d] : g.n[d] - 4;
    printf("fourier periodic=(%d,%d,%d): %lld points, max|dg|=%.3e max|dH|=%.3e max|dl2|=%.3e\n",
           periodic[0], periodic[1], periodic[2], (long long)checked, eg, eh, el);
    CHECK(st == NCI_OK, "fourier status %d: %s", st, err);
    CHECK(checked == expect_valid, "valid points %lld, expected %lld", (long long)checked,
          (long long)expect_valid);
    CHECK(eg < 1e-12, "gradient error %.3e", eg);
    CHECK(eh < 1e-11, "Hessian error %.3e", eh);
    CHECK(el < 1e-11, "lambda2 error %.3e", el);
    grid_free(&g);
}

/* ---------- the exact 61-point dependency set ---------- */

static void test_dependency(void) {
    static const double JI[9] = {2.0, 0.3, -0.1, 0.2, 2.5, 0.4, -0.3, 0.1, 1.8};
    const int per[3] = {1, 1, 1};
    grid_t g;
    grid_init(&g, 9, 9, 9, JI, per, 1);
    uint64_t seed = 12345;
    for (int64_t p = 0; p < g.npts; ++p) g.rho[p] = 1.0 + lcg_uniform(&seed);
    nci_options_v1 o = make_options(NCI_DIAGNOSTIC, 2, RHO_MIN, 0.0);
    void *ctx = NULL;
    nci_context_create_v1(&o, &ctx, NULL, 0);
    int st = grid_eval(ctx, &g, NULL, 0);
    check_flag_semantics(&g, per, RHO_MIN, st);
    int64_t c = lin(&g, 4, 4, 4);
    double base[12];
    memcpy(base, &g.grad[3 * c], 3 * sizeof(double));
    memcpy(base + 3, &g.hess[6 * c], 6 * sizeof(double));
    base[9] = g.lam2[c];
    base[10] = g.rdg[c];
    base[11] = g.srho[c];
    int mismatches = 0, dependent = 0;
    for (int dx = -2; dx <= 2; ++dx)
        for (int dy = -2; dy <= 2; ++dy)
            for (int dz = -2; dz <= 2; ++dz) {
                int64_t q = lin(&g, 4 + dx, 4 + dy, 4 + dz);
                double keep = g.rho[q];
                g.rho[q] = keep * (1.0 + 1e-3);
                grid_eval(ctx, &g, NULL, 0);
                g.rho[q] = keep;
                double now[12];
                memcpy(now, &g.grad[3 * c], 3 * sizeof(double));
                memcpy(now + 3, &g.hess[6 * c], 6 * sizeof(double));
                now[9] = g.lam2[c];
                now[10] = g.rdg[c];
                now[11] = g.srho[c];
                int changed = memcmp(now, base, sizeof base) != 0;
                dependent += changed;
                if (changed != in_stencil61(dx, dy, dz)) {
                    if (mismatches++ < 5)
                        fprintf(stderr, "  offset (%d,%d,%d): changed=%d\n", dx, dy, dz, changed);
                }
            }
    CHECK(mismatches == 0 && dependent == 61, "dependency set: %d dependent offsets, %d mismatches",
          dependent, mismatches);
    nci_context_destroy_v1(ctx, NULL, 0);
    grid_free(&g);
}

/* ---------- negative tails, zero and low densities ---------- */

static void background(grid_t *g) {
    for (int64_t i = 0; i < g->n[0]; ++i)
        for (int64_t j = 0; j < g->n[1]; ++j)
            for (int64_t k = 0; k < g->n[2]; ++k)
                g->rho[lin(g, i, j, k)] = 1.0 + 0.3 * sin(0.9 * (double)i + 0.2) *
                                                    cos(0.5 * (double)j) +
                                          0.1 * cos(0.7 * (double)k);
}

static void test_negative_tail(void) {
    static const double JI[9] = {3.0, 0.2, 0.0, -0.1, 2.7, 0.3, 0.2, 0.0, 3.1};
    const int per[3] = {1, 0, 0};
    grid_t g, h;
    grid_init(&g, 13, 13, 13, JI, per, 1);
    grid_init(&h, 13, 13, 13, JI, per, 1);
    background(&g);
    struct { int i, j, k; double v; } special[] = {
        {0, 6, 6, -5e-7},  /* wraps across the periodic x boundary */
        {6, 1, 6, -1e-7},  /* clipped by the finite y boundary */
        {8, 8, 3, -1e-6},  /* exactly -tolerance: accepted */
        {5, 5, 9, 0.0},    /* zero sample: legal, never invalidates neighbours */
        {10, 6, 6, 1e-12}, /* low positive sample: still participates */
    };
    for (size_t s = 0; s < sizeof special / sizeof special[0]; ++s)
        g.rho[lin(&g, special[s].i, special[s].j, special[s].k)] = special[s].v;
    memcpy(h.rho, g.rho, (size_t)g.npts * sizeof(double));
    for (int s = 0; s < 3; ++s) h.rho[lin(&h, special[s].i, special[s].j, special[s].k)] = 0.5;

    nci_options_v1 o = make_options(NCI_DIAGNOSTIC, 3, RHO_MIN, 1e-6);
    char err[256];
    int st = eval_with(&o, &g, err, sizeof err);
    check_flag_semantics(&g, per, RHO_MIN, st);
    CHECK(st == NCI_OK, "negative-tail status %d: %s", st, err);
    int64_t n3 = g.stats.bit_counts[3];
    printf("negative tail: %lld points carry STENCIL_INVALID\n", (long long)n3);
    CHECK(n3 > 61 && n3 < 3 * 61, "union of three (clipped) stencils: %lld", (long long)n3);
    CHECK(g.flags[lin(&g, 0, 6, 6)] == (NCI_NONPOSITIVE_RHO | NCI_STENCIL_INVALID),
          "negative centre carries bits 1 and 3");
    CHECK(g.flags[lin(&g, 12, 6, 6)] & NCI_STENCIL_INVALID, "periodic wrap of the stencil");
    CHECK(g.flags[lin(&g, 5, 5, 9)] == NCI_NONPOSITIVE_RHO, "zero sample: only bit 1");
    CHECK(g.flags[lin(&g, 5, 5, 8)] == NCI_LAMBDA_SCI_UNCERTAIN ||
              g.flags[lin(&g, 5, 5, 8)] == (NCI_LAMBDA_SCI_UNCERTAIN | NCI_LAMBDA_NUM_UNCERTAIN),
          "neighbour of a zero sample stays valid");
    CHECK(g.flags[lin(&g, 10, 6, 6)] == NCI_LOW_RHO, "low positive sample: only bit 2");
    CHECK((g.flags[lin(&g, 9, 6, 6)] & 31u) == 0, "neighbour of a low sample stays valid");

    st = eval_with(&o, &h, err, sizeof err);
    CHECK(st == NCI_OK, "replacement run status %d", st);
    int leaks = 0;
    for (int64_t p = 0; p < g.npts; ++p) {
        if (g.flags[p] & 31u) continue;
        if (!same_bits(g.rdg[p], h.rdg[p]) || !same_bits(g.lam2[p], h.lam2[p]) ||
            memcmp(&g.hess[6 * p], &h.hess[6 * p], 6 * sizeof(double)) != 0)
            leaks++;
    }
    CHECK(leaks == 0, "%d valid points depend on samples outside their 61-point stencil", leaks);

    /* low neighbours participate: changing the low sample changes a neighbour */
    double before[6];
    int64_t nb = lin(&g, 9, 6, 6);
    memcpy(before, &g.hess[6 * nb], sizeof before);
    g.rho[lin(&g, 10, 6, 6)] = 5e-12;
    eval_with(&o, &g, err, sizeof err);
    CHECK(memcmp(before, &g.hess[6 * nb], sizeof before) != 0, "low sample participates");
    grid_free(&g);
    grid_free(&h);
}

static void test_rho_min_edge(void) {
    static const double JI[9] = {3, 0, 0, 0, 3, 0, 0, 0, 3};
    const int per[3] = {1, 1, 1};
    grid_t g;
    grid_init(&g, 8, 7, 6, JI, per, 0);
    background(&g);
    const double rmin = 0.5;
    g.rho[lin(&g, 1, 1, 1)] = rmin;
    g.rho[lin(&g, 4, 4, 4)] = nextafter(rmin, 1.0);
    nci_options_v1 o = make_options(NCI_FULL, 2, rmin, 0.0);
    char err[256];
    int st = eval_with(&o, &g, err, sizeof err);
    check_flag_semantics(&g, per, rmin, st);
    CHECK(g.flags[lin(&g, 1, 1, 1)] == NCI_LOW_RHO, "rho == rho_min is LOW_RHO");
    CHECK((g.flags[lin(&g, 4, 4, 4)] & 31u) == 0, "rho just above rho_min is valid");
    grid_free(&g);
}

/* ---------- determinism over thread counts ---------- */

static uint64_t fnv1a(uint64_t h, const void *data, size_t n) {
    const unsigned char *b = data;
    for (size_t i = 0; i < n; ++i) h = (h ^ b[i]) * 1099511628211ULL;
    return h;
}

static void test_threads(void) {
    const int counts[5] = {1, 2, 3, 8, 16};
    grid_t ref;
    poly_grid(&ref, 1);
    nci_options_v1 o = make_options(NCI_DIAGNOSTIC, 1, RHO_MIN, 0.0);
    eval_with(&o, &ref, NULL, 0);
    {
        size_t n = (size_t)ref.npts;
        uint64_t h = 1469598103934665603ULL;
        h = fnv1a(h, ref.rdg, n * 8);
        h = fnv1a(h, ref.srho, n * 8);
        h = fnv1a(h, ref.lam2, n * 8);
        h = fnv1a(h, ref.grad, 3 * n * 8);
        h = fnv1a(h, ref.hess, 6 * n * 8);
        h = fnv1a(h, ref.flags, n);
        /* compare across build types/compilers to detect value-changing flags */
        printf("polynomial outputs FNV-1a: %016llx\n", (unsigned long long)h);
    }
    for (int c = 1; c < 5; ++c) {
        grid_t g;
        poly_grid(&g, 1);
        o.omp_threads = counts[c];
        eval_with(&o, &g, NULL, 0);
        size_t n = (size_t)g.npts;
        int same = memcmp(g.rdg, ref.rdg, n * 8) == 0 && memcmp(g.srho, ref.srho, n * 8) == 0 &&
                   memcmp(g.lam2, ref.lam2, n * 8) == 0 &&
                   memcmp(g.grad, ref.grad, 3 * n * 8) == 0 &&
                   memcmp(g.hess, ref.hess, 6 * n * 8) == 0 && memcmp(g.flags, ref.flags, n) == 0 &&
                   memcmp(&g.stats, &ref.stats, sizeof g.stats) == 0;
        CHECK(same, "outputs with %d threads differ from 1 thread", counts[c]);
        grid_free(&g);
    }
    /* FULL mode writes the same fields as DIAGNOSTIC */
    grid_t f;
    poly_grid(&f, 0);
    o = make_options(NCI_FULL, 7, RHO_MIN, 0.0);
    eval_with(&o, &f, NULL, 0);
    size_t n = (size_t)f.npts;
    CHECK(memcmp(f.rdg, ref.rdg, n * 8) == 0 && memcmp(f.lam2, ref.lam2, n * 8) == 0 &&
              memcmp(f.srho, ref.srho, n * 8) == 0 && memcmp(f.flags, ref.flags, n) == 0,
          "FULL and DIAGNOSTIC fields differ");
    grid_free(&f);
    grid_free(&ref);
}

/* ---------- exact zero and pure-rounding lambda2 ---------- */

static void test_zero_lambda2(void) {
    static const double JI[9] = {4, 0, 0, 0, 4, 0, 0, 0, 4};
    const int fin[3] = {0, 0, 0};
    grid_t g;
    grid_init(&g, 9, 9, 9, JI, fin, 1);
    for (int64_t i = 0; i < 9; ++i)
        for (int64_t j = 0; j < 9; ++j)
            for (int64_t k = 0; k < 9; ++k) {
                double x = 0.25 * (double)(i - 4);
                g.rho[lin(&g, i, j, k)] = 2.0 + 0.3 * x * x;
            }
    nci_options_v1 o = make_options(NCI_DIAGNOSTIC, 2, RHO_MIN, 0.0);
    int st = eval_with(&o, &g, NULL, 0);
    check_flag_semantics(&g, fin, RHO_MIN, st);
    int bad = 0;
    for (int64_t p = 0; p < g.npts; ++p) {
        if (g.flags[p] & 31u) continue;
        if (!(g.lam2[p] == 0.0 && same_bits(g.srho[p], 0.0) &&
              (g.flags[p] & NCI_LAMBDA_NUM_UNCERTAIN)))
            bad++;
    }
    CHECK(st == NCI_OK && bad == 0, "lambda2 == 0 => signedrho +0 and bit 5 (%d bad)", bad);

    /* affine density: lambda2 is pure rounding noise and must be uncertain */
    long double ji[9];
    double jd[9];
    inv3(JSTEP, ji);
    for (int i = 0; i < 9; ++i) jd[i] = (double)ji[i];
    grid_t a;
    grid_init(&a, 9, 9, 9, jd, fin, 0);
    for (int64_t i = 0; i < 9; ++i)
        for (int64_t j = 0; j < 9; ++j)
            for (int64_t k = 0; k < 9; ++k) {
                long double r[3];
                grid_position(&a, i, j, k, r);
                a.rho[lin(&a, i, j, k)] = (double)(2.0L + 0.1L * r[0] + 0.2L * r[1] - 0.05L * r[2]);
            }
    o = make_options(NCI_FULL, 2, RHO_MIN, 0.0);
    st = eval_with(&o, &a, NULL, 0);
    check_flag_semantics(&a, fin, RHO_MIN, st);
    CHECK(a.stats.bit_counts[5] == a.stats.valid_points && a.stats.valid_points == 125,
          "affine density: every valid point is LAMBDA_NUM_UNCERTAIN (%lld of %lld)",
          (long long)a.stats.bit_counts[5], (long long)a.stats.valid_points);
    grid_free(&a);
    grid_free(&g);
}

/* ---------- random field: lambda2 consistent with the exported Hessian ---------- */

static void test_random_consistency(void) {
    static const double JI[9] = {2.2, -0.4, 0.3, 0.5, 1.9, -0.2, 0.1, 0.6, 2.4};
    const int per[3] = {0, 1, 0};
    grid_t g;
    grid_init(&g, 9, 8, 7, JI, per, 1);
    uint64_t seed = 777;
    for (int64_t p = 0; p < g.npts; ++p) g.rho[p] = 0.05 + lcg_uniform(&seed);
    nci_options_v1 o = make_options(NCI_DIAGNOSTIC, 4, RHO_MIN, 0.0);
    int st = eval_with(&o, &g, NULL, 0);
    check_flag_semantics(&g, per, RHO_MIN, st);
    double worst = 0;
    long double C = rdg_const();
    double wr = 0;
    int skipped = 0;
    for (int64_t p = 0; p < g.npts; ++p) {
        if (g.flags[p] & 31u) continue;
        long double h6[6], le[3];
        for (int c = 0; c < 6; ++c) h6[c] = g.hess[6 * p + c];
        eig3_sym_closed(h6, le);
        long double hn = fabsl(le[0]) > fabsl(le[2]) ? fabsl(le[0]) : fabsl(le[2]);
        /* the acos reference loses ~sqrt(eps) near repeated roots: skip those */
        if (le[1] - le[0] < 1e-4L * hn || le[2] - le[1] < 1e-4L * hn) {
            skipped++;
            continue;
        }
        worst = fmax(worst, (double)(fabsl(g.lam2[p] - le[1]) / hn));
        long double gx = g.grad[3 * p], gy = g.grad[3 * p + 1], gz = g.grad[3 * p + 2];
        long double s = sqrtl(gx * gx + gy * gy + gz * gz) /
                        (C * powl((long double)g.rho[p], 4.0L / 3.0L));
        wr = fmax(wr, (double)fabsl((g.rdg[p] - s) / s));
    }
    printf("random field: max |lambda2 - closed form|/|H|_2 = %.3e, max rel RDG = %.3e "
           "(%d near-degenerate points skipped)\n",
           worst, wr, skipped);
    CHECK(worst < 1e-13, "Jacobi vs closed form %.3e", worst);
    CHECK(wr < 1e-14, "RDG from exported gradient %.3e", wr);
    grid_free(&g);
}

/* ---------- numeric failure and all-invalid grids ---------- */

static void test_numeric_failure(void) {
    static const double JI[9] = {2, 0, 0, 0, 2, 0, 0, 0, 2};
    const int per[3] = {1, 1, 1};
    grid_t g;
    grid_init(&g, 9, 9, 9, JI, per, 1);
    g.rho[lin(&g, 4, 4, 4)] = 1.5e308;
    nci_options_v1 o = make_options(NCI_DIAGNOSTIC, 2, RHO_MIN, 0.0);
    char err[256];
    int st = eval_with(&o, &g, err, sizeof err);
    check_flag_semantics(&g, per, RHO_MIN, st);
    printf("numeric failure: %lld failing points: %s\n", (long long)g.stats.numeric_failures, err);
    CHECK(st == NCI_NUMERIC_FAILURE, "status %d", st);
    CHECK(g.flags[lin(&g, 4, 4, 4)] == NCI_POINT_NUMERIC_FAILURE, "overflowing centre fails");
    CHECK(strstr(err, "numeric failure") != NULL, "message: %s", err);
    CHECK(g.stats.valid_points > 0, "other points still evaluated");
    grid_free(&g);
}

static void test_all_invalid(void) {
    static const double JI[9] = {2, 0, 0, 0, 2, 0, 0, 0, 2};
    const int fin[3] = {0, 0, 0};
    grid_t g;
    grid_init(&g, 5, 5, 5, JI, fin, 1);
    nci_options_v1 o = make_options(NCI_DIAGNOSTIC, 2, 10.0, 0.0);
    char err[256];
    int st = eval_with(&o, &g, err, sizeof err);
    check_flag_semantics(&g, fin, 10.0, st);
    CHECK(st == NCI_INVALID_INPUT, "all-invalid status %d", st);
    CHECK(g.stats.valid_points == 0 && g.stats.invalid_points == 125 &&
              g.stats.bit_counts[0] == 124 && g.stats.bit_counts[2] == 125,
          "all-invalid stats");
    o.rho_min = RHO_MIN;
    st = eval_with(&o, &g, err, sizeof err);
    check_flag_semantics(&g, fin, RHO_MIN, st);
    CHECK(st == NCI_OK && g.stats.valid_points == 1, "5^3 finite grid has exactly one valid point");
    grid_free(&g);
}

/* Finite g/H/eigen followed by unrepresentable RDG must clear diagnostics. */
static void test_rdg_overflow_diagnostics(void) {
    static const double JI[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1};
    const int finite[3] = {0, 0, 0};
    grid_t g;
    grid_init(&g, 5, 5, 5, JI, finite, 1);
    for (int64_t p = 0; p < g.npts; ++p) g.rho[p] = 1.0;
    const int64_t p = lin(&g, 2, 2, 2);
    g.rho[p] = 1e-250;
    g.rho[lin(&g, 3, 2, 2)] = 2.0;
    nci_options_v1 o = make_options(NCI_DIAGNOSTIC, 1, 1e-260, 0.0);
    char err[256];
    int st = eval_with(&o, &g, err, sizeof err);
    CHECK(st == NCI_NUMERIC_FAILURE, "RDG overflow status %d: %s", st, err);
    CHECK(g.flags[p] == NCI_POINT_NUMERIC_FAILURE, "RDG overflow has only bit4");
    CHECK(isnan(g.rdg[p]) && isnan(g.srho[p]) && isnan(g.lam2[p]), "RDG overflow formal fields NaN");
    for (int c = 0; c < 3; ++c) CHECK(isnan(g.grad[3*p+c]), "RDG overflow grad[%d] NaN", c);
    for (int c = 0; c < 6; ++c) CHECK(isnan(g.hess[6*p+c]), "RDG overflow hess[%d] NaN", c);
    check_flag_semantics(&g, finite, o.rho_min, st);
    grid_free(&g);
}

static void test_rdg_intermediate_overflow(void) {
    static const double JI[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1};
    const int finite[3] = {0, 0, 0};
    grid_t g;
    grid_init(&g, 5, 5, 5, JI, finite, 1);
    for (int64_t p = 0; p < g.npts; ++p) g.rho[p] = 1.0/64.0;
    const double a=ldexp(3.0,1017);
    g.rho[lin(&g,0,2,2)]=0.0;
    g.rho[lin(&g,1,2,2)]=0.0;
    g.rho[lin(&g,3,2,2)]=a;
    g.rho[lin(&g,4,2,2)]=16.0*a;
    nci_options_v1 o=make_options(NCI_DIAGNOSTIC,1,1e-8,0.0);
    char err[256];
    int st=eval_with(&o,&g,err,sizeof err);
    const int64_t p=lin(&g,2,2,2);
    const double expected=1.1621759632369337941e308;
    CHECK(st==NCI_OK,"representable RDG after intermediate overflow status %d: %s",st,err);
    CHECK((g.flags[p]&31u)==0,"representable RDG centre is valid, flags %u",g.flags[p]);
    CHECK(isfinite(g.rdg[p]) && fabs(g.rdg[p]/expected-1.0)<1e-14,"representable RDG %.17g",g.rdg[p]);
    CHECK(g.grad[3*p]==-ldexp(1.0,1018),"large finite gradient retained");
    CHECK(g.hess[6*p]==-5.0/128.0,"finite Hessian retained");
    CHECK(g.stats.valid_points==1 && g.stats.numeric_failures==0,"one valid point, no false bit4");
    check_flag_semantics(&g,finite,o.rho_min,st);
    grid_free(&g);
}

int main(void) {
    const int all_per[3] = {1, 1, 1}, mixed_per[3] = {1, 0, 1};
    test_polynomial();
    test_fourier(all_per);
    test_fourier(mixed_per);
    test_dependency();
    test_negative_tail();
    test_rho_min_edge();
    test_threads();
    test_zero_lambda2();
    test_random_consistency();
    test_numeric_failure();
    test_rdg_overflow_diagnostics();
    test_rdg_intermediate_overflow();
    test_all_invalid();
    return test_report("test_fields");
}
