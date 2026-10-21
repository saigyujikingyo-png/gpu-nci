# GPU NCI: research handoff

2026-10-21. This undergraduate-maintainable project evaluates established NCI
fields from an existing electron-density grid. Its first real-input water case
has **conditional scientific acceptance**. RTX 5070 Laptop GPU performance is
**NOT_RUN**: there is no measured speedup yet. Exact scope and evidence hashes
are in [water validation](docs/water-validation.md).

## What the program does

1. Read a strict CUBE density grid with explicit units, geometry and provenance
   metadata, preserving the original values.
2. Calculate FP64 fourth-order finite-difference gradients and Cartesian
   Hessians, then their algebraically ordered middle eigenvalue, lambda2.
3. Return reduced density gradient (RDG), `sign(lambda2)*rho`, diagnostics and
   validity/uncertainty flags through a C ABI or offline CLI. CPU/OpenMP and
   optional OpenACC backends support full grids and canonical X slabs.
4. Retain hashes, original outputs and failure records; assess scientific
   convergence separately from successful program completion.

Each grid point uses a fixed local stencil and a small symmetric eigensolve,
so many points can be evaluated in parallel. This makes the field stage a
plausible GPU workload. FP64 cost, memory traffic, transfers, launch overhead
and grid size still determine whether it is faster. Density generation and
visualization are separate costs. X slabs reduce extra field storage while
retaining the complete density in host memory.

## Density and NCI

For electron density rho, the reduced gradient is
`s = |grad(rho)| / [2*(3*pi^2)^(1/3)*rho^(4/3)]`. Low-density, low-RDG regions
can reveal noncovalent contacts; the sign of the middle Hessian eigenvalue
helps distinguish their character when mapped as `sign(lambda2)*rho`.
This follows the established NCI method; it does not directly produce an
interaction energy, binding affinity or separation selectivity.
See the original [NCI paper](https://doi.org/10.1021/ja100936w) and
[NCIPLOT methods paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC3080048/).

## How CPU and GPU results were checked

Synthetic analytic functions and independent LAPACK tests first checked the
discrete numerical implementation, masks, boundaries and full-grid/slab
equivalence. The real case then used the public stored RHF/STO-3G water model
from IOData, with five doubly occupied orbitals. An independent Gaussian
reference supplied continuous density derivatives and prior error budgets;
a separate rational-weight stencil oracle checked discrete derivatives.
Three directly sampled grids, h=0.15/0.075/0.0375 bohr, tested convergence.
Independent reviewers checked numerical evidence and actual GPU traces,
resource limits, exit status and cleanup.

On the **RTX 5070 Laptop GPU**, CPU/GPU gradient, Hessian, lambda2, flags and
signed-density files had identical hashes on all three grids. Maximum RDG
absolute difference across valid points was **1.1368684e-13**. Against the
continuous model, primary-ROI gradient RMS error fell from **3.3958e-5** to
**1.3635e-7 electron/bohr^4**; Hessian RMS error fell from **2.4070e-4** to
**9.8885e-7 electron/bohr^5**. Their two observed orders were approximately four.

The fixed primary ROI contains 26,817 nodes: 26,722 (**99.6457471%**) met the
conditional sign-stability criteria, with **100%** six-way grid/backend agreement
against the continuous reference. One nonasymptotic and 94 budget-unstable
nodes remain in the denominator; six coarse-grid raw sign flips lie outside
the stable set. Including nuclear-core nodes gives Hessian orders only
1.42908/2.83229. At h/4, two Hessian components per backend in the independent
stencil-oracle comparison needed the pre-frozen arithmetic allowance; every
strict nominal CPU/GPU gate passed.

This accepts the stored model and declared ROI under stated libm and local
Richardson assumptions. Historical SCF/model error is unknown. Production
uncertainty bit 6 remains set; the assessment is an external sidecar.
The 628-second validation wall time includes verification overhead and cannot
be used as a performance result. **P1 timing and speedup: NOT_RUN**; the separate
timing design is under review and will require its own frozen run and acceptance.

## Relation to NCIPLOT

The [official NCIPLOT repository](https://github.com/aoterodelaroza/nciplot)
documents WFN/WFX or XYZ input, density/RDG grid generation, CUBE output and VMD
visualization. Its [methods paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC3080048/)
describes self-consistent quantum and promolecular density routes.

| Capability | GPU NCI now |
|---|---|
| Density-grid derivatives, lambda2, RDG and signed density | Implemented on CPU and optional OpenACC GPU |
| Strict CUBE input, raw field arrays, masks and receipts | Implemented; [CLI guide](docs/cli-usage.md) |
| WFN/WFX/XYZ density generation or promolecular model | Not implemented; the water FCHK sampler is validation-only |
| NCI surface rendering / VMD workflow | Not implemented |
| Same-density NCIPLOT or CRITIC2 pointwise comparison (V4) | NOT_PERFORMED |
| Measured GPU speedup (P1) | NOT_RUN |

This narrow field evaluator has not been shown to replace mature analysis
tools. There is no new machine learning, topology or Monte Carlo method in scope.

## Possible research use and requested feedback

With appropriately licensed, method-consistent densities, a future study could
explore ligand/metal contact regions in extraction complexes, or intermolecular
contacts and packing in molecular materials. These are proposals for qualitative
analysis and validation, not demonstrated metal-recovery or materials results.
No energy, selectivity or predictive advantage is established by the water case.

The three most useful research questions are:

1. Which small, shareable ligand/metal or molecular-material case would provide
   an interpretable next test, and what all-electron/ECP density convention must
   be fixed before comparing it?
2. Are the fixed low-density ROI, retained unstable fraction and convergence
   evidence appropriate for that use, or is a different predeclared criterion
   scientifically necessary?
3. Which same-density NCIPLOT/CRITIC2 comparison and timing scope would make
   accuracy and any future GPU advantage useful to a practicing chemist?

Claude authored production numerical core work; GPT-6.1 Sol authored independent
reference, input/CLI and acceptance tooling and managed finite execution;
GPT-6 Astra handled architecture and independent numerical review. Roles vary
by milestone and are recorded in the linked results. AI assistance does not
replace frozen inputs, actual execution and independent review. Runtime uses
no language model or network service. The source and tests are deliberately
kept small and explicit for undergraduate maintenance; no internal group data,
private prompts or third-party dependency code are included in this handoff.
