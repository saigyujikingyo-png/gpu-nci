# Acceptance status

Updated 2026-10-20.

| Item | Status | Evidence boundary |
|---|---|---|
| Design and ABI | Prepared | Public header, layout contract, numerical specification |
| GNU toolchain | Verified | GCC/G++/gfortran 13.3; trivial programs compile and exit 0 |
| Isolated Python toolchain | Verified | Python 3.12.3; pinned development requirements; pip check |
| C ABI layout | PASS | 1 CTest, options=40 / tile=280 / stats=88 bytes |
| CPU numerical implementation | Merged PR #3, synthetic PASS | Dense-grid FP64 fields, flags, diagnostics and bounded OpenMP; independent review closed |
| Independent numerical oracle | Merged PR #1, actual-library PASS | 113 passed / 1 documented skip on each of three built libraries |
| Strict CUBE reader | Merged PR #2, synthetic PASS | Reader tests included in all three combined builds; independent and Claude reviews completed |
| Reader-to-ABI adapter and offline CLI | Synthetic PASS, merge pending | Real CLI/worker path: 37 independent tiny end-to-end tests per configuration; no integration skips |
| OpenACC SDK and device | Smoke PASS | Four FP64 values, actual NVIDIA kernel; NCI GPU backend absent |
| Real-density scientific validation | NOT_RUN | Matching source data and manual package required |
| Performance | NOT_RUN | No speedup claim |

The ABI includes future tile descriptors, while the first CPU milestone only
supports complete dense grids. Partial layouts must be explicitly rejected.
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
The new adapter, CLI and end-to-end branches remain separate pending the next
concrete merge confirmation. Their combined acceptance is recorded below.

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

Pending review artifacts: [contract/build integration](https://github.com/saigyujikingyo-png/gpu-nci/pull/4),
[offline CLI and native worker](https://github.com/saigyujikingyo-png/gpu-nci/pull/5),
[independent e2e tests](https://github.com/saigyujikingyo-png/gpu-nci/pull/6),
[reader allocation reservations](https://github.com/saigyujikingyo-png/gpu-nci/pull/7).
PR #5 depends on #7; its isolated branch does not contain the reservation API.
Local combined builds explicitly use all four frozen checkouts. Standalone PR
CI is not a substitute for that combined evidence. Approval should integrate
#7, #5 and #6 into #4, then verify the integrated tree before merging #4 to main.

AI-assisted development: Claude Opus 5.5 max authored the initial CPU core;
GPT-6.1 Sol implemented the independent oracle, input reader and bounded
follow-up fixes; GPT-6 Astra handled architecture and independent review.
Claude also reviewed the reader and authored its allocation reservations at
Opus 5.5 xhigh. Sol authored the offline CLI, native worker and independent e2e
tests; Astra defined the protocol and independently reviewed the frozen changes.
There is no model or network dependency at
scientific runtime. No unauthorized group data was used.

`RESEARCH_HANDOFF.md` remains deferred until a real end-to-end scientific case
has run and been accepted, as specified in [development](development.md).
