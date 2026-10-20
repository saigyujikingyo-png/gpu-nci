# Development sequence

M0 environment preparation is verified. The first M1 libraries and independent
tests passed combined synthetic checks and review; PRs #1, #2 and #3 were merged
with user approval on 2026-10-20. The adapter and CLI are in development under
the [frozen integration protocol](cli-contract.md).
See [acceptance status](status.md) for the actual test boundary.

1. M0: build isolation, ABI, public-source boundaries, independent worktrees.
2. M1: Fortran input parser and FP64 CPU fields; independent analytic and
   LAPACK tests, C/Fortran layout checks and negative cases.
3. M2: OpenMP scaling and full-grid/slab equivalence.
4. M3: OpenACC with explicit actual-device evidence and no CPU fallback.
5. M4: finite manually launched scientific validation/benchmark package.
6. Optional CUDA C ABI path only after profiling justifies it.

CPU implementation and independent tests are developed in separate branches.
Draft PRs are review artifacts; branch merge requires the user's confirmation.
The root checkout is the single-writer architecture/integration checkout.

The merged M1 libraries provide the reader and field evaluation. M1 still needs
an explicit metadata-to-ABI
adapter and a minimal offline CLI with tiny synthetic end-to-end tests. Source
provenance, units, Z-fastest order and matrix conventions must be transferred
explicitly; successful tests of the two libraries do not by themselves establish
that connection. Full-grid/slab work follows this interface check. No scaling
or speedup conclusion follows from thread-count consistency tests.

The original design remains frozen outside this repository. A toolchain
correction discovered during kickoff: the current HPC SDK 26.9 Linux x86-64
slim download is CUDA 13.3. Do not present the earlier CUDA 12.9 candidate as
installed. CPU GNU builds proceed independently of the optional SDK.

Sources:
- https://docs.nvidia.com/hpc-sdk/archive/26.9/installation-guide/index.html
- https://developer.nvidia.com/hpc-sdk-downloads
- https://docs.nvidia.com/cuda/wsl-user-guide/index.html

Actual scientific solver runs and performance benchmarks are NOT part of
agent-driven development tests. Preparation, successful build, synthetic
validation, scientific acceptance, and performance reporting remain separate.

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
