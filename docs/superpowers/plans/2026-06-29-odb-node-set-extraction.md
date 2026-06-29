# ODB 节点集提取功能 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 ODB 数据提取工具中增加按节点集筛选节点的能力，支持 GUI 自动发现和手动输入两种方式。

**Architecture:** 在 extractor.py（Abaqus Python 端）新增 `--node-sets`/`--list-node-sets` 参数和节点集过滤逻辑；在 launcher.py（普通 Python 端）新增节点集发现函数和 GUI 控件。节点集过滤与现有实例/节点编号过滤为 AND 叠加关系。

**Tech Stack:** Python 3, Abaqus Python API (odbAccess), tkinter, numpy, argparse, subprocess

## Global Constraints

- extractor.py 只能在 Abaqus Python 下运行（依赖 odbAccess）
- launcher.py 在普通 Python 下运行，通过子进程调用 Abaqus
- 节点集不影响 interpolate_points.py 和 mesh_convert/
- 所有单元测试不依赖真实 Abaqus 环境
- 现有测试必须全部保持通过

---

### Task 1: extractor.py — CLI 参数、节点集列出和过滤逻辑

**Files:**
- Modify: `odb_extract/extractor.py`

**Interfaces:**
- Consumes: (none — first task)
- Produces:
  - `parse_args()` 新增 `--node-sets` (list[str]|None) 和 `--list-node-sets` (bool) 参数
  - `list_node_sets(odb) -> list[str]` — 返回所有节点集名称
  - `run_list_node_sets(args)` — 入口，打印节点集 JSON 并返回
  - `collect_nodes(odb, instances=None, node_labels=None, node_set_names=None, warnings=None) -> list[NodeRef]` — 修改签名，新增 node_set_names 和 warnings 参数
  - `run(args)` — 传递 node_set_names，合并 warnings
  - `main(argv)` — 处理 `--list-node-sets` 分支，然后是 `--list-fields`

- [ ] **Step 1: 在 `parse_args()` 中添加 `--node-sets` 和 `--list-node-sets` 参数**

在 [extractor.py:32-81](odb_extract/extractor.py#L32-L81) 的 `parse_args` 函数中，在 `--list-fields` 参数（第 76-80 行）之前添加：

```python
    parser.add_argument(
        "--node-sets",
        nargs="+",
        default=None,
        help="Optional node set names to filter nodes by.",
    )
    parser.add_argument(
        "--list-node-sets",
        action="store_true",
        help="Print available node set names as JSON and exit.",
    )
```

完整上下文：在 `--frequency-max` 参数之后、`--list-fields` 参数之前插入。注意 `--list-fields` 在 `--list-node-sets` 之后，`--list-node-sets` 在 `--frequency-max` 之后。

- [ ] **Step 2: 添加 `list_node_sets()` 函数**

在 `collect_nodes` 函数之前（[extractor.py:123](odb_extract/extractor.py#L123) 之前）添加：

```python
def list_node_sets(odb):
    """Return sorted list of node set names in the ODB assembly."""
    return sorted(odb.rootAssembly.nodeSets.keys())
```

- [ ] **Step 3: 添加 `run_list_node_sets()` 函数**

在 `run` 函数之前（[extractor.py:478](odb_extract/extractor.py#L478) 之前）添加：

```python
def run_list_node_sets(args):
    """Print available node sets as JSON and exit."""
    odb = open_odb_readonly(args.odb)
    try:
        node_set_names = list_node_sets(odb)
        metadata = {
            "source_odb": os.path.abspath(args.odb),
            "node_sets": node_set_names,
        }
    finally:
        odb.close()
    print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
    return metadata
```

- [ ] **Step 4: 修改 `collect_nodes()` 增加节点集过滤**

修改 [extractor.py:123-135](odb_extract/extractor.py#L123-L135) 的 `collect_nodes` 函数：

```python
def collect_nodes(odb, instances=None, node_labels=None, node_set_names=None, warnings=None):
    """Collect NodeRef objects filtered by instance, label, and node set (AND logic)."""
    instance_filter = set(instances or [])
    node_label_filter = set(int(label) for label in (node_labels or []))
    nodes = []
    for instance_name in sorted(odb.rootAssembly.instances.keys()):
        if instance_filter and instance_name not in instance_filter:
            continue
        instance = odb.rootAssembly.instances[instance_name]
        for node in instance.nodes:
            if node_label_filter and int(node.label) not in node_label_filter:
                continue
            nodes.append(NodeRef(instance_name, int(node.label), _node_coordinates(node)))

    if node_set_names:
        nset_members = set()
        for nset_name in node_set_names:
            if nset_name in odb.rootAssembly.nodeSets:
                nset = odb.rootAssembly.nodeSets[nset_name]
                for node in nset.nodes:
                    nset_members.add(
                        (getattr(node, "instanceName", ""), int(node.label))
                    )
            else:
                if warnings is not None:
                    warnings.append(
                        "Node set {!r} not found in ODB.".format(nset_name)
                    )
        nodes = [
            n for n in nodes if (n.instance_name, n.label) in nset_members
        ]

    return sorted(nodes, key=lambda item: (item.instance_name, item.label))
```

- [ ] **Step 5: 修改 `run()` 函数传递节点集参数**

修改 [extractor.py:478-531](odb_extract/extractor.py#L478-L531) 的 `run` 函数中调用 `collect_nodes` 的部分（第 484-488 行）：

将：
```python
        nodes = collect_nodes(
            odb,
            instances=args.instances,
            node_labels=node_labels,
        )
```

改为：
```python
        node_set_warnings = []
        nodes = collect_nodes(
            odb,
            instances=args.instances,
            node_labels=node_labels,
            node_set_names=args.node_sets,
            warnings=node_set_warnings,
        )
```

并在 filters 和 command_options 字典中添加 node_sets 字段。

修改 filters 字典（约第 496 行），添加：
```python
            "node_sets": list(args.node_sets or []),
```

修改 command_options 字典（约第 502 行），添加：
```python
            "node_sets": list(args.node_sets or []),
```

并在 `extraction_metadata["warnings"]` 之后添加警告合并（在 `save_npz` 调用之前，约第 523 行）：
```python
        extraction_metadata["warnings"].extend(node_set_warnings)
```

- [ ] **Step 6: 修改 `main()` 处理 `--list-node-sets` 分支**

修改 [extractor.py:550-563](odb_extract/extractor.py#L550-L563) 的 `main` 函数：

```python
def main(argv=None):
    args = parse_args(argv)
    try:
        if args.list_fields:
            run_list_fields(args)
        elif args.list_node_sets:
            run_list_node_sets(args)
        else:
            run(args)
    except OdbAccessUnavailableError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 2
    return 0
```

- [ ] **Step 7: 验证现有测试仍然通过**

```bash
cd "d:\MINE\Data processing\Abaqus" && python -m unittest discover -v
```

预期：所有测试 PASS（无新增测试，仅验证未破坏现有功能）

- [ ] **Step 8: 提交**

```bash
git add odb_extract/extractor.py
git commit -m "feat: 在 extractor 中添加节点集列出和过滤功能

- 新增 --node-sets 和 --list-node-sets CLI 参数
- 新增 list_node_sets() 和 run_list_node_sets() 函数
- collect_nodes() 支持按节点集过滤（AND 叠加逻辑）
- 不存在的节点集名称产生 warning"
```

---

### Task 2: launcher.py — 工具函数、CLI 参数和命令构建

**Files:**
- Modify: `odb_extract/launcher.py`

**Interfaces:**
- Consumes: `extractor.py` 的 `--node-sets`、`--list-node-sets` 参数接口
- Produces:
  - `parse_node_set_text(text) -> list[str] | None`
  - `build_node_set_list_command(abaqus_command, extractor_module, odb_path) -> list[str]`
  - `parse_node_set_list_output(output_text) -> dict`
  - `discover_node_sets(abaqus_command, extractor_module, odb_path, runner=None) -> dict`
  - `build_extraction_command(..., node_sets=None)` — 修改签名
  - `run_extraction(..., node_sets=None)` — 修改签名
  - `run_workflow(..., node_sets=None)` — 修改签名
  - `run_cli()` — 传递 args.node_sets
  - `parse_args()` — 新增 `--node-sets` 参数
  - `UI_TEXT` — 新增 10 个节点集相关条目

- [ ] **Step 1: 在 `UI_TEXT` 中添加节点集相关文本**

在 [launcher.py:21-82](odb_extract/launcher.py#L21-L82) 的 `UI_TEXT` 字典末尾、闭合大括号之前添加：

```python
    "node_set_filter": "节点集",
    "node_set_hint": "请选择 ODB 文件以读取节点集。",
    "no_node_sets_found": "未找到节点集。",
    "found_node_sets": "已在 ODB 中找到 {count} 个节点集。",
    "select_all_node_sets": "全选",
    "clear_all_node_sets": "全不选",
    "refresh_node_sets": "读取节点集",
    "node_set_discovery_failed": "读取节点集失败",
    "node_set_discovery_failed_log": "读取节点集失败：{error}",
    "select_odb_for_node_sets": "请先选择 ODB 文件，再读取节点集。",
```

- [ ] **Step 2: 在 `parse_args()` 中添加 `--node-sets` 参数**

在 [launcher.py:85-121](odb_extract/launcher.py#L85-L121) 的 `parse_args` 函数中，在 `--node-labels` 参数（约第 95 行）之后添加：

```python
    parser.add_argument(
        "--node-sets",
        nargs="+",
        help="Optional node set names to filter nodes by.",
    )
```

- [ ] **Step 3: 添加 `parse_node_set_text()` 函数**

在 `parse_node_label_text` 函数（约第 133 行）之后添加：

```python
def parse_node_set_text(text):
    """Parse space/comma/semicolon separated node set names from user input."""
    names = [part for part in re.split(r"[\s,;]+", text.strip()) if part]
    return names or None
```

- [ ] **Step 4: 添加 `build_node_set_list_command()` 和 `discover_node_sets()` 函数**

在 `build_field_list_command` 函数（[launcher.py:252-265](odb_extract/launcher.py#L252-L265)）之后添加：

```python
def build_node_set_list_command(abaqus_command, extractor_module, odb_path):
    """Build the Abaqus command to list available node sets."""
    extractor_module = extractor_module or default_extractor_module()
    return [
        abaqus_command,
        "python",
        "-m",
        extractor_module,
        "--odb",
        odb_path,
        "--list-node-sets",
    ]


def parse_node_set_list_output(output_text):
    """Parse the JSON line from --list-node-sets output."""
    for line in output_text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        metadata = json.loads(line)
        node_sets = metadata.get("node_sets")
        if not isinstance(node_sets, list):
            raise ValueError("Node set list JSON does not contain a node_sets array.")
        return metadata
    raise ValueError("Could not find node set list JSON in Abaqus output.")


def discover_node_sets(abaqus_command, extractor_module, odb_path, runner=None):
    """Discover available node sets from an ODB by calling Abaqus Python."""
    runner = run_command_capture if runner is None else runner
    command = build_node_set_list_command(
        abaqus_command=abaqus_command,
        extractor_module=extractor_module,
        odb_path=odb_path,
    )
    code, output = runner(command)
    if code != 0:
        raise RuntimeError(
            "Node set discovery failed with exit code {}.\n{}".format(code, output)
        )
    return parse_node_set_list_output(output)
```

- [ ] **Step 5: 修改 `build_extraction_command()` 传递 `node_sets`**

在 `build_extraction_command` 函数签名中添加 `node_sets=None` 参数。修改 [launcher.py:215-249](odb_extract/launcher.py#L215-L249)：

将函数签名从：
```python
def build_extraction_command(
    abaqus_command,
    odb_path,
    extractor_module=None,
    output_path=None,
    metadata_path=None,
    step_name=None,
    fields=None,
    instances=None,
    node_labels=None,
    frequency_min=None,
    frequency_max=None,
):
```

改为：
```python
def build_extraction_command(
    abaqus_command,
    odb_path,
    extractor_module=None,
    output_path=None,
    metadata_path=None,
    step_name=None,
    fields=None,
    instances=None,
    node_labels=None,
    frequency_min=None,
    frequency_max=None,
    node_sets=None,
):
```

在函数体中，在 `frequency_max` 处理块（约第 247 行）之后添加：
```python
    if node_sets:
        command.append("--node-sets")
        command.extend(node_sets)
```

- [ ] **Step 6: 修改 `run_extraction()` 传递 `node_sets`**

在 [launcher.py:335-375](odb_extract/launcher.py#L335-L375) 的函数签名中添加 `node_sets=None` 参数，并在调用 `build_extraction_command` 时传递 `node_sets=node_sets`。

- [ ] **Step 7: 修改 `run_workflow()` 传递 `node_sets`**

在 [launcher.py:384-450](odb_extract/launcher.py#L384-L450) 的函数签名中添加 `node_sets=None` 参数，并在调用 `run_extraction` 时传递 `node_sets=node_sets`。

- [ ] **Step 8: 修改 `run_cli()` 传递 `args.node_sets`**

在 [launcher.py:453-487](odb_extract/launcher.py#L453-L487) 的 `run_cli` 函数中，`run_workflow` 调用处添加：
```python
        node_sets=args.node_sets,
```

- [ ] **Step 9: 运行现有测试确保不破坏**

```bash
cd "d:\MINE\Data processing\Abaqus" && python -m unittest tests.test_run_extract_odb -v
```

预期：所有测试 PASS

- [ ] **Step 10: 提交**

```bash
git add odb_extract/launcher.py
git commit -m "feat: 在 launcher 中添加节点集发现和命令构建功能

- 新增 --node-sets CLI 参数
- 新增 parse_node_set_text(), build_node_set_list_command(),
  parse_node_set_list_output(), discover_node_sets()
- 修改 build_extraction_command, run_extraction, run_workflow,
  run_cli 传递 node_sets
- 新增 10 个 UI_TEXT 条目"
```

---

### Task 3: launcher.py — GUI 节点集控件

**Files:**
- Modify: `odb_extract/launcher.py`

**Interfaces:**
- Consumes: Task 2 的 `discover_node_sets()`、`parse_node_set_text()`、UI_TEXT 条目
- Produces:
  - `ExtractOdbApp.__init__()` — 新增 `node_sets_var`、`node_set_vars` 实例变量
  - `ExtractOdbApp._build_node_set_widgets()` — 构建节点集区域
  - `ExtractOdbApp.refresh_node_sets()` — 触发节点集发现
  - `ExtractOdbApp._discover_node_sets_worker()` — 后台线程
  - `ExtractOdbApp._show_discovered_node_sets()` — 填充 Checkbox
  - `ExtractOdbApp._clear_node_set_checks()` — 清空
  - `ExtractOdbApp._sync_node_sets_from_checks()` — Checkbox→文本框同步
  - `ExtractOdbApp._set_node_set_selection()` — 全选/全不选
  - `ExtractOdbApp._validate_inputs()` — 修改，解析 node_sets
  - `ExtractOdbApp.choose_odb()` — 修改，自动刷新节点集
  - `ExtractOdbApp._set_running()` — 修改，禁用节点集按钮
  - `ExtractOdbApp._build_widgets()` — 修改，调整行号并调用 `_build_node_set_widgets()`

- [ ] **Step 1: 在 `__init__` 中添加节点集实例变量**

在 [launcher.py:491-518](odb_extract/launcher.py#L491-L518) 的 `__init__` 方法中，在其他 `StringVar` 声明之后（约第 514 行之后）添加：

```python
        self.node_sets_var = tk.StringVar()
        self.node_set_vars = {}
```

- [ ] **Step 2: 添加 `_build_node_set_widgets()` 方法**

在 `ExtractOdbApp` 类中（在 `_add_path_row` 方法之后，约第 688 行之前），添加：

```python
    def _build_node_set_widgets(self, frame, row_offset):
        """Build node set filter row: label, text entry, and action buttons."""
        from tkinter import ttk

        ttk.Label(frame, text=UI_TEXT["node_set_filter"]).grid(
            row=row_offset, column=0, sticky="w", pady=4
        )
        ttk.Entry(frame, textvariable=self.node_sets_var).grid(
            row=row_offset, column=1, sticky="ew", pady=4, padx=(0, 6)
        )
        nset_button_frame = ttk.Frame(frame)
        nset_button_frame.grid(row=row_offset, column=2, sticky="ew", pady=4)
        self.refresh_nset_button = ttk.Button(
            nset_button_frame,
            text=UI_TEXT["refresh_node_sets"],
            command=self.refresh_node_sets,
        )
        self.refresh_nset_button.pack(side="left", padx=(0, 4))
        ttk.Button(
            nset_button_frame,
            text=UI_TEXT["select_all_node_sets"],
            command=lambda: self._set_node_set_selection("all"),
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            nset_button_frame,
            text=UI_TEXT["clear_all_node_sets"],
            command=lambda: self._set_node_set_selection("none"),
        ).pack(side="left")

        # Node set checkbox canvas
        self.nset_box = ttk.LabelFrame(frame, text=UI_TEXT["node_set_filter"])
        self.nset_box.grid(
            row=row_offset + 1, column=0, columnspan=3, sticky="ew", pady=(4, 8)
        )
        self.nset_box.columnconfigure(0, weight=1)
        self.nset_box.rowconfigure(0, weight=1)

        self.nset_canvas = tk.Canvas(
            self.nset_box,
            height=80,
            highlightthickness=0,
        )
        self.nset_canvas.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        nset_scrollbar = ttk.Scrollbar(
            self.nset_box,
            orient="vertical",
            command=self.nset_canvas.yview,
        )
        nset_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=6)
        self.nset_canvas.configure(yscrollcommand=nset_scrollbar.set)

        self.nset_checks_frame = ttk.Frame(self.nset_canvas)
        self.nset_canvas_window = self.nset_canvas.create_window(
            (0, 0),
            window=self.nset_checks_frame,
            anchor="nw",
        )
        self.nset_checks_frame.bind("<Configure>", self._update_nset_scroll_region)
        self.nset_canvas.bind("<Configure>", self._resize_nset_checks_frame)
        self.nset_hint = ttk.Label(
            self.nset_checks_frame,
            text=UI_TEXT["node_set_hint"],
        )
        self.nset_hint.grid(row=0, column=0, sticky="w", padx=8, pady=8)
```

- [ ] **Step 3: 修改 `_build_widgets()` 调整行号并调用 `_build_node_set_widgets()`**

在 [launcher.py:521-673](odb_extract/launcher.py#L521-L673) 的 `_build_widgets` 方法中，段首处将 `frame.rowconfigure(17, weight=1)` 改为 `frame.rowconfigure(19, weight=1)`（因为后面插入两行）。

在节点编号行（row=10）之后、频率行（原来 row=11）之前插入节点集控件调用。将所有后续行的 row 编号 +2。

具体来说，在节点编号 Entry 的 grid 调用之后（第 571 行之后），频率部分之前添加：

```python
        self._build_node_set_widgets(frame, 11)
```

然后将以下行的 row 值加 2：
- 频率行：从 row=11 → row=13
- 点字段行：从 row=12 → row=14
- 邻近点行：从 row=13 → row=15
- 场输出 box：从 row=14 → row=16
- 按钮栏：从 row=15 → row=17
- 日志：从 row=17 → row=19

具体修改位置：
- 第 573-586 行：频率标签和输入框 `row=11` → `row=13`
- 第 588-591 行：点字段 `row=12` → `row=14`
- 第 593-606 行：邻近点和容差 `row=13` → `row=15`
- 第 609 行：field_box `row=14` → `row=16`
- 第 664 行：button_bar `row=15` → `row=17`
- 第 669 行：log_text `row=17` → `row=19`

- [ ] **Step 4: 添加节点集 Canvas 辅助方法**

在 `_resize_field_checks_frame` 方法（约第 787 行）之后添加：

```python
    def _update_nset_scroll_region(self, _event=None):
        self.nset_canvas.configure(scrollregion=self.nset_canvas.bbox("all"))

    def _resize_nset_checks_frame(self, event):
        self.nset_canvas.itemconfigure(self.nset_canvas_window, width=event.width)

    def _clear_node_set_checks(self):
        for child in self.nset_checks_frame.winfo_children():
            child.destroy()
        self.node_set_vars = {}

    def _sync_node_sets_from_checks(self):
        selected = [
            name
            for name, variable in sorted(self.node_set_vars.items())
            if variable.get()
        ]
        self.node_sets_var.set(" ".join(selected))

    def _set_node_set_selection(self, mode):
        if mode == "all":
            for variable in self.node_set_vars.values():
                variable.set(True)
        elif mode == "none":
            for variable in self.node_set_vars.values():
                variable.set(False)
        self._sync_node_sets_from_checks()

    def _show_discovered_node_sets(self, metadata):
        tk = self.tk
        from tkinter import ttk

        node_sets = metadata.get("node_sets", [])
        self._clear_node_set_checks()
        if not node_sets:
            ttk.Label(
                self.nset_checks_frame,
                text=UI_TEXT["no_node_sets_found"],
            ).grid(row=0, column=0, sticky="w", padx=8, pady=8)
            self.node_sets_var.set("")
            return

        for index, name in enumerate(node_sets):
            variable = tk.BooleanVar(value=False)
            self.node_set_vars[name] = variable
            ttk.Checkbutton(
                self.nset_checks_frame,
                text=name,
                variable=variable,
                command=self._sync_node_sets_from_checks,
            ).grid(row=index // 6, column=index % 6, sticky="w", padx=8, pady=4)

        self.nset_canvas.yview_moveto(0)
        self.log(
            UI_TEXT["found_node_sets"].format(count=len(node_sets))
        )
```

- [ ] **Step 5: 添加节点集发现方法**

在 `_discover_fields_worker` 方法之后（约第 893 行）添加：

```python
    def refresh_node_sets(self):
        """Trigger node set discovery in background thread."""
        if self._running:
            return
        odb_path = self.odb_var.get().strip()
        if not odb_path:
            self.log(UI_TEXT["select_odb_for_node_sets"])
            return
        abaqus_command = self.abaqus_var.get().strip()
        if not abaqus_command:
            self.log(UI_TEXT["empty_abaqus"])
            return
        self.log(UI_TEXT["discovering_fields"])
        self._set_running(True)
        worker = threading.Thread(
            target=self._discover_node_sets_worker,
            args=(abaqus_command, default_extractor_module(), odb_path),
        )
        worker.daemon = True
        worker.start()

    def _discover_node_sets_worker(self, abaqus_command, extractor_module, odb_path):
        from tkinter import messagebox

        try:
            metadata = discover_node_sets(
                abaqus_command=abaqus_command,
                extractor_module=extractor_module,
                odb_path=odb_path,
            )
        except Exception as exc:
            error_message = str(exc)

            def fail():
                self._set_running(False)
                self.log(
                    UI_TEXT["node_set_discovery_failed_log"].format(error=error_message)
                )
                messagebox.showerror(
                    UI_TEXT["node_set_discovery_failed"], error_message
                )

            self.root.after(0, fail)
            return

        def finish():
            self._set_running(False)
            self._show_discovered_node_sets(metadata)

        self.root.after(0, finish)
```

- [ ] **Step 6: 修改 `choose_odb()` 自动刷新节点集**

在 [launcher.py:689-705](odb_extract/launcher.py#L689-L705) 的 `choose_odb` 方法中，`self.refresh_fields()` 调用之后添加：

```python
        self.refresh_node_sets()
```

- [ ] **Step 7: 修改 `_set_running()` 禁用节点集按钮**

在 [launcher.py:776-782](odb_extract/launcher.py#L776-L782) 的 `_set_running` 方法中，在现有 `refresh_button` 禁用行之后添加：

```python
        self.refresh_nset_button.configure(state="disabled" if running else "normal")
```

- [ ] **Step 8: 修改 `_validate_inputs()` 解析节点集**

在 [launcher.py:904-986](odb_extract/launcher.py#L904-L986) 的 `_validate_inputs` 方法中，在 `instances = parse_field_text(...)` 之前（约第 962 行）添加：

```python
        node_sets = parse_node_set_text(self.node_sets_var.get())
```

并在返回字典（约第 969-986 行）中添加：

```python
            "node_sets": node_sets,
```

- [ ] **Step 9: 运行测试确保不破坏**

```bash
cd "d:\MINE\Data processing\Abaqus" && python -m unittest tests.test_run_extract_odb -v
```

预期：所有测试 PASS

- [ ] **Step 10: 提交**

```bash
git add odb_extract/launcher.py
git commit -m "feat: 在 launcher GUI 中添加节点集选择控件

- 新增节点集文本框、读取按钮、全选/全不选按钮
- 新增 Checkbox Canvas 列表展示发现的节点集
- 选择 ODB 后自动刷新节点集列表
- 节点集复选框与文本框双向同步
- 验证逻辑解析节点集输入"
```

---

### Task 4: 测试 — extractor 节点集功能

**Files:**
- Modify: `tests/test_extract_data_odb.py`

**Interfaces:**
- Consumes: Task 1 的 `parse_args()`, `list_node_sets()`, `collect_nodes()`, `run_list_node_sets()`
- Produces: 6 个新测试用例

- [ ] **Step 1: 添加 `test_node_sets_argument_parsing` 测试**

```python
    def test_node_sets_argument_parsing(self):
        from odb_extract.extractor import parse_args

        args = parse_args(["--node-sets", "NSET_TOP", "NSET_BOTTOM"])
        self.assertEqual(args.node_sets, ["NSET_TOP", "NSET_BOTTOM"])

    def test_list_node_sets_argument_parsing(self):
        from odb_extract.extractor import parse_args

        args = parse_args(["--list-node-sets"])
        self.assertTrue(args.list_node_sets)

    def test_node_sets_default_is_none(self):
        from odb_extract.extractor import parse_args

        args = parse_args([])
        self.assertIsNone(args.node_sets)
        self.assertFalse(args.list_node_sets)
```

- [ ] **Step 2: 添加 mock ODB 节点集测试**

```python
    def test_collect_nodes_filters_by_node_set(self):
        from odb_extract.extractor import collect_nodes

        # Build a minimal mock ODB
        fake_node_a = mock.Mock()
        fake_node_a.label = 1
        fake_node_a.coordinates = (0.0, 0.0, 0.0)
        fake_node_a.instanceName = "PART-1-1"

        fake_node_b = mock.Mock()
        fake_node_b.label = 2
        fake_node_b.coordinates = (1.0, 0.0, 0.0)
        fake_node_b.instanceName = "PART-1-1"

        fake_instance = mock.Mock()
        fake_instance.nodes = [fake_node_a, fake_node_b]

        fake_nset = mock.Mock()
        fake_nset.nodes = [fake_node_a]  # only node 1 is in the set

        fake_assembly = mock.Mock()
        fake_assembly.instances = {"PART-1-1": fake_instance}
        fake_assembly.nodeSets = {"NSET_TOP": fake_nset}

        fake_odb = mock.Mock()
        fake_odb.rootAssembly = fake_assembly

        warnings = []
        nodes = collect_nodes(
            fake_odb,
            node_set_names=["NSET_TOP"],
            warnings=warnings,
        )

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].label, 1)
        self.assertEqual(warnings, [])

    def test_collect_nodes_and_combines_filters(self):
        from odb_extract.extractor import collect_nodes

        fake_node_a = mock.Mock()
        fake_node_a.label = 1
        fake_node_a.coordinates = (0.0, 0.0, 0.0)
        fake_node_a.instanceName = "PART-1-1"

        fake_node_b = mock.Mock()
        fake_node_b.label = 2
        fake_node_b.coordinates = (1.0, 0.0, 0.0)
        fake_node_b.instanceName = "PART-1-2"

        fake_node_c = mock.Mock()
        fake_node_c.label = 3
        fake_node_c.coordinates = (2.0, 0.0, 0.0)
        fake_node_c.instanceName = "PART-1-1"

        inst1 = mock.Mock()
        inst1.nodes = [fake_node_a, fake_node_c]
        inst2 = mock.Mock()
        inst2.nodes = [fake_node_b]

        fake_nset = mock.Mock()
        fake_nset.nodes = [fake_node_a, fake_node_b]  # across two instances

        fake_assembly = mock.Mock()
        fake_assembly.instances = {"PART-1-1": inst1, "PART-1-2": inst2}
        fake_assembly.nodeSets = {"NSET_ALL": fake_nset}

        fake_odb = mock.Mock()
        fake_odb.rootAssembly = fake_assembly

        # Filter: only PART-1-1 instances AND node labels 1,3 AND NSET_ALL
        nodes = collect_nodes(
            fake_odb,
            instances=["PART-1-1"],
            node_labels=[1, 3],
            node_set_names=["NSET_ALL"],
        )

        # node_a: PART-1-1 + label 1 + in NSET_ALL → included
        # node_c: PART-1-1 + label 3 + NOT in NSET_ALL → excluded
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].label, 1)

    def test_node_set_not_found_emits_warning(self):
        from odb_extract.extractor import collect_nodes

        fake_node = mock.Mock()
        fake_node.label = 1
        fake_node.coordinates = (0.0, 0.0, 0.0)
        fake_node.instanceName = "PART-1-1"

        fake_instance = mock.Mock()
        fake_instance.nodes = [fake_node]

        fake_assembly = mock.Mock()
        fake_assembly.instances = {"PART-1-1": fake_instance}
        fake_assembly.nodeSets = {}  # empty node sets

        fake_odb = mock.Mock()
        fake_odb.rootAssembly = fake_assembly

        warnings = []
        nodes = collect_nodes(
            fake_odb,
            node_set_names=["NONEXISTENT"],
            warnings=warnings,
        )

        self.assertEqual(len(nodes), 0)
        self.assertEqual(len(warnings), 1)
        self.assertIn("NONEXISTENT", warnings[0])

    def test_collect_nodes_without_node_set_returns_all(self):
        from odb_extract.extractor import collect_nodes

        fake_node_a = mock.Mock()
        fake_node_a.label = 1
        fake_node_a.coordinates = (0.0, 0.0, 0.0)
        fake_node_a.instanceName = "PART-1-1"

        fake_node_b = mock.Mock()
        fake_node_b.label = 2
        fake_node_b.coordinates = (1.0, 0.0, 0.0)
        fake_node_b.instanceName = "PART-1-1"

        fake_instance = mock.Mock()
        fake_instance.nodes = [fake_node_a, fake_node_b]

        fake_assembly = mock.Mock()
        fake_assembly.instances = {"PART-1-1": fake_instance}
        fake_assembly.nodeSets = {}

        fake_odb = mock.Mock()
        fake_odb.rootAssembly = fake_assembly

        nodes = collect_nodes(fake_odb, node_set_names=None)
        self.assertEqual(len(nodes), 2)
```

- [ ] **Step 3: 运行测试**

```bash
cd "d:\MINE\Data processing\Abaqus" && python -m unittest tests.test_extract_data_odb -v
```

预期：所有测试 PASS（包括新增和已有）

- [ ] **Step 4: 提交**

```bash
git add tests/test_extract_data_odb.py
git commit -m "test: 添加 extractor 节点集功能单元测试

- 测试 --node-sets/--list-node-sets 参数解析
- 测试 collect_nodes 按节点集过滤
- 测试多条件 AND 叠加过滤
- 测试不存在的节点集产生 warning
- 测试未指定节点集时返回全部节点"
```

---

### Task 5: 测试 — launcher 节点集功能

**Files:**
- Modify: `tests/test_run_extract_odb.py`

**Interfaces:**
- Consumes: Task 2/3 的 `parse_node_set_text()`, `build_extraction_command()`, `discover_node_sets()`, `parse_node_set_list_output()`, `build_node_set_list_command()`, `UI_TEXT`, `ExtractOdbApp._validate_inputs()`
- Produces: 6 个新测试用例

- [ ] **Step 1: 添加 launcher 工具函数测试**

在 `LauncherTests` 类中添加：

```python
    def test_parse_node_set_text_accepts_spaces_and_commas(self):
        self.assertEqual(
            launcher.parse_node_set_text("NSET_TOP, NSET_BOTTOM  NSET_SIDE"),
            ["NSET_TOP", "NSET_BOTTOM", "NSET_SIDE"],
        )

    def test_parse_node_set_text_returns_none_for_blank(self):
        self.assertIsNone(launcher.parse_node_set_text("  ,  "))

    def test_build_node_set_list_command_includes_list_node_sets_flag(self):
        command = launcher.build_node_set_list_command(
            abaqus_command="abaqus",
            extractor_module="odb_extract.extractor",
            odb_path="data/test1.odb",
        )

        self.assertEqual(
            command,
            [
                "abaqus",
                "python",
                "-m",
                "odb_extract.extractor",
                "--odb",
                "data/test1.odb",
                "--list-node-sets",
            ],
        )

    def test_parse_node_set_list_output_reads_json_line(self):
        metadata = launcher.parse_node_set_list_output(
            'Abaqus startup text\n{"node_sets": ["NSET_TOP", "NSET_BOTTOM"], "source_odb": "test.odb"}\n'
        )

        self.assertEqual(metadata["node_sets"], ["NSET_TOP", "NSET_BOTTOM"])
        self.assertEqual(metadata["source_odb"], "test.odb")

    def test_parse_node_set_list_output_raises_on_missing_array(self):
        with self.assertRaises(ValueError):
            launcher.parse_node_set_list_output(
                '{"node_sets": "not_a_list"}\n'
            )

    def test_parse_node_set_list_output_raises_on_no_json(self):
        with self.assertRaises(ValueError):
            launcher.parse_node_set_list_output("No JSON here.\n")

    def test_discover_node_sets_calls_runner_and_returns_metadata(self):
        def fake_runner(command):
            return 0, '{"node_sets": ["NSET_A", "NSET_B"]}\n'

        metadata = launcher.discover_node_sets(
            abaqus_command="abaqus",
            extractor_module="odb_extract.extractor",
            odb_path="data/test1.odb",
            runner=fake_runner,
        )

        self.assertEqual(metadata["node_sets"], ["NSET_A", "NSET_B"])

    def test_discover_node_sets_raises_on_nonzero_exit(self):
        def fake_runner(command):
            return 1, "Error: ODB not found\n"

        with self.assertRaises(RuntimeError) as context:
            launcher.discover_node_sets(
                abaqus_command="abaqus",
                extractor_module="odb_extract.extractor",
                odb_path="data/test1.odb",
                runner=fake_runner,
            )

        self.assertIn("exit code 1", str(context.exception))
```

- [ ] **Step 2: 添加命令构建和 GUI 验证测试**

```python
    def test_build_extraction_command_includes_node_sets(self):
        command = launcher.build_extraction_command(
            abaqus_command="abq2024",
            extractor_module="odb_extract.extractor",
            odb_path=r"D:\work\data\test1.odb",
            node_sets=["NSET_TOP", "NSET_BOTTOM"],
        )

        self.assertIn("--node-sets", command)
        nset_index = command.index("--node-sets")
        self.assertEqual(command[nset_index + 1], "NSET_TOP")
        self.assertEqual(command[nset_index + 2], "NSET_BOTTOM")

    def test_ui_text_has_node_set_labels(self):
        self.assertEqual(launcher.UI_TEXT["node_set_filter"], "节点集")
        self.assertEqual(launcher.UI_TEXT["refresh_node_sets"], "读取节点集")
        self.assertEqual(launcher.UI_TEXT["select_all_node_sets"], "全选")
        self.assertEqual(launcher.UI_TEXT["clear_all_node_sets"], "全不选")
        self.assertEqual(
            launcher.UI_TEXT["node_set_hint"],
            "请选择 ODB 文件以读取节点集。",
        )
        self.assertEqual(
            launcher.UI_TEXT["no_node_sets_found"],
            "未找到节点集。",
        )
        self.assertEqual(
            launcher.UI_TEXT["found_node_sets"],
            "已在 ODB 中找到 {count} 个节点集。",
        )

    def test_validate_inputs_includes_node_sets(self):
        app = object.__new__(launcher.ExtractOdbApp)
        app.odb_var = self.FakeVar("data/test1.odb")
        app.output_var = self.FakeVar("output/data.npz")
        app.metadata_var = self.FakeVar("output/meta.json")
        app.step_var = self.FakeVar("Step-1")
        app.fields_var = self.FakeVar("U V")
        app.instances_var = self.FakeVar("PART-1-1")
        app.node_labels_var = self.FakeVar("")
        app.node_sets_var = self.FakeVar("NSET_TOP NSET_BOTTOM")
        app.frequency_min_var = self.FakeVar("")
        app.frequency_max_var = self.FakeVar("")
        app.points_var = self.FakeVar("")
        app.point_output_var = self.FakeVar("")
        app.point_fields_var = self.FakeVar("")
        app.neighbors_var = self.FakeVar("4")
        app.exact_tol_var = self.FakeVar("")
        app.abaqus_var = self.FakeVar("abaqus")
        app.field_vars = {}

        options = app._validate_inputs()

        self.assertEqual(options["node_sets"], ["NSET_TOP", "NSET_BOTTOM"])
```

- [ ] **Step 3: 运行全部测试**

```bash
cd "d:\MINE\Data processing\Abaqus" && python -m unittest discover -v
```

预期：所有测试 PASS（新增 + 已有全部通过）

- [ ] **Step 4: 提交**

```bash
git add tests/test_run_extract_odb.py
git commit -m "test: 添加 launcher 节点集功能单元测试

- 测试 parse_node_set_text 解析逻辑
- 测试 build_node_set_list_command 命令构建
- 测试 parse_node_set_list_output JSON 解析
- 测试 discover_node_sets 成功和失败场景
- 测试 build_extraction_command 包含 --node-sets
- 测试 UI_TEXT 节点集条目完整性
- 测试 GUI validate_inputs 解析 node_sets"
```

---

### 最终验证

- [ ] **运行全部测试确保集成正确**

```bash
cd "d:\MINE\Data processing\Abaqus" && python -m unittest discover -v
```

预期：全部测试 PASS

- [ ] **检查项清单**
  - extractor.py 以 Abaqus Python (`abaqus python -m odb_extract.extractor --list-node-sets --odb <real.odb>`) 运行确认节点集列出功能正常（如有真实 ODB）
  - GUI 以普通 Python (`python -m odb_extract`) 启动确认界面布局正常
  - 确认现有功能未退化：场输出发现、提取、点插值均可正常使用
