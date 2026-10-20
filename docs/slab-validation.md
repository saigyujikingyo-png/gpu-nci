# M2 independent slab validation freeze

State: **COMBINED_SYNTHETIC_PASS_MERGE_PENDING**. This suite was authored
against `docs/slab-contract.md` at base
`ae80fb929ca5ba12de247a2786117a452ac1e4d6`, before accepting the new production
backend or runtime. Root subsequently executed the frozen tests against the
actual core and runtime as recorded below. No real-density calculation, electronic-structure solver, GPU execution
or performance measurement is included or implied.

## Independent inputs and gates

`tests/oracle/slab_cases.py` copies each halo plane explicitly from the original
global array using the contract's modulo/clipped coordinates. It does not import
the production packer, backend implementation, CLI renderer or driver code.
References come from the existing independent `reference.fields` Fourier symbols,
FD4 implementation and NCI reference. The C binding is the existing public-only
`reference.abi` mirror. Mathematical gates retain the original fixed tolerances:

- Gradient, Hessian and lambda2: atol `1e-12`, rtol `1e-10`.
- RDG: atol `1e-11`, rtol `1e-9`.
- Reference sign comparison excludes only the existing fixed `abs(lambda2)<=1e-9`
  fixture band; raw signedrho always equals sign(actual lambda2)*original rho.
- Same-build full/slab and 1/2/4-thread comparisons require identical flags,
  identical NaN masks and identical binary64 bits for finite values. CLI raw
  output record hashes must also match, including NaN serialization. These gates
  are fixed before production integration and must not be relaxed after failure.

## Public C ABI coverage

`tests/oracle/test_x_slabs.py` contains 150 cases:

- All eight finite/periodic axis combinations on skew noncubic 7x9x11 data,
  B=1/3/4/7, full and diagnostic output. This covers odd blocks, nondivisors,
  short tails, full Nx and canonical periodic halo descriptors.
- Nx=5 on 5x7x9 data with B=1/3/5, including duplicated periodic halo planes;
  1/2/4-thread nontrivial field consistency without clocks or speedup claims.
- Allowed negatives across slab boundaries, periodic seams and mixed derivative
  corners. Exact independent stencil flags distinguish two-axis from three-axis
  corners. Source rho, options and geometry descriptors must remain unchanged.
- Full concatenation and summed stats; finite boundary-only ABI3 slabs with
  populated invalid fields; entirely invalid global outputs; actual binary64 RDG
  overflow producing ABI4 with completed slab stats and invalid diagnostic fields.
- Missing/extra halo, incorrect origins, partial Y/Z, padded/negative strides,
  at left/interior/right X positions for finite and periodic X. All five input
  and output capacity contracts are checked at required-minus-one.
- NaN, infinity and significantly negative samples in both extreme halo planes
  must fail preflight without changing outputs or caller stats.
- Every output pointer aliases the last supplied halo element in turn. This
  catches overlap checks that incorrectly limit input range to Nout instead of
  Nin. Caller storage and stats must remain unchanged.
- Isolated child processes check INT64_MIN start/count/origin/shape, overflowing
  global and input products, the retained global N*48 limit, and huge halo/count
  arithmetic. Actual backing arrays remain tiny; child failure or timeout fails
  the test. Overflow fixtures first construct a legal 7x8x5 or 7x5x5 slab and
  change only the target X extent. Global/input product overflow uses
  `(2**62+1)*8*5`, which wraps to positive 40 and fits the actual capacities;
  a short-capacity or unrelated Y/Z-layout rejection cannot substitute for
  detecting that overflow. No huge allocation is requested by the test harness.

Malformed bounds, capacities and overflow expect INVALID_ARGUMENT; well-formed
unsupported layouts (including negative stride and noncanonical INT64_MIN input
origin) expect UNSUPPORTED. Input preflight failures expect INVALID_INPUT.
The existing partial-layout regression was changed from X-partial to unsupported
Y-partial, preserving its negative purpose and assertion.

`tests/oracle/test_slab_packing.py` separately selfchecks every packed plane,
global/local descriptors, input/output capacities, copied storage and complete
partition coverage without loading a production library. Six additional review
selfchecks verify that the overflow fixtures mutate only the target X extent,
that wrapped products fit the actual tiny backing capacities, and that the
global byte-limit case fits int64 in points but exceeds it in N*48 bytes.

## Real CLI coverage

`tests/e2e/test_x_slabs_cli.py` contains 42 cases using the real configured CLI
and native driver, subprocesses, independent CUBE authoring and strict receipts:

- Full/slab output and stats equivalence for quadratic and mixed-periodic Fourier
  input, both output modes, B=1/3/4/7. Checks cover global output shape, lengths,
  hashes, flags, finite bits, NaN masks, SUCCESS integrity and declared compute.
- Nx=5, all-periodic negative mixed corner, B=1/3/5, compared with full execution.
- Exact atom-free tracked budget for 1/2/4 threads, and one byte below the frozen
  formula in both modes. A direct real-driver test bypasses Python validation to
  require native rejection of the insufficient budget before raw output.
- Missing, boolean, fractional, zero, negative, too-large, null and extra slab
  settings, forbidden full-grid slab key and unknown layout are card failures.
- Grid/product and slab reservation overflow fail before worker execution.
  The test oracle uses unbounded Python integer arithmetic, selfchecked separately
  in `tests/e2e/test_slab_fixture_math.py`.
- NaN and significantly negative density at (3,8,10) fail whole input preflight
  before any raw output, despite B=1. This point lies outside the entire first
  periodic-X input halo [5,6,0,1,2]; two pure selfchecks require that all those
  first-input samples remain finite and positive.
- Entirely invalid global output retains ABI3 and aggregated stats without
  SUCCESS. A true numeric failure stops at the first ABI4 slab, reports global
  npoints and stats for the first 75 evaluated points, and cannot publish SUCCESS.
  Partial bytes remain permitted failure diagnostics, never completion evidence.

Existing invocation assertions protect the source CUBE and card bytes on every
subprocess call. Synthetic N_atoms=0 makes atom_bytes=0 at the exact budget gate.
All allocated fixture arrays have at most 693 grid points; huge shape values only
appear in deliberately malformed descriptors/cards rejected before allocation.

## Verification and later integration

Combined execution on 2026-10-20 used root `ae80fb9`, core `4150f34`, runtime
`fcbecff3` and tests `30917d3`, all clean and unchanged at both ends. GNU Debug
and Release each passed 18 CTests; NVHPC CPU Debug passed 16 with one documented
unavailable-binary128 skip. Each configuration passed 84 real CLI e2e checks,
285 oracle checks with the one existing public Jacobi-hook skip, 46 CLI protocol
checks and 21 native-driver checks. No slab integration case was skipped and
no tolerance changed. Exact full revisions and boundaries are in the root
integration branch's [status](status.md). The following preparation record is
preserved as history and must not be substituted for that execution evidence.

The dedicated WSL Python is `/opt/gpu-nci-dev-20261020/bin/python` in
Ubuntu-24.04. The original freeze at
`e5471105375c086b36065031d6463b4b480ab549` passed 45 pure checks, with 317
absent-production integration skips. Following two independent Astra P2 review
findings, the remote-preflight and overflow fixtures were isolated as described
above. With NCI_LIBRARY/NCI_DRIVER/NCI_CLI explicitly removed from the subprocess
environment, the reviewed preparation run was:

```text
python -m pytest -q tests/oracle tests/e2e
53 passed, 317 skipped
```

The 317 skips are honest absent-production integration cases, not acceptance.
One preparation selfcheck caught that a drafted huge Y/Z reservation still fit
int64; the declared dimensions were corrected from 2**27 to 2**28 before freeze.
No numerical acceptance tolerance was changed. `git diff --check` also passes.

After production freeze, the integration owner should build each configuration
in a fresh `/opt/gpu-nci-development-builds-20261020/m2-tests-<UTC>` directory,
record exact test/core/runtime/scaffold SHAs and compile flags, and point the
existing CMake cache variables at the frozen checkouts:
`NCI_ORACLE_DIR`, `NCI_E2E_DIR`, `NCI_CPU_SOURCE_DIR`, `NCI_DRIVER_SOURCE_DIR`,
`NCI_CLI_DIR` and `NCI_CLI_TEST_DIR`. The existing `independent_oracle` and
`cli_end_to_end` CTest entries discover the added cases without build-file changes.
Use separate fresh Debug+OpenMP, Release+OpenMP and Release-without-OpenMP builds
when required by the integration plan. No shared mutable temporary build is
acceptance evidence. This commit contains no production or build-scaffold edits.
