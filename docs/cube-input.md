# 严格 CUBE 输入模块（M1 工程实现）

`src/io/nci_cube_input.f90` 提供独立 Fortran 模块 `nci_cube_input`，
CMake 静态库 target 为 `nci_cube_input`。不更改公共 C ABI；后续 CLI 可链接此库。
本模块不求解电子结构、不生成科学密度、不计算 NCI，也不认证来源。

## 接口与状态边界

```fortran
use nci_cube_input
type(cube_grid) :: grid
type(cube_status) :: status
type(cube_metadata) :: metadata
type(cube_read_limits) :: limits

! 调用方可以在读取前缩小资源预算。max_bytes/max_points 必须为正。
limits%max_bytes = 268435456_8
limits%max_points = 33554432_8
call read_cube('input.cube', grid, status, limits)
! status%code /= CUBE_OK 时不能使用 grid；输出已清理。
! read_cube 成功仅代表严格格式及几何校验成功。

metadata%quantity = 'electron_density'
metadata%spin_convention = 'spin_summed'
metadata%density_representation = 'valence' ! 必须按实际来源选择
metadata%length_unit = 'bohr'
metadata%density_unit = 'electron/bohr^3'
metadata%periodic = [0, 1, 0]               ! 示例，不能照抄为真实来源
metadata%endpoint_convention(1) = 'finite_nodes'
metadata%endpoint_convention(2) = 'independent_samples'
metadata%endpoint_convention(3) = 'finite_nodes'
metadata%negative_tolerance = 0.0_cube_dp
call validate_cube_metadata(grid, metadata, status)
! 成功仅表示调用方显式声明符合当前支持契约；不是证明声明为真。
call clear_cube(grid)
```

`read_cube(path, grid, status[, limits])` 的 grid 为 `intent(out)`，会清理该对象
原先持有的数组；调用方若需保留先前已读网格，应传入新的 grid 对象。
输入文件以只读方式打开，文件内容从不改变。

`status` 包含 `code`、`message`、`line`。line 是扫描器当前位置（从1开始），
不适用或在内存/几何/metadata 校验阶段时为0。模块无 `STOP/ERROR STOP`，
不打印日志，不要求交互。测试 probe 中的 `ERROR STOP` 仅处理错误的测试命令行。

grid 具有三个不同标志：

- `structurally_valid`：格式、尺寸、有限性、几何和所选内存预算通过。
- `metadata_validated`：显式物理、单位、周期/端点声明及负密度门限通过。
- `scientifically_certified`：本模块始终初始化/保持为 false；不能据本模块通过宣称
  来源哈希验证、真实密度认证、网格收敛或科学符号验收。

metadata 本身由调用方持有，不从注释、文件名、原子电荷或轴计数猜测。
库导出的派生类型不是防篡改容器；调用方仍必须管理原始文件和不可变来源记录。

## 支持的严格子集

支持任意长度的两行注释、空格/TAB、LF/CRLF/CR、最后无换行符，以及：

1. `NATOMS origin_x origin_y origin_z [NVAL]`；NATOMS 为 int64 非负整数。
2. 三条 `N step_x step_y step_z`；N 为 int64 正整数且每轴至少5点。
3. 恰好 NATOMS 条 `atomic_number charge x y z`，每条必须恰好5个 token。
   原子序数只接受整数1..118；dummy 原子0、元素符号、超范围序数明确拒绝。
   charge/坐标要求有限；charge 不是证明全电子/补核密度的依据。
4. 恰好 Nx*Ny*Nz 个有限 binary64 标量；数据可跨任意行。支持 E/e/D/d 指数、
   可选符号、小数点。拒绝 list-directed 重复项 `125*1`、逗号、斜线、kind 后缀。

负 NATOMS、多轨道扩展、NVAL 不为1、负轴计数单位扩展、附加字段、缺失样点和
多余 token 均拒绝。非法尾随非数值 token 仍按“多余 token”拒绝，不悄悄忽略。
单个 numeric token 最长256字符；超过返回专门错误。注释/数据行没有整行长度上限。

原始样点存于 `grid%rho(:)`，**Z 最快**，0基索引位置 `(ix,iy,iz)` 的 Fortran
1基位置为 `((ix*Ny)+iy)*Nz+iz+1`。不交换轴、不删端点、不插值、不夹零。
原点及三条一步位移分别存于 `origin` 和 `j(:,axis)`。

严格解析器允许有限的负标量以保留原值；物理 metadata 层默认
`negative_tolerance=0`，拒绝任何负密度。显式非零容忍门限下仍保留小负值，
后续数值内核必须按 numerics.md 标记，不得夹零求导。容忍门限的 producer 证据
由上层输入卡负责，本模块不会替调用方证明其合理性。

## 流式读取与资源控制

读取使用只读 unformatted stream、8192字节固定扫描块和256字符单 token 缓冲区；
不创建整文件字符串、逐行 token 列表或整文件 token 数组。密度本身仍按完整网格
存储，首版没有 slab/磁盘缓存接口。

分配前以 int64 溢出保护检查维度乘积、density/atom 字节数和总和。
默认点数上限33,554,432，默认预算256 MiB；预算计入 rho、atom 数组与扫描块，
不是进程 RSS 的严格上限（运行库、描述符、栈及分配器开销另计）。调用方可降低预算；
调高预算需自行承担资源责任。ALLOCATE 使用 STAT，不以分配错误终止宿主。
失败后不保留可误用的部分数组。读取前后重查文件长度，但没有来源内容哈希验证，
同长度的并发修改不在本模块可检测范围。

## 网格与单位

J 中每项必须有限。以最大绝对元素缩放的单边 Jacobi SVD 估计 κ₂(J)，最多50个
sweep；不构造 JᵀJ。只接受可逆且 κ₂<=1000 的网格，允许左手系，不自动正交化。
输出 `j_inv` 与 `volume_element=abs(det(J))`。即使条件数良好，若逆矩阵或 voxel
体积在 binary64 无法表示，也明确拒绝。阈值以浮点估计比较；极近1000的边界
需考虑舍入，解析 diagonal=1000 用例已覆盖。

仅支持明确声明 `length_unit='bohr'`、`density_unit='electron/bohr^3'`；其他单位
返回 UNSUPPORTED_UNIT，不转换。quantity 只接受 `electron_density`，spin 只接受
`spin_summed`；representation 必须在 `all_electron/valence/core_augmented/promolecular`
中选择。逐轴 periodic 必须明确0/1；有限轴必须声明 `finite_nodes`，周期轴必须
声明 `independent_samples`。重复周期端点需要上游独立 adapter，不在本模块移除。

## 错误码

这些是 Fortran 输入模块局部错误码，不占用/更改公共 C ABI 的 nci_status。

| code | 符号 | 原因 |
|---:|---|---|
| 0 | CUBE_OK | 当前层校验通过 |
| 1 | CUBE_IO_ERROR | 打开、读取、长度变化、关闭失败 |
| 2 | CUBE_MISSING_TOKEN | 缺注释、字段或数据 |
| 3 | CUBE_EXTRA_TOKEN | header/atom 多字段或数据尾有多余 token |
| 4 | CUBE_INVALID_INTEGER | 整数词法非法 |
| 5 | CUBE_INVALID_REAL | 实数词法/处理器实数转换失败 |
| 6 | CUBE_NONFINITE | NaN/Inf 或转换结果非有限 |
| 7 | CUBE_UNSUPPORTED | 负计数、多场等不支持扩展 |
| 8 | CUBE_DIMENSION | 非负计数不足5 |
| 9 | CUBE_OVERFLOW | int64 token、长度/字节乘积或求和溢出 |
| 10 | CUBE_MEMORY_LIMIT | 无效或超出调用方预算 |
| 11 | CUBE_ALLOCATION | 分配失败 |
| 12 | CUBE_INVALID_ATOM | 原子序数不在1..118 |
| 13 | CUBE_GRID_SINGULAR | 识别到零奇异值/零行列式 |
| 14 | CUBE_GRID_CONDITION | κ₂超过1000，包括部分退化矩阵 |
| 15 | CUBE_INVALID_METADATA | 未声明/错误的物理或周期/端点含义 |
| 16 | CUBE_UNSUPPORTED_UNIT | 单位不是明确支持的规范单位 |
| 17 | CUBE_INVALID_DENSITY | 密度低于显式负值门限 |
| 18 | CUBE_TOKEN_TOO_LONG | numeric token 超过256字符 |
| 19 | CUBE_GRID_RANGE | SVD未收敛或几何量超出binary64可表示范围 |

对于词法合法但溢出的实数，gfortran13 可给出 infinity（code6）；其他处理器若返回
conversion iostat 错误则为code5；两者均失败且清理输出。

## 开发验证与未实现项

本分支在 WSL Ubuntu 24.04 / gfortran 13.3 Debug（`-fcheck=all`、
`-ffp-contract=off`）构建。CTest 3/3通过：既有C ABI布局、原生Fortran生命周期
15项断言、26组合成输入测试（110次原生Fortran probe调用）。每个生成fixture
在调用前后核对SHA-256，只证明测试输入未被本次读取改写，不是实际来源认证。

`tests/io` 的 Python 标准库测试只生成小 synthetic CUBE 并调用原生 Fortran probe。
覆盖格式、token 数、非有限/非法数、分配前溢出/预算、左手/剪切/缩放网格、已知
奇异值的旋转矩阵条件数与逆、四种 representation、未知物理、单位、负密度和认证
边界。固定种子几何 oracle 使用旋转保持的已知奇异值，不调用待测 SVD 作真值。
原生生命周期测试另覆盖失败后重用、前一次metadata标志清理、可变数组被调用方
改成NaN后的复检、解析失败释放数组与重复clear。

尚未实现：JSON 输入卡读写、来源 SHA-256/授权/producer 验证、单位转换、多场/轨道
adapter、重复端点去除、自动补核、电子数积分诊断、真实 producer 兼容验收、C 入口、
out-of-core/slab 读取和 NCI 求值。没有真实数据/科学计算/GPU卸载/性能结论。
