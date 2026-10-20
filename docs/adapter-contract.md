# M1 contract: connect input to field evaluation

The reader, CPU backend and independent oracle are merged. The adapter and CLI
implement this contract, pass joint synthetic checks and were merged with user
approval. See [status](status.md) for tested
revisions and [cli-contract](cli-contract.md) for the precise execution protocol.

## Explicit transfer

| Reader or input-card value | ABI value | Required check |
|---|---|---|
| `grid%shape` | global dimensions, tile count, input shape | Checked int64 products; dense complete grid |
| `grid%rho` | caller-owned density buffer | Preserve Z-fastest ordering and all accepted samples |
| `grid%j_inv(i+1,a+1)` | `j_inv[3*i+a]`, i,a = 0..2 | Explicit row-major packing; no implicit Fortran reshape |
| Three periodic declarations | `periodic[3]` | Finite nodes or N independent samples, never inferred |
| Declared negative tolerance | context option | Same value used by metadata validation and numerical preflight |
| `rho_min`, output mode, thread limit | context options | Explicit validated execution-card values |

The input origin defines exported coordinates; it does not enter the derivative
transform. Apply the inverse step matrix once. Do not divide derivatives by
another step length, normalize the density, remove endpoints, or guess units.
The initial reader supports bohr and electron/bohr³ declarations only.

The adapter owns buffer lifetimes through the synchronous call and destroys
every successfully created context exactly once. It checks total requested
storage for input, fields, optional diagnostics, masks and parser overhead
before allocation; the reader's budget alone does not cover backend outputs.
Use a fresh output directory. A failed evaluation must produce an explicit
failed status and exit code, never a success marker.

## Evidence and output

The execution card must bind the original CUBE content hash to explicit quantity,
spin convention, density representation, units, endpoint conventions and producer
source. Metadata validation does not authenticate those declarations. Record
the actual source/build revision, compiler policy, options, dimensions, counts,
return status, and output hashes. Public synthetic fixtures need provenance
labels; private scientific inputs are not bundled into the repository.

Field export must retain raw valid results, NaNs at invalid points, the complete
flag byte and union statistics. Unknown scientific uncertainty remains bit6.
The adapter must not reinterpret a numerically valid sign as scientific evidence.

## Small synthetic acceptance

Use a non-cubic grid with nonzero origin, a skew step matrix, a mixed quadratic
with analytically known Cartesian derivatives, and distinct values along each
axis. Check the full path from written CUBE and explicit metadata through the
ABI to exported point order, fields, masks and statistics. Add mixed periodic
axes with a Fourier fixture to exercise endpoint declarations. Mismatched units,
unbound metadata, unsupported layouts, insufficient memory and numerical failures
must fail without a success marker or overwritten source.

These development tests do not run an electronic-structure solver. Real-density
studies and performance measurements remain separately frozen manual packages.
