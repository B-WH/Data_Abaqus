# Data_Abaqus 工具集

这个项目包含两个工具：

- `odb_extract`：从 Abaqus `.odb` 文件中提取频响场数据，并可按目标坐标导出节点场取点结果。
- `mesh_convert`：把 `.stp`、`.step` 或 STEP-like `.ins` 几何文件转换为 Abaqus `.inp` 网格。

两个工具都支持 GUI 和命令行。ODB 的真实读取必须在 Abaqus Python 中执行，普通 Python 负责启动器、参数校验、GUI 和后处理。

## 环境准备

安装普通 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

`requirements.txt` 当前用于安装 `mesh_convert` 需要的 `gmsh`，以及目标点 Excel 输入需要的 `openpyxl`。如果使用 `odb_extract` 的目标点后处理，并且普通 Python 环境缺少 NumPy，请额外安装：

```powershell
python -m pip install numpy
```

运行 ODB 提取还需要本机安装 Abaqus，并能通过 `abaqus`、`abq2024`、`abq2023`、`abq2022` 或环境变量 `ABAQUS_COMMAND` 找到 Abaqus 命令。

## ODB 数据提取

### 程序边界

- `python -m odb_extract` 是普通 Python 入口，负责 GUI、参数校验、调用 Abaqus 命令和后处理串联。
- `odb_extract.extractor` 必须由 Abaqus Python 执行，负责实际读取 `.odb`；启动器会自动用脚本绝对路径调用它，因此可从项目目录以外启动。
- `odb_extract.interpolate_points` 是普通 Python 后处理脚本，读取已导出的 NPZ、metadata JSON 和目标点坐标文件，并输出目标点 NPZ/JSON。

普通 Python 不能直接导入 Abaqus 的 `odbAccess`。如果手动运行提取脚本，应改用 Abaqus Python，例如：

```powershell
abaqus python -m odb_extract.extractor --odb data\test1.odb
```

### 推荐用法

双击或运行启动器时，不带参数会打开 GUI：

```powershell
python -m odb_extract
```

GUI 默认使用“ODB 提取”数据来源，通常按以下顺序操作：

1. 选择 `.odb` 文件。
2. 点击“读取场输出”，勾选需要导出的字段。
3. 按需填写实例、节点编号、节点集、频率范围过滤。
4. 如需按坐标取点，选择目标点坐标文件（`.csv`、`.xlsx` 或 `.xlsm`）。
5. 点击“开始提取”。

节点集和目标点坐标文件是两种互斥输入方式，不能同时填写。

如果同一个 ODB 需要反复导出不同目标点，可勾选“保留并复用全模型已选场缓存”。缓存只包含当前勾选的场输出；更改 ODB、Step、字段、实例/节点/节点集或频率范围后会自动重新提取。一次性导出时保持不勾选，程序继续使用并清理临时 NPZ/JSON。节点场在 Abaqus 支持时使用 bulkDataBlocks 批量读取；接口不可用或数据块不兼容时自动回退到逐值读取。

如果已有全节点 `*_point_data.npz` 或 `*_full_field_data.npz`，可把数据来源切换为“已有缓存”：

1. 选择缓存 NPZ；程序自动读取配套 metadata，并列出其中的节点场和节点集。
2. 勾选要输出的场，然后选择一种操作：
   - 提供目标点 CSV/XLSX：按现有规则进行精确命中或反距离加权；节点集可用于限制候选节点。
   - 不提供目标点文件、选择一个或多个节点集：直接筛选缓存中的原始节点并另存 NPZ/metadata，不插值、不重算。
3. 设置不同于源缓存的输出 NPZ 路径，点击“开始查询”。该模式不需要 ODB、Abaqus、Step 或频率过滤，也不会在缓存无效时静默重读 ODB。

多个节点集取并集并去重，直接提取时保留源缓存节点顺序，且只保存当前勾选的场。新生成的 schema v3 节点缓存会把装配级节点集成员压缩保存到 NPZ；旧缓存仍可查询全部节点，但不能按节点集直接提取。输出的节点集索引会重新映射，因此新 NPZ 仍可继续作为缓存使用。目标点查询的默认输出位于缓存目录，名称为 `<目标点文件名>_point_data.npz`；任何缓存输出都不能覆盖源缓存。

CLI 仍保留用于自动化：

```powershell
python -m odb_extract --odb data\test1.odb --fields U V A
```

带目标点导出：

```powershell
python -m odb_extract --odb data\test1.odb --points points.csv --fields U V
python -m odb_extract --odb data\test1.odb --points points.xlsx --fields U V
```

按节点集过滤导出：

```powershell
python -m odb_extract --odb data\test1.odb --node-sets NSET_TOP
```

### 目标点坐标文件格式

目标点坐标文件可以是 `.csv`、`.xlsx` 或 `.xlsm`。首行表头至少需要这些列：

```csv
point_id,x,y,z
p1,0.0,0.0,0.0
p2,1.0,0.0,0.0
```

`point_id` 可为空；为空时程序按行号生成点编号。
Excel 文件默认读取第一个工作表，不支持旧 `.xls` 格式。

### 输出文件

- `*_point_data.npz`：数值数组，包括频率、节点标签、节点坐标、各字段实部和虚部。
- `*_point_metadata.json`：字段、节点、坐标、数组布局、过滤条件和 warning 信息。

ODB 提取和目标点查询流程不直接导出 CSV。节点集直接提取保持节点场的 `frame,node,component` 布局；目标点插值结果使用 `frame,point,component` 布局。

目标点坐标模式也输出同名 NPZ/JSON，其中 NPZ 包含：

- `frequencies`：频率轴。
- `point_ids`：输入点编号。
- `point_coordinates`：输入点坐标。
- `<field>_real` / `<field>_imag`：形状为 `frame,point,component` 的目标点结果。

metadata JSON 中的 `points[].method` 表示取值方式：

- `exact`：目标点坐标在容差内命中某个节点，直接使用该节点值。
- `weighted`：未命中节点时，使用邻近节点反距离加权。

### 查看 NPZ 并导出幅值 CSV

主窗口点击“查看/转换 NPZ”，选择本工具生成的 NPZ。程序自动读取配套 metadata，
显示数组结构和预览，并可按字段、分量、频率及节点、点或单元编号筛选。导出的宽表
以前三列记录频率、字段和分量，其后将点编号横向展开为列；点编号下先写 `x`、`y`、
`z` 三行坐标，再按频率向下记录复数结果的幅值 `hypot(real, imag)`。
CSV 不包含实部、虚部或相位。
数据量超过 Excel 单工作表行数上限时，程序会在写出前提示确认。

`points[]` 还会记录 `neighbor_labels`、`neighbor_weights` 和 `neighbor_distances`；
`points[].fields[field]` 保留每个输出字段对应的同类取值明细。

注意：当前目标点导出是节点值精确命中或反距离加权，不是基于 Abaqus 单元形函数的严格单元内插值。

## 合并多个频率段结果

如果同一模型分多个 ODB 计算不同频率段，例如 `1-100 Hz`、`100-200 Hz`、
`200-300 Hz`，先分别导出 NPZ 和配套 metadata JSON。程序按以下规则自动配对：

- `*_data.npz` 对应同目录的 `*_metadata.json`，例如
  `j-test_100_data.npz` 对应 `j-test_100_metadata.json`；
- 其他 `任意名称.npz` 对应同目录的 `任意名称.json`。

然后在 GUI 主窗口点击 `合并结果`，选择多个 NPZ 文件。合并只读取已导出的
NPZ/JSON，不重新打开 ODB。

命令行也可以直接运行：

```powershell
python -m odb_extract.merge_point_data --input a_point_data.npz b_point_data.npz --output merged_point_data.npz --metadata-output merged_point_metadata.json
```

合并前会校验节点、坐标、字段、分量和数组布局一致；所有 frame 轴数组按频率拼接并
排序。边界重复频率在容差内数据一致时只保留一帧，不一致则停止并报错，不会静默覆盖。
输出 NPZ/JSON 不能与任一输入 NPZ/metadata 路径相同，避免误覆盖源数据。

## 测试

运行全部普通 Python 单元测试：

```powershell
python -m unittest discover -v
```

也可以显式运行当前测试模块：

```powershell
python -m unittest tests.test_extract_data_odb tests.test_interpolate_odb_points tests.test_run_extract_odb -v
```

这些测试不需要真实 Abaqus 环境；真实 `.odb` 读取仍需在装有 Abaqus 的机器上验证。

### ODB 打包注意

如果使用 PyInstaller 打包，必须把外部 Abaqus Python 需要执行的提取脚本包含进包内：

- `odb_extract/extractor.py`

`Extract_ODB.spec` 已配置该文件，并保留目标点后处理模块；修改提取或后处理脚本后需要重新打包。

## STEP/STP/INS 几何转 Abaqus INP 网格

本仓库还包含 `mesh_convert`，这是一个独立的网格转换工具，用于把 `.stp`、`.step`
几何文件转换为 Abaqus `.inp` 网格文件。`.ins` 文件只有在内容可识别为
STEP/ISO-10303 时才会被接受；普通 Abaqus 输入文件会直接报错，不会静默生成无效网格。

### 安装

```powershell
python -m pip install -r requirements.txt
```

`mesh_convert` 使用 Gmsh Python API 和 OpenCASCADE 读取 STEP 几何。如果当前
Python 版本没有可用的 `gmsh` wheel，请切换到受支持的 Python 或 Conda 环境后重新安装。

### 用法

GUI 优先使用方式：

```powershell
python -m mesh_convert
```

不带命令行参数启动时，`mesh_convert` 会打开桌面 GUI。界面中可以选择输入
几何文件、输出 `.inp`、日志/report 路径、网格尺寸、维度模式、目标单元类型，
以及是否允许混合单元降级。转换结束后，GUI 会读取 JSON report，并直接显示
是否成功、节点数、单元数、单元类型统计、是否发生 mixed 降级和警告信息。
下面的命令行模式仍保留给自动化流程使用。

构建 Windows GUI 可执行文件：

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller
.\packaging\build_mesh_convert_exe.ps1
```

可执行文件输出到 `dist\mesh_convert_gui\mesh_convert_gui.exe`。PowerShell
执行策略和重试方式见 `packaging\README.md`。

```powershell
python -m mesh_convert input.stp output.inp --dim auto --target hex --size 2.0 --order 1 --allow-degrade --log mesh.log --report mesh_report.json
```

参数说明：

- `input_path`：输入 `.stp`、`.step` 或 STEP-like `.ins` 文件。
- `output_path`：输出 Abaqus `.inp` 文件。
- `--size`：全局网格尺寸，默认 `1.0`，必须大于 0。
- `--dim auto|2d|3d`：维度模式，默认 `auto`。
- `--target hex|quad|mixed`：目标单元族，默认 `hex`。二维几何中 `hex` 会按 `quad` 处理，并写入 warning。
- `--element-type C3D8|C3D8R|S4|S4R`：指定 Abaqus 单元类型。三维默认 `C3D8R`，二维默认 `S4R`。
- `--order 1|2`：当前只支持一阶网格；传入 `--order 2` 会明确失败。
- `--allow-degrade` / `--no-allow-degrade`：允许或拒绝降级为 mixed 单元。默认不允许静默降级。
- `--log`：可选日志文件路径。
- `--report`：可选 JSON 诊断报告路径。

### 网格策略和限制

- 三维实体会先尝试结构化、扫掠友好的 transfinite 和 recombine 设置，再尝试 Gmsh 三维 recombination。
- 二维面模型会启用 recombination，并优先生成四边形单元。
- Gmsh 不能保证对任意复杂实体自动生成纯六面体网格。复杂模型可能得到四面体、棱柱、金字塔或其他 mixed 单元。
- 如果目标是 `hex` 或 `quad`，但实际生成 mixed 单元，默认会以非零退出码失败并说明原因。接受 mixed 输出时显式加 `--allow-degrade`。
- 现有 Gmsh physical groups 会尽量保留为 Abaqus `*NSET` 和 `*ELSET`；没有分组时会生成 `VOL_<tag>`、`SURF_<tag>` 等稳定名称。

### 网格转换测试

单元测试不需要 Abaqus，也不需要真实 Gmsh 后端：

```powershell
python -m unittest discover -v
```

安装 Gmsh 后，可以用真实 STEP 文件做转换验证：

```powershell
python -m mesh_convert examples/box.step output/box.inp --dim 3d --target hex --size 2.0 --no-allow-degrade --report output/box_report.json
python -m mesh_convert examples/plate.step output/plate.inp --dim 2d --target quad --size 2.0 --report output/plate_report.json
```
