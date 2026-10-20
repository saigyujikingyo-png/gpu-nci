# CPU milestone ABI v1

The authoritative layout is `include/nci_api.h`. Linux 64-bit sizes:
options 40 bytes, tile 280 bytes, stats 88 bytes. Fortran must verify
`c_sizeof` and interoperate through `bind(C)`, never compiler descriptors.

Options and tile version/size must match exactly; reserved fields must be zero.
CPU only in this milestone. FULL requires null grad/hess and zero corresponding
capacities; DIAGNOSTIC requires both pointers and capacities >= 3N / 6N.
`rho_min` is finite positive; negative tolerance is finite nonnegative.
`omp_threads` is 1..16; libraries must not change global OpenMP settings.

All pointers are caller-owned host buffers. Calls are synchronous.
Output pointers must be distinct and must not alias input. The caller guarantees
valid allocated pointers and their declared capacities; the library validates
nullability and declared lengths, not arbitrary address validity. Contexts are
used by one caller at a time, and destroyed exactly once.

Initial CPU implementation accepts complete grids only:
tile start/input origin = 0, tile count/input shape = global dimensions,
strides = [Ny*Nz,Nz,1]. Partial/slab layouts return UNSUPPORTED without writes.
Each dimension is >=5. Multiplication/offset overflow must be checked before
mapping pointers. J inverse is row-major, finite, invertible, and has 2-norm
condition <=1000. Periodic values are 0/1 and use N independent samples.

Points are CUBE Z-fastest. Gradients are point-major xyz; Hessians are
point-major xx,yy,zz,xy,xz,yz. Numeric routines and flags obey numerics.md.
In DIAGNOSTIC mode, every point with any of bits 0--4 set also has all three
gradient and all six Hessian entries set to NaN. Low-density Hessian exploration
mentioned in the design is a separate future diagnostic interface, not an
exception to this v1 output rule.
Input preflight rejects nonfinite rho or rho < -negative_tolerance.
These failures and invalid descriptors leave field buffers untouched.
If computation fails at a valid point, complete flags/stats and return
NUMERIC_FAILURE; expected invalid boundary/low/nonpositive/stencil points
alone do not make an otherwise nonempty grid fail.
All-invalid evaluation returns INVALID_INPUT with its flags/stats populated.

No grid/quantization certification is supplied by this ABI: bit 6 is always
set at numerically valid points. Bit 5 uses the numerical bound documented
by the implementation. Do not imply scientific sign acceptance.

Null errbuf is allowed only with len=0. Non-null errbuf with len=0 is permitted
and not touched. Any positive length is bounded and NUL terminated.
Create sets *context null before any failure when context is non-null.
Destroy null context returns INVALID_ARGUMENT. No STOP, exceptions, I/O, or
recursive model calls across this API.
