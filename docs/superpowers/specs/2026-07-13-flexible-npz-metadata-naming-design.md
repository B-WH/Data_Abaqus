# Flexible NPZ metadata naming

## Goal

Allow merge inputs to use general file names without requiring the
`*_point_data.npz` suffix, while preserving automatic discovery of the paired
metadata JSON and compatibility with existing exported files.

## Pairing rules

`infer_metadata_path(data_path)` applies these rules in order:

1. A file ending in `_data.npz` maps to the same path ending in
   `_metadata.json`.
2. Any other file ending in `.npz` maps to the same stem with a `.json`
   extension.
3. A path not ending in `.npz` is rejected with a clear error.

Examples:

- `j-test_100_data.npz` -> `j-test_100_metadata.json`
- `a_point_data.npz` -> `a_point_metadata.json`
- `band-100.npz` -> `band-100.json`

## Scope

- Update the shared inference function in `odb_extract/merge_point_data.py`.
- Keep the GUI and CLI interfaces unchanged; both already call the shared
  function.
- Update user-facing help text and README wording so they no longer claim that
  all inputs must use `*_point_data.npz`.
- Add focused tests for the generic `_data.npz` rule, the plain `.npz` rule,
  legacy compatibility, and rejection of non-NPZ input.

## Validation and safety

Metadata remains mandatory because merge validation depends on its field,
node, coordinate, and array-layout information. Existing checks preventing
output files from overwriting input NPZ or metadata files continue to use the
resolved metadata paths. No array schema or merge behavior changes.
