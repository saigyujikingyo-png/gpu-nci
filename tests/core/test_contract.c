/* SPDX-License-Identifier: MIT */
/* ABI v1 contract tests: argument validation, errbuf, untouched outputs,
 * preflight rejection, layout support and J inverse acceptance. */
#include "core_test_util.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

static const double JI4[9] = {4, 0, 0, 0, 4, 0, 0, 0, 4}; /* h = 0.25 bohr */
static const int FINITE[3] = {0, 0, 0};

static void smooth_density(grid_t *g) {
    for (int64_t i = 0; i < g->n[0]; ++i)
        for (int64_t j = 0; j < g->n[1]; ++j)
            for (int64_t k = 0; k < g->n[2]; ++k)
                g->rho[lin(g, i, j, k)] =
                    1.0 + 0.2 * sin(0.7 * (double)i) * cos(0.4 * (double)j) + 0.05 * (double)k;
}

static int msg_ok(const char *buf, size_t cap) {
    return memchr(buf, '\0', cap) != NULL && buf[0] != '\0';
}

static void test_create(void) {
    nci_options_v1 o = make_options(NCI_FULL, 2, 1e-8, 0.0);
    char err[128];
    void *ctx = NULL;

    int st = nci_context_create_v1(&o, &ctx, err, sizeof err);
    CHECK(st == NCI_OK && ctx != NULL, "valid create: %d", st);
    CHECK(err[0] == '\0', "success leaves an empty message");
    CHECK(nci_context_destroy_v1(ctx, err, sizeof err) == NCI_OK, "destroy");

    ctx = (void *)&o;
    st = nci_context_create_v1(NULL, &ctx, err, sizeof err);
    CHECK(st == NCI_INVALID_ARGUMENT && ctx == NULL && msg_ok(err, sizeof err),
          "NULL options: %d", st);
    st = nci_context_create_v1(&o, NULL, err, sizeof err);
    CHECK(st == NCI_INVALID_ARGUMENT && msg_ok(err, sizeof err), "NULL context: %d", st);

    ctx = (void *)&o;
    st = nci_context_create_v1(&o, &ctx, NULL, 8);
    CHECK(st == NCI_INVALID_ARGUMENT && ctx == NULL, "NULL errbuf with len>0: %d", st);
    st = nci_context_create_v1(&o, &ctx, NULL, 0);
    CHECK(st == NCI_OK && ctx != NULL, "NULL errbuf with len 0: %d", st);
    nci_context_destroy_v1(ctx, NULL, 0);

    struct {
        const char *what;
        nci_options_v1 o;
        int expect;
    } cases[32];
    int nc = 0;
#define OPTCASE(label, field, value, status)                                    \
    do {                                                                       \
        cases[nc].what = label;                                                \
        cases[nc].o = make_options(NCI_FULL, 2, 1e-8, 0.0);                    \
        cases[nc].o.field = value;                                             \
        cases[nc].expect = status;                                             \
        nc++;                                                                  \
    } while (0)
    OPTCASE("abi_version 2", abi_version, 2, NCI_INVALID_ARGUMENT);
    OPTCASE("abi_version 0", abi_version, 0, NCI_INVALID_ARGUMENT);
    OPTCASE("struct_bytes 39", struct_bytes, 39, NCI_INVALID_ARGUMENT);
    OPTCASE("struct_bytes 48", struct_bytes, 48, NCI_INVALID_ARGUMENT);
    OPTCASE("reserved 1", reserved, 1, NCI_INVALID_ARGUMENT);
    OPTCASE("backend openacc", backend, NCI_OPENACC, NCI_BACKEND_UNAVAILABLE);
    OPTCASE("backend cuda", backend, NCI_CUDA, NCI_BACKEND_UNAVAILABLE);
    OPTCASE("backend 3", backend, 3, NCI_INVALID_ARGUMENT);
    OPTCASE("backend -1", backend, -1, NCI_INVALID_ARGUMENT);
    OPTCASE("output_mode 2", output_mode, 2, NCI_INVALID_ARGUMENT);
    OPTCASE("output_mode -1", output_mode, -1, NCI_INVALID_ARGUMENT);
    OPTCASE("threads 0", omp_threads, 0, NCI_INVALID_ARGUMENT);
    OPTCASE("threads 17", omp_threads, 17, NCI_INVALID_ARGUMENT);
    OPTCASE("threads -3", omp_threads, -3, NCI_INVALID_ARGUMENT);
    OPTCASE("threads 1", omp_threads, 1, NCI_OK);
    OPTCASE("threads 16", omp_threads, 16, NCI_OK);
    OPTCASE("rho_min 0", rho_min, 0.0, NCI_INVALID_ARGUMENT);
    OPTCASE("rho_min -0", rho_min, -0.0, NCI_INVALID_ARGUMENT);
    OPTCASE("rho_min negative", rho_min, -1e-8, NCI_INVALID_ARGUMENT);
    OPTCASE("rho_min NaN", rho_min, NAN, NCI_INVALID_ARGUMENT);
    OPTCASE("rho_min Inf", rho_min, INFINITY, NCI_INVALID_ARGUMENT);
    OPTCASE("rho_min subnormal", rho_min, 4.9e-324, NCI_OK);
    OPTCASE("neg_tol negative", negative_tolerance, -1e-12, NCI_INVALID_ARGUMENT);
    OPTCASE("neg_tol NaN", negative_tolerance, NAN, NCI_INVALID_ARGUMENT);
    OPTCASE("neg_tol Inf", negative_tolerance, INFINITY, NCI_INVALID_ARGUMENT);
    OPTCASE("neg_tol -0", negative_tolerance, -0.0, NCI_OK);
    OPTCASE("neg_tol 1e-6", negative_tolerance, 1e-6, NCI_OK);
    OPTCASE("diagnostic", output_mode, NCI_DIAGNOSTIC, NCI_OK);
#undef OPTCASE
    for (int i = 0; i < nc; ++i) {
        ctx = (void *)&o;
        memset(err, 'Z', sizeof err);
        st = nci_context_create_v1(&cases[i].o, &ctx, err, sizeof err);
        CHECK(st == cases[i].expect, "%s: status %d expected %d", cases[i].what, st,
              cases[i].expect);
        if (st == NCI_OK) {
            CHECK(ctx != NULL && err[0] == '\0', "%s: context/message", cases[i].what);
            CHECK(nci_context_destroy_v1(ctx, NULL, 0) == NCI_OK, "%s: destroy", cases[i].what);
        } else {
            CHECK(ctx == NULL && msg_ok(err, sizeof err), "%s: ctx cleared and message",
                  cases[i].what);
        }
    }

    /* errbuf bounding */
    nci_options_v1 bad = make_options(NCI_FULL, 0, 1e-8, 0.0);
    memset(err, 'Z', sizeof err);
    st = nci_context_create_v1(&bad, &ctx, err, 0);
    CHECK(st == NCI_INVALID_ARGUMENT && err[0] == 'Z' && err[1] == 'Z', "len 0 untouched");
    st = nci_context_create_v1(&bad, &ctx, err, 1);
    CHECK(err[0] == '\0' && err[1] == 'Z', "len 1 writes only NUL");
    memset(err, 'Z', sizeof err);
    st = nci_context_create_v1(&bad, &ctx, err, 6);
    CHECK(strlen(err) == 5 && err[6] == 'Z', "len 6 truncates to 5 chars + NUL");
    memset(err, 'Z', sizeof err);
    st = nci_context_create_v1(&o, &ctx, err, sizeof err);
    CHECK(st == NCI_OK && err[0] == '\0' && err[1] == 'Z', "success writes one NUL");
    nci_context_destroy_v1(ctx, NULL, 0);
}

static void test_destroy(void) {
    char err[64];
    CHECK(nci_context_destroy_v1(NULL, err, sizeof err) == NCI_INVALID_ARGUMENT &&
              msg_ok(err, sizeof err),
          "destroy NULL");
    uint64_t fake[16] = {0};
    CHECK(nci_context_destroy_v1(fake, err, sizeof err) == NCI_INVALID_ARGUMENT,
          "destroy foreign pointer");
    nci_options_v1 o = make_options(NCI_FULL, 1, 1e-8, 0.0);
    void *ctx = NULL;
    nci_context_create_v1(&o, &ctx, NULL, 0);
    CHECK(nci_context_destroy_v1(ctx, NULL, 3) == NCI_INVALID_ARGUMENT,
          "destroy with NULL errbuf and len>0 rejected");
    CHECK(nci_context_destroy_v1(ctx, NULL, 0) == NCI_OK, "context still live after rejection");
}

static char last_err[256];

static int run_case(void *ctx, grid_t *g, int expect, const char *what) {
    memset(last_err, 'Z', sizeof last_err);
    grid_fill_sentinels(g);
    int st = grid_eval(ctx, g, last_err, sizeof last_err);
    CHECK(st == expect, "%s: status %d expected %d (%s)", what, st, expect,
          memchr(last_err, 0, sizeof last_err) ? last_err : "<no NUL>");
    if (expect != NCI_OK) {
        CHECK(grid_outputs_untouched(g), "%s: outputs were written", what);
        CHECK(msg_ok(last_err, sizeof last_err), "%s: missing message", what);
    }
    return st;
}

static void test_eval_arguments(void) {
    nci_options_v1 of = make_options(NCI_FULL, 3, 1e-8, 0.0);
    nci_options_v1 od = make_options(NCI_DIAGNOSTIC, 3, 1e-8, 0.0);
    void *cf = NULL, *cd = NULL;
    nci_context_create_v1(&of, &cf, NULL, 0);
    nci_context_create_v1(&od, &cd, NULL, 0);
    grid_t g, d;
    grid_init(&g, 7, 6, 5, JI4, FINITE, 0);
    grid_init(&d, 7, 6, 5, JI4, FINITE, 1);
    smooth_density(&g);
    smooth_density(&d);
    nci_tile_v1 base = g.tile, based = d.tile;
    char err[256];

    run_case(cf, &g, NCI_OK, "baseline FULL");
    run_case(cd, &d, NCI_OK, "baseline DIAGNOSTIC");

    /* contexts and mandatory pointers */
    grid_fill_sentinels(&g);
    CHECK(nci_eval_tile_f64_v1(NULL, &g.tile, g.rho, g.rdg, g.srho, g.lam2, NULL, NULL, g.flags,
                               &g.stats, err, sizeof err) == NCI_INVALID_ARGUMENT &&
              grid_outputs_untouched(&g),
          "NULL context");
    uint64_t fake[16] = {0};
    CHECK(nci_eval_tile_f64_v1(fake, &g.tile, g.rho, g.rdg, g.srho, g.lam2, NULL, NULL, g.flags,
                               &g.stats, err, sizeof err) == NCI_INVALID_ARGUMENT &&
              grid_outputs_untouched(&g),
          "foreign context");
    CHECK(nci_eval_tile_f64_v1(cf, NULL, g.rho, g.rdg, g.srho, g.lam2, NULL, NULL, g.flags,
                               &g.stats, err, sizeof err) == NCI_INVALID_ARGUMENT &&
              grid_outputs_untouched(&g),
          "NULL tile");
    double *ptrs[4] = {g.rho, g.rdg, g.srho, g.lam2};
    for (int which = 0; which < 6; ++which) {
        double *a[4] = {ptrs[0], ptrs[1], ptrs[2], ptrs[3]};
        uint8_t *fl = g.flags;
        nci_tile_stats_v1 *sp = &g.stats;
        if (which < 4) a[which] = NULL;
        if (which == 4) fl = NULL;
        if (which == 5) sp = NULL;
        int st = nci_eval_tile_f64_v1(cf, &g.tile, a[0], a[1], a[2], a[3], NULL, NULL, fl, sp,
                                      err, sizeof err);
        CHECK(st == NCI_INVALID_ARGUMENT && grid_outputs_untouched(&g) && msg_ok(err, sizeof err),
              "NULL mandatory pointer %d", which);
    }
    CHECK(nci_eval_tile_f64_v1(cf, &g.tile, g.rho, g.rdg, g.srho, g.lam2, NULL, NULL, g.flags,
                               &g.stats, NULL, 4) == NCI_INVALID_ARGUMENT &&
              grid_outputs_untouched(&g),
          "NULL errbuf with len>0");
    memset(err, 'Z', sizeof err);
    CHECK(nci_eval_tile_f64_v1(cf, &g.tile, g.rho, g.rdg, g.srho, g.lam2, NULL, NULL, g.flags,
                               &g.stats, err, 0) == NCI_OK && err[0] == 'Z',
          "errbuf len 0 untouched");

    /* output-mode pointer/capacity rules */
    double spare[6 * 210];
    grid_fill_sentinels(&g);
    CHECK(nci_eval_tile_f64_v1(cf, &g.tile, g.rho, g.rdg, g.srho, g.lam2, spare, NULL, g.flags,
                               &g.stats, err, sizeof err) == NCI_INVALID_ARGUMENT &&
              grid_outputs_untouched(&g),
          "FULL with grad");
    CHECK(nci_eval_tile_f64_v1(cf, &g.tile, g.rho, g.rdg, g.srho, g.lam2, NULL, spare, g.flags,
                               &g.stats, err, sizeof err) == NCI_INVALID_ARGUMENT &&
              grid_outputs_untouched(&g),
          "FULL with hess");
    g.tile.grad_capacity = 1;
    run_case(cf, &g, NCI_INVALID_ARGUMENT, "FULL grad_capacity 1");
    g.tile = base;
    g.tile.hess_capacity = 6 * g.npts;
    run_case(cf, &g, NCI_INVALID_ARGUMENT, "FULL hess_capacity");
    g.tile = base;
    grid_fill_sentinels(&d);
    CHECK(nci_eval_tile_f64_v1(cd, &d.tile, d.rho, d.rdg, d.srho, d.lam2, NULL, d.hess, d.flags,
                               &d.stats, err, sizeof err) == NCI_INVALID_ARGUMENT &&
              grid_outputs_untouched(&d),
          "DIAGNOSTIC without grad");
    CHECK(nci_eval_tile_f64_v1(cd, &d.tile, d.rho, d.rdg, d.srho, d.lam2, d.grad, NULL, d.flags,
                               &d.stats, err, sizeof err) == NCI_INVALID_ARGUMENT &&
              grid_outputs_untouched(&d),
          "DIAGNOSTIC without hess");
    d.tile.grad_capacity = 3 * d.npts - 1;
    run_case(cd, &d, NCI_INVALID_ARGUMENT, "grad_capacity 3N-1");
    d.tile = based;
    d.tile.hess_capacity = 6 * d.npts - 1;
    run_case(cd, &d, NCI_INVALID_ARGUMENT, "hess_capacity 6N-1");
    d.tile = based;

    /* header, dimensions, overflow, capacities */
#define TILECASE(stmt, status, label)                                          \
    do {                                                                       \
        g.tile = base;                                                         \
        stmt;                                                                  \
        run_case(cf, &g, status, label);                                       \
        g.tile = base;                                                         \
    } while (0)
    TILECASE(g.tile.abi_version = 0, NCI_INVALID_ARGUMENT, "tile abi 0");
    TILECASE(g.tile.abi_version = 2, NCI_INVALID_ARGUMENT, "tile abi 2");
    TILECASE(g.tile.struct_bytes = 279, NCI_INVALID_ARGUMENT, "tile bytes 279");
    TILECASE(g.tile.reserved = 1, NCI_INVALID_ARGUMENT, "tile reserved");
    for (int dd = 0; dd < 3; ++dd) {
        TILECASE((g.tile.global_n[dd] = 4, g.tile.tile_count[dd] = 4, g.tile.input_shape[dd] = 4),
                 NCI_INVALID_ARGUMENT, "dimension 4");
        TILECASE(g.tile.periodic[dd] = 2, NCI_INVALID_ARGUMENT, "periodic 2");
        TILECASE(g.tile.periodic[dd] = -1, NCI_INVALID_ARGUMENT, "periodic -1");
    }
    TILECASE((g.tile.global_n[0] = g.tile.global_n[1] = g.tile.global_n[2] = (int64_t)1 << 40),
             NCI_INVALID_ARGUMENT, "point count overflow");
    TILECASE((g.tile.global_n[0] = g.tile.global_n[1] = g.tile.global_n[2] = (int64_t)1 << 20),
             NCI_INVALID_ARGUMENT, "byte extent overflow");
    TILECASE((g.tile.global_n[0] = INT64_MAX, g.tile.global_n[1] = 5, g.tile.global_n[2] = 5),
             NCI_INVALID_ARGUMENT, "INT64_MAX dimension");
    TILECASE(g.tile.rho_capacity = g.npts - 1, NCI_INVALID_ARGUMENT, "rho_capacity N-1");
    TILECASE(g.tile.field_capacity = g.npts - 1, NCI_INVALID_ARGUMENT, "field_capacity N-1");
    TILECASE(g.tile.flags_capacity = g.npts - 1, NCI_INVALID_ARGUMENT, "flags_capacity N-1");
    TILECASE(g.tile.rho_capacity = -1, NCI_INVALID_ARGUMENT, "negative capacity");
    TILECASE(g.tile.rho_capacity = 2 * g.npts, NCI_OK, "larger capacity accepted");

    /* layouts: nonsensical descriptors are invalid, partial ones unsupported */
    TILECASE(g.tile.tile_count[0] = 0, NCI_INVALID_ARGUMENT, "tile_count 0");
    TILECASE(g.tile.tile_count[0] = INT64_MIN, NCI_INVALID_ARGUMENT, "tile_count INT64_MIN");
    TILECASE(g.tile.tile_start[0] = INT64_MIN, NCI_INVALID_ARGUMENT, "tile_start INT64_MIN");
    TILECASE(g.tile.tile_start[1] = -1, NCI_INVALID_ARGUMENT, "tile_start -1");
    TILECASE((g.tile.tile_start[2] = 1), NCI_INVALID_ARGUMENT, "start+count beyond grid");
    TILECASE(g.tile.input_shape[1] = 0, NCI_INVALID_ARGUMENT, "input_shape 0");
    TILECASE((g.tile.tile_start[0] = 1, g.tile.tile_count[0] = 5), NCI_UNSUPPORTED, "x slab");
    TILECASE(g.tile.tile_count[2] = 4, NCI_UNSUPPORTED, "partial z count");
    TILECASE(g.tile.input_origin[1] = 1, NCI_UNSUPPORTED, "input origin");
    TILECASE(g.tile.input_origin[0] = -2, NCI_UNSUPPORTED, "halo origin");
    TILECASE(g.tile.input_shape[0] = 9, NCI_UNSUPPORTED, "padded shape");
    TILECASE((g.tile.input_strides[0] = 1, g.tile.input_strides[1] = 7,
              g.tile.input_strides[2] = 42),
             NCI_UNSUPPORTED, "x-fastest strides");
    TILECASE(g.tile.input_strides[0] = 31, NCI_UNSUPPORTED, "padded strides");
    TILECASE(g.tile.input_strides[2] = 0, NCI_UNSUPPORTED, "zero stride");

    /* J inverse */
    TILECASE(g.tile.j_inv[4] = NAN, NCI_INVALID_ARGUMENT, "j_inv NaN");
    TILECASE(g.tile.j_inv[8] = INFINITY, NCI_INVALID_ARGUMENT, "j_inv Inf");
    TILECASE(memset(g.tile.j_inv, 0, sizeof g.tile.j_inv), NCI_INVALID_ARGUMENT, "j_inv zero");
    TILECASE((g.tile.j_inv[3] = 4, g.tile.j_inv[4] = 0), NCI_INVALID_ARGUMENT, "j_inv rank 2");
    TILECASE((g.tile.j_inv[0] = 1, g.tile.j_inv[4] = 1, g.tile.j_inv[8] = 1000),
             NCI_OK, "condition exactly 1000");
    TILECASE((g.tile.j_inv[0] = 1, g.tile.j_inv[4] = 1, g.tile.j_inv[8] = 1000.0000001),
             NCI_INVALID_ARGUMENT, "condition 1000.0000001");
    TILECASE((g.tile.j_inv[0] = -4), NCI_OK, "left-handed accepted");
    TILECASE((g.tile.j_inv[0] = 0, g.tile.j_inv[1] = 4, g.tile.j_inv[3] = 4, g.tile.j_inv[4] = 0),
             NCI_OK, "permutation accepted");
    {
        /* R diag(s) R^T with a generic rotation: accept 999.9, reject 1000.1. */
        long double a = 0.3L, b = -1.1L, c = 0.7L;
        long double rz[9] = {cosl(a), -sinl(a), 0, sinl(a), cosl(a), 0, 0, 0, 1};
        long double ry[9] = {cosl(b), 0, sinl(b), 0, 1, 0, -sinl(b), 0, cosl(b)};
        long double rx[9] = {1, 0, 0, 0, cosl(c), -sinl(c), 0, sinl(c), cosl(c)};
        long double t[9], r[9];
        for (int i = 0; i < 3; ++i)
            for (int j = 0; j < 3; ++j) {
                t[3 * i + j] = 0;
                for (int k = 0; k < 3; ++k) t[3 * i + j] += rz[3 * i + k] * ry[3 * k + j];
            }
        for (int i = 0; i < 3; ++i)
            for (int j = 0; j < 3; ++j) {
                r[3 * i + j] = 0;
                for (int k = 0; k < 3; ++k) r[3 * i + j] += t[3 * i + k] * rx[3 * k + j];
            }
        const long double smax[2] = {999.9L, 1000.1L};
        const int expect[2] = {NCI_OK, NCI_INVALID_ARGUMENT};
        for (int c2 = 0; c2 < 2; ++c2) {
            long double s[3] = {2.0L, 4.0L, 2.0L * smax[c2]};
            g.tile = base;
            for (int i = 0; i < 3; ++i)
                for (int j = 0; j < 3; ++j) {
                    long double v = 0;
                    for (int k = 0; k < 3; ++k) v += r[3 * i + k] * s[k] * r[3 * j + k];
                    g.tile.j_inv[3 * i + j] = (double)v;
                }
            run_case(cf, &g, expect[c2], c2 ? "rotated condition 1000.1" : "rotated 999.9");
            /* scale invariance of the acceptance decision */
            for (int i = 0; i < 9; ++i) g.tile.j_inv[i] *= 0x1p-600;
            run_case(cf, &g, c2 ? NCI_INVALID_ARGUMENT : NCI_OK, "scaled by 2^-600");
            g.tile = base;
        }
    }
#undef TILECASE

    /* overlapping buffers */
    grid_fill_sentinels(&g);
    CHECK(nci_eval_tile_f64_v1(cf, &g.tile, g.rho, g.rdg, g.rdg, g.lam2, NULL, NULL, g.flags,
                               &g.stats, err, sizeof err) == NCI_INVALID_ARGUMENT &&
              grid_outputs_untouched(&g),
          "rdg == signedrho");
    CHECK(nci_eval_tile_f64_v1(cf, &g.tile, g.rho, g.rdg, g.srho, g.rho, NULL, NULL, g.flags,
                               &g.stats, err, sizeof err) == NCI_INVALID_ARGUMENT &&
              grid_outputs_untouched(&g),
          "lambda2 aliases rho");
    CHECK(nci_eval_tile_f64_v1(cf, &g.tile, g.rho, g.rdg, g.srho, g.lam2, NULL, NULL,
                               (uint8_t *)(g.rdg + g.npts - 1), &g.stats, err,
                               sizeof err) == NCI_INVALID_ARGUMENT,
          "flags overlapping the end of rdg");
    CHECK(grid_outputs_untouched(&g), "overlap left outputs untouched");
    grid_fill_sentinels(&g);
    CHECK(nci_eval_tile_f64_v1(cf, &g.tile, g.rho, g.rdg, g.srho, g.lam2, NULL, NULL, g.flags,
                               &g.stats, (char *)g.lam2, 64) == NCI_INVALID_ARGUMENT &&
              grid_outputs_untouched(&g),
          "errbuf inside lambda2 is neither used nor written");
    grid_fill_sentinels(&d);
    CHECK(nci_eval_tile_f64_v1(cd, &d.tile, d.rho, d.rdg, d.srho, d.lam2, d.grad, d.grad + 3,
                               d.flags, &d.stats, err, sizeof err) == NCI_INVALID_ARGUMENT &&
              grid_outputs_untouched(&d),
          "grad/hess overlap");

    /* preflight */
    const double badvals[3] = {NAN, INFINITY, -INFINITY};
    for (int i = 0; i < 3; ++i) {
        double keep = g.rho[17], keep90 = g.rho[90];
        g.rho[17] = badvals[i];
        g.rho[90] = badvals[2 - i];
        run_case(cf, &g, NCI_INVALID_INPUT, "non-finite density");
        CHECK(strstr(last_err, "rho[17]") != NULL, "message names the first bad sample: %s",
              last_err);
        g.rho[17] = keep;
        g.rho[90] = keep90;
    }
    g.rho[40] = -1e-300;
    run_case(cf, &g, NCI_INVALID_INPUT, "negative sample with zero tolerance");
    g.rho[40] = 1.0;
    nci_options_v1 ot = make_options(NCI_FULL, 2, 1e-8, 1e-6);
    void *ct = NULL;
    nci_context_create_v1(&ot, &ct, NULL, 0);
    g.rho[40] = -2e-6;
    run_case(ct, &g, NCI_INVALID_INPUT, "sample below -tolerance");
    g.rho[40] = -1e-6;
    grid_fill_sentinels(&g);
    int st = grid_eval(ct, &g, err, sizeof err);
    check_flag_semantics(&g, FINITE, 1e-8, st);
    CHECK(g.flags[40] & NCI_STENCIL_INVALID, "sample at exactly -tolerance accepted and flagged");
    g.rho[40] = -0.0;
    grid_fill_sentinels(&g);
    st = grid_eval(cf, &g, err, sizeof err);
    check_flag_semantics(&g, FINITE, 1e-8, st);
    CHECK(g.flags[40] == (NCI_NONPOSITIVE_RHO | (g.flags[40] & NCI_BOUNDARY)),
          "-0.0 is a zero sample, not a negative tail: flags 0x%02x", g.flags[40]);
    g.rho[40] = 1.0;

    nci_context_destroy_v1(ct, NULL, 0);
    nci_context_destroy_v1(cf, NULL, 0);
    nci_context_destroy_v1(cd, NULL, 0);
    grid_free(&g);
    grid_free(&d);
}

int main(void) {
    test_create();
    test_destroy();
    test_eval_arguments();
    return test_report("test_contract");
}
