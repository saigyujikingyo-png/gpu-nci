# M3B2 optional OpenACC offline CLI: finite synthetic results

**Accepted on 2026-10-21 for the reviewed finite synthetic scope.**
The optional worker connects explicit OpenACC selection to the existing offline
CUBE CLI. Full grids and canonical X slabs preserve the public ABI, numerical
formulas, tolerances, flags and output ordering. This is synthetic integration
validation; real-density scientific validation and speedup measurements remain unrun.

The tested source is `001cf5c5a68d625878176179e4179fcdbbd5d2da`
(173 tracked files). Later documentation commits do not change this revision.
Complete GNU and NVHPC builds used its exact Git archive.

## Environment and actual checks

Execution on 2026-10-21 used WSL2 Ubuntu 24.04, GNU Fortran 13.3, NVHPC 26.9,
CUDA 13.3 and cc120 on an RTX 5070 **Laptop GPU**, with strict IEEE/no-FMA controls.

| Check | Independently accepted actual result |
|---|---|
| GNU Debug CPU CTest | 23 passed, zero CTest skips; binary128 reference checks ran |
| CPU pytest identities within CTest | 1,068 passed and one documented public Jacobi-injection-hook skip |
| OpenACC CLI pure fixture checks, included above | 32 passed |
| New opt-in native CLI suite | 29 passed, zero skips |
| Individual build-probe/evaluation/size processes | 96 attributed processes, 192 distinct original stdout/stderr streams |
| GPU field execution | 97 kernels across 27 field workers |
| Original runtime notices | 7,798, including 54 fresh-process static uploads |
| Logical device cleanup | 873 deletes matched the frozen per-call ownership grammar |
| Output and failure gates | Passed; original fields, flags, manifests, hashes and SUCCESS-last checks |
| Controller and terminal cleanup | All 10 stages, controller and launcher exited zero; owned processes/cgroup absent |

The 29 native cases made 50 CLI invocations plus six direct worker refusals.
Their 44 build probes and 43 evaluations, plus those six direct workers and three
standalone probes/size captures, account for the 96 attributed processes.
The CLI invocations are parent calls and are not an additional 50 worker processes.

The fixtures cover analytic quadratic/discrete Fourier and LAPACK comparisons,
both output modes, finite/periodic/mixed boundaries, full grids, B=1 and tail
slabs, exact and insufficient atom budgets, invalid density, checked plan
overflow, capability mismatch and explicit CPU selection in the optional worker.
Same-build GPU full/slab fields matched byte for byte; CPU/GPU comparisons passed
the existing tolerances and NaN-mask checks. Input/scientific flags are exact
under the declared comparison rules. Bit-5 threshold decisions and signed
density near a zero eigenvalue retain the suite's explicit limits; these checks
do not certify scientific signs or input uncertainty.

The trace gate binds each process to its selected executable/library,
source-derived invocation, original stdout/stderr, return code and class.
Nested CLI worker argv is reconstructed from reviewed source and verified
invocation artifacts; it is not an OS-probed argv receipt. Unknown notices are
rejected. Fresh-process initialization is checked separately from field work.
The observed 283 physical allocations and 283 physical frees are runtime
notifications, not peak-VRAM measurements or a proof of driver-pool balance.

## Preserved failure and minimal link correction

The earlier full attempt on source `104c39e` passed its CPU checks, then stopped
at its first GPU context creation: the standalone Fortran worker found no NVIDIA
device and did not fall back to CPU. No GPU field was evaluated in that attempt.
Its original failure and cleanup records remain preserved.

Static diagnosis found the worker linked NVHPC's host-only OpenACC API stubs
before the actual OpenACC runtime. The only production correction in
`001cf5c` adds the optional worker's explicit
`-acc=gpu -gpu=cc120,cuda13.3` link options. Complete GNU/NVHPC builds and
independent dependency/symbol inspection passed. CPU targets, normalized
compile-only command sequences and numerical sources are unchanged. The
corrected source then passed the separately frozen startup diagnostic and the
new full attempt recorded here; the consumed failed attempt was not replayed.

## Accepted prerequisites and evidence reuse

Independent static review verified the exact source/build closure, unchanged
backend implementation and generated OpenACC sites, separate worker metadata,
GPU-free CPU dependency closures and sanitized-loader resolution. Static
inspection alone does not establish execution or field correctness.

The corrected-source startup diagnostic captured the GNU build probe, optional
build probe and host size fixture. Each original stderr was empty under
NOTIFY31. This applies to those exact invocations, not every possible code path.
Compiled sizes were 14,352 bytes for workspace, including the 12,480-byte ledger
and 1,560-byte descriptors, 172 explicit scalar bytes, a 56-byte context wrapper
and a 40-byte reader atom record. The fixture contains the same production
objects directly; it does not load the public backend DSO. Independent atom
budget expectations use this compiled size rather than a candidate native receipt.

The accepted [M3B1 public-library results](openacc-public-results.md) remain
source-bound prior evidence for the unchanged ABI/backend/native/pthread scope.
Its 148 native tests and 278 GPU kernels were **not rerun by M3B2** and are not
included in the new totals above. M3B2 adds worker/CLI integration evidence.

## Finite resources and provenance

The frozen package allowed 1,800 seconds plus five seconds for cleanup,
2 GiB controlled host memory, zero swap, 64 processes and two CPU equivalents.
Output limits were 32 MiB per file, with a 200 ms sampled aggregate limit of
256 MiB, 16,384 files and 32,768 directory entries.

Actual controller elapsed time was 366.141 seconds, including validation
overhead; it is not a benchmark. Controlled memory peaked at 253,321,216 bytes.
No OOM, memory/pid maximum or output-limit event occurred. CPU quota throttled
three times without a failure. The final sampled
output was 26,121,939 bytes across 4,848 files and 5,672 entries. All recorded
owned process identities were absent and the owned cgroup was removed; cleanup
was unforced. Tracked host/device reservations are not process RSS or physical VRAM.

| Full-run evidence | SHA-256 |
|---|---|
| Frozen package | `2f3793180bac16a2c77ebc88fe7dd6c5adeeeb379d04333afeef34f84ddd1107` |
| Original completion and run, byte-identical | `e88bd4dc5f51fe7d2eb645c53c999a49c02f9d9492e9d585e899c30d62dc739a` |
| Terminal evidence seal | `7e7e297e17e1ead7d1f7934ab10f590a4ecf824f0ded8498236d1ea6b707bee7` |

Independent terminal review verified 846 unique sealed references (27,175,999
bytes), all 173 source identities, exact stage receipts, per-process traces and
outputs. The 50 CLI calls produced 33 expected successes and 17 expected
failures; all six direct worker refusals matched their contracts. All 25
successful GPU receipts had their seven-key memory plans independently checked.

Private original logs, host paths, device UUIDs and process identities remain
outside the public repository. Independent acceptance is recorded separately;
original reports keep their collection/completion states, and consumed failure
history remains unchanged.

Development was AI-assisted: GPT-6 Astra authored the M3B2 worker/build changes
and handled architecture and independent review; GPT-6.1 Sol authored CLI
integration and independent fixtures/tooling and managed frozen execution.
The attempted Claude coding invocation failed before inference and produced
no M3B2 code. Earlier M3B1 authorship remains in its own results.
All fixtures here are generated synthetic data, with no research-group inputs.

## Remaining limits

This M3B2 report establishes synthetic correctness, not a speedup or physical
peak-VRAM measurement. The subsequent M4 [stored-water case](water-validation.md)
has conditional scientific acceptance under its own reviewed, frozen execution
and independent acceptance. The [research handoff](../RESEARCH_HANDOFF.md) now
records that scope. P1 performance remains NOT_RUN and V4 same-input external-tool
comparison remains NOT_PERFORMED.
