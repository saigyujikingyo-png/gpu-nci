# Acceptance status

Updated 2026-10-21 (Europe/London).

| Item | Status | Evidence boundary |
|---|---|---|
| Design and ABI | Prepared | Public header, layout contract, numerical specification |
| GNU toolchain | Verified | GCC/G++/gfortran 13.3; trivial programs compile and exit 0 |
| Isolated Python toolchain | Verified | Python 3.12.3; pinned development requirements; pip check |
| C ABI layout | PASS | 1 CTest, options=40 / tile=280 / stats=88 bytes |
| CPU numerical implementation | Merged PR #3, synthetic PASS | Dense-grid FP64 fields, flags, diagnostics and bounded OpenMP; independent review closed |
| Independent numerical oracle | Merged PR #1, actual-library PASS | 113 passed / 1 documented skip on each of three built libraries |
| Strict CUBE reader | Merged PR #2, synthetic PASS | Reader tests included in all three combined builds; independent and Claude reviews completed |
| Reader-to-ABI adapter and offline CLI | Merged PR #4/#5/#6/#7, synthetic PASS | Real CLI/worker path: 37 independent tiny end-to-end tests per configuration; no integration skips |
| CPU X-slab execution | Merged PR #8/#9/#10/#11, combined and complete-tree synthetic PASS | Same ABI and numerics; [M2 contract](slab-contract.md); no scaling measurement |
| M3A OpenACC numerical portability | Finite synthetic PASS | 36 scalar / 9 RDG / 9 point records; actual NVIDIA kernels and independent verification; [results](openacc-probe-results.md) |
| OpenACC SDK and device | Smoke PASS | Four FP64 values, actual NVIDIA kernel; NCI GPU backend absent |
| Real-density scientific validation | NOT_RUN | Matching source data and manual package required |
| Performance | NOT_RUN | No speedup claim |

Merged main `a1ebe23` supports complete dense grids and canonical X slabs under
the same ABI; other partial layouts remain rejected.
Initial results retain scientific-uncertainty flags until independent input
quantization and grid-convergence information is available.

Local run logs and host identities are intentionally excluded from this public
repository. Reproducible commands and relevant test conclusions belong in PRs.

## Combined synthetic acceptance

Actual execution on 2026-10-20 used these clean worktrees, unchanged at the end:
scaffold `18b78a0`, CPU `cb4665e`, input `5f59e7d`, oracle `62e151f`.
Later edits to this status page do not change those tested revisions.

| Configuration | CTest passed / skipped | Actual-library pytest passed / skipped |
|---|---:|---:|
| GNU Fortran 13.3 Debug | 14 / 0 | 113 / 1 |
| GNU Fortran 13.3 Release | 14 / 0 | 113 / 1 |
| NVHPC 26.9 Debug, CPU execution | 12 / 1 | 113 / 1 |

All configure, build and CTest processes exited 0. NVHPC's explicit skip records
unavailable binary128: the two unchanged quad-reference tests were not built
there, and passed under GNU. The independent pytest skip is the unstandardized
public C Jacobi-injection interface. Separate native FP64 tests exercised forced
nonconvergence and normal convergence under both compilers.

One polynomial fixture's output FNV-1a was `06691df4e61c091c` in all three
builds; this is not a claim of bitwise identity for every possible output.
Independent tests exposed and verified fixes for invalid diagnostics, integer
overflow, RDG intermediate overflow, and NVHPC CPU scaling/exponent behavior
at binary64 endpoints. Formulae, Jacobi controls and tolerances were unchanged.
Synthetic tests support implementation checks, not a formal error-bound proof
or scientific sign certification.

To reproduce the combined build, check out the four revisions in independent
directories, install `requirements-dev.txt` from the scaffold, and run:

```sh
cmake -S /path/to/scaffold -B build-gnu-debug -G Ninja \
  -DCMAKE_Fortran_COMPILER=gfortran -DCMAKE_BUILD_TYPE=Debug \
  -DNCI_CPU_SOURCE_DIR=/path/to/core/src/backend_cpu \
  -DNCI_IO_SOURCE_DIR=/path/to/input/src/io \
  -DNCI_ORACLE_DIR=/path/to/oracle \
  -DNCI_BUILD_TEST_HOOKS=ON -DPython3_EXECUTABLE="$(command -v python)"
cmake --build build-gnu-debug --parallel 2
ctest --test-dir build-gnu-debug -V
```

Use a separate directory for Release, and another with the explicit nvfortran
path for NVHPC Debug. The root defaults apply IEEE/no-contraction controls.
These commands exercise small synthetic fixtures only.

Review artifacts: [independent tests](https://github.com/saigyujikingyo-png/gpu-nci/pull/1),
[CUBE reader](https://github.com/saigyujikingyo-png/gpu-nci/pull/2),
[CPU core](https://github.com/saigyujikingyo-png/gpu-nci/pull/3).
All three were merged with user approval on 2026-10-20. Merged main `b1df82c`
also passed [CPU CI](https://github.com/saigyujikingyo-png/gpu-nci/actions/runs/39493005661).
The adapter, CLI and end-to-end branches were subsequently integrated with user
approval. Their combined and integrated acceptance is recorded below.

## Offline CPU CLI synthetic acceptance

Actual execution on 2026-10-20 used four clean source revisions, unchanged at
entry and exit: integration `36b259476f4d64bb406342e0b05ac48b28710db8`,
reader reservation `8fef3df2e0305639c2aa84f14acabd2761e16802`,
CLI and native worker `a76542f88bd9441989616ebf8993f2f244e00236`,
independent e2e `9f3e2124367107cfb822fb6aaacc9a9e4b772de0`.
Later status-only edits do not change these tested revisions.

| Configuration | CTest passed / skipped | CLI e2e passed / skipped |
|---|---:|---:|
| GNU Fortran 13.3 Debug | 17 / 0 | 37 / 0 |
| GNU Fortran 13.3 Release | 17 / 0 | 37 / 0 |
| NVHPC 26.9 Debug, CPU execution | 15 / 1 | 37 / 0 |

Each configuration additionally passed 40 CLI protocol tests, 12 actual native
worker tests, 33 reader cases (165 native parser calls), and 113 independent
actual-library oracle tests with the same one documented public-hook skip.
NVHPC's CTest skip still records unavailable binary128; GNU ran those reference
tests. All configure, build and CTest processes exited 0. Source/build declarations
round-tripped exactly, and the local records retain executable/library hashes,
raw logs, exit status and synthetic output files. No timing here is a benchmark.

The e2e suite runs the real Python CLI and compiled Fortran worker on skew,
non-cubic quadratic and mixed-periodic Fourier fixtures in full/diagnostic modes.
It checks independent numerical expectations, point/component order, masks,
statistics, snapshots, binary and output hashes, and the final manifest marker.
Failure cases cover malformed cards, unsupported units, altered source hashes,
geometry mismatches, allocation reservations, numeric overflow, zero valid
points and existing output directories. No production formula or acceptance
tolerance was changed to obtain these passes. Reproduction commands are in
[integration](integration.md).

Merged review artifacts: [contract/build integration](https://github.com/saigyujikingyo-png/gpu-nci/pull/4),
[offline CLI and native worker](https://github.com/saigyujikingyo-png/gpu-nci/pull/5),
[independent e2e tests](https://github.com/saigyujikingyo-png/gpu-nci/pull/6),
[reader allocation reservations](https://github.com/saigyujikingyo-png/gpu-nci/pull/7).
User approval was followed in order: #7, dependency update and passing #5 CI,
then #5/#6, full integrated-tree checks, and #4 into main `c77d4ed`.
The prior #5 compile failure was caused by the then-unmerged reservation API;
the failed history is retained. The exact integrated source `8cc25b8` passed
all 17 GNU Debug CTests using only its own default source paths, including
37 e2e, 40 CLI unit, 12 native and 113/1 oracle cases. Source state was clean
and unchanged before/after execution. Integrated CI and subsequent
[main CI](https://github.com/saigyujikingyo-png/gpu-nci/actions/runs/39506644743)
passed. Old worktrees, branches and source evidence remain preserved.

## M2 CPU X-slab synthetic acceptance

Actual execution on 2026-10-20 used four clean revisions, unchanged at entry and
exit: root `ae80fb929ca5ba12de247a2786117a452ac1e4d6`,
core `4150f34e5a3a4ca5d45909d1fc48502ee1c1d202`,
runtime `fcbecff3ef1de8a4979636ccd1f49b874c0166f4`,
tests `30917d3e368fef5fc3163d4e769aa5e4c3484dc5`.
Subsequent documentation-only commits do not change the tested source code.

| Configuration | CTest passed / skipped | CLI e2e passed / skipped | Oracle passed / skipped |
|---|---:|---:|---:|
| GNU Fortran 13.3 Debug | 18 / 0 | 84 / 0 | 285 / 1 |
| GNU Fortran 13.3 Release | 18 / 0 | 84 / 0 | 285 / 1 |
| NVHPC 26.9 Debug, CPU | 16 / 1 | 84 / 0 | 285 / 1 |

Every configuration also passed 46 CLI protocol and 21 real native-driver
checks. All configure/build/CTest processes exited 0, with exact source/build
declarations and preserved binary hashes, raw logs, exit codes and synthetic
outputs. The oracle skip is the unchanged public Jacobi-injection hook; native
FP64 convergence tests ran. NVHPC's unavailable-binary128 skip remains explicit;
GNU ran both quad-reference tests. No new slab integration test was skipped.

The fixtures verify same-build full-grid/slab equality of finite binary64 bits,
NaN masks, flags, aggregate stats and raw CLI output hashes. Coverage includes
all eight periodic-axis combinations, skew geometry, B=1/odd/nondivisor/Nx,
short tails, Nx=5, 1/2/4-thread consistency, seam/corner negatives, halo aliases,
checked arithmetic, remote invalid-density preflight, exact tracked budgets,
completed boundary-only slabs and numeric failures. Independent mathematical
oracle tolerances are unchanged. These are finite synthetic checks, not a
full-domain proof, scientific sign certification or scaling measurement.

Independent Astra review closed core, runtime and tests. Two test-coverage
findings were corrected before production integration: the remote invalid
sample is outside the first halo, and overflow cases isolate the overflowing
X extent without an unrelated Y/Z or short-capacity rejection. The earlier
53-pass/317-skip fixture-only preparation is not counted as actual acceptance.

The C ABI structure, exported symbols, numerical evaluator, 61-point stencil,
thresholds and uncertainty policy are unchanged. The CLI retains the full rho
array and buffers only one slab's additional input and output fields. This is
not out-of-core input and its tracked allocation allowance is not a whole-process
RSS cap. OpenMP scaling, GPU-NCI fields, real-density acceptance and speedup remain
NOT_RUN. Reproduction commands are in [integration](integration.md).

Following explicit approval, #9, #10 and #11 were merged into #8 in that order.
The complete integration tree `1f118a1dc1504bfbe4b12228e0023c7fad852157` then passed
all 18 GNU Debug CTests using only its own default source paths: CLI 46, native
21, e2e 84 and oracle 285 passed with the same one public-hook oracle skip.
Both numerical test-hook suites were present, and GNU binary128 tests ran.
Clean source state, source/binary hashes and raw outputs were retained.
[Integrated CI](https://github.com/saigyujikingyo-png/gpu-nci/actions/runs/39511987296)
passed before #8 was merged into main `a1ebe23c5f56b2df143ee99aca8ac88497861fa0`.
The main file tree equals that tested integration exactly, and
[main CI](https://github.com/saigyujikingyo-png/gpu-nci/actions/runs/39512518654)
also passed. Earlier dependency failures and old worktrees remain preserved.

AI-assisted development: Claude Opus 5.5 max authored the initial CPU core;
GPT-6.1 Sol implemented the independent oracle, input reader and bounded
follow-up fixes; GPT-6 Astra handled architecture and independent review.
Claude also reviewed the reader and authored its allocation reservations at
Opus 5.5 xhigh. Sol authored the offline CLI, native worker and independent e2e
tests; Astra defined the protocol and independently reviewed the frozen changes.
For M2, Claude Opus 5.5 max authored the CPU slab core and native tests; separate
GPT-6.1 Sol agents authored the runtime and independent fixtures. Astra froze
the contract, reviewed the three branches and verified the combined results.
There is no model or network dependency at
scientific runtime. No unauthorized group data was used.

`RESEARCH_HANDOFF.md` remains deferred until a real end-to-end scientific case
has run and been accepted, as specified in [development](development.md).
