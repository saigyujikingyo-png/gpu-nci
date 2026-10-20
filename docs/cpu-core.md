# CPU core (ABI v1) — implementation notes

Status: first CPU implementation of `include/nci_api.h` in Fortran 2008 +
`ISO_C_BINDING` with optional OpenMP. It is **implemented and passes its own
synthetic tests** (grids ≤ 17³). It has **not** been compared with the
independent NumPy/SciPy oracle, has **no real-density acceptance**, performs
**no GPU offload**, and **no performance has been measured**. The sign
classification it reports concerns implementation roundoff only; it never
certifies a scientific sign (bit 6 is always set on valid points).

## Build and artefacts

| Target | Content |
|---|---|
| `nci_cpu_objects` | OBJECT library with all Fortran modules (`src/backend_cpu/*.f90`) |
| `nci_cpu` | shared library; a linker version script exports exactly `nci_context_create_v1`, `nci_eval_tile_f64_v1`, `nci_context_destroy_v1` |
| `nci_cpu_test_hooks` | test-only static library (only with `-DNCI_BUILD_TEST_HOOKS=ON`), never linked into `nci_cpu` |

Floating-point controls (GNU): the root scaffold adds `-ffp-contract=off`
to Fortran; the backend repeats it on its own target and adds `-frecursive`
(all locals on the stack, so distinct contexts may be used concurrently).
Configuration aborts if the Fortran flags contain `-ffast-math`, `-Ofast`,
`-funsafe-math-optimizations`, `-fassociative-math`, `-freciprocal-math` or
`-ffp-contract=fast`. The CTest `core_library_inspection` checks with
`nm`/`objdump` that the shared object exports only the three functions,
contains no `vfmadd*`/`vfmsub*`/`vfnmadd*`/`vfnmsub*` instruction, references
no Fortran STOP or external I/O entry point, and (non-Debug) no runtime-error
or allocation-abort path. Every multi-term sum in the stencil, transform,
Jacobi and bound code is explicitly parenthesized, so the evaluation order
assumed by the rounding analysis is fixed by the language. Apart from the
exact `frexp`/`scalbn` behind the `exponent`/`scale` intrinsics, the only
libm call in the numerics is `cbrt` (RDG); `hypot` is replaced by an exactly
power-of-two-scaled `sqrt`, so the derivative, transform, Jacobi and bound
paths use only correctly rounded IEEE operations.

OpenMP: one `parallel do collapse(2) num_threads(omp_threads)` over the grid
(and one over the density preflight). No `omp_set_*` call is made. Each point
is computed independently, so results are bitwise identical for every thread
count (tested for 1, 2, 3, 8, 16). Without `NCI_ENABLE_OPENMP` the same code
runs serially and `omp_threads` is only validated.

## ABI behaviour

`create`: `*context` is set to NULL first whenever `context` is non-NULL.
The context is one heap object (magic tag + validated copy of the options),
allocated once and freed by `destroy`; there is no module-level mutable state.
`destroy(NULL)` and pointers without the live tag return `INVALID_ARGUMENT`
(use after destroy remains a caller contract violation).

errbuf: NULL is accepted only with length 0; a non-NULL buffer with length 0
is never touched. Otherwise exactly one bounded, NUL-terminated message (empty
on success, at most 255 characters) is written when the call returns. If
errbuf overlaps any other buffer of the call, the call fails and errbuf is not
written.

Validation order of `eval` (first failure wins; nothing but errbuf is
written before the preflight succeeds):

| Check | Status |
|---|---|
| errbuf NULL with length > 0 | `INVALID_ARGUMENT` (no write at all) |
| build layout (`c_sizeof` 40/280/88) | `BACKEND_UNAVAILABLE` |
| NULL or foreign context; NULL tile | `INVALID_ARGUMENT` |
| tile `abi_version`/`struct_bytes`/`reserved` | `INVALID_ARGUMENT` |
| NULL rho/rdg/signedrho/lambda2/flags/stats | `INVALID_ARGUMENT` |
| FULL: grad/hess non-NULL or capacities ≠ 0; DIAGNOSTIC: grad/hess NULL | `INVALID_ARGUMENT` |
| `global_n[d] < 5`, `periodic[d] ∉ {0,1}` | `INVALID_ARGUMENT` |
| `Nx·Ny·Nz` or `48·N` byte extent overflows int64 (checked multiplication) | `INVALID_ARGUMENT` |
| `tile_count < 1`, `tile_start < 0`, start+count > global, `input_shape < 1` | `INVALID_ARGUMENT` |
| anything but start/origin 0, count/shape = global, strides `[Ny·Nz, Nz, 1]` | `UNSUPPORTED` |
| `rho/field/flags_capacity < N`; DIAGNOSTIC `grad < 3N`, `hess < 6N` | `INVALID_ARGUMENT` |
| `j_inv` non-finite, singular, κ₂ > 1000 or unverifiable | `INVALID_ARGUMENT` |
| overlapping byte ranges among rho (read) and all written buffers incl. errbuf | `INVALID_ARGUMENT` |
| preflight: any NaN/±Inf, or any rho < −negative_tolerance | `INVALID_INPUT` |
| evaluation: at least one point with bit 4 | `NUMERIC_FAILURE` |
| evaluation: no numerically valid point | `INVALID_INPUT` |

Options: `abi_version == 1`, `struct_bytes == 40`, `reserved == 0`
(`INVALID_ARGUMENT`); `backend` OPENACC/CUDA → `BACKEND_UNAVAILABLE`, any
other non-CPU value → `INVALID_ARGUMENT`; `output_mode ∈ {FULL, DIAGNOSTIC}`;
`omp_threads ∈ 1..16`; `rho_min` finite and > 0 (no library default; callers
pass the 1e−8 e·bohr⁻³ of numerics.md explicitly); `negative_tolerance`
finite and ≥ 0 (−0.0 is accepted as 0).

The density is never written. The overlap check is a best-effort guard
(address arithmetic in a flat address space); the caller still guarantees
valid, distinct allocations.

## Grid, flags and outputs

Point index `p = (i·Ny + j)·Nz + k` (CUBE Z-fastest). Gradient output is
point-major `x,y,z`; Hessian output point-major `xx,yy,zz,xy,xz,yz`, both
Cartesian. Periodic axes wrap modulo the global `N` independent samples;
finite axes flag indices `< 2` or `> N−3` as BOUNDARY.

| bit | rule in this implementation |
|---|---|
| 0 | some finite axis index in {0, 1, N−2, N−1} |
| 1 | centre `rho ≤ 0` (includes −0.0 and accepted negative samples) |
| 2 | `0 < rho ≤ rho_min` |
| 3 | some point of the 61-point stencil (wrapped on periodic axes, clipped on finite axes) holds an accepted negative sample (`−tol ≤ rho < 0`); the negative sample itself is included |
| 4 | a point with bits 0–3 clear failed: non-finite derivative/transform, asymmetry above the rounding bound, Jacobi nonconvergence, residual/orthogonality check, non-finite eigenvalue or RDG |
| 5 | numerically valid and `¬(|λ̂₂| > τ_num)` (see below) |
| 6 | every numerically valid point (no grid/quantization certificate exists) |
| 7 | always 0 |

Zero samples are legal: they participate in neighbours' derivatives and never
set bit 3. Low positive samples participate as well. No value is clamped.

Outputs: bits 0–3 → rdg, signedrho, lambda2 and (DIAGNOSTIC) all 9
gradient/Hessian components are the quiet NaN `0x7FF8000000000000`, bits
4–6 are 0. Bit 4 → rdg/signedrho/lambda2 NaN, bits 5/6 zero, the diagnostic
gradient/Hessian hold the values computed before the failure (possibly
non-finite) for debugging. Valid → finite rdg/lambda2/signedrho; signedrho is
exactly `+rho`, `−rho`, or `+0.0` when `λ̂₂ == 0`.

Statistics: `total = N`; `valid = |V|` with V = points with bits 0–4 clear;
`invalid = N − valid` (the union of bits 0–4, each point counted once);
`numeric_failures = bit_counts[4]` (a subset of `invalid`); `bit_counts[b]`
counts points carrying bit b (overlapping).

## Numerics

**Differences** (integer index space, no h): with `S(a,b,c,d) = (a − d) + 8(c − b)`
for samples at offsets −2, −1, +1, +2,

- `D_i = S/12`,
- `D_ii = ((16(ρ₋₁ + ρ₊₁) − (ρ₋₂ + ρ₊₂)) − 30ρ₀)/12`,
- `D_ij = S_p(S_t(ρ(p,t)))/144`: inner difference along the higher axis,
  outer along the lower axis (both with `c = (1,−8,8,−1)/12`).

Multiplications by 8 and 16 are exact. The stencil union is the 61 offsets of
`{−2..2}³` with at most two non-zero components.

**Transform**: `M[i][a] = j_inv[3i+a] = ∂q_i/∂r_a`; `g_r = Mᵀ g_q`,
`H_r = Mᵀ(H_q M)` computed in all nine entries; each off-diagonal pair must
agree within `2γ₁₂·P_ab·(1+2⁻⁴⁰) + F` (below), else bit 4; then
`H_ab ← (H_ab + H_ba)·0.5`.

**Eigenvalues**: the symmetric `H_r` is scaled by the exact power of two
`2⁻ᵉ`, `e = exponent(max|H_ij|)` (max entry in [0.5, 1)); the zero matrix
returns zeros. Classical Jacobi pivots on the largest `|a_pq|` (ties: first of
(1,2),(1,3),(2,3)), uses `d = (a_qq − a_pp)/2`,
`t = sign(d)·a_pq/(|d| + hypot(d, a_pq))`, `c = 1/√(1+t²)`, `s = tc`,
`τ = s/(1+c)` and Rutishauser's updates, accumulating V. Before each rotation
it stops when `√(2Σ_{p<q} a_pq²) ≤ 64ε·max|a⁰_ij|` (ε = 2⁻⁵²); after 30
rotations without meeting the criterion the point gets bit 4 (no
pseudo-normal values). Eigenvalues are sorted by value and rescaled by `2ᵉ`.
Because the frozen stopping rule may leave an off-diagonal of up to
`64ε·max|H_ij|`, the absolute eigenvalue error can reach about `64ε‖H‖₂`
(observed ≤ 35ε‖H‖₂ on graded matrices); small eigenvalues of strongly graded
Hessians can therefore have large relative error — the bound below reports
it. The test-only hook `hook_eig3(..., max_rotations, ...)` exercises the
nonconvergence branch (`max_rotations = 1` on `[[2,1,1],[1,2,1],[1,1,2]]`);
production always passes the constant 30 and exposes no tuning.

**RDG**: `s = (|g_r|/ρ)/(C·cbrt(ρ))`, which equals `|g|/(Cρ^{4/3})` but never
forms `ρ^{4/3}` on its own (no spurious overflow/underflow). `|g_r|` uses a
power-of-two-scaled 2-norm.

`C = 2(3π²)^{1/3}`: evaluated with Python `decimal` at 80 significant digits
(π to 100 digits, Newton cube root):
`6.1873354525602718619378904144447739159080312602974…`. The nearest binary64
is `0x4018BFD4DD6882CB` = 6.187335452560272 (the exact value lies 0.103 ulp
above it, so the rounding is unambiguous). The Fortran literal
`6.1873354525602718619378904144447739159_dp` is checked bit-for-bit and
against a binary128 evaluation by `core_test_numerics`.

## Roundoff bound behind bit 5

Target: for a valid point, the exact real-arithmetic value `λ₂*` of the frozen
discrete formulas above evaluated on the given binary64 samples and the given
binary64 `j_inv`. If bit 5 is clear, `sign(λ̂₂) = sign(λ₂*)`. Discretization
and input errors are outside this bound (bit 6).

Model: round to nearest binary64, `fl(x∘y) = (x∘y)(1+δ) + η'`, `|δ| ≤ u = 2⁻⁵³`,
`|η'| ≤ 2⁻¹⁰⁷⁵` for × and ÷ (η' = 0 for ±, whose subnormal results are
exact), no contraction. `γ_n = nu/(1−nu)`.

1. **Stencil.** Each Hessian component is a fixed tree whose leaves are samples
   times exact powers of two; the longest leaf-to-root path has 4 roundings
   (diagonal) or 5 (mixed, including the final ÷12 or ÷144). Hence
   `|Ĥ_q − H_q| ≤ γ₅·A + 2η` componentwise, with
   `A_c = Σ_k |w_k||ρ_k|` (exact rational weights; A is index-space,
   e·bohr⁻³). Also `|Ĥ_q| ≤ (1+γ₅)A`.
2. **Transform.** Two 3-term dot-product stages give
   `|fl(Mᵀ fl(Ĥ_q M)) − MᵀĤ_qM| ≤ γ₆|M|ᵀ|Ĥ_q||M|`; combined with step 1,
   `|Ĥ_r − H_r| ≤ γ₁₁ P`, `P = |M|ᵀ A |M|` (e·bohr⁻⁵: `h⁻²` enters once,
   through |M|, never on top of an already physical quantity). Symmetrization
   adds one rounding: `γ₁₂ P`. Thus `‖Ĥ_sym − H_r‖₂ ≤ γ₁₂‖P‖_F` and, by
   Weyl, the same bounds `|λ_k(Ĥ_sym) − λ_k(H_r)|`.
3. **Eigen residual.** With the scaled matrix `A⁰`, accumulated `V` and final
   diagonal `D`, the code computes `R̂ = fl(A⁰V − VD)` and
   `Ĝ = fl(VᵀV − I)` and the a-priori rounding of those products, giving
   `r = ‖R̂‖_F + γ₄‖|A⁰||V| + |V||D|‖_F ≥ ‖R‖₂` and
   `δ = ‖Ĝ‖_F + γ₄‖|V|ᵀ|V| + I‖_F ≥ ‖VᵀV − I‖₂`. If `δ ≤ 1/4`
   (else bit 4), the polar factor `V = UP` gives
   `UᵀA⁰U = D + X`, X symmetric,
   `‖X‖₂ ≤ (‖R‖₂ + 2δ‖D‖₂)/√(1−δ) ≤ (1+δ)(r + 2δ·max|d|)`, and Weyl gives
   `|λ_k(A⁰) − d_(k)| ≤ ‖X‖₂`. Rescaling: `B_eig = 2ᵉ(1+δ)(r + 2δ·max|d|)`.
   This is independent of the pivoting order and of how converged Jacobi is.
4. **Underflow and bound arithmetic.** All absolute underflow contributions
   are below `14η(1+s)²`, `s = max_a Σ_i|M_ia|`; they are dominated by
   `F = ((1+s)·2⁻⁵³²)² ≈ 2⁻¹⁰⁶⁴(1+s)²`. Relative rounding in computing the
   bound itself (A, P, norms, r, δ: < 300 operations) is covered by the factor
   `1 + 2⁻⁴⁰`. Overflow anywhere in the bound makes it +Inf or NaN, which
   sets bit 5 (the comparison is NaN-safe).

Final quantities, per valid point:

```
B_lambda = (gamma_12*||P||_F + B_eig)*(1 + 2**-40) + F
tau_num  = 1e-12 + 1e-10*max(|lambda_1|, |lambda_3|) + B_lambda
bit 5    = .not. (|lambda_2| > tau_num)
```

The two fixed terms are the provisional margins of numerics.md §6 (to be
frozen in M1 with the oracle); they only enlarge the uncertain set and are not
part of the rigorous bound. `core_test_numerics` checks
`|λ̂_k − λ_k*| ≤ B_lambda` against a binary128 evaluation of the same
discrete formulas for 24 000 points (random, cancellation-dominated,
Gaussian, graded 1e−12…1 neighbours, κ(J) up to ~900, scales 2^±700 including
the subnormal regime): maximum `err/B_lambda` = 0.11, mean 0.006.
`core_test_eigen` checks `B_eig` on 40 000 random, graded, clustered and
near-singular matrices plus known-root cases: maximum ratio 0.50.

## J inverse condition number

`κ₂` is computed without squaring it: the matrix is scaled by an exact power of
two; `max/min` column norm (a lower bound of κ₂) rejects κ₂ > 1000 early
(with a 2⁻⁴⁰ margin so that only certain rejections happen there); otherwise
one-sided (Hestenes) Jacobi orthogonalizes the columns (pair tolerance
`16ε·‖a_p‖‖a_q‖`, at most 30 sweeps, unverifiable → reject) and the singular
values are the final column norms. Acceptance is `σ_max ≤ 1000·σ_min`.
`diag(1,1,1000)` is accepted with κ = 1000 exactly, `diag(1,1,1000+ulp)` is
rejected; rotated matrices agree with a binary128 reference to < 1e−12
relative (tested), so only matrices with κ₂ within roughly that distance of
1000 can be classified either way (estimate, not a proven bound).
Left-handed J are accepted.

## Tests (`ctest`, label `core`)

| Test | Kind | Content |
|---|---|---|
| `core_test_contract` | C, public ABI | every option/tile/pointer/capacity/overflow/layout/J-inverse/overlap/errbuf rule, untouched outputs on rejection, preflight NaN/±Inf/negative, −0.0 handling |
| `core_test_fields` | C, public ABI | FD4 exactness on a quartic density with skewed left-handed J; exact discrete Fourier symbols on periodic and mixed axes; exact 61-point dependency set; negative-tail scatter incl. wrap/clipping and no leakage; zero/low samples; rho_min edge; thread determinism; λ₂ = 0 → signedrho +0 and bit 5; affine density → all bit 5; Jacobi vs closed form; overflow → NUMERIC_FAILURE; all-invalid → INVALID_INPUT; independent flag/stat recomputation everywhere |
| `core_test_concurrency` | C, public ABI, pthreads | four contexts (different modes, J, periodicity, thread counts) evaluated concurrently from four POSIX threads reproduce the serial outputs bit for bit |
| `core_test_layout` | C + Fortran | sizeof/offsetof of all fields vs the library's `BIND(C)` types; field-by-field echo |
| `core_library_inspection` | CMake script | exports, no FMA, no STOP/I-O |
| `core_test_eigen` | Fortran, hooks | known roots, power-of-two scale invariance, decimal/subnormal scaling, extreme ratios, forced nonconvergence, random families vs binary128, bound validity |
| `core_test_numerics` | Fortran, hooks | constants, stencil set, stencil isolation (NaN outside the 61 points), norms, transform/row-major mapping, condition number, bound vs binary128, RDG extremes |

The last two need `-DNCI_BUILD_TEST_HOOKS=ON`. `core_test_fields` also
prints an FNV-1a checksum of all outputs of its polynomial grid; comparing it
across build types is a quick check that no value-changing optimization slipped
in (it was identical for GNU 13.3 Debug `-O0`, Release `-O3` and an
OpenMP-disabled build).

## Known limitations

- No comparison yet with the independent oracle; the τ margins and tolerances
  are not frozen.
- Only complete grids; slabs/tiles/halos return `UNSUPPORTED` (M2).
- RDG uses libm `cbrt`: values may differ by about one ulp across libm
  implementations (no sign role).
- The rounding guarantees assume IEEE binary64 round-to-nearest without
  contraction; only the GNU toolchain is configured and inspected.
- Messages carry indices but no floating-point values (no I/O formatting is
  used inside the library).
- `omp_threads` is unused without OpenMP (gfortran reports an unused dummy
  argument in that configuration).
