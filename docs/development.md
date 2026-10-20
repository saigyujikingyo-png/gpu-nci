# Development sequence

Status at scaffold: M0 prepared in part, implementation not yet accepted.

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
