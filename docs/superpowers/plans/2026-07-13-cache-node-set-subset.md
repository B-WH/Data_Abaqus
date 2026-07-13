# Cache Node-Set Subset Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow cache mode to save original cached node values filtered by one or more node sets without requiring a target-point file.

**Architecture:** Add one direct-slice function beside the existing interpolation function, reusing the current node-set membership validator and NPZ/JSON writers. Change the launcher cache path to dispatch to interpolation when a point file exists and to direct slicing when only node sets are selected; keep ODB extraction unchanged.

**Tech Stack:** Python 3, NumPy, tkinter, unittest, JSON/NPZ.

## Global Constraints

- Do not open the ODB or invoke Abaqus in cache mode.
- Direct subset export must not interpolate or recompute field values.
- Preserve source-cache node order; multiple selected node sets use a deduplicated union.
- Save only fields selected in the GUI.
- Do not overwrite the source NPZ or its paired metadata.
- Do not add a runtime module or dependency.
- Follow the repository AGENTS.md rule: no recursive, wildcard, piped, or bulk deletion.

---

## File Map

- Modify `odb_extract/interpolate_points.py`: implement direct NPZ/metadata slicing and reusable output metadata.
- Modify `tests/test_interpolate_odb_points.py`: protect exact values, source order, field selection, union behavior, and remapped node-set indices.
- Modify `odb_extract/launcher.py`: allow cache mode without points when node sets are selected and dispatch the correct cache operation.
- Modify `tests/test_run_extract_odb.py`: protect validation and dispatch behavior.
- Modify `README.md`: document the two cache-mode operations and old-cache limitation.

### Task 1: Direct node-set slicing core

**Files:**
- Modify: `tests/test_interpolate_odb_points.py:330-400`
- Modify: `odb_extract/interpolate_points.py:5-14, 266-426`

**Interfaces:**
- Consumes: existing `load_metadata(path)`, `_available_node_fields(metadata)`, `_validate_field(metadata, field_name)`, `_selected_node_keys(data, metadata, node_sets)`, `_save_npz(path, arrays)`, and `_save_metadata(path, metadata)`.
- Produces: `subset_node_sets_files(data_path, metadata_path, output_path, metadata_output_path, fields=None, node_sets=None) -> dict`.

- [ ] **Step 1: Write the failing direct-subset regression test**

Add this test to `InterpolateOdbPointsTests`:

```python
def test_subset_node_sets_preserves_values_order_fields_and_membership(self):
    with np.load(self.data_path) as source:
        arrays = {key: source[key] for key in source.files}
    arrays["node_set_0003_indices"] = np.array([1, 2], dtype=np.int64)
    np.savez_compressed(self.data_path, **arrays)
    with open(self.metadata_path, "r", encoding="utf-8") as stream:
        source_metadata = json.load(stream)
    source_metadata["node_sets"]["SET_RIGHT_UP"] = {
        "indices_key": "node_set_0003_indices",
        "member_count": 2,
    }
    with open(self.metadata_path, "w", encoding="utf-8") as stream:
        json.dump(source_metadata, stream)

    metadata = interp.subset_node_sets_files(
        data_path=self.data_path,
        metadata_path=self.metadata_path,
        output_path=self.output_path,
        metadata_output_path=self.metadata_output_path,
        fields=["U"],
        node_sets=["SET_UP", "SET_RIGHT_UP"],
    )

    with np.load(self.output_path) as data:
        self.assertEqual(data["frequencies"].tolist(), [5.0])
        self.assertEqual(data["node_labels"].tolist(), [2, 3])
        self.assertEqual(
            data["node_coordinates"].tolist(),
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        )
        np.testing.assert_array_equal(data["U_real"], [[[20.0], [30.0]]])
        np.testing.assert_array_equal(data["U_imag"], [[[2.0], [3.0]]])
        self.assertNotIn("V_real", data.files)
        up_key = metadata["node_sets"]["SET_UP"]["indices_key"]
        right_up_key = metadata["node_sets"]["SET_RIGHT_UP"]["indices_key"]
        self.assertEqual(data[up_key].tolist(), [1])
        self.assertEqual(data[right_up_key].tolist(), [0, 1])

    self.assertEqual(metadata["fields"], ["U"])
    self.assertEqual([node["label"] for node in metadata["nodes"]], [2, 3])
    self.assertEqual(
        [point["node_label"] for point in metadata["field_outputs"]["U"]["points"]],
        [2, 3],
    )
    self.assertEqual(metadata["array_shapes"]["U_real"], [1, 2, 1])
    self.assertEqual(metadata["filters"]["node_sets"], ["SET_UP", "SET_RIGHT_UP"])
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
python -m unittest tests.test_interpolate_odb_points.InterpolateOdbPointsTests.test_subset_node_sets_preserves_values_order_fields_and_membership -v
```

Expected: `ERROR` with `AttributeError: module 'odb_extract.interpolate_points' has no attribute 'subset_node_sets_files'`.

- [ ] **Step 3: Implement the minimal direct-slice function**

Add `import copy` near the imports in `odb_extract/interpolate_points.py`, then add this function before `interpolate_files`:

```python
def subset_node_sets_files(
    data_path,
    metadata_path,
    output_path,
    metadata_output_path,
    fields=None,
    node_sets=None,
):
    source_metadata = load_metadata(metadata_path)
    requested_fields = list(
        fields if fields is not None else _available_node_fields(source_metadata)
    )
    selected_set_names = []
    for name in node_sets or []:
        if name not in selected_set_names:
            selected_set_names.append(name)
    if not selected_set_names:
        raise ValueError("At least one cached node set is required.")
    if not requested_fields:
        raise ValueError("At least one cached node field is required.")

    nodes = source_metadata.get("nodes") or []
    source_layouts = source_metadata.get("array_layouts") or {}
    field_metadata_by_name = {
        field_name: _validate_field(source_metadata, field_name)
        for field_name in requested_fields
    }

    with np.load(data_path) as data:
        allowed_node_keys = _selected_node_keys(
            data, source_metadata, selected_set_names
        )
        selected_node_indexes = np.asarray(
            [
                index
                for index, node in enumerate(nodes)
                if (node.get("instance", ""), int(node.get("label")))
                in allowed_node_keys
            ],
            dtype=np.int64,
        )
        if not len(selected_node_indexes):
            raise ValueError("Selected cached node sets contain no nodes.")

        required_arrays = ("frequencies", "node_labels", "node_coordinates")
        missing = [name for name in required_arrays if name not in data]
        if missing:
            raise ValueError("Cache is missing array(s): {}".format(", ".join(missing)))
        node_labels = np.asarray(data["node_labels"])
        node_coordinates = np.asarray(data["node_coordinates"])
        if node_labels.shape != (len(nodes),) or node_coordinates.shape != (
            len(nodes),
            3,
        ):
            raise ValueError("Cached node arrays do not match metadata nodes.")

        arrays = {
            "frequencies": np.asarray(data["frequencies"]),
            "node_labels": node_labels[selected_node_indexes],
            "node_coordinates": node_coordinates[selected_node_indexes],
        }
        array_layouts = {
            "frequencies": list(source_layouts.get("frequencies") or ["frame"]),
            "node_labels": list(source_layouts.get("node_labels") or ["node"]),
            "node_coordinates": list(
                source_layouts.get("node_coordinates") or ["node", "coordinate"]
            ),
        }
        field_outputs = {}

        for field_name in requested_fields:
            field_metadata = field_metadata_by_name[field_name]
            points = field_metadata.get("points") or []
            field_indexes = np.asarray(
                [
                    index
                    for index, point in enumerate(points)
                    if (
                        point.get("instance", ""),
                        int(point.get("node_label")),
                    )
                    in allowed_node_keys
                ],
                dtype=np.int64,
            )
            if not len(field_indexes):
                raise ValueError(
                    "Field {} has no points in the selected node sets.".format(
                        field_name
                    )
                )
            for suffix in ("real", "imag"):
                key = "{}_{}".format(field_name, suffix)
                if key not in data:
                    raise ValueError("Cache is missing array {}.".format(key))
                values = np.asarray(data[key])
                if values.ndim != 3 or values.shape[1] != len(points):
                    raise ValueError(
                        "Cached field {} does not match metadata points.".format(
                            field_name
                        )
                    )
                arrays[key] = values[:, field_indexes, :]
                array_layouts[key] = list(
                    source_layouts.get(key)
                    or field_metadata.get("array_layout")
                    or ["frame", "node", "component"]
                )
            output_field_metadata = copy.deepcopy(field_metadata)
            output_field_metadata["points"] = [
                copy.deepcopy(points[int(index)]) for index in field_indexes
            ]
            field_outputs[field_name] = output_field_metadata

        old_to_new = {
            int(source_index): output_index
            for output_index, source_index in enumerate(selected_node_indexes.tolist())
        }
        node_set_metadata = {}
        definitions = source_metadata.get("node_sets") or {}
        for output_set_index, name in enumerate(selected_set_names):
            source_key = definitions[name]["indices_key"]
            output_key = "node_set_{:04d}_indices".format(output_set_index)
            output_indexes = np.asarray(
                [
                    old_to_new[int(index)]
                    for index in np.asarray(data[source_key]).tolist()
                    if int(index) in old_to_new
                ],
                dtype=np.int64,
            )
            arrays[output_key] = output_indexes
            array_layouts[output_key] = ["node_set_member"]
            node_set_metadata[name] = {
                "indices_key": output_key,
                "member_count": len(output_indexes),
            }

    metadata = copy.deepcopy(source_metadata)
    metadata["source_data"] = os.path.abspath(data_path)
    metadata["source_metadata"] = os.path.abspath(metadata_path)
    metadata["fields"] = requested_fields
    metadata["node_count"] = len(selected_node_indexes)
    metadata["nodes"] = [
        copy.deepcopy(nodes[int(index)]) for index in selected_node_indexes
    ]
    metadata["array_shapes"] = {
        name: list(values.shape) for name, values in arrays.items()
    }
    metadata["array_layouts"] = array_layouts
    metadata["field_outputs"] = field_outputs
    metadata["node_sets"] = node_set_metadata
    metadata["filters"] = dict(metadata.get("filters") or {})
    metadata["filters"]["node_sets"] = selected_set_names
    metadata["command_options"] = dict(metadata.get("command_options") or {})
    metadata["command_options"].update(
        {
            "fields": requested_fields,
            "node_sets": selected_set_names,
            "output": os.path.abspath(output_path),
            "metadata": os.path.abspath(metadata_output_path),
        }
    )
    metadata["cache_subset"] = {
        "source_data": os.path.abspath(data_path),
        "source_metadata": os.path.abspath(metadata_path),
        "fields": requested_fields,
        "node_sets": selected_set_names,
    }
    _save_npz(output_path, arrays)
    _save_metadata(metadata_output_path, metadata)
    return metadata
```

- [ ] **Step 4: Run the core test and related interpolation tests**

Run:

```powershell
python -m unittest tests.test_interpolate_odb_points.InterpolateOdbPointsTests.test_subset_node_sets_preserves_values_order_fields_and_membership -v
python -m unittest tests.test_interpolate_odb_points -v
```

Expected: both commands report `OK`; the new test proves raw values and node order are unchanged.

- [ ] **Step 5: Commit the core slice**

```powershell
git add odb_extract/interpolate_points.py tests/test_interpolate_odb_points.py
git commit -m "feat: subset cached data by node set"
```

### Task 2: Cache-mode validation and dispatch

**Files:**
- Modify: `tests/test_run_extract_odb.py:577-622, 1098-1133`
- Modify: `odb_extract/launcher.py:55-63, 729-764, 1720-1796, 1903-1939`

**Interfaces:**
- Consumes: `interpolate_points.interpolate_files(...)` and `interpolate_points.subset_node_sets_files(...)` from Task 1.
- Produces: `run_cached_query(data_path, metadata_path, output_path, metadata_output_path, fields, points_path=None, node_sets=None, neighbors=4, exact_tol=1e-9, point_runner=None, subset_runner=None, log_callback=None) -> int`.

- [ ] **Step 1: Write failing launcher tests**

Replace the existing `test_run_cached_point_query_calls_only_point_runner` with the first test below, then add the other two tests:

```python
def test_run_cached_query_dispatches_point_interpolation(self):
    calls = []

    code = launcher.run_cached_query(
        data_path="cache.npz",
        metadata_path="cache_metadata.json",
        points_path="points.csv",
        output_path="points_point_data.npz",
        metadata_output_path="points_point_metadata.json",
        fields=["U"],
        node_sets=["SET_A"],
        point_runner=lambda **kwargs: calls.append(kwargs),
    )

    self.assertEqual(code, 0)
    self.assertEqual(len(calls), 1)
    self.assertEqual(calls[0]["data_path"], "cache.npz")
    self.assertEqual(calls[0]["points_path"], "points.csv")
    self.assertEqual(calls[0]["node_sets"], ["SET_A"])

def test_run_cached_query_dispatches_node_set_subset_without_points(self):
    calls = []

    code = launcher.run_cached_query(
        data_path="cache.npz",
        metadata_path="cache_metadata.json",
        output_path="set_point_data.npz",
        metadata_output_path="set_point_metadata.json",
        fields=["U"],
        node_sets=["SET_A"],
        subset_runner=lambda **kwargs: calls.append(kwargs),
    )

    self.assertEqual(code, 0)
    self.assertEqual(len(calls), 1)
    self.assertEqual(calls[0]["node_sets"], ["SET_A"])
    self.assertNotIn("points_path", calls[0])

def test_validate_inputs_accepts_cache_node_set_without_points(self):
    data_path, metadata_path = self._write_cache_source("cache-node-set-mode")
    app = launcher.ExtractOdbApp.__new__(launcher.ExtractOdbApp)
    app.source_mode_var = self.FakeVar("cache")
    app.cache_var = self.FakeVar(data_path)
    app.output_var = self.FakeVar(
        os.path.join(os.path.dirname(data_path), "set_subset_data.npz")
    )
    app.points_var = self.FakeVar("")
    app.neighbors_var = self.FakeVar("not-used")
    app.exact_tol_var = self.FakeVar("not-used")
    app.field_vars = {"U": self.FakeVar(True)}
    app.node_sets_var = self.FakeVar("SET_A")

    options = app._validate_inputs()

    self.assertEqual(options["source_mode"], "cache")
    self.assertIsNone(options["points_path"])
    self.assertEqual(options["metadata_path"], metadata_path)
    self.assertEqual(options["node_sets"], ["SET_A"])
```

- [ ] **Step 2: Run the launcher tests and verify RED**

Run:

```powershell
python -m unittest tests.test_run_extract_odb.LauncherTests.test_run_cached_query_dispatches_node_set_subset_without_points tests.test_run_extract_odb.LauncherTests.test_validate_inputs_accepts_cache_node_set_without_points -v
```

Expected: the dispatch test errors because `run_cached_query` is missing, and the validation test fails because cache mode currently requires a point file.

- [ ] **Step 3: Add the cache dispatcher**

Replace `run_cached_point_query` in `odb_extract/launcher.py` with:

```python
def _default_subset_runner(**kwargs):
    from odb_extract import interpolate_points

    return interpolate_points.subset_node_sets_files(**kwargs)


def run_cached_query(
    data_path,
    metadata_path,
    output_path,
    metadata_output_path,
    fields,
    points_path=None,
    node_sets=None,
    neighbors=4,
    exact_tol=1.0e-9,
    point_runner=None,
    subset_runner=None,
    log_callback=None,
):
    if points_path:
        if log_callback:
            log_callback(UI_TEXT["starting_cache_query"])
        runner = _default_point_runner if point_runner is None else point_runner
        runner(
            data_path=data_path,
            metadata_path=metadata_path,
            points_path=points_path,
            output_path=output_path,
            metadata_output_path=metadata_output_path,
            fields=fields,
            node_sets=node_sets,
            neighbors=neighbors,
            exact_tol=exact_tol,
        )
    else:
        if log_callback:
            log_callback(UI_TEXT["starting_cache_subset"])
        runner = _default_subset_runner if subset_runner is None else subset_runner
        runner(
            data_path=data_path,
            metadata_path=metadata_path,
            output_path=output_path,
            metadata_output_path=metadata_output_path,
            fields=fields,
            node_sets=node_sets,
        )
    return 0
```

Update `UI_TEXT` so the relevant entries are:

```python
"missing_cache_selection": "请选择目标点 CSV/Excel 文件，或至少选择一个节点集。",
"missing_output_for_cache": "缓存处理必须设置 NPZ 输出路径。",
"cache_output_conflict": "缓存输出不能覆盖源缓存 NPZ 或配套 metadata。",
"starting_cache_query": "开始从缓存查询目标点。",
"starting_cache_subset": "开始从缓存按节点集提取原始节点。",
"cache_query_finished": "缓存数据处理完成。",
```

- [ ] **Step 4: Allow cache validation without points when node sets exist**

Replace `_validate_cache_inputs` with the complete implementation below:

```python
def _validate_cache_inputs(self):
    from tkinter import messagebox

    cache_path = self.cache_var.get().strip()
    if not cache_path:
        messagebox.showerror(
            UI_TEXT["invalid_cache_title"], UI_TEXT["missing_cache_message"]
        )
        return None
    try:
        source = load_cache_source(cache_path)
    except Exception as exc:
        messagebox.showerror(UI_TEXT["invalid_cache_title"], str(exc))
        return None
    points_path = self.points_var.get().strip() or None
    node_sets = parse_node_set_text(self.node_sets_var.get())
    if not points_path and not node_sets:
        messagebox.showerror(
            UI_TEXT["invalid_cache_title"], UI_TEXT["missing_cache_selection"]
        )
        return None
    output_path = self.output_var.get().strip()
    if not output_path:
        messagebox.showerror(
            UI_TEXT["invalid_cache_title"], UI_TEXT["missing_output_for_cache"]
        )
        return None
    metadata_output_path = metadata_path_for_output(output_path)
    if _same_path(output_path, cache_path) or _same_path(
        metadata_output_path, source["metadata_path"]
    ):
        messagebox.showerror(
            UI_TEXT["invalid_cache_title"], UI_TEXT["cache_output_conflict"]
        )
        return None
    fields = self._selected_fields()
    if not fields:
        messagebox.showerror(
            UI_TEXT["no_fields_selected_title"], UI_TEXT["no_fields_selected_message"]
        )
        return None
    if any(field not in source["fields"] for field in fields):
        messagebox.showerror(
            UI_TEXT["invalid_cache_title"], "所选场输出不在缓存中。"
        )
        return None
    if any(name not in source["node_sets"] for name in (node_sets or [])):
        messagebox.showerror(
            UI_TEXT["invalid_cache_title"], "所选节点集不在缓存中。"
        )
        return None

    neighbors = 4
    exact_tol = 1.0e-9
    if points_path:
        try:
            neighbors = int(self.neighbors_var.get().strip() or "4")
            if neighbors < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                UI_TEXT["invalid_neighbors_title"],
                UI_TEXT["invalid_neighbors_message"],
            )
            return None
        try:
            parsed_tol = parse_optional_float(self.exact_tol_var.get())
        except ValueError:
            messagebox.showerror(
                UI_TEXT["invalid_exact_tol_title"],
                UI_TEXT["invalid_exact_tol_message"],
            )
            return None
        exact_tol = parsed_tol if parsed_tol is not None else 1.0e-9

    return {
        "source_mode": "cache",
        "data_path": cache_path,
        "metadata_path": source["metadata_path"],
        "points_path": points_path,
        "output_path": output_path,
        "metadata_output_path": metadata_output_path,
        "fields": fields,
        "node_sets": node_sets,
        "neighbors": neighbors,
        "exact_tol": exact_tol,
    }
```

In `_run_worker`, replace `run_cached_point_query(...)` with `run_cached_query(...)`; the options dictionary already carries `points_path`.

- [ ] **Step 5: Run focused and full launcher tests**

Run:

```powershell
python -m unittest tests.test_run_extract_odb.LauncherTests.test_run_cached_query_dispatches_point_interpolation tests.test_run_extract_odb.LauncherTests.test_run_cached_query_dispatches_node_set_subset_without_points tests.test_run_extract_odb.LauncherTests.test_validate_inputs_accepts_cache_node_set_without_points -v
python -m unittest tests.test_run_extract_odb -v
```

Expected: both commands report `OK`; the existing point-query test still proves interpolation dispatch.

- [ ] **Step 6: Commit launcher integration**

```powershell
git add odb_extract/launcher.py tests/test_run_extract_odb.py
git commit -m "feat: export cached node sets without interpolation"
```

### Task 3: Documentation and complete regression

**Files:**
- Modify: `README.md:60-66, 81-90`

**Interfaces:**
- Consumes: the two cache-mode paths completed in Tasks 1 and 2.
- Produces: user-facing instructions that distinguish target-point interpolation from raw node-set subset export.

- [ ] **Step 1: Update the cache-mode README contract**

Replace the current cache-mode numbered instructions with this exact text:

```markdown
如果已有全节点 `*_point_data.npz` 或 `*_full_field_data.npz`，可把数据来源切换为“已有缓存”：

1. 选择缓存 NPZ；程序自动读取配套 metadata，并列出其中的节点场和节点集。
2. 勾选要输出的场，然后选择一种操作：
   - 提供目标点 CSV/XLSX：按现有规则进行精确命中或反距离加权；节点集可用于限制候选节点。
   - 不提供目标点文件、选择一个或多个节点集：直接筛选缓存中的原始节点并另存 NPZ/metadata，不插值、不重算。
3. 设置不同于源缓存的输出 NPZ 路径，点击“开始查询”。

多个节点集取并集并去重，直接提取时保留源缓存节点顺序，且只保存当前勾选的场。新版缓存会把节点集成员索引保存在 NPZ 中；旧缓存仍可查询全部节点，但不能按节点集直接提取。输出的节点集索引会重新映射，因此新 NPZ 仍可继续作为缓存使用。
```

In the output section, add one sentence stating that direct subset output keeps the node-field layout `frame,node,component`, while target-point interpolation uses `frame,point,component`.

- [ ] **Step 2: Run all tests and static checks**

Run:

```powershell
python -m unittest discover -s tests -v
python -c "import ast, pathlib; [ast.parse(path.read_text(encoding='utf-8')) for path in pathlib.Path('.').rglob('*.py') if '.venv' not in path.parts]"
git diff --check
```

Expected: unittest reports `OK`; the AST command exits `0`; `git diff --check` prints nothing and exits `0`.

- [ ] **Step 3: Inspect the final scoped diff**

Run:

```powershell
git status --short
git diff --stat HEAD~2
git diff -- README.md odb_extract/interpolate_points.py odb_extract/launcher.py tests/test_interpolate_odb_points.py tests/test_run_extract_odb.py
```

Expected: only the five listed implementation/documentation files are modified by this feature after the two implementation commits; no temporary files appear in the project root or source directories.

- [ ] **Step 4: Commit the documentation update**

```powershell
git add README.md
git commit -m "docs: explain cached node-set subset export"
```
