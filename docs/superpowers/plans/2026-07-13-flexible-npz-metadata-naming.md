# Flexible NPZ Metadata Naming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow merge inputs to pair `*_data.npz` with `*_metadata.json` and other `.npz` files with a same-stem `.json` file.

**Architecture:** Keep metadata discovery in the existing shared `infer_metadata_path()` function so CLI, GUI validation, loading, and overwrite checks all receive the same behavior. Preserve the existing merge schema and validation code.

**Tech Stack:** Python standard library, NumPy, `unittest`, Markdown

## Global Constraints

- Do not require `_point_` in merge input names.
- Map `*_data.npz` to `*_metadata.json`.
- Map any other `name.npz` to `name.json`.
- Reject paths that do not end in `.npz`.
- Preserve existing merge validation and output-overwrite protection.
- Do not modify unrelated changes in `odb_extract/launcher.py`.

---

### Task 1: Generalize metadata path inference

**Files:**
- Modify: `tests/test_merge_point_data.py`
- Modify: `odb_extract/merge_point_data.py`

**Interfaces:**
- Consumes: `infer_metadata_path(data_path: str)`
- Produces: The inferred metadata JSON path as `str`, or `ValueError` for a non-NPZ path.

- [x] **Step 1: Write the failing test**

Replace the fixed-name inference test with:

```python
def test_infer_metadata_path_supports_general_npz_names(self):
    cases = (
        (r"D:\work\j-test_100_data.npz", r"D:\work\j-test_100_metadata.json"),
        (r"D:\work\a_point_data.npz", r"D:\work\a_point_metadata.json"),
        (r"D:\work\band-100.npz", r"D:\work\band-100.json"),
    )
    for data_path, expected in cases:
        with self.subTest(data_path=data_path):
            self.assertEqual(merge_point_data.infer_metadata_path(data_path), expected)

def test_infer_metadata_path_rejects_non_npz_path(self):
    with self.assertRaisesRegex(ValueError, "\\.npz"):
        merge_point_data.infer_metadata_path(r"D:\work\band-100.dat")
```

- [x] **Step 2: Run the inference tests to verify RED**

Run:

```powershell
python -B -m unittest tests.test_merge_point_data.MergePointDataTests.test_infer_metadata_path_supports_general_npz_names tests.test_merge_point_data.MergePointDataTests.test_infer_metadata_path_rejects_non_npz_path -v
```

Expected: the general-name test fails because `j-test_100_data.npz` does not end in `_point_data.npz`.

- [x] **Step 3: Implement the minimal inference rules**

Replace `infer_metadata_path()` with:

```python
def infer_metadata_path(data_path):
    data_suffix = "_data.npz"
    base_name = os.path.basename(data_path)
    if base_name.endswith(data_suffix):
        metadata_name = base_name[: -len(data_suffix)] + "_metadata.json"
    elif base_name.endswith(".npz"):
        metadata_name = base_name[:-4] + ".json"
    else:
        raise ValueError("Input file must use a .npz extension: {}".format(data_path))
    return os.path.join(os.path.dirname(data_path), metadata_name)
```

- [x] **Step 4: Run the focused merge tests to verify GREEN**

Run:

```powershell
python -B -m unittest tests.test_merge_point_data -v
```

Expected: all `tests.test_merge_point_data` tests pass.

- [x] **Step 5: Commit the inference change**

```powershell
git add -- tests/test_merge_point_data.py odb_extract/merge_point_data.py
git commit -m "feat: support general NPZ metadata names"
```

### Task 2: Align user-facing descriptions

**Files:**
- Modify: `odb_extract/merge_point_data.py`
- Modify: `odb_extract/merge_gui.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the pairing rules implemented by `infer_metadata_path()`.
- Produces: CLI, GUI, and README text that describes general NPZ input and automatic metadata pairing.

- [x] **Step 1: Update existing text without adding UI controls**

Make these replacements:

```text
Merge exported Abaqus ODB point-data NPZ files across frequency bands.
-> Merge exported Abaqus ODB NPZ files across frequency bands.

Input *_point_data.npz files.
-> Input NPZ files.

请至少选择两个 *_point_data.npz 文件。
-> 请至少选择两个 NPZ 文件。
```

In README, document both rules with examples:

```markdown
- `*_data.npz` 自动配对同目录的 `*_metadata.json`；
- 其他 `任意名称.npz` 自动配对同目录的 `任意名称.json`。
```

- [x] **Step 2: Run targeted GUI and documentation checks**

Run:

```powershell
python -B -m unittest tests.test_run_extract_odb.LauncherTests.test_merge_window_validate_inputs_requires_two_npz_files tests.test_run_extract_odb.LauncherTests.test_merge_window_validate_inputs_requires_paired_metadata -v
```

Expected: all selected tests pass.

- [x] **Step 3: Run final verification**

Run:

```powershell
python -B -m unittest tests.test_merge_point_data tests.test_run_extract_odb -v
git diff --check
```

Expected: all selected tests pass and `git diff --check` reports no whitespace errors.

- [x] **Step 4: Commit the user-facing text changes**

```powershell
git add -- README.md odb_extract/merge_gui.py odb_extract/merge_point_data.py
git commit -m "docs: describe flexible NPZ metadata pairing"
```
