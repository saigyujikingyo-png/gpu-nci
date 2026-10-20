# CPU X slabs (M2) — implementation notes

Status: the CPU backend implements the canonical X slabs of the
[M2 slab contract](slab-contract.md) under the unchanged C ABI v1. It is
**implemented and passes its own small synthetic native tests**. Root's combined
validation of frozen core `4150f34`, runtime `fcbecff3`, tests `30917d3` and
root `ae80fb9` also passed in GNU Debug/Release and NVHPC CPU Debug: 84 e2e and
285 oracle passes per configuration, with the one existing public-hook oracle
skip. See the root integration branch's [status](status.md). Merge is pending.
There is **no real-density acceptance, no GPU offload
and no performance measurement**; 1/2/4-thread equality is a consistency check,
not a scaling result. The header, `nci_abi` types, exported symbols, options,
formulas, thresholds and eigen policy are unchanged.

## Supported layouts

Strides are always the dense Z-fastest `[Ny*Nz, Nz, 1]`; Y and Z are complete
(`tile_start = input_origin = 0`, `tile_count = input_shape = Ny/Nz`).

| Layout | Tile X | Input X origin / shape | X neighbours |
|---|---|---|---|
| Legacy complete grid (takes precedence) | `0`, `Nx` | `0` / `Nx` | wrapped modulo `Nx` inside the input on a periodic axis |
| Periodic X slab, including `B = Nx` | `s`, `B` | `s-2` / `B+4` | input plane `k` is global `modulo(s-2+k, Nx)`, materialized by the caller; indexed directly, never wrapped inside `B` or `B+4` |
| Finite X slab | `s`, `B` | `lo=max(0,s-2)` / `min(Nx,s+B+2)-lo` | clipped; samples outside the global grid are absent, not zero-filled |

For `2 <= s` and `s+B+2 <= Nx` the periodic and finite input descriptors are
identical; `periodic[0]` then only decides the global BOUNDARY classification.
Any other origin/extent (missing, extra, shifted or wrapped halo, partial Y/Z
tiles, Y/Z halos, padded/negative/X-fastest strides) is `UNSUPPORTED`.

## Validation order of `eval`

Unchanged up to and including the dimension, periodic-flag, `Nx*Ny*Nz` and
`48*N` checks (see [CPU core](cpu-core.md)). Then, first failure wins:

| Check | Status |
|---|---|
| `tile_count < 1`, `tile_start < 0`, `start+count > global`, `input_shape < 1` | `INVALID_ARGUMENT` |
| `input_origin + input_shape` overflows int64 (checked as `origin > INT64_MAX - shape`) | `INVALID_ARGUMENT` |
| `Nin = product(input_shape)` or `8*Nin` overflows int64 | `INVALID_ARGUMENT` |
| strides other than `[Ny*Nz, Nz, 1]` | `UNSUPPORTED` |
| not the legacy grid and a partial Y/Z tile, Y/Z origin, or Y/Z shape | `UNSUPPORTED` |
| not the legacy grid and an X input other than the canonical halo above | `UNSUPPORTED` |
| `rho_capacity < Nin`; `field/flags_capacity < Nout`; DIAGNOSTIC `grad < 3*Nout`, `hess < 6*Nout` | `INVALID_ARGUMENT` |
| `j_inv` checks, then overlap of rho (`8*Nin` bytes, read) with every written range (`8*Nout`, `Nout`, `24*Nout`, `48*Nout`, stats, errbuf) | `INVALID_ARGUMENT` |
| preflight of all `Nin` supplied samples, halo included | `INVALID_INPUT`, nothing but errbuf written |

`Nout = B*Ny*Nz`. Only validated values enter arithmetic (INT64_MIN extents are
rejected by comparisons before any subtraction or product); the `-ftrapv` build
below exercises those paths. Compared with the complete-grid-only
implementation, an input shape whose product or end overflows now returns
`INVALID_ARGUMENT` instead of `UNSUPPORTED`, the unsupported-layout and
capacity messages name the specific rule, and capacities refer to `Nin`/`Nout`.

## Evaluation

There is one kernel: the complete grid is the case `s = 0`, `B = Nx`. The X
neighbour table covers only the `B` output planes and maps global `s+i+o`
(`o = -2..2`) to an input offset (legacy wrap, unwrapped periodic halo, or
`-1` outside a finite axis); the Y/Z tables are global. The three tables take
`40*(B+Ny+Nz)` bytes; if they cannot be allocated the call returns
`ALLOCATION_FAILURE` before writing any output. The same `classify_point`,
exact 61-point stencil and `point_eval` are used for every layout; no slab
formula exists. BOUNDARY uses the global coordinates `(s+i, y, z)`; outputs are
local dense Z-fastest `p = (i*Ny + y)*Nz + z` with point-major gradient/Hessian.
Stats count only the `Nout` output points, so halo planes are never counted.
Each output point reads the same samples as its full-grid counterpart. The
finite validation fixtures produce bitwise-identical full/slab values within
each tested build; this is not a full-domain proof or a cross-compiler guarantee.

Statuses are unchanged: a completed boundary-only or low-only slab returns
`INVALID_INPUT` (3) with all fields NaN, flags and stats populated
(`total = invalid = Nout`, `valid = numeric_failures = 0`); a slab with a bit-4
point returns `NUMERIC_FAILURE` (4) with flags/stats populated. Its message
names the first failing output point by its zero-based **global** Z-fastest
index `((s+i)*Ny + y)*Nz + z`, identical to the earlier message for complete
grids; the diagnosis recomputes only that point's 5-entry neighbour columns and
allocates nothing. A preflight message `rho[k]` indexes the supplied input
buffer (halo included), not the global grid.

## Caller obligations

- The library validates only the samples it is given. A caller evaluating a
  complete dataset must validate the whole density before its first slab (the
  M2 CLI uses the strict reader for that); a slab call cannot detect a bad
  sample outside its input (tested).
- Materialize the periodic halo planes, including duplicates when `B` is large.
- Initialize stats before every call and continue after status 3 only for a
  completed invalid slab as defined by the contract; stop on status 4.
- Context ownership and options are unchanged; no OpenMP global state is set.

## Tests

`core_test_slabs` (C, public ABI, guarded caller buffers; NaN guards around the
input would change results if read):

- every slab of `11x9x8` and `5x8x7` skew-J grids for six finite/periodic/mixed
  axis sets and `B = 1, 2, 3, 4, Nx-1 (10), Nx` (short tails, nondivisors, the
  periodic `B = Nx` halo with duplicate planes) equals the complete grid bit for
  bit in fields, NaN masks, gradients, Hessians and flags; per-slab stats
  describe the slab's own flags; checked sums equal the complete-grid stats and
  status; FULL and DIAGNOSTIC; 1/2/4 threads give identical results;
- accepted negative samples on X/Y/Z seams and at mixed-stencil corners across
  slab and periodic seams (the references are checked independently by
  `check_flag_semantics`);
- completed boundary-only, low-only and globally zero-valid slabs (status 3),
  numeric-failure slabs (status 4, message names the global point);
- preflight rejections in periodic and finite halo planes with untouched
  outputs/stats and the supplied-buffer index in the message;
- missing/extra/shifted halos, finite/periodic halo mismatch, partial Y/Z,
  Y halo, padded/negative/X-fastest strides, INT64_MIN/INT64_MAX in every
  extent and capacity, product/byte/global overflow, `Nin` versus `Nout`
  capacities, alias ranges extending into halo storage, adjacent accepted ranges;
- a global `Nx = 2^40` with six allocated planes: interior slabs equal a small
  grid's slab, finite ends are BOUNDARY-only, and a numeric failure is
  diagnosed at its global index (Nx-sized tables could not be allocated).

`core_test_contract` now expects the finite slab `[1,6)` of `Nx = 7` (whose
clipped halo is the whole grid) to succeed, and adds Y-slab and
periodic-without-halo `UNSUPPORTED` cases.

## Local verification

Synthetic native checks of the commit that adds this file (based on
`ae80fb9`); exact commands and logs are recorded in the local handoff:

| Build | Targeted core tests | Notes |
|---|---|---|
| GNU 13.3 Debug (`-fcheck=all`) | 6/6 passed | contract 359, fields 478, slabs 3189 checks |
| GNU 13.3 Debug `-ftrapv` (C and Fortran) | contract, fields, slabs passed | trapping int64 helpers linked |
| GNU 13.3 Release | 6/6 passed | inspection: 3 exports, no FMA/STOP/I-O/runtime-error path |
| NVHPC 26.9 Debug, CPU | 6/6 passed | same check counts |

The polynomial FNV-1a checksum of `core_test_fields` stayed `06691df4e61c091c`
in all four builds (the value recorded before this change). The unchanged
hook/quad numerics tests, the independent oracle, CLI and e2e suites were not
run here; joint acceptance is performed by the root.

## Known dependencies and limitations

- The original independent oracle's `test_initial_complete_grid_rejects_partial_layout`
  cases `tile_start` and `tile_count` describe finite X slabs whose clipped
  halo is the whole `5x7x9` grid. They are canonical supported slabs now and
  return `NCI_OK`. The separately reviewed tests branch preserves the negative
  checks using unsupported Y layouts and supplies the new positive X tests.
  Those changes are required for combined CI; this core branch alone retains
  the old oracle and does not represent the integrated source tree.
- The root integration branch updates `cpu-core.md`, `abi.md` and `status.md`;
  these sibling changes are not yet merged into this branch.
- The first runtime keeps the complete density in memory (not out of core).
  Partial Y/Z tiles, padded layouts, GPU execution and performance are out of
  scope.
