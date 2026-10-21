# Development sequence

M0 environment preparation is verified. The first M1 libraries and independent
tests passed combined synthetic checks and review; PRs #1, #2 and #3 were merged
with user approval on 2026-10-20. The adapter and offline CLI now pass combined
synthetic checks under the [frozen integration protocol](cli-contract.md), and
PRs #4/#5/#6/#7 were merged after approval and integrated-tree verification.
M2 CPU X-slab code and thread-consistency checks pass combined synthetic
validation under the [layout and scheduling contract](slab-contract.md).
PRs #9/#10/#11 were integrated into #8, the complete source tree and CI passed,
and #8 was merged into main with user approval. OpenMP scaling is NOT_RUN.
See [acceptance status](status.md) for the actual test boundary.

M3A's isolated evaluator now passes its frozen 54-record synthetic corpus on
the RTX 5070 Laptop GPU; [results and limits](openacc-probe-results.md) identify
the exact tested revisions. The next M3 work is public-backend integration:
checked allocation/cleanup, per-context resources, tile/slab mapping and
synchronous output commit under the existing ABI. These remain unimplemented.
No scientific or performance package was executed during M3A development.

1. M0: build isolation, ABI, public-source boundaries, independent worktrees.
2. M1: Fortran input parser and FP64 CPU fields; independent analytic and
   LAPACK tests, C/Fortran layout checks and negative cases.
3. M2: OpenMP scaling and full-grid/slab equivalence.
4. M3: OpenACC with explicit actual-device evidence and no CPU fallback, beginning
   with the isolated [M3A numerical portability probe](openacc-probe-contract.md).
5. M4: finite scientific validation/benchmark package managed by a GPT-6.1 Sol
   execution subagent under the user's standing authorization.
6. Optional CUDA C ABI path only after profiling justifies it.

CPU implementation and independent tests are developed in separate branches.
Draft PRs are review artifacts. On 2026-10-21 the user gave standing approval
for routine merges once independent review, integrated-source checks and CI pass.
The root checkout is the single-writer architecture/integration checkout.

The merged M1 libraries and CLI provide the reader, field evaluation and explicit
metadata-to-ABI connection. Tiny synthetic end-to-end tests pass in GNU
Debug/Release and NVHPC CPU Debug. The merged M2 implementation adds full-grid/slab
equivalence under the same configurations. The implementation preserves source
declarations, units, Z-fastest order and matrix conventions, without authenticating
the input's scientific provenance. OpenMP scaling measurements
still require a bounded manual package; thread consistency tests establish no
speedup conclusion.

The original design remains frozen outside this repository. A toolchain
correction discovered during kickoff: the current HPC SDK 26.9 Linux x86-64
slim download is CUDA 13.3. Do not present the earlier CUDA 12.9 candidate as
installed. CPU GNU builds proceed independently of the optional SDK.

Sources:
- https://docs.nvidia.com/hpc-sdk/archive/26.9/installation-guide/index.html
- https://developer.nvidia.com/hpc-sdk-downloads
- https://docs.nvidia.com/cuda/wsl-user-guide/index.html

Scientific solver runs and performance benchmarks remain separate from these
synthetic development tests. On 2026-10-21 the user authorized their automatic
execution for this project: first freeze input provenance, finite stages,
resource/time limits, logs and stopping conditions, then assign execution to a
GPT-6.1 Sol subagent. This supersedes the earlier manual-launch requirement;
it does not change scientific specifications or acceptance thresholds.
Preparation, build, synthetic validation, scientific acceptance and performance
reporting remain separate states.

## Research handoff gate

Create `RESEARCH_HANDOFF.md` only after the first end-to-end scientific case
has actually run and its outputs have been checked. A synthetic unit-test pass
does not open this gate. Current implementation and correctness work take
priority over presentation material; this addition does not change the frozen
scientific specification.

The concise document should let a computational chemist understand, in about
five minutes: the scientific task; its GPU suitability; the density/NCI relation;
CPU validation; measured speedup and error on the exact tested RTX 5070 model;
implemented and missing capabilities relative to NCIPLOT and related tools;
possible relevance to metal recovery or molecular materials; and three specific
questions for research feedback. Performance values require actual execution,
recorded baselines and scope; unmeasured items remain explicitly unmeasured.
Describe the scope of AI-assisted development and independent checks. Use only
inputs with authorized provenance and avoid claims of new scientific results
from unvalidated algorithms.

Keep the implementation understandable and maintainable at undergraduate level.
Do not add machine learning, topological analysis or Monte Carlo functionality
to this development scope.
