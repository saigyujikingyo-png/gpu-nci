# Independent synthetic CPU validation

This suite owns no production implementation. `reference/abi.py` mirrors only
the public C header; `reference/fields.py` supplies independent analytic and
NumPy/SciPy references. No production Fortran/CUDA source is read or imported.
All grids have at most 17^3 samples. These are small synthetic unit tests,
not scientific runs, real-density validation, GPU offload tests, or benchmarks.

## Run and interpret

On Linux/WSL, from this checkout:

```sh
/opt/gpu-nci-dev-20261020/bin/python -m pytest -q -ra tests/oracle
NCI_LIBRARY=/absolute/build/path/libnci_cpu.so \
  /opt/gpu-nci-dev-20261020/bin/python -m pytest -q -ra tests/oracle \
  --junitxml=/absolute/new-output-path/oracle-results.xml -o junit_family=xunit1
```

The pinned local development dependencies are in `reference/requirements.txt`.
Installing them is separate from running tests. Run the suite from its own
checkout; the shared object can come from any independent production build.
`NCI_LIBRARY` must be an absolute Linux path to the actual `.so`, not a Windows
path or a dummy library. No shared object is generated or substituted by this
suite. When the variable is absent, actual-library tests explicitly **SKIP**;
reference-only passes do not mean the core passed. A supplied missing path,
unloadable library, or missing public symbol is a failure, not a skip.

The C ABI layout self-test compiles only a tiny `sizeof/offsetof` probe against
the public header in pytest's temporary directory. It contains no numerical
implementation. If `cc` is unavailable, that probe alone explicitly skips.

## Evidence and independence

- ABI sizes and every mirrored field offset are compared against a compiled
  public-header probe. Error tests check options, nullability, bounded/NUL
  error strings, capacities, complete-grid restrictions, J, and input preflight.
  Product overflow is tested in a short-lived isolated process; a crash or
  timeout fails rather than terminating the entire test report.
- Noncubic, skew and left-handed quadratic fixtures provide exact Cartesian
  g/H and expose Z-fastest or matrix-transpose mistakes. Constant fields and
  positive/negative middle eigenvalues are covered. Tolerances are the fixed
  initial contract: g/H/lambda2 atol=1e-12, rtol=1e-10;
  RDG atol=1e-11, rtol=1e-9. They are not fitted to production output.
- Periodic trigonometric fixtures use the independently derived FD4 Fourier
  symbols, including the pure-second versus composed-first distinction.
  Mixed finite/periodic boundaries use the same true periodic field but only
  compare valid finite interiors. Oracle self-tests cross-check those symbols
  with a separate NumPy rolled-array stencil.
- LAPACK `scipy.linalg.eigvalsh(driver='evr')` supplies the middle eigenvalue;
  known rotated spectra separately check LAPACK and NumPy. Gaussian analytic
  derivatives are self-checked using complex-step differentiation, independent
  of the production finite differences.
- Exact input-mask checks include all 61 stencil locations, a two-axis corner,
  exclusion of three-axis corners, permitted small negative samples, exact
  zero, low/threshold-adjacent rho, all-invalid outputs, and proof that positive
  low-rho neighbors remain in differentiation. Semantic NaNs must match flags;
  expected invalid points must not acquire bit4, bit5, or bit6.
- Valid points must retain bit6 because this ABI supplies no scientific
  certification. Conservative bit5 is allowed even at every valid point;
  `numeric_sign_stable_points`, `numeric_valid_points`, and zero
  `scientific_sign_certified_points` are JUnit properties. Zero stable points
  are an explicit coverage gap, not evidence of reliable numerical signs.
  Raw signedrho is checked away from mathematical zero eigenvalues regardless
  of whether the production implementation conservatively sets bit5.
- The public ABI exposes no test-only Jacobi signature. The optional ctypes
  hook test explicitly skips; it does not guess or call private symbols.
  Production-core CTest must exercise its test-only rotation-limit injection.

## Current execution evidence

On 2026-10-20 the no-library command completed with **14 passed, 70 skipped**,
pytest exit code 0. The public-header C layout probe was among the passes.
All 70 skips arose because `NCI_LIBRARY` was unset, including the optional hook
test's unavailable-library fixture. No actual production library was evaluated:
**production CPU core NOT_TESTED**. Once a library is supplied, the hook test
will still explicitly skip for lack of a standardized public test-only ABI.
The ignored local XML report is `runs/reference-only-20261020.xml`.

Execution details and remaining work are recorded in local ignored
`.agents/handoff.md`. Reference self-tests do not establish production-core
correctness, scientific acceptance, reliable numerical signs, or performance.

Independent mathematical/API references:

- SciPy symmetric eigenvalues, ascending order and symmetry precondition:
  <https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.eigvalsh.html>
- Python ctypes structures and function signatures:
  <https://docs.python.org/3/library/ctypes.html>
- Original NCI paper: <https://pubmed.ncbi.nlm.nih.gov/20394428/>
