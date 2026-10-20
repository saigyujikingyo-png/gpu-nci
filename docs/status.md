# Acceptance status

Updated 2026-10-20.

| Item | Status | Evidence boundary |
|---|---|---|
| Design and ABI | Prepared | Public header, layout contract, numerical specification |
| GNU toolchain | Verified | GCC/G++/gfortran 13.3; trivial programs compile and exit 0 |
| Isolated Python toolchain | Verified | Python 3.12.3; pinned development requirements; pip check |
| C ABI layout | PASS | 1 CTest, options=40 / tile=280 / stats=88 bytes |
| CPU numerical implementation | In progress | Separate Claude implementation branch |
| Independent numerical oracle | In progress | Separate GPT reference-test branch |
| Strict CUBE reader | In progress | Separate GPT input branch |
| OpenACC SDK and device | Preparing | No offload acceptance yet |
| Real-density scientific validation | NOT_RUN | Matching source data and manual package required |
| Performance | NOT_RUN | No speedup claim |

The ABI includes future tile descriptors, while the first CPU milestone only
supports complete dense grids. Partial layouts must be explicitly rejected.
Initial results retain scientific-uncertainty flags until independent input
quantization and grid-convergence information is available.

Local run logs and host identities are intentionally excluded from this public
repository. Reproducible commands and relevant test conclusions belong in PRs.
