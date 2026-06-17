"""Extract nodal frequency-response data from an Abaqus ODB file.

Run with Abaqus Python, for example:
    abaqus python Extract_data_ODB.py --odb data\\test1.odb
"""

from __future__ import print_function

import argparse
import importlib
import json
import os
import sys
from collections import namedtuple
from datetime import datetime


DEFAULT_ODB = os.path.join("data", "test1.odb")
DEFAULT_OUTPUT = os.path.join("output", "test1_point_data.npz")
DEFAULT_METADATA = os.path.join("output", "test1_point_metadata.json")
DEFAULT_FIELDS = ("U", "UR", "V", "VR", "A", "AR")

NodeRef = namedtuple("NodeRef", ["instance_name", "label"])


class OdbAccessUnavailableError(RuntimeError):
    pass


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract all nodal point response data from an Abaqus ODB."
    )
    parser.add_argument("--odb", default=DEFAULT_ODB, help="Input ODB path.")
    parser.add_argument(
        "--step",
        default=None,
        help="Step name. Defaults to the only step in the ODB, or HARMONIC_RESPONSE if present.",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output NPZ file path.")
    parser.add_argument(
        "--metadata", default=DEFAULT_METADATA, help="Output metadata JSON file path."
    )
    parser.add_argument(
        "--fields",
        nargs="+",
        default=list(DEFAULT_FIELDS),
        help="Field output names to extract.",
    )
    parser.add_argument(
        "--list-fields",
        action="store_true",
        help="Print available field output names as JSON and exit.",
    )
    return parser.parse_args(argv)


def open_odb_readonly(path):
    try:
        odb_access = importlib.import_module("odbAccess")
    except ImportError as exc:
        raise OdbAccessUnavailableError(
            "Abaqus module 'odbAccess' is not available in this Python environment. "
            "Run this script with Abaqus Python, for example: "
            "abaqus python Extract_data_ODB.py --odb data\\test1.odb"
        ) from exc
    return odb_access.openOdb(path=path, readOnly=True)


def _numpy():
    return importlib.import_module("numpy")


def ensure_parent_dir(path):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)


def collect_nodes(odb):
    nodes = []
    for instance_name in sorted(odb.rootAssembly.instances.keys()):
        instance = odb.rootAssembly.instances[instance_name]
        for node in instance.nodes:
            nodes.append(NodeRef(instance_name, int(node.label)))
    return sorted(nodes, key=lambda item: (item.instance_name, item.label))


def choose_step_name(odb, requested_step=None):
    step_names = list(odb.steps.keys())
    if requested_step:
        if requested_step not in odb.steps:
            raise ValueError(
                "Step {!r} not found. Available steps: {}".format(
                    requested_step, ", ".join(step_names)
                )
            )
        return requested_step
    if len(step_names) == 1:
        return step_names[0]
    if "HARMONIC_RESPONSE" in odb.steps:
        return "HARMONIC_RESPONSE"
    raise ValueError(
        "ODB has multiple steps. Use --step. Available steps: {}".format(
            ", ".join(step_names)
        )
    )


def collect_field_names(step):
    field_names = set()
    for frame in step.frames:
        field_names.update(frame.fieldOutputs.keys())
    return sorted(field_names)


def _tuple_to_float_array(value):
    np = _numpy()
    return np.asarray(_value_data_tuple(value), dtype=float)


def _value_data_tuple(value):
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _component_count_from_step(step, fields):
    for frame in step.frames:
        for field_name in fields:
            if field_name not in frame.fieldOutputs:
                continue
            field = frame.fieldOutputs[field_name]
            values = _get_field_values(field)
            if len(values):
                return len(_value_data_tuple(values[0].data))
    return 0


def _component_count_for_field(step, field_name):
    component_count = 0
    for frame in step.frames:
        if field_name not in frame.fieldOutputs:
            continue
        for value in _get_field_values(frame.fieldOutputs[field_name]):
            component_count = max(component_count, len(_value_data_tuple(value.data)))
    return component_count


def _get_field_values(field):
    if hasattr(field, "values"):
        return field.values
    return field.getSubset().values


def _instance_name(value):
    instance_name = getattr(getattr(value, "instance", None), "name", "")
    return instance_name


def _optional_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _section_point_id(value):
    section_point = getattr(value, "sectionPoint", None)
    if section_point is None:
        return None
    for attribute in ("number", "index"):
        if hasattr(section_point, attribute):
            return _optional_int(getattr(section_point, attribute))
    return str(section_point)


def _field_value_key(value, ordinal=0):
    instance_name = _instance_name(value)
    if hasattr(value, "nodeLabel"):
        return ("NODE", instance_name, int(value.nodeLabel))
    if hasattr(value, "elementLabel"):
        return (
            "ELEMENT",
            instance_name,
            int(value.elementLabel),
            _optional_int(getattr(value, "integrationPoint", None)),
            _section_point_id(value),
        )
    return ("VALUE", instance_name, int(ordinal))


def _node_key(node):
    return ("NODE", node.instance_name, int(node.label))


def _sort_key(key):
    return tuple("" if part is None else part for part in key)


def _field_location_from_step(step, field_name):
    for frame in step.frames:
        if field_name not in frame.fieldOutputs:
            continue
        values = _get_field_values(frame.fieldOutputs[field_name])
        if len(values):
            return _field_value_key(values[0])[0]
    return "NODE"


def _collect_field_point_keys(step, field_name, nodes, location):
    if location == "NODE":
        return [_node_key(node) for node in nodes]

    keys = set()
    for frame in step.frames:
        if field_name not in frame.fieldOutputs:
            continue
        for ordinal, value in enumerate(_get_field_values(frame.fieldOutputs[field_name])):
            keys.add(_field_value_key(value, ordinal))
    return sorted(keys, key=_sort_key)


def _field_point_metadata(key):
    location = key[0]
    if location == "NODE":
        return {"instance": key[1], "node_label": int(key[2])}
    if location == "ELEMENT":
        point = {"instance": key[1], "element_label": int(key[2])}
        if key[3] is not None:
            point["integration_point"] = key[3]
        if key[4] is not None:
            point["section_point"] = key[4]
        return point
    return {"instance": key[1], "value_index": int(key[2])}


def extract_field_arrays(step, nodes, fields):
    np = _numpy()
    frames = list(step.frames)
    frequencies = np.asarray([float(frame.frameValue) for frame in frames], dtype=float)
    node_labels = np.asarray([node.label for node in nodes], dtype=np.int64)
    default_component_count = _component_count_from_step(step, fields)
    warnings = []

    arrays = {
        "frequencies": frequencies,
        "node_labels": node_labels,
    }
    metadata = {
        "array_shapes": {
            "frequencies": list(frequencies.shape),
            "node_labels": list(node_labels.shape),
        },
        "field_outputs": {},
        "warnings": warnings,
    }

    for field_name in fields:
        location = _field_location_from_step(step, field_name)
        point_keys = _collect_field_point_keys(step, field_name, nodes, location)
        point_index = dict((key, index) for index, key in enumerate(point_keys))
        component_count = _component_count_for_field(step, field_name) or default_component_count
        real_key = "{}_real".format(field_name)
        imag_key = "{}_imag".format(field_name)
        real_data = np.full(
            (len(frames), len(point_keys), component_count), np.nan, dtype=float
        )
        imag_data = np.full(
            (len(frames), len(point_keys), component_count), np.nan, dtype=float
        )

        for frame_index, frame in enumerate(frames):
            if field_name not in frame.fieldOutputs:
                warnings.append(
                    "Field {} is missing from frame {} at frameValue {}.".format(
                        field_name, frame_index, frame.frameValue
                    )
                )
                continue

            field = frame.fieldOutputs[field_name]
            seen = set()
            for ordinal, value in enumerate(_get_field_values(field)):
                key = _field_value_key(value, ordinal)
                if key not in point_index:
                    continue
                output_index = point_index[key]
                real_values = _tuple_to_float_array(value.data)
                imag_values = _tuple_to_float_array(
                    getattr(value, "conjugateData", np.zeros(len(real_values)))
                )
                real_data[frame_index, output_index, : len(real_values)] = real_values
                imag_data[frame_index, output_index, : len(imag_values)] = imag_values
                seen.add(key)

            missing_count = len(point_keys) - len(seen)
            if missing_count:
                warnings.append(
                    "Field {} frame {} is missing values for {} output point(s).".format(
                        field_name, frame_index, missing_count
                    )
                )

        arrays[real_key] = real_data
        arrays[imag_key] = imag_data
        metadata["array_shapes"][real_key] = list(real_data.shape)
        metadata["array_shapes"][imag_key] = list(imag_data.shape)
        metadata["field_outputs"][field_name] = {
            "location": location,
            "component_count": int(component_count),
            "points": [_field_point_metadata(key) for key in point_keys],
        }

    return arrays, metadata


def save_npz(output_path, arrays):
    np = _numpy()
    ensure_parent_dir(output_path)
    np.savez_compressed(output_path, **arrays)


def save_metadata(metadata_path, metadata):
    ensure_parent_dir(metadata_path)
    with open(metadata_path, "w", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2, sort_keys=True)


def build_metadata(odb_path, step_name, fields, nodes, arrays, extraction_metadata):
    metadata = {
        "source_odb": os.path.abspath(odb_path),
        "step": step_name,
        "fields": list(fields),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "node_count": len(nodes),
        "nodes": [
            {"instance": node.instance_name, "label": int(node.label)} for node in nodes
        ],
        "node_labels": [int(label) for label in arrays["node_labels"].tolist()],
        "frequencies": [float(value) for value in arrays["frequencies"].tolist()],
        "array_shapes": extraction_metadata["array_shapes"],
        "field_outputs": extraction_metadata.get("field_outputs", {}),
        "warnings": extraction_metadata["warnings"],
    }
    return metadata


def run(args):
    odb = open_odb_readonly(args.odb)
    try:
        step_name = choose_step_name(odb, args.step)
        step = odb.steps[step_name]
        nodes = collect_nodes(odb)
        arrays, extraction_metadata = extract_field_arrays(step, nodes, args.fields)
        metadata = build_metadata(
            args.odb, step_name, args.fields, nodes, arrays, extraction_metadata
        )
        save_npz(args.output, arrays)
        save_metadata(args.metadata, metadata)
    finally:
        odb.close()
    print("Saved NPZ: {}".format(args.output))
    print("Saved metadata: {}".format(args.metadata))
    if metadata["warnings"]:
        print("Warnings: {}".format(len(metadata["warnings"])))
    return metadata


def run_list_fields(args):
    odb = open_odb_readonly(args.odb)
    try:
        step_name = choose_step_name(odb, args.step)
        fields = collect_field_names(odb.steps[step_name])
        metadata = {
            "source_odb": os.path.abspath(args.odb),
            "step": step_name,
            "fields": fields,
        }
    finally:
        odb.close()
    print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
    return metadata


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.list_fields:
            run_list_fields(args)
        else:
            run(args)
    except OdbAccessUnavailableError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
