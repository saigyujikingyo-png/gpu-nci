#ifndef NCI_API_H
#define NCI_API_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

#define NCI_ABI_VERSION 1
enum nci_status {
    NCI_OK = 0, NCI_INVALID_ARGUMENT = 1, NCI_UNSUPPORTED = 2,
    NCI_INVALID_INPUT = 3, NCI_NUMERIC_FAILURE = 4,
    NCI_ALLOCATION_FAILURE = 5, NCI_BACKEND_UNAVAILABLE = 6
};
enum nci_backend { NCI_CPU = 0, NCI_OPENACC = 1, NCI_CUDA = 2 };
enum nci_output_mode { NCI_FULL = 0, NCI_DIAGNOSTIC = 1 };
enum nci_flag {
    NCI_BOUNDARY = 1, NCI_NONPOSITIVE_RHO = 2, NCI_LOW_RHO = 4,
    NCI_STENCIL_INVALID = 8, NCI_POINT_NUMERIC_FAILURE = 16,
    NCI_LAMBDA_NUM_UNCERTAIN = 32, NCI_LAMBDA_SCI_UNCERTAIN = 64
};

typedef struct {
    int32_t abi_version, struct_bytes, backend, output_mode;
    int32_t omp_threads, reserved;
    double rho_min, negative_tolerance;
} nci_options_v1;

typedef struct {
    int32_t abi_version, struct_bytes;
    int64_t global_n[3], tile_start[3], tile_count[3];
    int64_t input_origin[3], input_shape[3], input_strides[3];
    double j_inv[9]; /* row-major inverse; J columns are physical steps */
    int32_t periodic[3], reserved;
    int64_t rho_capacity, field_capacity, flags_capacity;
    int64_t grad_capacity, hess_capacity; /* element counts, not bytes */
} nci_tile_v1;

typedef struct {
    int64_t total_points, valid_points, invalid_points, numeric_failures;
    int64_t bit_counts[7]; /* counts can overlap */
} nci_tile_stats_v1;

int nci_context_create_v1(const nci_options_v1 *options, void **context,
                         char *errbuf, size_t errbuf_len);
int nci_eval_tile_f64_v1(void *context, const nci_tile_v1 *tile,
                       const double *rho, double *rdg, double *signedrho,
                       double *lambda2, double *grad, double *hess,
                       uint8_t *flags, nci_tile_stats_v1 *stats,
                       char *errbuf, size_t errbuf_len);
int nci_context_destroy_v1(void *context, char *errbuf, size_t errbuf_len);
#ifdef __cplusplus
}
#endif
#endif
