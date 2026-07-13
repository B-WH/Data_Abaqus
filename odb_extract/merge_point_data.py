"""Merge exported Abaqus ODB NPZ files across frequency bands."""

from __future__ import print_function

import argparse
import copy
import json
import os

import numpy as np


FREQUENCY_ATOL = 1.0e-8
VALUE_RTOL = 1.0e-8
VALUE_ATOL = 1.0e-10


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


def load_part(data_path, metadata_path=None):
    metadata_path = metadata_path or infer_metadata_path(data_path)
    with open(metadata_path, "r", encoding="utf-8") as stream:
        metadata = json.load(stream)
    return {
        "data_path": os.path.abspath(data_path),
        "metadata_path": os.path.abspath(metadata_path),
        "arrays": np.load(data_path),
        "metadata": metadata,
    }


def merge_files(
    data_paths,
    output_path,
    metadata_output_path,
    duplicate_frequency_tolerance=FREQUENCY_ATOL,
):
    validate_output_paths(data_paths, output_path, metadata_output_path)
    parts = [load_part(path) for path in data_paths]
    try:
        arrays, metadata = merge_parts(
            parts,
            duplicate_frequency_tolerance=duplicate_frequency_tolerance,
        )
        _ensure_parent_dir(output_path)
        _ensure_parent_dir(metadata_output_path)
        np.savez_compressed(output_path, **arrays)
        with open(metadata_output_path, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream, ensure_ascii=False, indent=2, sort_keys=True)
        return arrays, metadata
    finally:
        for part in parts:
            close = getattr(part["arrays"], "close", None)
            if close is not None:
                close()


def validate_output_paths(data_paths, output_path, metadata_output_path):
    output = _normalized_path(output_path)
    metadata_output = _normalized_path(metadata_output_path)
    if output == metadata_output:
        raise ValueError("Output NPZ and metadata JSON must use different paths.")
    input_data_paths = {_normalized_path(path) for path in data_paths}
    input_metadata_paths = {_normalized_path(infer_metadata_path(path)) for path in data_paths}
    if output in input_data_paths:
        raise ValueError("Output NPZ must not overwrite an input NPZ.")
    if metadata_output in input_metadata_paths:
        raise ValueError("Output metadata JSON must not overwrite input metadata.")


def merge_parts(parts, duplicate_frequency_tolerance=FREQUENCY_ATOL):
    if len(parts) < 2:
        raise ValueError("At least two NPZ files are required for merging.")

    base = parts[0]
    base_arrays = base["arrays"]
    base_metadata = base["metadata"]
    _validate_required_arrays(base_arrays)
    array_layouts = dict(base_metadata.get("array_layouts") or {})
    frame_keys = _frame_array_keys(array_layouts)
    if "frequencies" not in frame_keys:
        raise ValueError("array_layouts must mark frequencies as a frame array.")

    for part in parts[1:]:
        _validate_part_matches_base(base, part, array_layouts)

    sorted_keep_indexes = _sorted_unique_frame_indexes(
        parts,
        frame_keys,
        duplicate_frequency_tolerance,
    )
    arrays = {}
    for key in _array_names(base_arrays):
        if key in frame_keys:
            # ponytail: one full concatenate per array; stream zip writing only if NPZ files become multi-GB.
            concatenated = np.concatenate([part["arrays"][key] for part in parts], axis=0)
            arrays[key] = concatenated[sorted_keep_indexes]
        else:
            arrays[key] = np.array(base_arrays[key])
    return arrays, _merged_metadata(base_metadata, parts, arrays)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Merge exported Abaqus ODB NPZ files by frequency."
    )
    parser.add_argument("--input", nargs="+", required=True, help="Input NPZ files.")
    parser.add_argument("--output", required=True, help="Merged output NPZ path.")
    parser.add_argument("--metadata-output", required=True, help="Merged metadata JSON path.")
    parser.add_argument(
        "--duplicate-frequency-tolerance",
        type=float,
        default=FREQUENCY_ATOL,
        help="Frequency tolerance for treating boundary frames as duplicates.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    arrays, metadata = merge_files(
        args.input,
        args.output,
        args.metadata_output,
        duplicate_frequency_tolerance=args.duplicate_frequency_tolerance,
    )
    print(
        "Merged {} file(s), {} frequency frame(s): {} to {} Hz".format(
            len(args.input),
            len(arrays["frequencies"]),
            metadata["merge"]["frequency_min"],
            metadata["merge"]["frequency_max"],
        )
    )
    return 0


def _ensure_parent_dir(path):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)


def _normalized_path(path):
    return os.path.normcase(os.path.abspath(path))


def _array_names(arrays):
    if hasattr(arrays, "files"):
        return list(arrays.files)
    return list(arrays.keys())


def _validate_required_arrays(arrays):
    names = set(_array_names(arrays))
    missing = [
        name
        for name in ("frequencies", "node_labels", "node_coordinates")
        if name not in names
    ]
    if missing:
        raise ValueError("NPZ is missing required array(s): {}".format(", ".join(missing)))


def _frame_array_keys(array_layouts):
    return {
        key
        for key, layout in array_layouts.items()
        if layout and layout[0] == "frame"
    }


def _validate_part_matches_base(base, part, base_layouts):
    arrays = part["arrays"]
    metadata = part["metadata"]
    base_arrays = base["arrays"]
    base_metadata = base["metadata"]

    _validate_required_arrays(arrays)
    if set(_array_names(arrays)) != set(_array_names(base_arrays)):
        raise ValueError("array keys do not match between NPZ files.")
    if metadata.get("fields") != base_metadata.get("fields"):
        raise ValueError("fields do not match between metadata files.")
    if metadata.get("field_outputs") != base_metadata.get("field_outputs"):
        raise ValueError("field_outputs do not match between metadata files.")
    if (metadata.get("node_sets") or {}) != (base_metadata.get("node_sets") or {}):
        raise ValueError("node_sets do not match between metadata files.")
    if (metadata.get("array_layouts") or {}) != base_layouts:
        raise ValueError("array_layouts do not match between metadata files.")
    if _node_identity(metadata) != _node_identity(base_metadata):
        raise ValueError("nodes do not match between metadata files.")
    if not np.array_equal(arrays["node_labels"], base_arrays["node_labels"]):
        raise ValueError("node_labels do not match between NPZ files.")
    if not np.allclose(
        arrays["node_coordinates"],
        base_arrays["node_coordinates"],
        rtol=VALUE_RTOL,
        atol=VALUE_ATOL,
        equal_nan=True,
    ):
        raise ValueError("node_coordinates do not match between NPZ files.")

    for key, layout in base_layouts.items():
        if layout and layout[0] == "frame":
            continue
        if key in arrays and key not in ("node_labels", "node_coordinates"):
            if not np.allclose(
                arrays[key],
                base_arrays[key],
                rtol=VALUE_RTOL,
                atol=VALUE_ATOL,
                equal_nan=True,
            ):
                raise ValueError("{} does not match between NPZ files.".format(key))


def _node_identity(metadata):
    return [
        (node.get("instance"), int(node.get("label")))
        for node in metadata.get("nodes", [])
    ]


def _sorted_unique_frame_indexes(parts, frame_keys, duplicate_frequency_tolerance):
    frequency_chunks = [part["arrays"]["frequencies"] for part in parts]
    frequencies = np.concatenate(frequency_chunks)
    row_refs = []
    for part_index, chunk in enumerate(frequency_chunks):
        row_refs.extend((part_index, row_index) for row_index in range(len(chunk)))
    sort_order = np.argsort(frequencies, kind="mergesort")

    keep_indexes = []
    previous_index = None
    for index in sort_order:
        frequency = frequencies[index]
        if previous_index is None:
            keep_indexes.append(index)
            previous_index = index
            continue

        previous_frequency = frequencies[previous_index]
        if abs(float(frequency) - float(previous_frequency)) <= duplicate_frequency_tolerance:
            _validate_duplicate_frame_refs(
                parts,
                frame_keys,
                row_refs[previous_index],
                row_refs[index],
                float(previous_frequency),
            )
            continue

        keep_indexes.append(index)
        previous_index = index

    return keep_indexes


def _validate_duplicate_frame_refs(parts, frame_keys, first_ref, second_ref, frequency):
    first_part, first_index = first_ref
    second_part, second_index = second_ref
    for key in _array_names(parts[first_part]["arrays"]):
        if key == "frequencies" or key not in frame_keys:
            continue
        if not np.allclose(
            parts[first_part]["arrays"][key][first_index],
            parts[second_part]["arrays"][key][second_index],
            rtol=VALUE_RTOL,
            atol=VALUE_ATOL,
            equal_nan=True,
        ):
            raise ValueError(
                "Duplicate frequency {} Hz has conflicting data in {}.".format(
                    frequency,
                    key,
                )
            )


def _merged_metadata(base_metadata, parts, arrays):
    metadata = copy.deepcopy(base_metadata)
    frequencies = arrays["frequencies"]
    metadata["source_parts"] = [_source_part_metadata(part) for part in parts]
    metadata["merge"] = {
        "tool": "odb_extract.merge_point_data",
        "source_part_count": len(parts),
        "frequency_count": int(len(frequencies)),
        "frequency_min": float(frequencies[0]) if len(frequencies) else None,
        "frequency_max": float(frequencies[-1]) if len(frequencies) else None,
        "duplicate_frequency_policy": "equal_frames_deduplicated_conflicts_error",
    }
    metadata["array_shapes"] = {key: list(value.shape) for key, value in arrays.items()}
    metadata["warnings"] = _merged_warnings(parts)
    return metadata


def _merged_warnings(parts):
    warnings = []
    for part in parts:
        label = os.path.basename(part.get("data_path") or "")
        for warning in part["metadata"].get("warnings") or []:
            warnings.append("{}: {}".format(label, warning))
    return warnings


def _source_part_metadata(part):
    frequencies = part["arrays"]["frequencies"]
    return {
        "data_path": part.get("data_path"),
        "metadata_path": part.get("metadata_path"),
        "source_odb": part["metadata"].get("source_odb"),
        "frequency_count": int(len(frequencies)),
        "frequency_min": float(frequencies[0]) if len(frequencies) else None,
        "frequency_max": float(frequencies[-1]) if len(frequencies) else None,
    }


if __name__ == "__main__":
    raise SystemExit(main())
