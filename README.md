# Abaqus ODB 数据提取工具

这个项目用于从 Abaqus `.odb` 文件中提取频响场数据，并可按目标坐标导出节点场的取点结果。

## 程序边界

- `python -m odb_extract` 是普通 Python 入口，负责 GUI、参数校验、调用 Abaqus 命令和后处理串联。
- `odb_extract.extractor` 必须由 Abaqus Python 执行，负责实际读取 `.odb`。
- `odb_extract.interpolate_points` 是普通 Python 后处理脚本，读取已导出的 NPZ、metadata JSON 和目标点 CSV。

普通 Python 不能直接导入 Abaqus 的 `odbAccess`。如果直接运行 `odb_extract.extractor` 时提示缺少 `odbAccess`，应改用 Abaqus Python，例如：

```powershell
abaqus python -m odb_extract.extractor --odb data\test1.odb
```

## 推荐用法

双击或运行启动器时，不带参数会打开 GUI：

```powershell
python python -m odb_extract
```

GUI 中通常按以下顺序操作：

1. 选择 `.odb` 文件。
2. 点击“读取场输出”，勾选需要导出的字段。
3. 按需填写实例、节点编号、频率范围过滤。
4. 如需按坐标取点，选择目标点 CSV，并确认目标点输出 CSV 路径。
5. 点击“开始提取”。

CLI 仍保留用于自动化：

```powershell
python python -m odb_extract --odb data\test1.odb --fields U V A
```

带目标点导出：

```powershell
python python -m odb_extract --odb data\test1.odb --points points.csv --point-fields U V
```

## 目标点 CSV 格式

目标点 CSV 至少需要这些列：

```csv
point_id,x,y,z
p1,0.0,0.0,0.0
p2,1.0,0.0,0.0
```

`point_id` 可为空；为空时程序按行号生成点编号。

## 输出文件

- `*_point_data.npz`：数值数组，包括频率、节点标签、节点坐标、各字段实部和虚部。
- `*_point_metadata.json`：字段、节点、坐标、数组布局、过滤条件和 warning 信息。
- `*_interpolated_points.csv`：目标点长表结果。

目标点 CSV 输出中的 `method` 表示取值方式：

- `exact`：目标点坐标在容差内命中某个节点，直接使用该节点值。
- `weighted`：未命中节点时，使用邻近节点反距离加权。

注意：当前目标点导出是节点值精确命中或反距离加权，不是基于 Abaqus 单元形函数的严格单元内插值。

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

## 打包注意

如果使用 PyInstaller 打包，必须把以下脚本包含进包内：

- `odb_extract.extractor`
- `odb_extract.interpolate_points`

`Extract_ODB.spec` 当前可能被 `.gitignore` 忽略；检查打包配置时应显式查看该文件内容。
## STEP/STP/INS geometry to Abaqus INP mesh conversion

This repository also includes `mesh_convert`, an independent command-line program
for converting `.stp` / `.step` geometry files into Abaqus `.inp` mesh files.
`.ins` files are accepted only when their content is recognizable as
STEP/ISO-10303. Other `.ins` files fail with a clear error instead of silently
producing an invalid mesh.

### Install

```powershell
python -m pip install -r requirements.txt
```

`mesh_convert` uses the Gmsh Python API and OpenCASCADE for STEP import. If the
current Python version has no compatible `gmsh` wheel, use a supported
Python/Conda environment and install again.

### Usage

```powershell
python -m mesh_convert input.stp output.inp --dim auto --target hex --size 2.0 --order 1 --allow-degrade --log mesh.log --report mesh_report.json
```

Parameters:

- `input_path`: input `.stp`, `.step`, or STEP-like `.ins` file.
- `output_path`: output Abaqus `.inp` file.
- `--size`: global mesh seed size. Default is `1.0`; it must be greater than zero.
- `--dim auto|2d|3d`: dimension mode. Default is `auto`.
- `--target hex|quad|mixed`: preferred element family. Default is `hex`. For 2D
  geometry, `hex` is treated as `quad` and recorded as a warning.
- `--element-type C3D8|C3D8R|S4|S4R`: preferred Abaqus element type. Defaults are
  `C3D8R` for 3D and `S4R` for 2D.
- `--order 1|2`: only first-order output is currently supported. `--order 2`
  fails explicitly.
- `--allow-degrade` / `--no-allow-degrade`: allow or reject explained fallback to
  mixed elements. The default is no silent degradation.
- `--log`: optional log file path.
- `--report`: optional JSON diagnostic report path.

### Mesh strategy and limits

- 3D solid models first attempt explainable structured/sweep-friendly
  transfinite and recombine settings, then Gmsh 3D recombination.
- 2D face models enable recombination and prefer quadrilateral elements.
- Gmsh is not a guaranteed fully automatic hexahedral mesher for arbitrary
  complex geometry. Complex solids may produce tetrahedral, prism, pyramid, or
  other mixed elements.
- If the requested target is `hex` or `quad` and the generated mesh contains
  mixed elements, the default behavior is a non-zero exit with a clear reason.
  With `--allow-degrade`, the program writes the mixed INP and records the
  downgrade reason and element statistics in the log/report.
- Existing Gmsh physical groups are preserved as much as possible as `*NSET` and
  `*ELSET`; when no groups exist, stable names such as `VOL_<tag>` and
  `SURF_<tag>` are generated.

### Tests

The unit tests do not require Abaqus or a real Gmsh backend:

```powershell
python -m unittest discover -v
```

After installing Gmsh, real STEP files can be converted with:

```powershell
python -m mesh_convert examples/box.step output/box.inp --dim 3d --target hex --size 2.0 --no-allow-degrade --report output/box_report.json
python -m mesh_convert examples/plate.step output/plate.inp --dim 2d --target quad --size 2.0 --report output/plate_report.json
```
