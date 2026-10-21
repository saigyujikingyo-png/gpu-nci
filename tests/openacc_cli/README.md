# Optional OpenACC CLI checks

Native tests are deliberately outside default CPU CTest. Plain pytest here
collects only `test_pure.py`. Real tests require the explicit option
`--openacc-cli-native` and all three frozen executable inputs `NCI_DRIVER`,
`NCI_OPENACC_DRIVER`, `NCI_CLI`. Missing paths fail, never skip. Collection does
not execute a worker or load a candidate library. Explicit file/nodeid selection
also requires the option before atom metadata or native paths are inspected.

The local CMake file registers only `test_pure.py` (32 cases), with plugin
autoload/cache disabled and a 120-second timeout. Root integration must add its
subdirectory; no native test is registered with CTest.

The finite execution package must additionally provide `NCI_CUBE_ATOM_BYTES`,
derived from independently reviewed `reader_atom_size_bytes` in the compiled
size-fixture receipt, bound to the same source/compiler/reader objects. It must
not copy this expectation from a worker's native receipt. Native invocation is
only allowed after package review, freeze and Sol-managed GO.

The matrix reuses the existing independent analytic quadratic, discrete Fourier
and NumPy LAPACK reference, masks and tolerances. GPU full/B1/tail fields must be
byte-identical within one build. CPU/GPU fields use the original per-field
numeric tolerances and NaN masks. Cross-backend input flags/scientific bit6 are
exact. Bit5 counts are checked against each result's returned flags; its
threshold decisions are not independently certified, and cross-backend bit5
equality is not required.
Signed density is exact against the reference only for `abs(lambda2)>1e-9`,
and each result retains its own raw signed-density/eigenvalue identity everywhere.
These are separate gates; neither sign stability nor bit5 equality is inferred
from a candidate output.

Each CLI invocation keeps its original build-probe and evaluation stdout/stderr
inside its exclusive output directory. A sibling `*.evidence.json` binds paths,
hashes and bytes for later independent per-worker runtime tracing. The outer
pytest stderr is not GPU execution evidence. The three direct rejected-selector
workers (two invalid selectors, one CPU capability mismatch) also retain raw
stdout/stderr. No runtime notice is filtered or declared
accepted by these field tests; the final package must bind and check a separate
per-worker trace policy, including fresh-process initialization.

No clocks, benchmarks, density solver, real data, fallback or automatic retry is
part of this inventory. Execution counts and conservative artifact bounds are
recorded in the private preparation handoff; final integrated-source counts and
external caps must be independently frozen before running.

Current authored inventory: 29 native cases (50 CLI invocations and six direct
worker invocations: three selector/capability and three plan-guard refusals),
plus 32 pure cases. The six matrix cases
each use CPU full plus GPU full/B1/tail. Six atom cases each use exact budget
and one byte below. The remaining 14 cases cover three bad card selectors,
CPU-worker mismatch, two optional-worker CPU selections, four density failures,
three unsupported CLI plans and one direct-selector case. Three additional
direct-worker IDs independently serialize NML and pass a nonexistent CUBE to
exercise Fortran int64 overflow, packed mapped-object limit and one-byte-below
host-budget guards before input opening. They preserve raw logs and argv/exit/
settings/native receipts. Existing CPU e2e now has
96 collected cases (84 existing plus 12 capability selfchecks); driver21 is
unchanged. These are preparation collections, not native pass claims.
