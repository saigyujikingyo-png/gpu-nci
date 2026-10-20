# M2 CPU X-slab contract

This extends supported layouts under the unchanged C ABI v1. It does not change
the density model, finite differences, Cartesian transforms, eigensolver, masks
or uncertainty policy. Separate implementation branches passed the finite
synthetic checks recorded in [status](status.md); their merge is pending. The first
runtime retains the complete density array; it is not an out-of-core reader.

## Supported input and output layouts

The existing dense full-grid descriptor and results remain supported unchanged.
The additional layout is an X slab of the global Nx by Ny by Nz grid:

- `tile_start = [s,0,0]`, `tile_count = [B,Ny,Nz]`, with `0 <= s < Nx` and
  `1 <= B <= Nx-s`. Y/Z partial tiles and padded/negative strides are unsupported.
- Y/Z input origin is zero and input shape is Ny/Nz. Input strides are exactly
  `[Ny*Nz,Nz,1]`. Full Y/Z coverage supplies mixed-derivative corner samples;
  periodic Y/Z lookup always uses the global Ny/Nz.
- For periodic X, `input_origin[0]=s-2`, `input_shape[0]=B+4`. Plane k in that
  dense input represents global `modulo(s-2+k,Nx)`. The caller materializes the
  two halo planes on each side, including duplicate planes when B is large.
  The backend indexes this unwrapped buffer, never wraps within B or B+4.
- For finite X, the canonical input starts at `lo=max(0,s-2)` and ends before
  `hi=min(Nx,s+B+2)`. Its X shape is `hi-lo`. Outside-global samples are absent,
  not zero-filled. Boundary flags depend on global coordinates, not slab edges.
- A legacy complete-grid descriptor takes precedence when it exactly matches
  the original dense form. A periodic B=Nx halo descriptor is also supported.
  Other origins/extents, including missing or extra halo, are unsupported.

The supplied input has Nin=product(input_shape) samples; outputs have
Nout=B*Ny*Nz. All capacities, C pointer mappings, byte ranges and preflight loops
must distinguish Nin from Nout. Outputs are local dense Z-fastest arrays; grad
and Hessian remain point-major xyz and xx,yy,zz,xy,xz,yz. Only output points
contribute to stats; overlapping halo planes never contribute twice.

Products, byte extents, endpoints and capacity arithmetic are checked before
pointer mapping or allocation. Reject malformed bounds/overflow/short capacities
with INVALID_ARGUMENT and unsupported well-formed layouts with UNSUPPORTED,
without changing fields or stats. Retain the existing conservative global
N*48 signed-int64 limit as well as checking actual Nin/Nout extents. No C struct
layout, exported symbol, options field or scientific threshold changes.

## Preflight, statuses and aggregation

The C function preflights every supplied input sample, including halos, before
writing outputs. It cannot establish the validity of density outside that input.
A caller evaluating a complete dataset must validate the complete original
density before its first slab writes. The M2 CLI achieves this with the existing
strict reader and metadata validation before beginning the slab loop.

Each tile call retains existing status semantics. In particular a completed
finite boundary-only slab can return INVALID_INPUT (3) with populated stats,
zero valid points and fully populated invalid fields. A full-run scheduler may
continue only when stats.total=Nout, valid=0, invalid=Nout, numeric_failures=0
and flags/stats consistently describe that completed invalid slab. It must not
continue after an input-preflight failure or arbitrary status3. Initialize stats
before every call so a previous completed slab cannot mask a preflight failure.

The scheduler visits increasing X starts without gaps/overlap, appends only the
output planes, and aggregates all counts with checked arithmetic. Successful
completion requires total=global N, at least one valid point and no numeric
failure. Entirely invalid global output remains status3/failed, with no SUCCESS.
Any numeric failure (4) stops the run and preserves failure status and available
diagnostics. On failure, native npoints is global N and populated stats describe
completed computation, including an evaluated ABI4 slab. They do not guarantee
that every corresponding byte was written. Partial files are not successful.

Context ownership remains one create and one destroy, including errors. Input
rho, options and geometry remain immutable. The same point evaluator and
61-point stencil must be used; no independent slab numerical formula is added.

## Offline CLI extension

Existing schema1 `compute.layout="full_grid"` cards remain unchanged, with exactly
their original compute keys. New `compute.layout="x_slabs"` cards additionally
require `slab_planes`, an integer in 1..Nx (not bool). Missing, extra, noninteger
or out-of-range values are rejected. `slab_planes` is forbidden in full_grid.
The last block uses min(slab_planes,Nx-s); no adaptive block-size change/retry.

The internal namelist adds layout_mode (0 full grid, 1 X slabs) and slab_planes;
defaults 0/0 preserve old full-grid settings. Full mode requires slab_planes=0;
slab mode requires 1..Nx. The Python settings renderer need only emit the new
keys for x_slabs. Manifest schema/keys and raw output names, units and global
shapes remain unchanged; manifest.compute records the original declared layout
and slab size. This is an extension of executable capability, not certification.

Before evaluating, allocate at most one slab input and one set of output arrays.
Create each raw output stream exclusively once, append blocks in global order,
check writes and closes, retain byte-wise little-endian output, then publish the
existing native receipt. The Python integrity/success gate is unchanged. Failures
retain files but never publish SUCCESS. Do not create an additional large array
through RESHAPE, TRANSPOSE or whole-field TRANSFER while writing diagnostic data.

For requested B=slab_planes, P=Ny*Nz, reserve the following worst-case tracked
allocation before the reader allocates density or atom arrays:

`8*N + 8*(B+4)*P + Q*B*P + 40*(B+Ny+Nz) + 8192 + atom_bytes + 65536 + 4096*T`

where Q=25 for full output, Q=97 for diagnostic, and T=omp_threads. The complete
rho array is 8*N; the extra input copy uses at most B+4 planes even at finite
boundaries. Neighbor tables must be proportional to B+Ny+Nz, not global Nx.
Use checked int64 arithmetic at each multiply/add. Set the reader's per-point
and per-axis reservations to zero and put the extra slab/table/fixed reservation
in reserve_fixed_bytes; its existing density, scanner and atom accounting remain.
The Python lower bound excludes only unknown atom storage. This is tracked-array
accounting plus allowances, not a bound on all process RSS. Full-grid reservations
remain unchanged. This milestone reduces field buffers, not the reader's 8*N.

## Independent finite synthetic acceptance

Use small non-cubic grids and skew J. Independently pack slabs and compare
concatenated raw fields, NaN masks, flags and summed stats against full-grid
execution and the existing independent mathematical oracle. Include B=1, odd B,
nondivisors, B=Nx, short tails, all finite/all periodic/mixed axes and Nx=5;
accepted negative samples crossing a slab/periodic seam and mixed-stencil corners;
all-invalid boundary-only slabs, global zero-valid output and numeric failure.
Check 1/2/4-thread consistency without calling it a scaling benchmark.

Validate missing/wrong halo, Y/Z partial layouts, padded strides, INT64_MIN,
overflow, input/output capacities and alias ranges extending into halo storage.
Preflight-failure tests preserve caller buffers; all tests preserve source input.
Completed ABI3/4 calls retain their defined fields and stats. Real CLI tests compare global
output files and receipts for both modes and slab sizes, exercise whole-input
preflight before first output, and verify memory-budget boundary arithmetic.
Keep the original declared FP64 tolerance gates; no tuning after failed runs.

Only small synthetic tests are agent-run. Real-density studies and performance
measurements remain separately frozen user-launched packages. GPU execution,
OpenMP speedup and scientific acceptance are not implied by CPU slab equivalence.
