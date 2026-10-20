# Acceptance status

Updated 2026-10-20.

| Item | Status | Evidence boundary |
|---|---|---|
| Design and ABI | Prepared | Public header, layout contract, numerical specification |
| GNU toolchain | Verified | GCC/G++/gfortran 13.3; trivial programs compile and exit 0 |
| Isolated Python toolchain | Verified | Python 3.12.3; pinned development requirements; pip check |
| C ABI layout | PASS | 1 CTest, options=40 / tile=280 / stats=88 bytes |
| CPU numerical implementation | Draft PR #3, synthetic PASS | Dense-grid FP64 fields, flags, diagnostics and bounded OpenMP; independent review closed |
| Independent numerical oracle | Draft PR #1, actual-library PASS | 113 passed / 1 documented skip on each of three built libraries |
| Strict CUBE reader | Draft PR #2, synthetic PASS | Reader tests included in all three combined builds; independent and Claude reviews completed |
| Reader-to-ABI adapter and offline CLI | NOT_IMPLEMENTED | Next M1 gate; library tests do not establish an end-to-end pipeline |
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
All remain draft and unmerged pending user confirmation.

AI-assisted development: Claude Opus 5.5 max authored the initial CPU core;
GPT-6.1 Sol implemented the independent oracle, input reader and bounded
follow-up fixes; GPT-6 Astra handled architecture and independent review.
Claude also reviewed the reader. There is no model or network dependency at
scientific runtime. No unauthorized group data was used.

`RESEARCH_HANDOFF.md` remains deferred until a real end-to-end scientific case
has run and been accepted, as specified in [development](development.md).
