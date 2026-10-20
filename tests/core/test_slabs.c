/* SPDX-License-Identifier: MIT */
/* M2 X-slab tests through the public C ABI (docs/slab-contract.md).  Every
 * canonical X slab of small non-cubic skew grids must reproduce the
 * complete-grid fields, NaN masks, flags and stats bit for bit (finite,
 * periodic and mixed axes; B = 1, odd, nondivisors, short tails, B = Nx;
 * 1/2/4 threads as a consistency check, not a benchmark).  Rejected
 * descriptors leave every caller buffer untouched; completed boundary-only,
 * low-only and numeric-failure slabs keep ABI statuses 3/4 with populated
 * fields and stats.  One test declares a huge global Nx while allocating only
 * a few planes, so neighbour tables proportional to Nx could not be
 * allocated.  Synthetic data only; the complete-grid references are checked
 * independently by check_flag_semantics. */
#include "core_test_util.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

static const double RHO_MIN = 1e-8;
static const double NEG_TOL = 1e-6;
static const double JSKEW[9] = {2.0, 0.3, -0.1, 0.2, 2.5, 0.4, -0.3, 0.1, 1.8};
static const double JDIAG[9] = {2, 0, 0, 0, 2, 0, 0, 0, 2};

/* ---------- guarded caller buffers ---------- */

#define GUARD_BYTES 64
#define OUT_FILL 0x5A
#define FLAG_FILL 0xA5
#define IN_GUARD 0xFF /* every input guard double is a NaN */

typedef struct {
    unsigned char *base; /* GUARD_BYTES + bytes + GUARD_BYTES */
    size_t bytes;
} gbuf_t;

static void *xalloc(size_t bytes) {
    void *p = malloc(bytes ? bytes : 1);
    if (!p) {
        fprintf(stderr, "test allocation of %zu bytes failed\n", bytes);
        exit(2);
    }
    return p;
}

static void gbuf_alloc(gbuf_t *b, size_t bytes, unsigned char fill) {
    b->bytes = bytes;
    b->base = xalloc(bytes + 2 * GUARD_BYTES);
    memset(b->base, fill, bytes + 2 * GUARD_BYTES);
}

static void *gbuf_ptr(const gbuf_t *b) { return b->base ? b->base + GUARD_BYTES : NULL; }

static void gbuf_fill(gbuf_t *b, unsigned char fill) {
    if (b->base) memset(b->base, fill, b->bytes + 2 * GUARD_BYTES);
}

/* All bytes equal fill: guards only, or guards and payload. */
static int gbuf_is(const gbuf_t *b, unsigned char fill, int payload_too) {
    if (!b->base) return 1;
    for (size_t i = 0; i < b->bytes + 2 * GUARD_BYTES; ++i) {
        int payload = i >= GUARD_BYTES && i < GUARD_BYTES + b->bytes;
        if ((payload_too || !payload) && b->base[i] != fill) return 0;
    }
    return 1;
}

static void gbuf_free(gbuf_t *b) {
    free(b->base);
    b->base = NULL;
    b->bytes = 0;
}

/* ---------- one X slab with caller-owned guarded buffers ---------- */

typedef struct {
    int64_t s, b, xlo, nxin, nyz, nin, nout;
    int diag;
    gbuf_t in, rdg, srho, lam2, grad, hess, flags;
    nci_tile_stats_v1 stats;
    nci_tile_v1 tile;
} slab_t;

static double *sl_rho(const slab_t *sl) { return gbuf_ptr(&sl->in); }
static double *sl_out(const gbuf_t *b) { return gbuf_ptr(b); }
static uint8_t *sl_flags(const slab_t *sl) { return gbuf_ptr(&sl->flags); }

static void slab_fill_sentinels(slab_t *sl) {
    gbuf_fill(&sl->rdg, OUT_FILL);
    gbuf_fill(&sl->srho, OUT_FILL);
    gbuf_fill(&sl->lam2, OUT_FILL);
    gbuf_fill(&sl->grad, OUT_FILL);
    gbuf_fill(&sl->hess, OUT_FILL);
    gbuf_fill(&sl->flags, FLAG_FILL);
    memset(&sl->stats, OUT_FILL, sizeof sl->stats);
}

static int stats_untouched(const nci_tile_stats_v1 *s) {
    const unsigned char *b = (const unsigned char *)s;
    for (size_t i = 0; i < sizeof *s; ++i)
        if (b[i] != OUT_FILL) return 0;
    return 1;
}

/* Every output byte, guard and stat still holds its sentinel. */
static int slab_untouched(const slab_t *sl) {
    return gbuf_is(&sl->rdg, OUT_FILL, 1) && gbuf_is(&sl->srho, OUT_FILL, 1) &&
           gbuf_is(&sl->lam2, OUT_FILL, 1) && gbuf_is(&sl->grad, OUT_FILL, 1) &&
           gbuf_is(&sl->hess, OUT_FILL, 1) && gbuf_is(&sl->flags, FLAG_FILL, 1) &&
           stats_untouched(&sl->stats);
}

static int slab_guards_intact(const slab_t *sl) {
    return gbuf_is(&sl->rdg, OUT_FILL, 0) && gbuf_is(&sl->srho, OUT_FILL, 0) &&
           gbuf_is(&sl->lam2, OUT_FILL, 0) && gbuf_is(&sl->grad, OUT_FILL, 0) &&
           gbuf_is(&sl->hess, OUT_FILL, 0) && gbuf_is(&sl->flags, FLAG_FILL, 0);
}

/* B planes from global plane s; the input holds nxin planes from global xlo.
 * tmpl is a complete-grid descriptor supplying global_n, J and periodicity. */
static void slab_alloc(slab_t *sl, const nci_tile_v1 *tmpl, int64_t s, int64_t b, int64_t xlo,
                       int64_t nxin, int diag) {
    memset(sl, 0, sizeof *sl);
    sl->s = s;
    sl->b = b;
    sl->xlo = xlo;
    sl->nxin = nxin;
    sl->diag = diag;
    sl->nyz = tmpl->global_n[1] * tmpl->global_n[2];
    sl->nin = nxin * sl->nyz;
    sl->nout = b * sl->nyz;
    size_t nout = (size_t)sl->nout;
    gbuf_alloc(&sl->in, (size_t)sl->nin * sizeof(double), IN_GUARD);
    gbuf_alloc(&sl->rdg, nout * sizeof(double), OUT_FILL);
    gbuf_alloc(&sl->srho, nout * sizeof(double), OUT_FILL);
    gbuf_alloc(&sl->lam2, nout * sizeof(double), OUT_FILL);
    gbuf_alloc(&sl->flags, nout, FLAG_FILL);
    if (diag) {
        gbuf_alloc(&sl->grad, 3 * nout * sizeof(double), OUT_FILL);
        gbuf_alloc(&sl->hess, 6 * nout * sizeof(double), OUT_FILL);
    }
    memset(&sl->stats, OUT_FILL, sizeof sl->stats);
    nci_tile_v1 *t = &sl->tile;
    *t = *tmpl;
    t->tile_start[0] = s;
    t->tile_count[0] = b;
    t->input_origin[0] = xlo;
    t->input_shape[0] = nxin;
    t->rho_capacity = sl->nin;
    t->field_capacity = sl->nout;
    t->flags_capacity = sl->nout;
    t->grad_capacity = diag ? 3 * sl->nout : 0;
    t->hess_capacity = diag ? 6 * sl->nout : 0;
}

static void slab_free(slab_t *sl) {
    gbuf_free(&sl->in);
    gbuf_free(&sl->rdg);
    gbuf_free(&sl->srho);
    gbuf_free(&sl->lam2);
    gbuf_free(&sl->grad);
    gbuf_free(&sl->hess);
    gbuf_free(&sl->flags);
}

/* Canonical input X planes (docs/slab-contract.md), computed independently. */
static void canonical_x(int64_t nx, int periodic_x, int64_t s, int64_t b, int64_t *xlo,
                        int64_t *nxin) {
    if (periodic_x) {
        *xlo = s - 2;
        *nxin = b + 4;
        return;
    }
    int64_t lo = s - 2 > 0 ? s - 2 : 0;
    int64_t hi = s + b + 2 < nx ? s + b + 2 : nx;
    *xlo = lo;
    *nxin = hi - lo;
}

static int64_t mod64(int64_t a, int64_t n) {
    int64_t r = a % n;
    return r < 0 ? r + n : r;
}

/* Packs the canonical slab [s, s+b) of the global density of g, materializing
 * duplicate periodic halo planes when b is large. */
static void slab_from_grid(slab_t *sl, const grid_t *g, int64_t s, int64_t b, int diag) {
    int64_t xlo, nxin;
    canonical_x(g->n[0], g->tile.periodic[0], s, b, &xlo, &nxin);
    slab_alloc(sl, &g->tile, s, b, xlo, nxin, diag);
    double *in = sl_rho(sl);
    for (int64_t k = 0; k < nxin; ++k)
        memcpy(in + k * sl->nyz, g->rho + mod64(xlo + k, g->n[0]) * sl->nyz,
               (size_t)sl->nyz * sizeof(double));
}

/* Evaluates the slab; the input (with its NaN guards) must stay unchanged
 * and no output guard may be written. */
static int slab_eval(void *ctx, slab_t *sl, char *err, size_t errlen) {
    size_t inb = sl->in.bytes + 2 * GUARD_BYTES;
    unsigned char *copy = xalloc(inb);
    memcpy(copy, sl->in.base, inb);
    int st = nci_eval_tile_f64_v1(ctx, &sl->tile, sl_rho(sl), sl_out(&sl->rdg), sl_out(&sl->srho),
                                  sl_out(&sl->lam2), sl->diag ? sl_out(&sl->grad) : NULL,
                                  sl->diag ? sl_out(&sl->hess) : NULL, sl_flags(sl), &sl->stats,
                                  err, errlen);
    CHECK(memcmp(copy, sl->in.base, inb) == 0, "slab input or its guards were modified");
    CHECK(slab_guards_intact(sl), "slab output guards were written (status %d)", st);
    free(copy);
    return st;
}

/* Number of output arrays differing bitwise from the complete-grid
 * reference g (evaluated in DIAGNOSTIC mode). */
static int slab_diff(const slab_t *sl, const grid_t *g) {
    size_t off = (size_t)(sl->s * sl->nyz), n = (size_t)sl->nout;
    int bad = 0;
    bad += memcmp(sl_out(&sl->rdg), g->rdg + off, n * sizeof(double)) != 0;
    bad += memcmp(sl_out(&sl->srho), g->srho + off, n * sizeof(double)) != 0;
    bad += memcmp(sl_out(&sl->lam2), g->lam2 + off, n * sizeof(double)) != 0;
    bad += memcmp(sl_flags(sl), g->flags + off, n) != 0;
    if (sl->diag) {
        bad += memcmp(sl_out(&sl->grad), g->grad + 3 * off, 3 * n * sizeof(double)) != 0;
        bad += memcmp(sl_out(&sl->hess), g->hess + 6 * off, 6 * n * sizeof(double)) != 0;
    }
    return bad;
}

/* Bitwise equality of all outputs and stats of two slabs of equal size. */
static int slab_same(const slab_t *a, const slab_t *b) {
    size_t n = (size_t)a->nout;
    int same = a->nout == b->nout && a->diag == b->diag &&
               memcmp(sl_out(&a->rdg), sl_out(&b->rdg), n * sizeof(double)) == 0 &&
               memcmp(sl_out(&a->srho), sl_out(&b->srho), n * sizeof(double)) == 0 &&
               memcmp(sl_out(&a->lam2), sl_out(&b->lam2), n * sizeof(double)) == 0 &&
               memcmp(sl_flags(a), sl_flags(b), n) == 0 &&
               memcmp(&a->stats, &b->stats, sizeof a->stats) == 0;
    if (same && a->diag)
        same = memcmp(sl_out(&a->grad), sl_out(&b->grad), 3 * n * sizeof(double)) == 0 &&
               memcmp(sl_out(&a->hess), sl_out(&b->hess), 6 * n * sizeof(double)) == 0;
    return same;
}

/* A completed slab's stats and status must describe its own output flags. */
static void slab_check_stats(const slab_t *sl, int st, const char *what) {
    const uint8_t *f = sl_flags(sl);
    int64_t bits[7] = {0}, valid = 0;
    for (int64_t p = 0; p < sl->nout; ++p) {
        for (int b = 0; b < 7; ++b)
            if (f[p] & (1u << b)) bits[b]++;
        if ((f[p] & 31u) == 0) valid++;
    }
    const nci_tile_stats_v1 *s = &sl->stats;
    int ok = s->total_points == sl->nout && s->valid_points == valid &&
             s->invalid_points == sl->nout - valid && s->numeric_failures == bits[4];
    for (int b = 0; b < 7; ++b) ok = ok && s->bit_counts[b] == bits[b];
    CHECK(ok, "%s: slab stats do not describe its %lld output flags", what, (long long)sl->nout);
    int expect = bits[4] > 0 ? NCI_NUMERIC_FAILURE : (valid == 0 ? NCI_INVALID_INPUT : NCI_OK);
    CHECK(st == expect, "%s: status %d, expected %d", what, st, expect);
}

/* Every formal and diagnostic field of the slab is NaN. */
static int slab_all_nan(const slab_t *sl) {
    const double *r = sl_out(&sl->rdg), *s = sl_out(&sl->srho), *l = sl_out(&sl->lam2);
    for (int64_t p = 0; p < sl->nout; ++p) {
        if (!isnan(r[p]) || !isnan(s[p]) || !isnan(l[p])) return 0;
        if (sl->diag) {
            for (int c = 0; c < 3; ++c)
                if (!isnan(sl_out(&sl->grad)[3 * p + c])) return 0;
            for (int c = 0; c < 6; ++c)
                if (!isnan(sl_out(&sl->hess)[6 * p + c])) return 0;
        }
    }
    return 1;
}

static int add_checked(int64_t *acc, int64_t v) {
    if (v < 0 || *acc > INT64_MAX - v) return 0;
    *acc += v;
    return 1;
}

static int stats_accumulate(nci_tile_stats_v1 *sum, const nci_tile_stats_v1 *s) {
    int ok = add_checked(&sum->total_points, s->total_points) &&
             add_checked(&sum->valid_points, s->valid_points) &&
             add_checked(&sum->invalid_points, s->invalid_points) &&
             add_checked(&sum->numeric_failures, s->numeric_failures);
    for (int b = 0; b < 7; ++b) ok = ok && add_checked(&sum->bit_counts[b], s->bit_counts[b]);
    return ok;
}

static long long message_point(const char *err) {
    const char *key = "first at point ";
    const char *at = strstr(err, key);
    return at ? strtoll(at + strlen(key), NULL, 10) : -1;
}

static void *make_context(int mode, int threads, double rho_min) {
    nci_options_v1 o = make_options(mode, threads, rho_min, NEG_TOL);
    void *ctx = NULL;
    int st = nci_context_create_v1(&o, &ctx, NULL, 0);
    CHECK(st == NCI_OK && ctx != NULL, "context creation failed: %d", st);
    return ctx;
}

/* ---------- synthetic densities and complete-grid references ---------- */

static void seeded_density(grid_t *g, uint64_t seed) {
    for (int64_t i = 0; i < g->n[0]; ++i)
        for (int64_t j = 0; j < g->n[1]; ++j)
            for (int64_t k = 0; k < g->n[2]; ++k)
                g->rho[lin(g, i, j, k)] = 1.0 + 0.3 * sin(0.9 * (double)i + 0.2) * cos(0.5 * (double)j) +
                                          0.1 * cos(0.7 * (double)k) + 0.05 * lcg_uniform(&seed);
}

/* Accepted negative samples on the X seams, across Y/Z seams and at
 * mixed-stencil corners of neighbouring slabs; a zero and a low sample. */
static void scatter_specials(grid_t *g) {
    const int64_t nx = g->n[0], ny = g->n[1], nz = g->n[2];
    const struct {
        int64_t i, j, k;
        double v;
    } sp[] = {
        {0, 1, 2, -5e-7},           /* periodic X seam / finite X boundary */
        {nx / 2, ny - 1, 3, -3e-7}, /* slab seams of several B, Y seam */
        {nx - 1, 3, nz - 1, -1e-6}, /* exactly -tolerance on the X and Z seams */
        {2, 4, 4, 0.0},             /* zero: legal, never invalidates neighbours */
        {nx - 3, 2, 1, 1e-12},      /* low positive sample still participates */
    };
    for (size_t s = 0; s < sizeof sp / sizeof sp[0]; ++s) g->rho[lin(g, sp[s].i, sp[s].j, sp[s].k)] = sp[s].v;
}

/* Complete-grid DIAGNOSTIC reference, independently checked. */
static int reference_eval(grid_t *g, const int periodic[3], double rho_min, char *err, size_t errlen) {
    nci_options_v1 o = make_options(NCI_DIAGNOSTIC, 3, rho_min, NEG_TOL);
    int st = eval_with(&o, g, err, errlen);
    check_flag_semantics(g, periodic, rho_min, st);
    return st;
}

/* Every slab of size bsize (shorter tail) of ref against the complete grid;
 * the summed stats and the aggregated status must match it as well. */
static void sweep(const char *what, const grid_t *ref, int ref_status, int mode, int threads,
                  double rho_min, int64_t bsize) {
    char label[192], err[256];
    void *ctx = make_context(mode, threads, rho_min);
    if (!ctx) return;
    nci_tile_stats_v1 sum;
    memset(&sum, 0, sizeof sum);
    for (int64_t s = 0; s < ref->n[0]; s += bsize) {
        int64_t b = ref->n[0] - s < bsize ? ref->n[0] - s : bsize;
        snprintf(label, sizeof label, "%s mode=%d threads=%d B=%lld s=%lld", what, mode, threads,
                 (long long)bsize, (long long)s);
        slab_t sl;
        slab_from_grid(&sl, ref, s, b, mode == NCI_DIAGNOSTIC);
        err[0] = '\0';
        int st = slab_eval(ctx, &sl, err, sizeof err);
        int bad = slab_diff(&sl, ref);
        CHECK(bad == 0, "%s: %d output arrays differ from the complete grid (status %d: %s)", label,
              bad, st, err);
        slab_check_stats(&sl, st, label);
        CHECK(stats_accumulate(&sum, &sl.stats), "%s: checked stats aggregation overflowed", label);
        slab_free(&sl);
    }
    snprintf(label, sizeof label, "%s mode=%d threads=%d B=%lld", what, mode, threads,
             (long long)bsize);
    CHECK(memcmp(&sum, &ref->stats, sizeof sum) == 0,
          "%s: summed slab stats differ from the complete grid (valid %lld vs %lld)", label,
          (long long)sum.valid_points, (long long)ref->stats.valid_points);
    int global = sum.numeric_failures > 0 ? NCI_NUMERIC_FAILURE
                                          : (sum.valid_points == 0 ? NCI_INVALID_INPUT : NCI_OK);
    CHECK(sum.total_points == ref->npts && global == ref_status,
          "%s: aggregated status %d, complete grid %d", label, global, ref_status);
    nci_context_destroy_v1(ctx, NULL, 0);
}

/* ---------- equivalence with the complete grid ---------- */

static void test_equivalence(void) {
    static const int PER[6][3] = {{0, 0, 0}, {1, 1, 1}, {1, 0, 1}, {0, 1, 0}, {1, 0, 0}, {0, 1, 1}};
    static const int64_t DIMS[2][3] = {{11, 9, 8}, {5, 8, 7}};
    static const int64_t BS[2][6] = {{1, 2, 3, 4, 10, 11}, {1, 2, 3, 4, 5, 0}};
    static const int THREADS[3] = {1, 2, 4};
    char err[256], what[96];
    for (int d = 0; d < 2; ++d)
        for (int c = 0; c < 6; ++c) {
            grid_t ref;
            grid_init(&ref, DIMS[d][0], DIMS[d][1], DIMS[d][2], JSKEW, PER[c], 1);
            seeded_density(&ref, 1000 + 10 * (uint64_t)d + (uint64_t)c);
            scatter_specials(&ref);
            int st = reference_eval(&ref, PER[c], RHO_MIN, err, sizeof err);
            snprintf(what, sizeof what, "%lldx%lldx%lld periodic=(%d,%d,%d)", (long long)ref.n[0],
                     (long long)ref.n[1], (long long)ref.n[2], PER[c][0], PER[c][1], PER[c][2]);
            printf("%s: complete grid status %d, %lld valid, %lld STENCIL_INVALID\n", what, st,
                   (long long)ref.stats.valid_points, (long long)ref.stats.bit_counts[3]);
            CHECK(st == NCI_OK, "%s: reference status %d (%s)", what, st, err);
            if (PER[c][1]) {
                /* (nx/2-1, 1, 3) reaches the negative (nx/2, ny-1, 3) through the
                 * mixed corner offset (1,-2,0) across the X slab and Y seams. */
                int64_t corner = lin(&ref, ref.n[0] / 2 - 1, 1, 3);
                CHECK(ref.flags[corner] & NCI_STENCIL_INVALID, "%s: seam corner not exercised", what);
            }
            for (int b = 0; b < 6 && BS[d][b] > 0; ++b) {
                sweep(what, &ref, st, NCI_DIAGNOSTIC, THREADS[b % 3], RHO_MIN, BS[d][b]);
                if (BS[d][b] == 3 || BS[d][b] == ref.n[0])
                    sweep(what, &ref, st, NCI_FULL, THREADS[(b + 1) % 3], RHO_MIN, BS[d][b]);
            }
            if (d == 0 && c == 2) {
                /* The same reference for 1, 2 and 4 threads: consistency only. */
                for (int t = 0; t < 3; ++t) {
                    sweep(what, &ref, st, NCI_DIAGNOSTIC, THREADS[t], RHO_MIN, 4);
                    sweep(what, &ref, st, NCI_DIAGNOSTIC, THREADS[t], RHO_MIN, 1);
                }
            }
            grid_free(&ref);
        }
}

/* ---------- completed all-invalid slabs (ABI status 3) ---------- */

static void test_invalid_only_slabs(void) {
    const int per[3] = {0, 1, 1};
    char err[256];
    grid_t ref;
    grid_init(&ref, 9, 8, 7, JSKEW, per, 1);
    seeded_density(&ref, 77);
    for (int64_t j = 0; j < 8; ++j)
        for (int64_t k = 0; k < 7; ++k) {
            ref.rho[lin(&ref, 4, j, k)] = 1e-12;
            ref.rho[lin(&ref, 5, j, k)] = 2e-12;
        }
    int st = reference_eval(&ref, per, RHO_MIN, err, sizeof err);
    CHECK(st == NCI_OK, "low-plane reference status %d (%s)", st, err);
    const struct {
        int64_t s, b;
        int expect, bit;
        const char *what;
    } cases[] = {
        {0, 2, NCI_INVALID_INPUT, 0, "finite X start: boundary-only slab"},
        {7, 2, NCI_INVALID_INPUT, 0, "finite X end: boundary-only slab"},
        {8, 1, NCI_INVALID_INPUT, 0, "finite X last plane"},
        {4, 2, NCI_INVALID_INPUT, 2, "low-only slab"},
        {0, 3, NCI_OK, -1, "boundary planes plus one interior plane"},
        {3, 3, NCI_OK, -1, "low planes plus interior planes"},
    };
    void *ctx = make_context(NCI_DIAGNOSTIC, 2, RHO_MIN);
    for (size_t c = 0; c < sizeof cases / sizeof cases[0]; ++c) {
        slab_t sl;
        slab_from_grid(&sl, &ref, cases[c].s, cases[c].b, 1);
        err[0] = '\0';
        st = slab_eval(ctx, &sl, err, sizeof err);
        CHECK(st == cases[c].expect, "%s: status %d expected %d (%s)", cases[c].what, st,
              cases[c].expect, err);
        CHECK(slab_diff(&sl, &ref) == 0, "%s: differs from the complete grid", cases[c].what);
        slab_check_stats(&sl, st, cases[c].what);
        if (cases[c].expect == NCI_INVALID_INPUT) {
            const nci_tile_stats_v1 *s = &sl.stats;
            CHECK(s->total_points == sl.nout && s->valid_points == 0 &&
                      s->invalid_points == sl.nout && s->numeric_failures == 0 &&
                      s->bit_counts[cases[c].bit] == sl.nout,
                  "%s: completed invalid slab stats", cases[c].what);
            CHECK(slab_all_nan(&sl), "%s: all fields must be NaN", cases[c].what);
            CHECK(strstr(err, "no numerically valid point") != NULL, "%s: message %s",
                  cases[c].what, err);
        }
        slab_free(&sl);
    }
    nci_context_destroy_v1(ctx, NULL, 0);
    grid_free(&ref);

    /* Globally zero valid output: every slab completes with status 3 and the
     * aggregate still has no valid point (a scheduler must not report OK). */
    grid_t low;
    grid_init(&low, 9, 8, 7, JSKEW, per, 1);
    seeded_density(&low, 78);
    st = reference_eval(&low, per, 10.0, err, sizeof err);
    CHECK(st == NCI_INVALID_INPUT && low.stats.valid_points == 0, "all-low reference status %d", st);
    sweep("all-low 9x8x7", &low, st, NCI_DIAGNOSTIC, 2, 10.0, 4);
    sweep("all-low 9x8x7", &low, st, NCI_FULL, 1, 10.0, 9);
    grid_free(&low);
}

/* ---------- numeric failure inside slabs (ABI status 4) ---------- */

static void test_numeric_failure_slabs(void) {
    const int per[3] = {1, 1, 1};
    char err[256], label[96];
    grid_t ref;
    grid_init(&ref, 9, 9, 9, JDIAG, per, 1);
    seeded_density(&ref, 5);
    ref.rho[lin(&ref, 4, 4, 4)] = 1.5e308;
    int st = reference_eval(&ref, per, RHO_MIN, err, sizeof err);
    CHECK(st == NCI_NUMERIC_FAILURE, "reference status %d", st);
    int64_t first = -1;
    for (int64_t p = 0; p < ref.npts && first < 0; ++p)
        if (ref.flags[p] & NCI_POINT_NUMERIC_FAILURE) first = p;
    CHECK(message_point(err) == first, "complete grid message '%s' should name point %lld", err,
          (long long)first);
    printf("numeric failure reference: %lld failing points: %s\n",
           (long long)ref.stats.numeric_failures, err);

    void *ctx = make_context(NCI_DIAGNOSTIC, 2, RHO_MIN);
    int failing_slabs = 0;
    nci_tile_stats_v1 sum;
    memset(&sum, 0, sizeof sum);
    for (int64_t s = 0; s < 9; s += 2) {
        int64_t b = 9 - s < 2 ? 9 - s : 2;
        snprintf(label, sizeof label, "numeric failure slab s=%lld B=%lld", (long long)s, (long long)b);
        slab_t sl;
        slab_from_grid(&sl, &ref, s, b, 1);
        err[0] = '\0';
        st = slab_eval(ctx, &sl, err, sizeof err);
        CHECK(slab_diff(&sl, &ref) == 0, "%s: differs from the complete grid", label);
        slab_check_stats(&sl, st, label);
        CHECK(stats_accumulate(&sum, &sl.stats), "%s: stats overflow", label);
        int64_t gfirst = -1;
        for (int64_t p = 0; p < sl.nout && gfirst < 0; ++p)
            if (sl_flags(&sl)[p] & NCI_POINT_NUMERIC_FAILURE) gfirst = s * sl.nyz + p;
        if (gfirst >= 0) {
            failing_slabs++;
            CHECK(st == NCI_NUMERIC_FAILURE && strstr(err, "numeric failure") != NULL &&
                      message_point(err) == gfirst,
                  "%s: message '%s' should name global point %lld", label, err, (long long)gfirst);
        }
        slab_free(&sl);
    }
    CHECK(failing_slabs >= 1, "no slab reported the numeric failure");
    CHECK(memcmp(&sum, &ref.stats, sizeof sum) == 0, "numeric failure: summed stats differ");
    nci_context_destroy_v1(ctx, NULL, 0);
    grid_free(&ref);
}

/* ---------- preflight of the supplied input, halo included ---------- */

static void test_halo_preflight(void) {
    const int per[3] = {1, 0, 1};
    char err[256], expect[64];
    grid_t ref;
    grid_init(&ref, 9, 8, 7, JSKEW, per, 1);
    seeded_density(&ref, 11);
    int st = reference_eval(&ref, per, RHO_MIN, err, sizeof err);
    CHECK(st == NCI_OK, "preflight reference status %d", st);
    void *ctx = make_context(NCI_DIAGNOSTIC, 2, RHO_MIN);

    /* Periodic X slab [3,5): input planes are global 1..6. */
    slab_t sl;
    slab_from_grid(&sl, &ref, 3, 2, 1);
    const int64_t nyz = sl.nyz;
    const struct {
        int64_t idx;
        double v;
        const char *what;
    } bad[] = {
        {0 * nyz + 2 * 7 + 3, NAN, "NaN in the first halo plane"},
        {1 * nyz + 0, INFINITY, "+Inf in the second halo plane"},
        {4 * nyz + 3 * 7 + 1, -INFINITY, "-Inf in the right halo"},
        {5 * nyz + 7 * 7 + 6, -2e-6, "below -tolerance as the last input sample"},
    };
    double *in = sl_rho(&sl);
    for (size_t c = 0; c < sizeof bad / sizeof bad[0]; ++c) {
        double keep = in[bad[c].idx];
        in[bad[c].idx] = bad[c].v;
        slab_fill_sentinels(&sl);
        memset(err, 'Z', sizeof err);
        st = slab_eval(ctx, &sl, err, sizeof err);
        CHECK(st == NCI_INVALID_INPUT && slab_untouched(&sl), "%s: status %d or outputs written",
              bad[c].what, st);
        snprintf(expect, sizeof expect, "rho[%lld]", (long long)bad[c].idx);
        CHECK(memchr(err, 0, sizeof err) && strstr(err, expect) != NULL,
              "%s: message should name the supplied sample %s", bad[c].what, expect);
        in[bad[c].idx] = keep;
    }
    slab_free(&sl);

    /* An accepted negative halo sample at global (2,4,3) flags slab points
     * across the seam, including the mixed corners (-1,+2,0) and (-2,+2,0),
     * but not the three-axis offset (-1,+1,+1) outside the 61-point stencil. */
    grid_t neg;
    grid_init(&neg, 9, 8, 7, JSKEW, per, 1);
    memcpy(neg.rho, ref.rho, (size_t)ref.npts * sizeof(double));
    neg.rho[lin(&neg, 2, 4, 3)] = -5e-7;
    st = reference_eval(&neg, per, RHO_MIN, err, sizeof err);
    CHECK(st == NCI_OK, "negative-halo reference status %d", st);
    slab_from_grid(&sl, &neg, 3, 2, 1);
    st = slab_eval(ctx, &sl, err, sizeof err);
    CHECK(st == NCI_OK && slab_diff(&sl, &neg) == 0, "negative halo sample: status %d or mismatch", st);
    slab_check_stats(&sl, st, "negative halo sample");
    const uint8_t *f = sl_flags(&sl); /* local (i, y, z) -> (i*8 + y)*7 + z */
    CHECK((f[(0 * 8 + 4) * 7 + 3] & NCI_STENCIL_INVALID) && (f[(1 * 8 + 4) * 7 + 3] & NCI_STENCIL_INVALID) &&
              (f[(0 * 8 + 2) * 7 + 3] & NCI_STENCIL_INVALID) &&
              (f[(1 * 8 + 2) * 7 + 3] & NCI_STENCIL_INVALID),
          "halo negative must invalidate axial and corner neighbours in the slab");
    CHECK(!(f[(0 * 8 + 3) * 7 + 2] & NCI_STENCIL_INVALID),
          "three-axis offset (-1,+1,+1) is outside the 61-point stencil: flags 0x%02x",
          f[(0 * 8 + 3) * 7 + 2]);
    slab_free(&sl);
    grid_free(&neg);

    /* Finite X clipped halo: the right halo planes are global 2 and 3. */
    const int fper[3] = {0, 1, 1};
    grid_t fin;
    grid_init(&fin, 9, 8, 7, JSKEW, fper, 1);
    seeded_density(&fin, 12);
    slab_from_grid(&sl, &fin, 0, 2, 1);
    CHECK(sl.xlo == 0 && sl.nxin == 4, "finite clipped halo geometry");
    sl_rho(&sl)[3 * nyz + 10] = NAN;
    slab_fill_sentinels(&sl);
    st = slab_eval(ctx, &sl, err, sizeof err);
    CHECK(st == NCI_INVALID_INPUT && slab_untouched(&sl), "finite halo NaN: status %d", st);
    slab_free(&sl);
    grid_free(&fin);

    /* Only the supplied input is seen: a NaN plane outside it is not detected
     * by this call; the caller validates the complete dataset first. */
    grid_t nan_plane;
    grid_init(&nan_plane, 9, 8, 7, JSKEW, per, 1);
    seeded_density(&nan_plane, 13);
    for (int64_t q = 0; q < nyz; ++q) nan_plane.rho[8 * nyz + q] = NAN;
    slab_from_grid(&sl, &nan_plane, 3, 1, 1); /* input planes 1..5 */
    st = slab_eval(ctx, &sl, err, sizeof err);
    CHECK(st == NCI_OK, "slab whose input excludes the bad plane: status %d (%s)", st, err);
    slab_free(&sl);
    slab_from_grid(&sl, &nan_plane, 0, 2, 1); /* input planes 7,8,0,1,2,3 */
    st = slab_eval(ctx, &sl, err, sizeof err);
    CHECK(st == NCI_INVALID_INPUT && slab_untouched(&sl), "bad periodic halo plane: status %d", st);
    snprintf(expect, sizeof expect, "rho[%lld]", (long long)nyz);
    CHECK(strstr(err, expect) != NULL, "halo plane message %s should name %s", err, expect);
    slab_free(&sl);
    grid_free(&nan_plane);
    nci_context_destroy_v1(ctx, NULL, 0);
    grid_free(&ref);
}

/* ---------- descriptor rejections leave every caller buffer untouched ---------- */

static void run_case(void *ctx, slab_t *sl, const grid_t *ref, int expect, const char *what) {
    char err[256];
    memset(err, 'Z', sizeof err);
    slab_fill_sentinels(sl);
    int st = slab_eval(ctx, sl, err, sizeof err);
    CHECK(st == expect, "%s: status %d expected %d (%s)", what, st, expect,
          memchr(err, 0, sizeof err) ? err : "<no NUL>");
    if (expect == NCI_OK || expect == NCI_INVALID_INPUT) {
        if (ref) CHECK(slab_diff(sl, ref) == 0, "%s: accepted slab differs from the complete grid", what);
    } else {
        CHECK(slab_untouched(sl), "%s: caller buffers were written", what);
        CHECK(memchr(err, 0, sizeof err) && err[0] != '\0', "%s: missing message", what);
    }
}

#define TCASE(stmt, expect, what)                                              \
    do {                                                                       \
        sl.tile = base;                                                        \
        stmt;                                                                  \
        run_case(ctx, &sl, &ref, expect, what);                                \
        sl.tile = base;                                                        \
    } while (0)

static void test_rejections(void) {
    const int per[3] = {1, 0, 1};
    const int UNSUP = NCI_UNSUPPORTED, INVAL = NCI_INVALID_ARGUMENT;
    char err[256];
    grid_t ref;
    grid_init(&ref, 11, 9, 8, JSKEW, per, 1);
    seeded_density(&ref, 21);
    int st = reference_eval(&ref, per, RHO_MIN, err, sizeof err);
    CHECK(st == NCI_OK, "rejection reference status %d", st);
    void *ctx = make_context(NCI_DIAGNOSTIC, 2, RHO_MIN);

    /* Periodic X slab [3,7): input planes 1..8, Nin = 576 > Nout = 288. */
    slab_t sl;
    slab_from_grid(&sl, &ref, 3, 4, 1);
    const nci_tile_v1 base = sl.tile;
    CHECK(base.input_origin[0] == 1 && base.input_shape[0] == 8 && sl.nin == 576 && sl.nout == 288,
          "periodic slab geometry");
    TCASE((void)0, NCI_OK, "canonical periodic slab");
    TCASE(sl.tile.input_origin[0] = 2, UNSUP, "halo shifted by one plane");
    TCASE((sl.tile.input_origin[0] = 2, sl.tile.input_shape[0] = 7), UNSUP, "missing left halo plane");
    TCASE(sl.tile.input_shape[0] = 7, UNSUP, "missing right halo plane");
    TCASE(sl.tile.input_shape[0] = 9, UNSUP, "extra right halo plane");
    TCASE((sl.tile.input_origin[0] = 0, sl.tile.input_shape[0] = 10), UNSUP, "three-plane halo");
    TCASE((sl.tile.input_origin[0] = 3, sl.tile.input_shape[0] = 4), UNSUP, "no halo");
    TCASE((sl.tile.input_origin[0] = 0, sl.tile.input_shape[0] = 11), UNSUP,
          "complete-grid input for a periodic partial slab");
    TCASE((sl.tile.tile_start[1] = 1, sl.tile.tile_count[1] = 8), UNSUP, "partial Y tile");
    TCASE(sl.tile.tile_count[2] = 7, UNSUP, "partial Z tile");
    TCASE((sl.tile.input_origin[1] = -2, sl.tile.input_shape[1] = 13), UNSUP, "Y halo");
    TCASE(sl.tile.input_shape[2] = 9, UNSUP, "padded Z shape");
    TCASE(sl.tile.input_strides[0] = 80, UNSUP, "padded X stride");
    TCASE(sl.tile.input_strides[1] = 9, UNSUP, "padded Y stride");
    TCASE(sl.tile.input_strides[2] = -1, UNSUP, "negative Z stride");
    TCASE(sl.tile.input_strides[0] = -72, UNSUP, "negative X stride");
    TCASE((sl.tile.input_strides[0] = 1, sl.tile.input_strides[1] = 8, sl.tile.input_strides[2] = 72),
          UNSUP, "X-fastest strides");

    TCASE(sl.tile.input_origin[0] = INT64_MIN, UNSUP, "input_origin[0] INT64_MIN");
    TCASE(sl.tile.input_origin[1] = INT64_MIN, UNSUP, "input_origin[1] INT64_MIN");
    TCASE(sl.tile.input_shape[0] = INT64_MIN, INVAL, "input_shape[0] INT64_MIN");
    TCASE(sl.tile.input_shape[2] = INT64_MIN, INVAL, "input_shape[2] INT64_MIN");
    TCASE(sl.tile.tile_start[0] = INT64_MIN, INVAL, "tile_start[0] INT64_MIN");
    TCASE(sl.tile.tile_count[0] = INT64_MIN, INVAL, "tile_count[0] INT64_MIN");
    TCASE(sl.tile.tile_count[1] = INT64_MIN, INVAL, "tile_count[1] INT64_MIN");
    TCASE(sl.tile.input_strides[0] = INT64_MIN, UNSUP, "input_strides[0] INT64_MIN");
    TCASE(sl.tile.global_n[0] = INT64_MIN, INVAL, "global_n[0] INT64_MIN");
    TCASE(sl.tile.rho_capacity = INT64_MIN, INVAL, "rho_capacity INT64_MIN");
    TCASE(sl.tile.field_capacity = INT64_MIN, INVAL, "field_capacity INT64_MIN");
    TCASE(sl.tile.flags_capacity = INT64_MIN, INVAL, "flags_capacity INT64_MIN");
    TCASE(sl.tile.grad_capacity = INT64_MIN, INVAL, "grad_capacity INT64_MIN");
    TCASE(sl.tile.hess_capacity = INT64_MIN, INVAL, "hess_capacity INT64_MIN");

    TCASE(sl.tile.input_shape[0] = INT64_MAX, INVAL, "input end overflows (shape INT64_MAX)");
    TCASE(sl.tile.input_origin[0] = INT64_MAX, INVAL, "input end overflows (origin INT64_MAX)");
    TCASE(sl.tile.input_shape[0] = (int64_t)1 << 59, INVAL, "input sample count overflows");
    TCASE(sl.tile.input_shape[0] = (int64_t)1 << 56, INVAL, "input byte extent overflows");
    TCASE(sl.tile.input_shape[0] = (int64_t)1 << 50, UNSUP, "representable non-canonical shape");
    TCASE(sl.tile.tile_count[0] = INT64_MAX, INVAL, "tile_count[0] INT64_MAX");
    TCASE(sl.tile.tile_start[0] = INT64_MAX, INVAL, "tile_start[0] INT64_MAX");
    TCASE((sl.tile.tile_start[0] = 8, sl.tile.input_origin[0] = 6), INVAL, "slab beyond the grid");
    TCASE(sl.tile.global_n[0] = (int64_t)1 << 60, INVAL, "global point count overflows");
    TCASE(sl.tile.global_n[2] = (int64_t)1 << 56, INVAL, "global byte extent overflows");

    TCASE(sl.tile.rho_capacity = sl.nin - 1, INVAL, "rho_capacity Nin-1");
    TCASE(sl.tile.rho_capacity = sl.nout, INVAL, "rho_capacity Nout < Nin");
    TCASE(sl.tile.field_capacity = sl.nout - 1, INVAL, "field_capacity Nout-1");
    TCASE(sl.tile.flags_capacity = sl.nout - 1, INVAL, "flags_capacity Nout-1");
    TCASE(sl.tile.grad_capacity = 3 * sl.nout - 1, INVAL, "grad_capacity 3*Nout-1");
    TCASE(sl.tile.hess_capacity = 6 * sl.nout - 1, INVAL, "hess_capacity 6*Nout-1");
    TCASE(sl.tile.grad_capacity = sl.nout, INVAL, "grad_capacity counts components");
    TCASE((sl.tile.rho_capacity = 2 * sl.nin, sl.tile.field_capacity = sl.nin,
           sl.tile.flags_capacity = sl.nin),
          NCI_OK, "larger capacities accepted");
    slab_free(&sl);

    /* Near the X seam the periodic halo differs from the clipped finite one. */
    slab_from_grid(&sl, &ref, 0, 4, 1);
    CHECK(sl.tile.input_origin[0] == -2 && sl.tile.input_shape[0] == 8, "periodic seam geometry");
    run_case(ctx, &sl, &ref, NCI_OK, "periodic slab across the X seam");
    sl.tile.periodic[0] = 0;
    run_case(ctx, &sl, &ref, UNSUP, "unwrapped periodic halo on a finite X axis");
    slab_free(&sl);

    /* A legacy-looking periodic B = Nx descriptor needs no halo; its halo
     * form (origin -2, shape Nx+4, duplicated planes) is supported too. */
    slab_from_grid(&sl, &ref, 0, 11, 1);
    CHECK(sl.tile.input_origin[0] == -2 && sl.tile.input_shape[0] == 15, "B = Nx periodic halo geometry");
    run_case(ctx, &sl, &ref, NCI_OK, "periodic B = Nx halo descriptor");
    slab_free(&sl);

    /* FULL mode: grad/hess must be NULL with zero capacities. */
    void *cfull = make_context(NCI_FULL, 1, RHO_MIN);
    slab_from_grid(&sl, &ref, 3, 4, 0);
    run_case(cfull, &sl, &ref, NCI_OK, "FULL slab");
    sl.tile.grad_capacity = 3 * sl.nout;
    run_case(cfull, &sl, &ref, INVAL, "FULL slab with grad_capacity");
    slab_free(&sl);
    nci_context_destroy_v1(cfull, NULL, 0);
    nci_context_destroy_v1(ctx, NULL, 0);
    grid_free(&ref);

    /* Finite X: clipped halo at the interior, the start and the end. */
    const int fper[3] = {0, 1, 0};
    grid_t fin;
    grid_init(&fin, 11, 9, 8, JSKEW, fper, 1);
    seeded_density(&fin, 22);
    st = reference_eval(&fin, fper, RHO_MIN, err, sizeof err);
    CHECK(st == NCI_OK, "finite rejection reference status %d", st);
    ctx = make_context(NCI_DIAGNOSTIC, 4, RHO_MIN);
    {
        slab_from_grid(&sl, &fin, 4, 3, 1);
        const nci_tile_v1 fbase = sl.tile;
        CHECK(fbase.input_origin[0] == 2 && fbase.input_shape[0] == 7, "finite interior geometry");
#define FCASE(stmt, expect, what)                                              \
    do {                                                                       \
        sl.tile = fbase;                                                       \
        stmt;                                                                  \
        run_case(ctx, &sl, &fin, expect, what);                                \
        sl.tile = fbase;                                                       \
    } while (0)
        FCASE((void)0, NCI_OK, "canonical finite interior slab");
        FCASE(sl.tile.input_shape[0] = 6, UNSUP, "finite: missing right halo plane");
        FCASE((sl.tile.input_origin[0] = 3, sl.tile.input_shape[0] = 6), UNSUP,
              "finite: missing left halo plane");
        FCASE((sl.tile.input_origin[0] = 1, sl.tile.input_shape[0] = 8), UNSUP, "finite: extra halo planes");
        FCASE((sl.tile.input_origin[0] = 0, sl.tile.input_shape[0] = 11), UNSUP,
              "finite: complete-grid input for a partial slab");
        slab_free(&sl);

        slab_from_grid(&sl, &fin, 0, 3, 1);
        const nci_tile_v1 fstart = sl.tile;
        CHECK(fstart.input_origin[0] == 0 && fstart.input_shape[0] == 5, "finite start geometry");
        run_case(ctx, &sl, &fin, NCI_OK, "canonical finite start slab");
        sl.tile.input_origin[0] = -2;
        sl.tile.input_shape[0] = 7;
        run_case(ctx, &sl, &fin, UNSUP, "finite: samples outside the grid are absent, not zero-filled");
        sl.tile = fstart;
        sl.tile.periodic[0] = 1;
        run_case(ctx, &sl, &fin, UNSUP, "clipped finite halo on a periodic X axis");
        slab_free(&sl);

        slab_from_grid(&sl, &fin, 9, 2, 1);
        CHECK(sl.tile.input_origin[0] == 7 && sl.tile.input_shape[0] == 4, "finite end geometry");
        run_case(ctx, &sl, &fin, NCI_INVALID_INPUT, "canonical finite end slab (boundary only)");
        sl.tile.input_shape[0] = 6;
        run_case(ctx, &sl, &fin, UNSUP, "finite: halo beyond the finite end");
        slab_free(&sl);
#undef FCASE
    }
    nci_context_destroy_v1(ctx, NULL, 0);
    grid_free(&fin);
}

/* ---------- byte ranges use Nin for rho and Nout for outputs ---------- */

static void test_alias_ranges(void) {
    const int per[3] = {1, 0, 1};
    char err[256];
    grid_t ref;
    grid_init(&ref, 11, 9, 8, JSKEW, per, 1);
    seeded_density(&ref, 31);
    int st = reference_eval(&ref, per, RHO_MIN, err, sizeof err);
    CHECK(st == NCI_OK, "alias reference status %d", st);
    void *ctx = make_context(NCI_DIAGNOSTIC, 2, RHO_MIN);
    slab_t sl;
    slab_from_grid(&sl, &ref, 3, 4, 1);
    const size_t nin = (size_t)sl.nin, nout = (size_t)sl.nout;
    double *rdg = sl_out(&sl.rdg), *srho = sl_out(&sl.srho), *lam2 = sl_out(&sl.lam2);
    double *grad = sl_out(&sl.grad), *hess = sl_out(&sl.hess);
    uint8_t *flags = sl_flags(&sl);

    /* pool = [rho: Nin samples][Nout + 16 spare doubles] */
    const size_t pool_n = nin + nout + 16;
    double *pool = xalloc(pool_n * sizeof(double));
    memset(pool, OUT_FILL, pool_n * sizeof(double));
    memcpy(pool, sl_rho(&sl), nin * sizeof(double));
    double *snap = xalloc(pool_n * sizeof(double));
    memcpy(snap, pool, pool_n * sizeof(double));

    const struct {
        int which;
        size_t at;
        const char *what;
    } bad[] = {
        {0, nin - 1, "rdg overlapping the last halo sample"},
        {1, nout, "flags inside halo storage beyond the first Nout samples"},
        {2, nin - 2, "errbuf inside the halo storage"},
    };
    for (size_t c = 0; c < sizeof bad / sizeof bad[0]; ++c) {
        slab_fill_sentinels(&sl);
        memset(err, 'Z', sizeof err);
        double *r = bad[c].which == 0 ? pool + bad[c].at : rdg;
        uint8_t *fl = bad[c].which == 1 ? (uint8_t *)(pool + bad[c].at) : flags;
        char *eb = bad[c].which == 2 ? (char *)(pool + bad[c].at) : err;
        st = nci_eval_tile_f64_v1(ctx, &sl.tile, pool, r, srho, lam2, grad, hess, fl, &sl.stats, eb, 64);
        CHECK(st == NCI_INVALID_ARGUMENT, "%s: status %d", bad[c].what, st);
        CHECK(memcmp(pool, snap, pool_n * sizeof(double)) == 0, "%s: rho storage or errbuf written",
              bad[c].what);
        CHECK(slab_untouched(&sl), "%s: outputs written", bad[c].what);
    }

    /* Adjacent, non-overlapping ranges are accepted: signedrho right after
     * the Nin input samples. */
    slab_fill_sentinels(&sl);
    st = nci_eval_tile_f64_v1(ctx, &sl.tile, pool, rdg, pool + nin, lam2, grad, hess, flags, &sl.stats,
                              err, sizeof err);
    CHECK(st == NCI_OK, "signedrho adjacent to the input end: status %d (%s)", st, err);
    CHECK(memcmp(pool, snap, nin * sizeof(double)) == 0, "input samples modified");
    CHECK(memcmp(pool + nin, ref.srho + 3 * sl.nyz, nout * sizeof(double)) == 0,
          "adjacent signedrho differs from the complete grid");
    unsigned char spare[16 * sizeof(double)];
    memset(spare, OUT_FILL, sizeof spare);
    CHECK(memcmp(pool + nin + nout, spare, sizeof spare) == 0, "signedrho written beyond Nout");

    /* grad/hess: the Hessian may start exactly 3*Nout after grad, not before. */
    double *gh = xalloc(9 * nout * sizeof(double));
    memset(gh, OUT_FILL, 9 * nout * sizeof(double));
    slab_fill_sentinels(&sl);
    st = nci_eval_tile_f64_v1(ctx, &sl.tile, pool, rdg, srho, lam2, gh, gh + 3 * nout - 1, flags,
                              &sl.stats, err, sizeof err);
    CHECK(st == NCI_INVALID_ARGUMENT && slab_untouched(&sl), "hess overlapping grad: status %d", st);
    st = nci_eval_tile_f64_v1(ctx, &sl.tile, pool, rdg, srho, lam2, gh, gh + 3 * nout, flags,
                              &sl.stats, err, sizeof err);
    CHECK(st == NCI_OK && memcmp(gh, ref.grad + 3 * 3 * sl.nyz, 3 * nout * sizeof(double)) == 0 &&
              memcmp(gh + 3 * nout, ref.hess + 6 * 3 * sl.nyz, 6 * nout * sizeof(double)) == 0,
          "adjacent grad/hess: status %d or values differ", st);
    free(gh);
    free(snap);
    free(pool);
    slab_free(&sl);
    nci_context_destroy_v1(ctx, NULL, 0);
    grid_free(&ref);
}

/* ---------- huge global Nx: tables scale with B+Ny+Nz, not Nx ---------- */

static void test_huge_global_nx(void) {
    const int64_t NX = (int64_t)1 << 40, NY = 9, NZ = 8;
    const int64_t S = ((int64_t)1 << 39) + 3;
    const int per[3] = {1, 1, 1};
    char err[256];
    /* Six input planes shared by a small periodic slab and the huge ones. */
    grid_t small;
    grid_init(&small, 7, NY, NZ, JDIAG, per, 1);
    seeded_density(&small, 99);
    slab_t ref;
    slab_from_grid(&ref, &small, 2, 2, 1);
    CHECK(ref.xlo == 0 && ref.nxin == 6, "small periodic slab geometry");
    void *ctx = make_context(NCI_DIAGNOSTIC, 2, RHO_MIN);
    int st = slab_eval(ctx, &ref, err, sizeof err);
    CHECK(st == NCI_OK, "small slab status %d (%s)", st, err);
    const int64_t nyz = ref.nyz;

    for (int finite = 0; finite < 2; ++finite) {
        nci_tile_v1 tmpl = small.tile;
        tmpl.global_n[0] = NX;
        tmpl.periodic[0] = !finite;
        slab_t big;
        slab_alloc(&big, &tmpl, S, 2, S - 2, 6, 1);
        memcpy(sl_rho(&big), sl_rho(&ref), (size_t)ref.nin * sizeof(double));
        st = slab_eval(ctx, &big, err, sizeof err);
        CHECK(st == NCI_OK && slab_same(&big, &ref), "Nx = 2^40 %s interior slab: status %d (%s)",
              finite ? "finite" : "periodic", st, err);
        slab_free(&big);
    }

    /* Finite X ends at global coordinates near 0 and 2^40: BOUNDARY only. */
    nci_tile_v1 ftmpl = small.tile;
    ftmpl.global_n[0] = NX;
    ftmpl.periodic[0] = 0;
    const struct {
        int64_t s, b, xlo, nxin;
        const char *what;
    } ends[] = {{NX - 2, 2, NX - 4, 4, "last two planes"}, {0, 1, 0, 3, "first plane"}};
    for (size_t c = 0; c < 2; ++c) {
        slab_t end;
        slab_alloc(&end, &ftmpl, ends[c].s, ends[c].b, ends[c].xlo, ends[c].nxin, 1);
        memcpy(sl_rho(&end), sl_rho(&ref), (size_t)end.nin * sizeof(double));
        st = slab_eval(ctx, &end, err, sizeof err);
        CHECK(st == NCI_INVALID_INPUT && end.stats.total_points == end.nout &&
                  end.stats.valid_points == 0 && end.stats.bit_counts[0] == end.nout &&
                  end.stats.numeric_failures == 0 && slab_all_nan(&end),
              "Nx = 2^40 finite %s: status %d", ends[c].what, st);
        slab_check_stats(&end, st, ends[c].what);
        slab_free(&end);
    }

    /* Numeric failure diagnosed at the global point without Nx tables. */
    nci_tile_v1 ptmpl = small.tile;
    ptmpl.global_n[0] = NX;
    slab_t big;
    slab_alloc(&big, &ptmpl, S, 2, S - 2, 6, 1);
    memcpy(sl_rho(&big), sl_rho(&ref), (size_t)ref.nin * sizeof(double));
    sl_rho(&big)[2 * nyz + 4 * NZ + 4] = 1.5e308; /* global (S, 4, 4) */
    st = slab_eval(ctx, &big, err, sizeof err);
    slab_check_stats(&big, st, "Nx = 2^40 numeric failure");
    int64_t first = -1;
    for (int64_t p = 0; p < big.nout && first < 0; ++p)
        if (sl_flags(&big)[p] & NCI_POINT_NUMERIC_FAILURE) first = S * nyz + p;
    CHECK(st == NCI_NUMERIC_FAILURE && first >= 0 && message_point(err) == first,
          "Nx = 2^40 numeric failure: status %d, message '%s', expected global point %lld", st, err,
          (long long)first);
    CHECK(sl_flags(&big)[4 * NZ + 4] == NCI_POINT_NUMERIC_FAILURE, "overflowing centre fails");
    printf("huge Nx numeric failure: %s\n", err);
    slab_free(&big);
    slab_free(&ref);
    nci_context_destroy_v1(ctx, NULL, 0);
    grid_free(&small);
}

int main(void) {
    test_equivalence();
    test_invalid_only_slabs();
    test_numeric_failure_slabs();
    test_halo_preflight();
    test_rejections();
    test_alias_ranges();
    test_huge_global_nx();
    return test_report("test_slabs");
}
