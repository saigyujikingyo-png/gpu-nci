/* SPDX-License-Identifier: MIT */
/* Independent contexts used concurrently from several POSIX threads (each
 * with its own OpenMP team) must reproduce the serial results bit for bit:
 * no cross-context or module-level mutable state. */
#include "core_test_util.h"
#include <math.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>

#define NJOBS 4
#define REPEATS 3

typedef struct {
    grid_t g;
    int mode, threads;
    double *ref[5];
    uint8_t *ref_flags;
    int bad_status, bad_output;
} job_t;

static int eval_once(job_t *j) {
    nci_options_v1 o = make_options(j->mode, j->threads, 1e-8, 1e-6);
    void *ctx = NULL;
    if (nci_context_create_v1(&o, &ctx, NULL, 0) != NCI_OK) return -1;
    grid_t *g = &j->g;
    int st = nci_eval_tile_f64_v1(ctx, &g->tile, g->rho, g->rdg, g->srho, g->lam2,
                                  g->diag ? g->grad : NULL, g->diag ? g->hess : NULL, g->flags,
                                  &g->stats, NULL, 0);
    if (nci_context_destroy_v1(ctx, NULL, 0) != NCI_OK) return -2;
    return st;
}

static void *worker(void *arg) {
    job_t *j = arg;
    size_t n = (size_t)j->g.npts;
    for (int r = 0; r < REPEATS; ++r) {
        grid_fill_sentinels(&j->g);
        if (eval_once(j) != NCI_OK) j->bad_status++;
        double *out[5] = {j->g.rdg, j->g.srho, j->g.lam2, j->g.grad, j->g.hess};
        size_t len[5] = {n, n, n, 3 * n, 6 * n};
        for (int a = 0; a < 5; ++a)
            if (out[a] && memcmp(out[a], j->ref[a], len[a] * sizeof(double)) != 0) j->bad_output++;
        if (memcmp(j->g.flags, j->ref_flags, n) != 0) j->bad_output++;
    }
    return NULL;
}

int main(void) {
    static const double JI[NJOBS][9] = {{2.0, 0.3, -0.1, 0.2, 2.5, 0.4, -0.3, 0.1, 1.8},
                                        {3, 0, 0, 0, 3, 0, 0, 0, 3},
                                        {-2.2, 0.4, 0.0, 0.1, 1.9, -0.6, 0.3, 0.2, 2.4},
                                        {1.5, 0, 0.2, 0, 1.6, 0, -0.2, 0, 1.7}};
    static const int PER[NJOBS][3] = {{1, 1, 1}, {0, 0, 0}, {1, 0, 1}, {0, 1, 0}};
    static const int64_t DIM[NJOBS][3] = {{12, 11, 10}, {13, 9, 11}, {10, 12, 9}, {11, 10, 13}};
    job_t jobs[NJOBS];
    memset(jobs, 0, sizeof jobs);
    uint64_t seed = 99;
    for (int k = 0; k < NJOBS; ++k) {
        job_t *j = &jobs[k];
        j->mode = (k % 2) ? NCI_FULL : NCI_DIAGNOSTIC;
        j->threads = 1 + k;
        grid_init(&j->g, DIM[k][0], DIM[k][1], DIM[k][2], JI[k], PER[k],
                  j->mode == NCI_DIAGNOSTIC);
        for (int64_t p = 0; p < j->g.npts; ++p)
            j->g.rho[p] = 0.7 + lcg_uniform(&seed) + 0.5 * sin(0.01 * (double)p);
        j->g.rho[7] = -5e-7; /* exercise the negative-tail path as well */
        int st = eval_once(j);
        CHECK(st == NCI_OK, "serial reference %d: status %d", k, st);
        size_t n = (size_t)j->g.npts;
        double *out[5] = {j->g.rdg, j->g.srho, j->g.lam2, j->g.grad, j->g.hess};
        size_t len[5] = {n, n, n, 3 * n, 6 * n};
        for (int a = 0; a < 5; ++a) {
            if (!out[a]) continue;
            j->ref[a] = malloc(len[a] * sizeof(double));
            memcpy(j->ref[a], out[a], len[a] * sizeof(double));
        }
        j->ref_flags = malloc(n);
        memcpy(j->ref_flags, j->g.flags, n);
        check_flag_semantics(&j->g, PER[k], 1e-8, st);
    }
    pthread_t tid[NJOBS];
    for (int k = 0; k < NJOBS; ++k)
        CHECK(pthread_create(&tid[k], NULL, worker, &jobs[k]) == 0, "pthread_create %d", k);
    for (int k = 0; k < NJOBS; ++k) pthread_join(tid[k], NULL);
    for (int k = 0; k < NJOBS; ++k) {
        CHECK(jobs[k].bad_status == 0, "job %d: %d non-OK statuses", k, jobs[k].bad_status);
        CHECK(jobs[k].bad_output == 0, "job %d: %d outputs differ from serial", k,
              jobs[k].bad_output);
        for (int a = 0; a < 5; ++a) free(jobs[k].ref[a]);
        free(jobs[k].ref_flags);
        grid_free(&jobs[k].g);
    }
    return test_report("test_concurrency");
}
