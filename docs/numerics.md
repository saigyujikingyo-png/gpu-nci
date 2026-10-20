# 数值与输入规范 v0.1

所有阈值是首版拟定契约，需 M1 独立 oracle 校准并冻结；不是已经通过实测的容差。

## 1. 输入物理含义

仅接收明确声明为 **spin-summed electron density（自旋求和的电子密度）** 的单标量场。它与“全电子密度”不是同一概念：另设 `density_representation = all_electron | valence | core_augmented | promolecular`，必须明确选择。unknown、轨道振幅、spin density、密度差、势、RDG 不能当 rho 输入。

valence/promolecular 可用于相应模型的工程验证，但不能自动获得 all-electron 化学解释。目标论文采用补核密度时，对照也必须采用相同补核模型；首版不实现自动补核。CUBE 原子记录的“核电荷”字段不能证明密度已经补核。

`input.json` 至少记录：

| 字段组 | 必需信息 |
|---|---|
| 来源 | 原始路径/稳定链接、SHA-256、字节数、使用权限、producer/version、生成设置 |
| 物理 | quantity、spin convention、density_representation、电子数（已知时）、ECP/赝势/补核说明 |
| 网格 | origin、三个 step vectors、shape、轴顺序、每轴周期性、端点约定 |
| 单位 | length_unit、density_unit，独立声明，不从文件名猜 |
| 精度 | 输出有效位/格式（可得时）、单样点量化误差界或 UNKNOWN |
| 转换 | 转换器版本、参数、输入/输出哈希，任何轴置换或端点移除记录 |

标准路径统一为 bohr、electron/bohr³。非标准 producer 的 Å 坐标仅在明确声明时转换；密度若已是 e/bohr³则不再次缩放。若密度为 e/Å³，转换为 e/bohr³ 时乘 `(Å per bohr)^3`。原点、原子坐标和三个步进向量都必须使用同一长度转换。

## 2. CUBE 严格子集

支持两行注释、原子数与 origin、三条计数/步进、原子记录、单场数据；可变空白、跨行和 E/e/D/d 指数。首版要求 `NATOMS>=0`、网格计数为正、可选 NVAL 缺省或为1、数值 token 数精确等于 NxNyNz。显式无原子的解析 fixture 可使用 NATOMS=0。

负 NATOMS 的多轨道/数据集、NVAL>1、负轴计数扩展、元素符号代替原子序数、多场衍生布局、未知单位均明确拒绝；不偷偷取第一列或用符号猜 Å。可后续由独立 adapter 转换并保留来源。VMD 官方格式说明明确 Z 最快、多轨道额外标识和原子单位；兼容范围以 producer fixture 和本规范为准。[VMD](https://www.ks.uiuc.edu/Research/vmd/plugins/molfile/cubeplugin.html)

检查缺数、多数、NaN/Inf、维度和乘积溢出、非法原子记录、非有限 origin/J、奇异 J。初始支持范围 `κ₂(J)<=1000`；左手网格允许，奇异或超范围则拒绝并报告，不自动正交化。

周期性必须显式声明；对独立 N 个周期样点，cell vector=N*step。有限域跨度为(N−1)*step。重复末端面只能通过已声明适配器检查、生成新输入去重，禁止凭数值相似自行判断。

加入积分诊断 `sum(rho)*abs(det J)`：完整周期胞与已知电子数比较，valence与补核分别对应其电子数；有限分子域须考虑盒外尾部与求积误差，裁剪ROI不要求等于全分子电子数。容差由producer与网格定义冻结，未知电子数标UNKNOWN，不能靠积分正常反推量纲必然正确。

## 3. 四阶差分

整数索引 q=(i,j,k)ᵀ，位置 r=o+Jq，J=[a b c]，a/b/c是**一步位移**。

\[
 D_i\rho(q)=\frac{\rho(q-2e_i)-8\rho(q-e_i)+8\rho(q+e_i)-\rho(q+2e_i)}{12}
\]

\[
 D_{ii}\rho(q)=\frac{-\rho(q-2e_i)+16\rho(q-e_i)-30\rho(q)+16\rho(q+e_i)-\rho(q+2e_i)}{12}
\]

\[
D_{ij}\rho(q)=\sum_{p,t\in\{-2,-1,1,2\}}c_pc_t\rho(q+pe_i+te_j),\quad
c=(1,-8,8,-1)/12 .
\]

因为 q 的步长为1，以上没有物理 h 因子。统一在变换时处理：

\[
g_r=J^{-T}g_q,\qquad H_r=J^{-T}H_qJ^{-1}.
\]

只生成六个独立 Hq 分量，然后显式填成对称矩阵。变换后检查非对称残差并仅允许舍入量级的对称化。Hq 的普通特征值不是非正交网格上的物理曲率；必须对 Cartesian Hr 求特征值。

联合 stencil 共61个不同位置：中心1、轴向12、三个混合导数平面各16。每轴半径2，包括两轴同时偏移的角点。矩形完整 halo2 足够，只有“六张面而无角点”的 halo 不足。不能把一阶差分重复两次当作上述纯二阶差分。

有限边界每个非周期轴两端各2层标无效；periodic轴从全域取模。不降阶、不零填、不把 tile 局部当周期。最小维度5。所有导数使用原密度；rho/ROI筛选放在求导与邻域合法性判断之后。

## 4. 指标与特征值

\[
s(r)=\frac{\|g_r\|}{2(3\pi^2)^{1/3}\rho^{4/3}},\quad
\lambda_1\le\lambda_2\le\lambda_3,\quad
\mathrm{signedrho}_{raw}=\operatorname{sign}(\lambda_2)\rho.
\]

s无量纲，g/H/λ₂单位依次为 e·bohr⁻⁴、e·bohr⁻⁵、e·bohr⁻⁵，signedrho为e·bohr⁻³。NCI指标描述局部密度特征，不等于相互作用能、分离自由能或回收率。[NCI原始工作](https://pubmed.ncbi.nlm.nih.gov/20394428/)

基线采用缩放的对称3×3 Jacobi：先除以最大绝对元素，零矩阵单独处理；循环消去最大非对角项，使用防溢出的旋转公式，最多30次旋转，达到归一化 off-diagonal Frobenius norm <=64ε 即停。未达到则 `EIGEN_NONCONVERGED`，不输出伪正常值。排序按数值，不按绝对值。将来闭式法必须独立覆盖退化/重根/零矩阵/acos边界后才能替换。

生产旋转上限固定30并入回执；失败分支测试通过仅测试构建可用的`test_max_rotations=1`注入，以矩阵`[[2,1,1],[1,2,1],[1,1,2]]`触发未收敛。生产二进制不暴露此参数。无需假定一定存在能耗尽30次旋转的正常3×3输入。

独立 oracle 使用 SciPy/LAPACK `eigvalsh`，记录driver与库版本，并提前验证对称性。生产 Fortran 和 GPU 共享逻辑是移植手段，不能因此把其中一个当科学真值。

Fortran统一 `implicit none`、`real(c_double)`或等效dp，并为常数/指数加 `_dp`；避免`1.0/3.0`先按默认real求值。RDG常数以独立高精度生成的binary64常数及来源同时固定于两个后端。基线记录并控制FMA：GNU `-ffp-contract=off`、nvfortran host/device显式nofma、nvcc `--fmad=false`为候选诊断配置；具体开关经固定编译器验证。生产FMA模式另建配置回归，不能静默改变。

## 5. 异常、mask 与统计分母

全域出现 NaN/Inf、显著负值或错误格式，默认整任务预检失败。首版默认负密度容忍值为0；针对已证明舍入负尾的 producer，必须在输入卡上冻结非零容差并报告来源，不能运行中自动放宽。

允许范围内的小负值保持原数据，不参与中心点RDG，并使包含该值的精确61点邻域导数标 `STENCIL_INVALID`；不得夹零再求导。严格零密度是合法样点但中心RDG不可用。普通正的低密度点仍参与其他点的差分，不能先删除。

默认 rho_min=1e−8 e/bohr³；仅 `0<rho<=rho_min` 标 `LOW_RHO`，非正rho使用NONPOSITIVE_RHO位。阈值改变属于新配置，应报告敏感性。高密度/高RDG筛选是可视化ROI，不能改变原始数值。

uint8 bit定义：

| bit | 名称 | 含义 |
|---:|---|---|
| 0 | BOUNDARY | 非周期边界不具备完整stencil |
| 1 | NONPOSITIVE_RHO | 中心rho<=0 |
| 2 | LOW_RHO | 正rho<=rho_min |
| 3 | STENCIL_INVALID | 邻域含被拒作数值样点的值 |
| 4 | NUMERIC_FAILURE | 本应计算的字段eigen未收敛/异常非有限/严重非对称 |
| 5 | LAMBDA_NUM_UNCERTAIN | 数值误差下λ₂符号不确定 |
| 6 | LAMBDA_SCI_UNCERTAIN | 网格与输入误差下符号不确定；未知也置位 |
| 7 | RESERVED | v0.1必须为0 |

bits可重叠，不能把各bit计数直接相加作为无效点数。数值有效域 V 用bits0–4的并集补集确定；稳定符号集合另排bits5/6。报告每bit计数、唯一无效点数、V总数、ROI与其分母。V为空判验收失败。科学稳定集合为空/覆盖不足时写 `INSUFFICIENT_COVERAGE`，不能用空集宣称100%一致。

逐字段输出规则：bits0–3任一置位，v0.1正式输出的RDG、λ₂、signedrho全部写约定NaN，原rho仍在原文件/规范缓存中保留；这些预期NaN不触发bit4，bits5–6保持0。有效路径若eigen或其他运算异常，置bit4并将三个结果写NaN；这会使配置失败。仅bits5/6置位时三个原始结果仍保留有限值。小fixture诊断模式可另导出低rho处Hessian，但不得混入正式结果语义。

bits0–3由输入决定，必须逐点一致；bit4任何一侧出现都要判该配置数值失败。bits5–6在误差阈值附近可能因舍入产生差别：仅在预冻结的分类边界带 `abs(abs(lambda2_ref)-tau_ref)<=B_lambda_ref+B_lambda_test+B_tau` 内允许差别，逐点报告，不能任意扩大为“近零都不比较”。raw sign翻转与flag翻转分别计数。

保留λ₂、原始signedrho和不确定标志；不把近零带硬改成中性。λ₂恰为0时signedrho为0。记录阈值内/外翻转数及阈值内覆盖比例。

## 6. 三类误差预算

1. **实现/浮点误差**：同一离散输入，不同CPU/GPU执行路径造成的差异。
2. **离散误差**：连续密度到有限差分导数的截断误差。
3. **输入误差**：文本有效位、密度生成、插值、补核等造成的误差。

GPU/CPU容差只处理第1类，绝不能因为输入很粗而放宽实现容差。

若单样点量化绝对误差上界为δρ，权重绝对值和给出索引空间界：

- |δD_i| <=1.5δρ。
- |δD_ii| <=(16/3)δρ。
- |δD_ij| <=2.25δρ。

再传播经J⁻¹变换为δHr；保守可用 Frobenius norm 上界替代谱范数。Weyl界给出 |δλ₂|<=||δHr||₂。h变小会以约h⁻²放大量化误差，FP64不会恢复文本丢失的有效位；例如一些程序的CUBE默认仅输出约5–6位。[CP2K输出源码](https://www.cp2k.org/static/coverage/src/pw/realspace_grid_cube.F.gcov.html)

初始 `tau_num = 1e−12 e·bohr⁻⁵ + 1e−10 ||Hr||₂ + B_lambda_comp`，用于计算符号稳定性，M1须用oracle和先验误差分析冻结。`B_lambda_comp`计入局部stencil消减、坐标变换和eigen残差。`tau_sci = tau_num + E_quant + E_grid`只说明相对于已声明密度模型的数值可信度；另列E_model=UNKNOWN时不宣称物理模型误差已界定。若E_quant或E_grid未知，不能把它当0。

首版认证的**输出网格固定为h网格**；另从同一连续密度独立采样h/2、h/4，只在输出h的共同节点和共同内部ROI比较，禁止用粗网格插值生成细网格。在确认四阶渐近区后，输出h的截断误差估计为 `E_grid_h = (16/15)*||H(h/2)−H(h)||`；h/4用于检查渐近关系。这样每个待认证的输出h节点都有估计，不存在只认证细网格1/8却声称全域覆盖的问题。

`||H(h/2)−H(h)||/15`只估计**这些重合节点上的细网格h/2误差**，不能赋给所有细网格节点或粗h节点。若另要求认证整张h/2输出，须重新以h/2为目标并取得对应更细采样；本轮不把估计插值当作证明。Richardson量是渐近估计，不是任意真实CUBE的严格上界。只有插值细网格、输入量化未知或未进入渐近区时，科学符号状态保持未认证。
