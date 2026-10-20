# GPU NCI

An experimental, offline density-grid NCI evaluator: strict CUBE input,
FP64 fourth-order finite differences, and Cartesian Hessian eigenvalues.

Development order: independent CPU validation → OpenMP → OpenACC →
profile-guided CUDA only if justified. The CPU libraries are merged. The offline
CPU CLI passed combined synthetic validation in three compiler configurations
and was merged after independent review and user approval. CPU X-slab support
now passes combined synthetic validation in separate review branches; those
branches are not yet merged. OpenMP scaling measurements remain unrun.
See [current status](docs/status.md).
**No GPU NCI backend, scientific reproduction, or speedup is claimed.**

## Build

The first target is Linux / WSL2 with GNU Fortran 13 and CMake 3.28+.

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug -DNCI_BUILD_TEST_HOOKS=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

Small synthetic tests are development checks. Real-density calculations
and benchmarks require a separately frozen, bounded execution package.

See [architecture](docs/architecture.md), [development plan](docs/development.md), [ABI contract](docs/abi.md),
[numerical specification](docs/numerics.md), and [C header](include/nci_api.h).
External programs are references, not bundled dependencies.

## Prior work

NCI is an established method, not an invention of this project:
[Johnson et al. (2010)](https://doi.org/10.1021/ja100936w).
GPU precedents include cuNCI and CuGBasis. A Morrison/Love
[gold-complex study (2024)](https://doi.org/10.1021/acs.inorgchem.4c01279)
used CRITIC2 with a specific core-augmented density model; obtaining
matching density inputs is a separate prerequisite for reproducing it.

## License

Original code and documentation: MIT. No third-party source is copied
into this initial repository. Referenced projects retain their own licenses.
