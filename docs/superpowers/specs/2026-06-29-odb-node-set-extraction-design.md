# ODB 节点集提取功能 — 设计文档

**日期**: 2026-06-29
**状态**: 已批准

## 目标

在现有 ODB 数据提取工具中增加按节点集（Node Set）筛选节点的能力。用户可以选择 ODB 中预定义的节点集来限定提取范围，作为现有实例/节点编号过滤的补充。

## 架构概览

修改三个文件：

| 文件 | 角色 | 改动 |
|------|------|------|
| `odb_extract/extractor.py` | Abaqus Python 端，读取 ODB | 新增 `--node-sets`、`--list-node-sets`；新增节点集收集与过滤逻辑 |
| `odb_extract/launcher.py` | 普通 Python 端，GUI/CLI | 新增节点集发现函数；GUI 新增节点集选择区域；传递 `--node-sets` 参数 |
| `tests/` | 单元测试 | 覆盖新增的解析、过滤、命令构建、GUI 验证逻辑 |

不修改 `interpolate_points.py` 和 `mesh_convert/`。

## 数据流

### 1. 节点集发现

```
用户点击"读取节点集"
  → launcher.py 构建命令: abaqus python -m odb_extract.extractor --odb X.odb --list-node-sets
  → extractor.py 打开 ODB, 遍历 odb.rootAssembly.nodeSets
  → 输出 JSON: {"node_sets": ["NSET_TOP", "NSET_BOTTOM", ...], "source_odb": "..."}
  → launcher.py 解析 JSON, GUI 显示 Checkbox 列表
```

### 2. 提取时叠加过滤（AND 逻辑）

```
用户指定: instances=["PART-1-1"], node_sets=["NSET_TOP"], node_labels=[1,2,3]
  → collect_nodes(odb, instances, node_labels, node_set_names):
      1. 遍历所有实例节点
      2. 如果指定 instances → 过滤
      3. 如果指定 node_labels → 过滤
      4. 如果指定 node_set_names → 过滤（节点属于任一指定节点集）
      5. 返回同时满足所有条件的节点（AND 叠加）
  → 后续提取流程不变
```

### 3. 命令行传递

```
launcher 生成: abaqus python -m odb_extract.extractor --odb X.odb --node-sets NSET_TOP NSET_BOTTOM
extractor 解析: args.node_sets = ["NSET_TOP", "NSET_BOTTOM"]
```

## 详细设计

### extractor.py 改动

**新增参数**：
- `--node-sets`：接受节点集名称列表（nargs="+"）
- `--list-node-sets`：列出可用节点集并退出（store_true）

**新增函数**：
- `collect_node_sets(odb)` → `dict[str, list[NodeRef]]`：遍历 `odb.rootAssembly.nodeSets`，返回每个节点集包含的节点引用列表
- `list_node_sets(odb)` → `list[str]`：返回所有节点集名称
- `run_list_node_sets(args)`：入口函数，输出 JSON

**修改函数**：
- `collect_nodes(odb, instances=None, node_labels=None, node_set_names=None)`：新增 `node_set_names` 参数。如果指定，先收集各节点集内的节点，然后只保留属于这些节点集的节点。不存在的节点集名称产生 warning。
- `run(args)`：传递 `node_set_names` 给 `collect_nodes()`；在 filters 和 command_options 中记录 node_sets
- `main(argv)`：处理 `--list-node-sets` 分支

**节点集查询逻辑**：
```python
# Abaqus ODB API: odb.rootAssembly.nodeSets[name] 返回 OdbSet
# OdbSet 包含 nodes 序列，每个 node 有 label 和 instanceName
def collect_nodes(odb, instances=None, node_labels=None, node_set_names=None):
    # ... 现有逻辑收集 candidate_nodes ...
    if node_set_names:
        # 构建节点集成员快速查找集合
        nset_members = set()
        for nset_name in node_set_names:
            if nset_name in odb.rootAssembly.nodeSets:
                nset = odb.rootAssembly.nodeSets[nset_name]
                for node in nset.nodes:
                    nset_members.add((node.instanceName, node.label))
            else:
                warnings.append("Node set {!r} not found in ODB.".format(nset_name))
        # 过滤
        nodes = [n for n in nodes if (n.instance_name, n.label) in nset_members]
    return sorted(nodes, key=...)
```

### launcher.py 改动

**新增 CLI 参数**：
- `--node-sets`：节点集名称列表（nargs="+"）

**新增函数**：
- `discover_node_sets(abaqus_command, extractor_module, odb_path, step_name=None, runner=None)`：调用 Abaqus 子进程 `--list-node-sets`，解析 JSON 返回结果
- `build_node_set_list_command(abaqus_command, extractor_module, odb_path)`：构建 `--list-node-sets` 命令
- `parse_node_set_text(text)` → `list[str] | None`：解析手动输入的节点集名称文本
- `parse_node_set_list_output(output_text)` → `dict`：解析 `--list-node-sets` 的 JSON 输出

**修改函数**：
- `build_extraction_command()`：新增 `node_sets` 参数，附加 `--node-sets` 到命令
- `run_extraction()`：新增 `node_sets` 参数
- `run_workflow()`：新增 `node_sets` 参数，传递给 `run_extraction()`
- `run_cli()`：传递 `args.node_sets` 给 `run_workflow()`

**GUI 改动** (`ExtractOdbApp`)：
- 新增 UI 文本到 `UI_TEXT`：
  - `"node_set_filter"`: "节点集"
  - `"node_set_hint"`: "请选择 ODB 文件以读取节点集。"
  - `"no_node_sets_found"`: "未找到节点集。"
  - `"found_node_sets"`: "已在 ODB 中找到 {count} 个节点集。"
  - `"select_all_node_sets"`: "全选"
  - `"clear_all_node_sets"`: "全不选"
  - `"refresh_node_sets"`: "读取节点集"
  - `"node_set_discovery_failed"`: "读取节点集失败"
  - `"node_set_discovery_failed_log"`: "读取节点集失败：{error}"
- 新增 Instance 变量：`node_sets_var`（StringVar，手动输入）、`node_set_vars`（dict，Checkbox 变量）、`_node_set_canvas`（Canvas）
- 新增方法：
  - `_build_node_set_widgets()`：构建节点集区域（文本框 + 按钮 + Canvas + Checkbox）
  - `refresh_node_sets()`：后台线程触发节点集发现
  - `_discover_node_sets_worker()`：工作线程，调用 `discover_node_sets()`
  - `_show_discovered_node_sets(metadata)`：填充 Checkbox 列表
  - `_clear_node_set_checks()`：清空 Checkbox
  - `_sync_node_sets_from_checks()`：从 Checkbox 同步到文本框
  - `_set_node_set_selection(mode)`：全选/全不选
- 修改 `_validate_inputs()`：解析 `node_sets_var`，返回 `node_sets` 字段
- 修改 `choose_odb()`：选择 ODB 后自动刷新节点集列表
- 修改 `_set_running()`：同时禁用/启用节点集按钮

**GUI 布局**：在节点编号行下方、频率范围行上方插入节点集区域：
```
[节点编号]    [____________________]
[节点集]      [____________________] [读取节点集] [全选] [全不选]
[节点集列表 Canvas — Checkbox]
```

**交互规则**：
- 复选框勾选/取消 → 文本框自动同步
- 手动输入文本框 → 不自动反向同步复选框（避免覆盖）——但选择 ODB 后首次读取节点集时，如果文本框已有内容，自动匹配勾选
- 仅在发现成功后才显示 Checkbox 列表区域
- ODB 中无节点集时显示"未找到节点集"提示

### 错误处理

| 场景 | 行为 |
|------|------|
| 未选 ODB 点"读取节点集" | 日志提示"请先选择 ODB 文件" |
| Abaqus 命令为空 | 日志提示"请设置 Abaqus 命令" |
| 子进程失败 | 弹窗显示错误，日志记录详情 |
| 输入的节点集在 ODB 中不存在 | extractor 记录 warning（非致命），结果节点数为 0 |
| ODB 中无任何节点集 | 显示"未找到节点集"提示 |

## 测试策略

### extractor 端 (`test_extract_data_odb.py`)

- `test_list_node_sets_returns_json` — `--list-node-sets` 输出正确 JSON 格式
- `test_collect_node_sets_returns_dict` — `collect_node_sets()` 返回 `dict[str,list]`
- `test_collect_nodes_filters_by_node_set` — node_set_names 过滤正确
- `test_collect_nodes_and_combines_filters` — instance + labels + node_sets 叠加
- `test_node_set_not_found_emits_warning` — 不存在名称产生 warning
- `test_node_sets_argument_parsing` — `--node-sets` 参数解析

### launcher 端 (`test_run_extract_odb.py`)

- `test_build_extraction_command_includes_node_sets` — 命令包含 `--node-sets`
- `test_discover_node_sets_parses_output` — JSON 解析正确
- `test_discover_node_sets_failure_raises` — 失败抛异常
- `test_ui_text_has_node_set_labels` — UI_TEXT 完整性
- `test_validate_inputs_parses_node_sets` — GUI 验证逻辑
- `test_parse_node_set_text` — 空格/逗号分隔解析

### 测试原则
- 不依赖真实 Abaqus 环境
- 使用 mock：FakeVar、fake_runner、mock.patch
- 现有测试全部保持通过
