# M1 offline CLI protocol (version 1)

This freezes the integration interface, without changing the numerical design or
the public C ABI. Only the full-grid CPU path is in scope. Synthetic development
tests are not scientific acceptance or performance measurements.

## Command and ownership

`python cli/nci_cli.py run --card CARD.json --driver NCI_DRIVER --output-dir NEWDIR`

Use Python 3.12 standard library only at runtime. Python owns JSON, provenance,
snapshotting, process limits and final receipts. The Fortran executable owns the
existing CUBE reader/metadata validation and calls the three public C ABI symbols.
It must not call private CPU implementation routines. Do not duplicate the CUBE
parser in Python. Paths are passed as subprocess argument arrays, never a shell.
Card input paths are relative to the card's parent; other relative paths are
relative to the invoking working directory. The output parent must exist and the
output directory must not exist. Never overwrite an existing output directory.

## Exact execution-card schema

Every listed field is required; reject unknown fields at every level, duplicate
keys, nonfinite numbers, nulls, and booleans in numeric fields. JSON size is at
most 1 MiB. Integers are exact JSON integers. Floating inputs may also be integers.

```json
{
  "schema_version": 1,
  "input": {
    "path": "fixture.cube",
    "sha256": "64 lowercase hexadecimal characters",
    "bytes": 12345,
    "source": {
      "kind": "synthetic",
      "reference": "local analytical fixture",
      "permission": "generated for this test",
      "producer": "fixture generator",
      "producer_version": "1",
      "settings": "analytical formula and parameters",
      "density_precision": "unknown"
    }
  },
  "grid": {
    "shape": [7, 9, 11],
    "origin": [0.0, 0.0, 0.0],
    "step_vectors": [[0.25, 0.0, 0.0], [0.0, 0.25, 0.0], [0.0, 0.0, 0.25]],
    "axis_order": "z_fastest"
  },
  "metadata": {
    "quantity": "electron_density",
    "spin_convention": "spin_summed",
    "density_representation": "all_electron",
    "length_unit": "bohr",
    "density_unit": "electron/bohr^3",
    "periodic": [0, 0, 0],
    "endpoint_convention": ["finite_nodes", "finite_nodes", "finite_nodes"]
  },
  "compute": {
    "backend": "cpu",
    "layout": "full_grid",
    "output_mode": "diagnostic",
    "rho_min": 1e-12,
    "negative_tolerance": 0.0,
    "omp_threads": 1
  },
  "limits": {
    "memory_budget_bytes": 16777216,
    "max_points": 100000,
    "timeout_seconds": 60
  }
}
```

Source kind is `synthetic`, `public`, or `user_authorized`. All source strings
are nonempty and at most 4096 characters; input path is nonempty. Declarations
are recorded, not authenticated. Do not infer missing precision information.
Representation is `all_electron`, `valence`, `core_augmented`, or `promolecular`.
Periodic 0 requires `finite_nodes`; 1 requires `independent_samples`. Axes have
at least five points. Positive sizes, capacities and their products fit signed
int64; product(shape) must not exceed max_points. rho_min is finite and positive;
negative_tolerance finite and nonnegative. Threads are 1..16; timeout is an
integer 1..3600 seconds. Output mode is `full` or `diagnostic`. Other literal
values in the example are fixed enums, except geometry and source declarations.
Step vectors are the CUBE axis vectors: each listed vector is one column of J.

## Input binding and internal worker protocol

Create NEWDIR exclusively. Freeze original card bytes as `card.json`. Stream
copy input to `input.cube`, computing and checking its byte count and SHA-256
against the card. The worker only reads this snapshot. Recheck its hash before
success. Original card/input are never written. Reject a snapshot mismatch.

The private executable invocation is:
`nci_driver NEWDIR/input.cube NEWDIR/settings.nml NEWDIR`

`settings.nml` has one Fortran namelist `/nci_run/`, with exactly these variables:
`protocol_version` (1), `shape(3)` (int64), `origin(3)` (real64),
`step_vectors(3,3)` (real64: columns are axis vectors), `periodic(3)` (int),
`endpoint_convention(3)` (character), `quantity`, `spin_convention`,
`density_representation`, `length_unit`, `density_unit` (character),
`output_mode` (0 full / 1 diagnostic), `rho_min`, `negative_tolerance` (real64),
`omp_threads` (int), `memory_budget_bytes`, `max_points` (int64).
Python writes real values with 17 significant digits and Fortran-compatible
exponents. Only validated enums enter quoted namelist strings. The worker
validates its own protocol and values. It compares actual shape exactly and
actual origin/J elementwise by parsed binary64 numerical equality. The 17-digit
namelist serialization round-trips these declarations. No absolute epsilon
floor is permitted: it could hide a factor-of-two change to a very small J.
It validates metadata using the same negative tolerance passed to the ABI.

Reader limits gain nonnegative int64 reservations (default zero, preserving
existing callers): `reserve_bytes_per_point`, `reserve_bytes_per_axis_node`,
`reserve_fixed_bytes`. The reader's existing header budget check includes these
with checked arithmetic **before** allocating atoms or density. Worker reserves
25 bytes/point in full mode or 97 in diagnostic mode, 40 bytes per axis node,
and 65536 + 4096*omp_threads fixed bytes, in addition to the reader's existing
8*N density, atom storage and 8192 scanner allowance. This covers explicitly
tracked arrays (33*N or 105*N total), CPU neighbor tables and an allowance;
it is not a hard whole-process RSS limit. Output allocations use STAT checks.

Use `nci_abi` BIND(C) types with explicit interfaces to the public symbols.
Pack j_inv row-major explicitly. Use diagnostics shaped (3,N)/(6,N), flags
one byte/point. Every created context is destroyed exactly once, including on
failure. Allocation or cleanup failure must not erase the original error.

## Raw fields and native receipt

Write unformatted stream files, little-endian IEEE binary64 / uint8, Z-fastest:
`rdg.f64`, `lambda2.f64`, `signedrho.f64`, `flags.u8`; diagnostic mode adds
`grad.f64` (gx,gy,gz point-major) and `hess.f64` (xx,yy,zz,xy,xz,yz point-major).
The expected lengths are 8*N for each scalar, N for flags, 24*N/48*N for grad/H.
Detect unsupported byte order or representation and fail explicitly. All file
creation is exclusive (`status='new'`); check writes and closes. Invalid raw
values, including diagnostic NaNs, and the entire flag byte are preserved.
Do not serialize floating output values as JSON.

Write `native.json`, including on a handled failure after launch, with required
keys: `protocol_version` (1), `state` (`completed` or `failed`), `stage` (string),
`message` (string), `abi_status` (integer or null if not called), `npoints`
(integer, zero before input acceptance), `stats` (null before evaluation or
object with `total`, `valid`, `invalid`, `numeric_failures`, `bit_counts` array
of seven integers). Success requires abi_status=0 and valid+invalid=total=N.
Numerical failure (ABI status 4) may retain raw diagnostics for inspection but
must exit nonzero, state failed, and never produce SUCCESS. Expected boundary
and low-density masks do not fail evaluation when at least one valid point
remains. A zero-valid-point field follows the existing ABI status 3 and fails
without SUCCESS. Invalid source/metadata,
memory, numerical and IO failures have distinguishable stage/message fields.

`nci_driver --build-info` emits one JSON object to stdout, then exits 0, with
`protocol_version`, `source_revision` (CMake NCI_BUILD_REVISION or `UNKNOWN`),
`compiler_id`, `compiler_version`, `build_type`, `fp_policy`, `backend_library`
(absolute built shared-library path). JSON-escape all strings. This compiled
build description is a declaration, not cryptographic build authentication.
The public contract's floating-point policy remains unchanged. Unset loader
injection variables LD_PRELOAD and LD_LIBRARY_PATH for the child and use the
build's runtime library path. Record SHA-256/size of driver and declared backend
library; UNKNOWN revision remains explicitly unknown, never fabricated.

## Final receipt and failure behavior

Python captures `stdout.log`/`stderr.log`, applies the declared timeout to its
own worker, and records exit/timeout. Build-info probe is bounded to 10 seconds.
Write `manifest.json` with schema_version=1, state `running`, `failed`, or
`completed_numerical`, stage/message, original card SHA/size, input SHA/size,
explicit grid/metadata/compute/limits/source declarations, build info and binary
fingerprints, worker return code, native receipt and output file sizes/hashes.
Unknown scientific uncertainty is recorded; success is numerical completion only.
The exact top-level manifest keys are `schema_version`, `state`, `stage`,
`message`, `card`, `input`, `grid`, `metadata`, `compute`, `limits`, `source`,
`build`, `binaries`, `worker`, `native`, `settings`, `outputs`, `scientific`.
`card` is `{path,sha256,bytes}`; `input` adds `snapshot:"input.cube"` to those
keys. `grid/metadata/compute/limits/source` retain the card declarations.
`build` is the build-info object; `binaries` has `driver` and `backend_library`
objects, each `{path,sha256,bytes}`. `worker` is
`{returncode,timed_out,timeout_seconds}`; `native` is the native receipt;
`settings` is `{path:"settings.nml",sha256,bytes}`. Unknown objects on failure
are null; `outputs` starts as an empty object. `scientific` is
`{certified:false,uncertainty:"unknown",completion:"numerical_only"}`.
`outputs` is indexed by filename; entries have `sha256`, `bytes`,
`dtype` (`float64` or `uint8`), `byte_order` (`little`), `shape`
([Nx,Ny,Nz] or [Nx,Ny,Nz,3/6]), `component_order`, `unit`, `point_order`
(`z_fastest`), `storage_order` (`point_major`). Component arrays are
`[rdg]`, `[lambda2]`, `[signedrho]`, `[flag_byte]`, `[gx,gy,gz]`, or
`[xx,yy,zz,xy,xz,yz]`. Units are dimensionless for RDG/flags,
electron/bohr^3 for signedrho, electron/bohr^4 for gradients and
electron/bohr^5 for lambda2/Hessian.
Manifest replacements are atomic and limited to this newly owned directory.
Before success, require worker exit 0, valid native receipt and statistics,
correct field byte sizes/hashes, unchanged input snapshot and binaries. Validate
integer statistics (nonnegative, counts <= N, union valid+invalid=N) without
loading complete result arrays. Tests independently inspect actual field values.
Successful receipts also require native.state=`completed`,
0 < valid <= N, total=npoints=N, numeric_failures=bit_counts[4]=0,
each of bits 0..4 counts <= invalid, bit_counts[5] <= valid, and
bit_counts[6]=valid (the current backend marks scientific uncertainty at every
valid point). These small-JSON checks reject contradictory success receipts.
Then publish completed_numerical manifest and create `SUCCESS` exclusively,
containing the final manifest SHA-256 followed by newline. CLI exits 0 only then.

Handled failures exit nonzero, preserve failure receipt/logs and partial output,
and never create SUCCESS. Existing output directories are untouched, including
on failure. An interruption without final manifest/SUCCESS is incomplete, not
success. Timeout only stops the CLI's own worker, never unrelated applications.
No driver, CLI or test performs a benchmark or electronic-structure calculation.

## Acceptance and deferred work

Independent small tests exercise noncubic skew quadratic and mixed-periodic
Fourier inputs, both modes, byte order/point order/component order, analytic or
discrete-stencil derivatives, masks/statistics and hashes. Negative tests cover
strict schema, units, metadata/hash mismatch, allocation reservation, numerical
overflow, output collision, immutable sources and absence of false success.
Actual scientific cases, GPU fields, speedup measurements and RESEARCH_HANDOFF.md
remain behind the existing later gates.
