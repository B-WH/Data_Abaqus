"""Extract nodal frequency-response data from an Abaqus ODB file.

Run with Abaqus Python, for example:
    abaqus python .\\odb_extract\\extractor.py --odb data\\test1.odb
"""

from __future__ import print_function

import argparse
import csv
import io
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
TOOL_NAME = "odb_extract.extractor"
METADATA_SCHEMA_VERSION = 1
CSV_COMPONENT_KEYS = ("1", "2", "3", "total")

NodeRef = namedtuple("NodeRef", ["instance_name", "label", "coordinates"])


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
        "--csv-output",
        default=None,
        help="Optional node set long-table CSV output path.",
    )
    parser.add_argument(
        "--csv-components",
        nargs="+",
        default=None,
        help="Optional CSV component selections, e.g. V=1,2,3,total.",
    )
    parser.add_argument(
        "--fields",
        nargs="+",
        default=list(DEFAULT_FIELDS),
        help="Field output names to extract.",
    )
    parser.add_argument(
        "--instances",
        nargs="+",
        default=None,
        help="Optional instance names to include.",
    )
    parser.add_argument(
        "--node-labels",
        nargs="+",
        default=None,
        help="Optional node labels to include. Accepts spaces or comma-separated values.",
    )
    parser.add_argument(
        "--frequency-min",
        type=float,
        default=None,
        help="Optional minimum frame frequency.",
    )
    parser.add_argument(
        "--frequency-max",
        type=float,
        default=None,
        help="Optional maximum frame frequency.",
    )
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
    parser.add_argument(
        "--list-fields",
        action="store_true",
        help="Print available field output names as JSON and exit.",
    )
    return parser.parse_args(argv)


def open_odb_readonly(path):
    try:
        odb_access = importlib.import_module("odbAccess")
    except ImportError:
        raise OdbAccessUnavailableError(
            "Abaqus module 'odbAccess' is not available in this Python environment. "
            "Run this script with Abaqus Python, for example: "
            "abaqus python .\\odb_extract\\extractor.py --odb data\\test1.odb"
        )
    return odb_access.openOdb(path=path, readOnly=True)


def _numpy():
    return importlib.import_module("numpy")


def _full_array(np, shape, fill_value, dtype=float):
    array = np.empty(shape, dtype=dtype)
    array.fill(fill_value)
    return array


def _now_iso_seconds():
    return datetime.now().replace(microsecond=0).isoformat()


def ensure_parent_dir(path):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)


def default_csv_output_path(output_path):
    base_path, _extension = os.path.splitext(output_path)
    suffix = "_point_data"
    if base_path.endswith(suffix):
        base_path = base_path[: -len(suffix)]
    return "{}_node_set_data.csv".format(base_path)


def parse_node_label_values(values):
    if not values:
        return None
    labels = []
    for value in values:
        for part in str(value).replace(",", " ").replace(";", " ").split():
            labels.append(int(part))
    return labels or None


def parse_csv_component_specs(specs):
    if not specs:
        return None
    selections = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(
                "CSV component selection must use FIELD=1,2,3,total syntax."
            )
        field_name, values_text = spec.split("=", 1)
        field_name = field_name.strip()
        values = [
            value.strip().lower()
            for value in values_text.replace(";", ",").split(",")
            if value.strip()
        ]
        invalid = [value for value in values if value not in CSV_COMPONENT_KEYS]
        if not field_name or invalid:
            raise ValueError(
                "Invalid CSV component selection {!r}.".format(spec)
            )
        selections[field_name] = values
    return selections or None


def _node_coordinates(node):
    coordinates = [float(value) for value in getattr(node, "coordinates", ())]
    if len(coordinates) < 3:
        coordinates.extend([0.0] * (3 - len(coordinates)))
    return tuple(coordinates[:3])


def list_node_sets(odb):
    """Return sorted list of node set names in the ODB assembly."""
    return sorted(odb.rootAssembly.nodeSets.keys())


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
                for instance_name, label in _node_set_members(nset):
                    nset_members.add((instance_name, label))
            else:
                if warnings is not None:
                    warnings.append(
                        "Node set {!r} not found in ODB.".format(nset_name)
                    )
        nodes = [
            n for n in nodes if (n.instance_name, n.label) in nset_members
        ]

    return sorted(nodes, key=lambda item: (item.instance_name, item.label))


def _node_set_members(nset):
    for item in nset.nodes:
        if hasattr(item, "label"):
            yield getattr(item, "instanceName", ""), int(item.label)
            continue
        instance_name = getattr(item, "instanceName", "")
        for node in item:
            yield getattr(node, "instanceName", instance_name), int(node.label)


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


def _component_labels_for_field(step, field_name, component_count):
    for frame in step.frames:
        if field_name not in frame.fieldOutputs:
            continue
        labels = getattr(frame.fieldOutputs[field_name], "componentLabels", None)
        if labels and len(labels) == component_count:
            return [str(label) for label in labels]

    if component_count == 1:
        return [field_name]
    return ["component_{}".format(index + 1) for index in range(component_count)]


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


def _array_layout_for_location(location):
    if location == "NODE":
        return ["frame", "node", "component"]
    if location == "ELEMENT":
        return ["frame", "element_point", "component"]
    return ["frame", "value", "component"]


def _filter_frames_by_frequency(frames, frequency_min=None, frequency_max=None):
    filtered_frames = []
    for frame in frames:
        frequency = float(frame.frameValue)
        if frequency_min is not None and frequency < frequency_min:
            continue
        if frequency_max is not None and frequency > frequency_max:
            continue
        filtered_frames.append(frame)
    return filtered_frames


def extract_field_arrays(step, nodes, fields, frequency_min=None, frequency_max=None):
    np = _numpy()
    frames = _filter_frames_by_frequency(
        list(step.frames),
        frequency_min=frequency_min,
        frequency_max=frequency_max,
    )
    frequencies = np.asarray([float(frame.frameValue) for frame in frames], dtype=float)
    node_labels = np.asarray([node.label for node in nodes], dtype=np.int64)
    node_coordinates = np.asarray([node.coordinates for node in nodes], dtype=float)
    default_component_count = _component_count_from_step(step, fields)
    warnings = []

    arrays = {
        "frequencies": frequencies,
        "node_labels": node_labels,
        "node_coordinates": node_coordinates,
    }
    metadata = {
        "array_shapes": {
            "frequencies": list(frequencies.shape),
            "node_labels": list(node_labels.shape),
            "node_coordinates": list(node_coordinates.shape),
        },
        "array_layouts": {
            "frequencies": ["frame"],
            "node_labels": ["node"],
            "node_coordinates": ["node", "coordinate"],
        },
        "field_outputs": {},
        "warnings": warnings,
    }

    for field_name in fields:
        location = _field_location_from_step(step, field_name)
        point_keys = _collect_field_point_keys(step, field_name, nodes, location)
        point_index = {}  # type: dict
        for index, point_key in enumerate(point_keys):
            point_index[point_key] = index
        component_count = _component_count_for_field(step, field_name) or default_component_count
        components = _component_labels_for_field(step, field_name, component_count)
        array_layout = _array_layout_for_location(location)
        real_key = "{}_real".format(field_name)
        imag_key = "{}_imag".format(field_name)
        real_data = _full_array(
            np,
            (len(frames), len(point_keys), component_count), np.nan, dtype=float
        )
        imag_data = _full_array(
            np,
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
        metadata["array_layouts"][real_key] = list(array_layout)
        metadata["array_layouts"][imag_key] = list(array_layout)
        metadata["field_outputs"][field_name] = {
            "location": location,
            "component_count": int(component_count),
            "components": components,
            "array_layout": array_layout,
            "points": [_field_point_metadata(key) for key in point_keys],
        }

    return arrays, metadata


def save_npz(output_path, arrays):
    np = _numpy()
    ensure_parent_dir(output_path)
    np.savez_compressed(output_path, **arrays)


def save_metadata(metadata_path, metadata):
    ensure_parent_dir(metadata_path)
    with io.open(metadata_path, "w", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2, sort_keys=True)


def _open_csv_for_write(path):
    ensure_parent_dir(path)
    if sys.version_info[0] < 3:
        return open(path, "wb")
    return open(path, "w", newline="", encoding="utf-8")


def csv_component_items(field_name, components, selection=None, warnings=None):
    if not selection:
        return [
            ("component", index, component)
            for index, component in enumerate(components)
        ]

    items = []
    for token in selection:
        token = str(token).lower()
        if token == "total":
            if len(components) < 3:
                if warnings is not None:
                    warnings.append(
                        "Field {} has fewer than 3 components; skipped total CSV export.".format(
                            field_name
                        )
                    )
                continue
            items.append(("total", None, "{}_total".format(field_name)))
            continue

        index = int(token) - 1
        if 0 <= index < len(components):
            items.append(("component", index, components[index]))
        elif warnings is not None:
            warnings.append(
                "Field {} does not have component {}; skipped CSV export.".format(
                    field_name,
                    token,
                )
            )
    return items


def csv_total_values(real_values, imag_values):
    real = sum(float(value) ** 2 for value in real_values[:3]) ** 0.5
    imag = sum(float(value) ** 2 for value in imag_values[:3]) ** 0.5
    return real, imag


def save_node_set_csv(csv_path, arrays, metadata, csv_components=None):
    headers = [
        "frequency_index",
        "frequency",
        "instance",
        "node_label",
        "x",
        "y",
        "z",
        "field",
        "component",
        "real",
        "imag",
    ]
    warnings = metadata.setdefault("warnings", [])
    nodes = metadata.get("nodes", [])
    field_outputs = metadata.get("field_outputs", {})
    array_layouts = metadata.get("array_layouts", {})

    with _open_csv_for_write(csv_path) as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for field_name in metadata.get("fields", []):
            real_key = "{}_real".format(field_name)
            imag_key = "{}_imag".format(field_name)
            field_metadata = field_outputs.get(field_name, {})
            layout = field_metadata.get("array_layout") or array_layouts.get(real_key)
            if layout != ["frame", "node", "component"]:
                warnings.append(
                    "Field {} is not a node field; skipped CSV export.".format(
                        field_name
                    )
                )
                continue
            if real_key not in arrays or imag_key not in arrays:
                warnings.append(
                    "Field {} arrays are missing; skipped CSV export.".format(field_name)
                )
                continue

            real_data = arrays[real_key]
            imag_data = arrays[imag_key]
            components = field_metadata.get("components") or [
                "component_{}".format(index + 1)
                for index in range(real_data.shape[2])
            ]
            output_items = csv_component_items(
                field_name,
                components,
                None if csv_components is None else csv_components.get(field_name),
                warnings=warnings,
            )
            for frequency_index, frequency in enumerate(arrays["frequencies"]):
                for node_index, node in enumerate(nodes):
                    coordinates = list(node.get("coordinates", []))
                    coordinates.extend([0.0] * (3 - len(coordinates)))
                    for item_type, component_index, component in output_items:
                        if item_type == "total":
                            real, imag = csv_total_values(
                                real_data[frequency_index, node_index],
                                imag_data[frequency_index, node_index],
                            )
                        else:
                            real = real_data[frequency_index, node_index, component_index]
                            imag = imag_data[frequency_index, node_index, component_index]
                        writer.writerow(
                            [
                                frequency_index,
                                float(frequency),
                                node.get("instance", ""),
                                int(node.get("label", arrays["node_labels"][node_index])),
                                float(coordinates[0]),
                                float(coordinates[1]),
                                float(coordinates[2]),
                                field_name,
                                component,
                                float(real),
                                float(imag),
                            ]
                        )


def build_metadata(
    odb_path,
    step_name,
    fields,
    nodes,
    arrays,
    extraction_metadata,
    filters=None,
    command_options=None,
):
    metadata = {
        "tool": {
            "name": TOOL_NAME,
            "metadata_schema_version": METADATA_SCHEMA_VERSION,
        },
        "source_odb": os.path.abspath(odb_path),
        "step": step_name,
        "fields": list(fields),
        "generated_at": _now_iso_seconds(),
        "node_count": len(nodes),
        "nodes": [
            {
                "instance": node.instance_name,
                "label": int(node.label),
                "coordinates": [float(value) for value in node.coordinates],
            }
            for node in nodes
        ],
        "node_labels": [int(label) for label in arrays["node_labels"].tolist()],
        "node_coordinates": [
            [float(value) for value in row] for row in arrays["node_coordinates"].tolist()
        ],
        "frequencies": [float(value) for value in arrays["frequencies"].tolist()],
        "array_shapes": extraction_metadata["array_shapes"],
        "array_layouts": extraction_metadata.get("array_layouts", {}),
        "field_outputs": extraction_metadata.get("field_outputs", {}),
        "filters": filters or {},
        "command_options": dict(command_options or {}),
        "warnings": extraction_metadata["warnings"],
    }
    return metadata


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


def run(args):
    odb = open_odb_readonly(args.odb)
    try:
        step_name = choose_step_name(odb, args.step)
        step = odb.steps[step_name]
        node_labels = parse_node_label_values(args.node_labels)
        node_set_warnings = []
        nodes = collect_nodes(
            odb,
            instances=args.instances,
            node_labels=node_labels,
            node_set_names=args.node_sets,
            warnings=node_set_warnings,
        )
        arrays, extraction_metadata = extract_field_arrays(
            step,
            nodes,
            args.fields,
            frequency_min=args.frequency_min,
            frequency_max=args.frequency_max,
        )
        filters = {
            "instances": list(args.instances or []),
            "node_labels": list(node_labels or []),
            "node_sets": list(args.node_sets or []),
            "frequency_min": args.frequency_min,
            "frequency_max": args.frequency_max,
        }
        csv_output = args.csv_output
        if args.node_sets and not csv_output:
            csv_output = default_csv_output_path(args.output)
        command_options = {
            "odb": args.odb,
            "output": args.output,
            "metadata": args.metadata,
            "csv_output": csv_output,
            "csv_components": list(args.csv_components or []),
            "step": args.step,
            "fields": list(args.fields or []),
            "instances": list(args.instances or []),
            "node_labels": list(node_labels or []),
            "node_sets": list(args.node_sets or []),
            "frequency_min": args.frequency_min,
            "frequency_max": args.frequency_max,
        }
        metadata = build_metadata(
            args.odb,
            step_name,
            args.fields,
            nodes,
            arrays,
            extraction_metadata,
            filters=filters,
            command_options=command_options,
        )
        extraction_metadata["warnings"].extend(node_set_warnings)
        save_npz(args.output, arrays)
        if csv_output:
            save_node_set_csv(
                csv_output,
                arrays,
                metadata,
                csv_components=parse_csv_component_specs(args.csv_components),
            )
        save_metadata(args.metadata, metadata)
    finally:
        odb.close()
    print("Saved NPZ: {}".format(args.output))
    if csv_output:
        print("Saved CSV: {}".format(csv_output))
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


if __name__ == "__main__":
    sys.exit(main())
