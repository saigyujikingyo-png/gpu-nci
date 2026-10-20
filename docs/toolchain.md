# Verified development toolchain

Verified on 2026-10-20 in WSL2 Ubuntu 24.04. This is a development
environment record, not application-level GPU validation.

| Component | Version |
|---|---|
| GCC / G++ / GNU Fortran | 13.3.0 |
| Python | 3.12.3 |
| CMake / Ninja package | 4.1.2 / 1.13.0 |
| NumPy / SciPy / pytest | 2.3.4 / 1.16.2 / 8.4.2 |
| NVIDIA HPC SDK / nvfortran | 26.9 / 26.9-0 |
| CUDA toolkit in slim SDK | 13.3 |
| Tested GPU target | RTX 5070 Laptop / cc120 |

The SDK lives in an isolated prefix. GNU and NVIDIA Fortran build directories
are separate; compiler `.mod` files must never be shared. No system driver or
global PATH changes are required.

Validation actually performed:

- Pinned Python installation, dependency consistency and independent read-back.
- Trivial C/C++/Fortran compilation and exit-code checks.
- Independent GNU and NVIDIA CPU builds of a four-value FP64 fixture.
- Forced `acc_device_nvidia` OpenACC execution, with `acc_on_device` true
  inside the compute region, compiler/runtime CUDA kernel evidence,
  32-byte input/output transfers, and exact expected four-value results.

The GPU smoke is **not** the NCI application, a performance measurement,
or scientific validation. The NCI OpenACC backend is still to be implemented.

Archive used:
[official HPC SDK 26.9 Linux x86-64 CUDA 13.3 slim](https://developer.download.nvidia.com/hpc-sdk/26.9/nvhpc_2026_269_Linux_x86_64_cuda_13.3.tar.gz)

- Bytes: 6,927,405,256.
- Publisher MD5: `4f191f9b66a4790f62e2ebc42f4b8b67`, matched locally.
- Locally calculated SHA-256:
  `e1bbf2ccdb112a3773d2cc141f09fb1d087562e266ec7ec7adb30a0519d45877`.
  This is a local record, not a publisher-signed SHA-256.

References:
[installation guide](https://docs.nvidia.com/hpc-sdk/archive/26.9/installation-guide/index.html),
[official MD5 list](https://developer.download.nvidia.com/hpc-sdk/26.9/md5sum.txt),
[CUDA on WSL](https://docs.nvidia.com/cuda/wsl-user-guide/index.html).
