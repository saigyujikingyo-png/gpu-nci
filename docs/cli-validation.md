# Independent tiny CLI-to-native validation

The suite is `tests/e2e/`; CTest name is **cli_end_to_end**, timeout180s.
It targets the frozen `docs/cli-contract.md` protocol and the exact manifest
shape supplied by the CLI author and approved by the root architect. Geometry
binding includes exact parsed-binary64 comparison, including the tiny-J
counterexample. All-low positive density is ABI3 failure, never empty success.

The tests never import CLI, reader, adapter or native numerical implementation.
Only the merged independent `reference.fields` from base8c56369 is reused for
analytic quadratic/Fourier derivatives, FD4 self-checks, LAPACK eigenvalues,
and input-mask mathematics. The CUBE author writes its own small text fixture;
Python does not parse the actual input for production. No fake worker is built.

## Run

From this checkout under the dedicated development Python:

```sh
/opt/gpu-nci-dev-20261020/bin/python -m pytest -q -ra tests/e2e
NCI_DRIVER=/absolute/build/nci_driver NCI_CLI=/absolute/cli/nci_cli.py \
  /opt/gpu-nci-dev-20261020/bin/python -m pytest -q -ra tests/e2e \
  --junitxml=/absolute/new-report.xml -o junit_family=xunit1
```

Dependencies for tests are the existing pinned reference NumPy/SciPy/pytest;
the actual runtime CLI remains standard-library-only. CMake receives external
test/CLI locations through NCI_E2E_DIR and NCI_CLI_DIR, passes the real target
path through NCI_DRIVER, and launches the suite from any build working directory.
The test subprocess invokes CLI with an argv array from a separate directory
whose name and card/input names contain spaces. Card input resolution must be
relative to the card, while output resolution is relative to invocation cwd.

Unset NCI_DRIVER or NCI_CLI explicitly skips actual integration. Supplying
nonexistent paths fails rather than skips. A real combined acceptance must run
the integration cases, not accept the fixture-only passes or an absent CTest.

## Pinned successful fixtures

- Shape7x9x11; origin=(0.375,-0.5,0.625).
- J rows=(0.25,0.0625,-0.03125), (0.015625,0.1875,0.046875),
  (0,-0.03125,0.21875). Listed CUBE vectors are its **columns**.
- Quadratic rho=4+b.r+r.H.r/2, b=(0.125,-0.0625,0.1875),
  H rows=(-0.25,0.0625,-0.03125), (0.0625,0.125,0.046875),
  (-0.03125,0.046875,0.375). rho_min4.5 intentionally gives both valid and
  low-density interior points; finite boundary radius2 remains independent.
- Fourier background1, modes(amplitude,integer frequency,phase)=
  (0.05,(1,2,1),0.2), (0.03,(2,-1,0),-0.4), with X/Z periodic and Y finite.
  Its385 boundary-legal points use independent FD4 Fourier symbols, not
  continuous derivatives substituted for discrete ones.
- Both modes run both `full` and `diagnostic` output paths. Fields contain at
  most693 points, written with17 significant digits. No real-density input.

Unchanged initial FP64 gates: g/H/lambda2 atol1e-12,rtol1e-10;
RDG atol1e-11,rtol1e-9. They were chosen before production execution and must
not be widened to accommodate a failure. Raw signedrho must equal
sign(actual lambda2)*rho at every valid point; reference sign comparison uses
the previously fixed1e-9 near-zero band. Bit6 remains unknown; numerical sign
coverage is reported without claiming scientific certification.

Success checks cover raw point/component order, little-endian types, exact
byte counts, NaN masks, flags/statistics union and individual bit counts, original
and snapshot bytes/hashes, declaration/geometry retention, settings hash,
independently queried build-info, actual driver/backend binary hashes, logs,
and SUCCESS containing the final manifest SHA256 plus newline. JSON receipts
reject duplicate keys and nonfinite tokens; integer counts reject booleans.

## Negative cases

Unknown keys at all card levels; duplicate keys/null/bool/nonfinite/missing/
fractional-integer/oversize JSON; unsupported length/density units; altered
comment hash with unchanged numerical data; wrong bytes/shape/origin/J/endpoint;
well-conditioned actualJ=2e-16I versus declaredJ=1e-16I; reservation budget
that fits reader rho+scanner but not backend arrays/tables/fixed allowance;
true RDG overflow; all-low positive density; existing output/input-directory
collision. Every call checks original card/CUBE immutability. Failures require
nonzero exit, failed receipt and no new SUCCESS; preexisting output contents,
including an old SUCCESS sentinel, must remain byte-for-byte unchanged.

Numeric overflow is the independent5^3 case with center1e-250,x+1=2,otherwise1,
rho_min1e-260. It requires ABI4 and numeric_failures1. Optional retained raw
diagnostics must all be NaN. All-low uses5^3 positive rho0.5e-8,rho_min1e-8,
requiring ABI3,zero valid,total125,zero numeric failures. These statuses are
different; neither permits a success marker.

## Execution evidence

Initial no-executable self-check: **5 passed,32 skipped**, exit0. All32 skips
are explicit NCI_DRIVER/NCI_CLI absence. The actual CLI-to-native path is
**NOT_TESTED**, not PASS. Ignored private report:
`runs/e2e-fixture-only-20261020.xml`. Local handoff records commands and revisions.
No electronic-structure computation, science acceptance, benchmark or source
mutation was performed. Full M1/real-data/GPU gates remain separate.
