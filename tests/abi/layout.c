#include "nci_api.h"
#include <stdio.h>
_Static_assert(sizeof(nci_options_v1) == 40, "options layout");
_Static_assert(offsetof(nci_options_v1, rho_min) == 24, "options padding");
_Static_assert(sizeof(nci_tile_v1) == 280, "tile layout");
_Static_assert(offsetof(nci_tile_v1, j_inv) == 152, "matrix offset");
_Static_assert(offsetof(nci_tile_v1, rho_capacity) == 240, "capacity offset");
_Static_assert(sizeof(nci_tile_stats_v1) == 88, "stats layout");
int main(void) {
    printf("ABI v1: options=%zu tile=%zu stats=%zu\n",
           sizeof(nci_options_v1), sizeof(nci_tile_v1), sizeof(nci_tile_stats_v1));
    return 0;
}
