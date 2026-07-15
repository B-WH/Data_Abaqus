# NPZ viewer and magnitude-only CSV export

## Goal

Add a GUI-first post-processing tool for NPZ files produced by this Abaqus
project. The tool previews the stored arrays and exports selected field data to
CSV in a readable long-table layout. Exported field values contain magnitude
only; real part, imaginary part, and phase are not written.

## Scope

- Open one project-generated NPZ file and automatically locate its paired
  metadata JSON using the repository's existing naming rule.
- Show each array's name, shape, data type, element count, NaN count, and a
  small preview.
- Let the user select fields, components, a frequency range, and optional
  entity identifiers before export.
- Export one CSV with one row per frequency, entity, field, and component.
- Add an entry to the existing launcher GUI rather than creating another
  independent application workflow.
- Keep the first version specific to this repository's NPZ/metadata contract.
  TXT, XLSX, Parquet, and arbitrary third-party NPZ schemas are out of scope.

## CSV contract

Every row contains these common columns:

- `frequency`
- `field`
- `component`
- `magnitude`

Identity columns are added from metadata when applicable:

- node data: `instance`, `node_label`, `x`, `y`, `z`
- interpolated point data: `point_id`, `x`, `y`, `z`
- element data: `instance`, `element_label`, `integration_point`,
  `section_point`
- generic value data: `instance`, `value_index`

Magnitude is calculated as `hypot(real, imag)`. Existing NaN values remain
NaN in the CSV. The CSV does not contain real-part, imaginary-part, or phase
columns.

## Components and data flow

1. The launcher opens the converter window.
2. The converter loads metadata first, then opens the NPZ with NumPy.
3. It validates field names, array layouts, real/imaginary pairs, shapes, and
   entity metadata before enabling export.
4. The preview reads only a small slice of the selected array.
5. Export estimates the output row count, asks for confirmation when it exceeds
   Excel's worksheet row limit, then writes rows directly with Python's
   standard `csv` module instead of building a full in-memory table.

The implementation should reuse the repository's metadata-path inference and
metadata field definitions. No new dependency is required.

## Errors and safety

- Missing or invalid metadata, unsupported layouts, mismatched real/imaginary
  shapes, and missing entity records stop export with a clear GUI error.
- The output path must differ from both input files.
- Existing output CSV files are replaced only after normal GUI overwrite
  confirmation.
- A failed export must not leave a partial file at the final output path.

## Verification

Add focused tests covering metadata pairing, magnitude calculation, long-table
headers and rows for representative node data, filtering, NaN preservation,
shape rejection, and safe temporary-file replacement. Run the existing unit
test suite after the focused tests pass.
