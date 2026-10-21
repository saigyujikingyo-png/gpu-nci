# M3A finite numerical portability result

**PASS for the frozen synthetic corpus, 2026-10-21 UTC.** The existing point
evaluator ran on the actual NVIDIA device and passed the independent gates.
This is an isolated experiment on unmerged review branches. The public GPU
backend is still `NOT_IMPLEMENTED`; no real-density case, timing benchmark,
speedup, or scientific sign certification is claimed.

## Exact execution scope

| Source | Tested revision |
|---|---|
| Production source and frozen contract | `2322204bdc4c675be3cfcdf2140ea671e398e42c` |
| Device experiment and host reference | `5a5657f639cd74c3d0d961e366eea24674cc5446` |
| Independent corpus and verifier | `efd64adc35aa0ec60fd3ef1cdd79e8000a466d12` |

All three checkouts were clean at those exact revisions before and after the
run. The corpus was first committed at `ee5489078fa8bcaf8107d7d93b6de09d99ad6cf7`
before candidate execution; its 22024-byte input SHA-256 remained
`ad9fd786113d8db5d7760475ab1be110eb7f042d576206efdcdd13535607c7f5`.
The deterministic adapter only inserts allowed device declarations and test
visibility; the production formulas, operation order, purity and ABI are unchanged.

Environment: Linux/WSL2 x86_64, NVHPC 26.9, CUDA 13.3, compute capability 12.0,
**NVIDIA GeForce RTX 5070 Laptop GPU**, 8151 MiB reported total memory, driver
610.71. The [contract](openacc-probe-contract.md) fixes compiler flags and gates.
This hardware identity must not be shortened to a desktop RTX 5070 claim.

One host process and one device process each ran once, with a 30-second limit.
Both exited 0; the compare-only independent verifier exited 0. Runtime logs
contain three NVIDIA kernel launches and actual uploads/downloads, and every
GPU result carries the same-region DEVICE=1 marker. There was no CPU fallback.
Source, generated source/diffs, stdin bytes, binaries, outputs and logs were
hashed; original receipts and the earlier failed attempt remain preserved.

## Observed checks and errors

All 36 scalar, 9 standalone RDG and 9 point cases passed their original gates.
The point cases comprise six successful evaluations and three deliberate
failure cases (statuses 4, 1 and 6), with the specified output field classes.
CPU/GPU status and uncertainty agreed; raw middle-eigenvalue sign differences
were empty. Independent rational/rounding references, high-precision RDG and
analytic/SciPy eigenvalue checks are separate from the production implementation.

The following are measured differences in this finite output, not domain-wide
error bounds:

| Comparison | Sample count | Observed maximum |
|---|---:|---:|
| GPU cube root vs correctly rounded independent reference | 30 finite, nonzero scalar values | 0 ULP |
| Host cube root vs that reference | Same 30 values | 1 ULP |
| GPU vs host gradient components | 18, from six successful points | 0 absolute difference; bitwise equal |
| GPU vs host Hessian components | 36, same six points | 0 absolute difference; bitwise equal |
| GPU vs host eigenvalues | 18, same six points | 0 absolute difference; bitwise equal |
| GPU vs host point RDG | 6, same six points | `4.336808689942018e-19` absolute difference |
| GPU vs host signed density, bound and tau | 6 values of each | 0 absolute difference; bitwise equal |

Signed zeros, infinities and NaNs were checked separately from the finite
cube-root comparison. Standalone RDG checks include nonzero subnormals and true
overflow/underflow, so an absolute tolerance cannot conceal a flushed result.
The observed host/GPU agreement is not a proof of the analytic bound theorem.

## Failures retained and remaining work

The initial LIBM-import candidate linked but produced PURE-interface warnings;
it was rejected in favor of retaining the original pure bind(C) interfaces.
The first native attempt then failed in host stdin parsing before any GPU run:
NVHPC nonadvancing formatted input lost the remainder of a long line. A bounded
POSIX byte reader fixed only experimental input transport. Ten parser-only
regressions passed, including full parsed-token equality, cross-buffer tokens,
no final newline, exact 8 MiB and oversized/malformed rejection. The numerical
corpus and tolerances were unchanged before the successful new run.

M3A does not implement tile/slab GPU execution, allocation and cleanup failure
paths, context budgets, direct C ABI GPU dispatch, or real-density validation.
Those are the next integration work. Default GNU CPU builds do not require
NVHPC; the pure verifier is included in CTest when its test directory is present.
The PR #13 merge preview at `efd64ad` into `2322204` passed all 19 CPU CTests.
The device experiment is validated locally, not by claiming GitHub-hosted GPU CI.

AI-assisted development: Claude Opus 5.5 max wrote the experiment and adaptation;
GPT-6.1 Sol wrote independent fixtures/verifier and the stdin repair; GPT-6 Astra
defined architecture, coordinated execution and reviewed frozen code. Only
synthetic data was used. No model or network is a runtime dependency.
`RESEARCH_HANDOFF.md` remains deferred until a real scientific end-to-end case.
