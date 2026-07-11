"""Extract nodal frequency-response data from an Abaqus ODB file.

Run with Abaqus Python, for example:
    abaqus python .\\odb_extract\\extractor.py --odb data\\test1.odb
"""

from __future__ import print_function

import argparse
import io
import importlib
import json
import os
import sys
import time
from collections import namedtuple
from datetime import datetime


DEFAULT_ODB = os.path.join("data", "test1.odb")
DEFAULT_OUTPUT = os.path.join("output", "test1_point_data.npz")
DEFAULT_METADATA = os.path.join("output", "test1_point_metadata.json")
DEFAULT_FIELDS = ("U", "UR", "V", "VR", "A", "AR")
TOOL_NAME = "odb_extract.extractor"
METADATA_SCHEMA_VERSION = 2

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
    parser.add_argument(
        "--inspect-odb",
        action="store_true",
        help="Print ODB structure summary as JSON and exit.",
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


def _log_elapsed(label, start_time, now=None):
    current_time = time.time() if now is None else now
    print("[timing] {}: {:.3f} s".format(label, current_time - start_time))
    sys.stdout.flush()
    return current_time


def _create_memmap_array(np, shape, dtype=float):
    """Create a temporary memory-mapped array to avoid large RAM allocations.

    Returns (array, temp_file_path).  The caller is responsible for
    deleting the temp file via _cleanup_memmap_files when done.
    """
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".dat", prefix="odb_extract_")
    os.close(fd)
    # np.memmap on Windows with Python 2 requires a unicode path
    if sys.version_info[0] < 3 and isinstance(path, bytes):
        path = path.decode(sys.getfilesystemencoding() or "utf-8")
    array = np.memmap(path, dtype=dtype, mode="w+", shape=shape)
    return array, path


def _cleanup_memmap_files(paths, arrays=None):
    """Delete temporary memmap backing files.

    Safe to call with an empty list or paths that no longer exist.
    """
    for array in (arrays or {}).values():
        mmap = getattr(array, "_mmap", None)
        if mmap is not None:
            try:
                mmap.close()
            except (OSError, ValueError):
                pass
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass


def _now_iso_seconds():
    return datetime.now().replace(microsecond=0).isoformat()


def ensure_parent_dir(path):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)


def parse_node_label_values(values):
    if not values:
        return None
    labels = []
    for value in values:
        for part in str(value).replace(",", " ").replace(";", " ").split():
            labels.append(int(part))
    return labels or None


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


def _mapping_keys(mapping):
    if mapping is None:
        return []
    return sorted(mapping.keys())


def _inspect_value_location(value):
    if hasattr(value, "nodeLabel"):
        return "NODE"
    if hasattr(value, "elementLabel"):
        if getattr(value, "integrationPoint", None) is not None:
            return "INTEGRATION_POINT"
        return "ELEMENT"
    return "VALUE"


def _inspect_field(step, field_name):
    component_labels = None
    location = "UNKNOWN"
    component_count = 0

    for frame in step.frames:
        if field_name not in frame.fieldOutputs:
            continue
        field = frame.fieldOutputs[field_name]
        labels = getattr(field, "componentLabels", None)
        if labels and component_labels is None:
            component_labels = [str(label) for label in labels]
        values = _get_field_values(field)
        if not len(values):
            continue
        value = values[0]
        location = _inspect_value_location(value)
        component_count = len(_value_data_tuple(value.data))
        break

    if component_labels is None:
        if component_count == 1:
            component_labels = [field_name]
        elif component_count:
            component_labels = [
                "component_{}".format(index + 1)
                for index in range(component_count)
            ]
        else:
            component_labels = []

    return {
        "location": location,
        "component_count": int(component_count or len(component_labels)),
        "components": component_labels,
    }


def _inspect_step(step):
    frame_values = [float(frame.frameValue) for frame in step.frames]
    fields = {}
    for field_name in collect_field_names(step):
        fields[field_name] = _inspect_field(step, field_name)

    history_regions = {}
    for region_name in _mapping_keys(getattr(step, "historyRegions", {})):
        region = step.historyRegions[region_name]
        history_regions[region_name] = _mapping_keys(
            getattr(region, "historyOutputs", {})
        )

    return {
        "frame_count": len(step.frames),
        "frame_value_range": [min(frame_values), max(frame_values)] if frame_values else [],
        "fields": fields,
        "history_regions": history_regions,
    }


def inspect_odb(odb, source_odb=None):
    assembly = odb.rootAssembly
    instances = {}
    for instance_name in _mapping_keys(getattr(assembly, "instances", {})):
        instance = assembly.instances[instance_name]
        instances[instance_name] = {
            "node_count": len(getattr(instance, "nodes", [])),
            "element_count": len(getattr(instance, "elements", [])),
        }

    metadata = {
        "source_odb": os.path.abspath(source_odb) if source_odb else None,
        "instances": instances,
        "node_sets": _mapping_keys(getattr(assembly, "nodeSets", {})),
        "element_sets": _mapping_keys(getattr(assembly, "elementSets", {})),
        "steps": {},
    }
    for step_name in _mapping_keys(getattr(odb, "steps", {})):
        metadata["steps"][step_name] = _inspect_step(odb.steps[step_name])
    return metadata


def _tuple_to_float_array(value):
    np = _numpy()
    return np.asarray(_value_data_tuple(value), dtype=float)


def _value_data_tuple(value):
    try:
        return tuple(value)
    except TypeError:
        return (value,)


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


def _bulk_block_array(np, values, row_count):
    array = np.asarray(values, dtype=float)
    if row_count == 0:
        return array.reshape((0, 0))
    if array.ndim == 1:
        if array.size % row_count:
            raise ValueError("Bulk field data size does not match node labels.")
        array = array.reshape((row_count, array.size // row_count))
    if array.ndim != 2 or array.shape[0] != row_count:
        raise ValueError("Bulk field data shape does not match node labels.")
    return array


def _bulk_node_field_info(field):
    blocks = getattr(field, "bulkDataBlocks", None)
    if blocks is None:
        return None
    np = _numpy()
    component_count = None
    labels = []
    try:
        for block in blocks:
            if str(getattr(block, "position", "")) != "NODAL":
                return None
            node_labels = getattr(block, "nodeLabels", None)
            if node_labels is None:
                return None
            if not len(node_labels):
                continue
            data = _bulk_block_array(np, block.data, len(node_labels))
            component_labels = getattr(field, "componentLabels", None)
            if not component_labels:
                component_labels = getattr(block, "componentLabels", None)
            if component_labels and len(component_labels) != data.shape[1]:
                return None
            raw_imag = getattr(block, "conjugateData", None)
            if raw_imag is not None and len(raw_imag):
                imag = _bulk_block_array(np, raw_imag, len(node_labels))
                if imag.shape[1] != data.shape[1]:
                    return None
            if component_count is None:
                component_count = data.shape[1]
                labels = [str(label) for label in (component_labels or [])]
            elif data.shape[1] != component_count:
                return None
    except Exception:
        return None
    if component_count is None:
        return None
    return component_count, labels


def _collect_field_metadata(step, fields, nodes, frequency_min, frequency_max):
    """Collect field metadata without scanning every nodal value twice."""
    np = _numpy()
    filtered_frames = []
    freq_values = []
    for frame in step.frames:
        freq = float(frame.frameValue)
        if frequency_min is not None and freq < frequency_min:
            continue
        if frequency_max is not None and freq > frequency_max:
            continue
        filtered_frames.append(frame)
        freq_values.append(freq)

    frequencies = np.asarray(freq_values, dtype=float)
    field_locations = {}
    field_max_components = {}
    field_raw_labels = {}
    field_point_sets = {field_name: set() for field_name in fields}

    for field_name in fields:
        first_frame_index = None
        first_values = None
        for frame_index, frame in enumerate(filtered_frames):
            if field_name not in frame.fieldOutputs:
                continue
            field = frame.fieldOutputs[field_name]
            bulk_info = _bulk_node_field_info(field)
            if bulk_info is not None:
                component_count, labels = bulk_info
                first_frame_index = frame_index
                field_locations[field_name] = "NODE"
                field_max_components[field_name] = component_count
                if labels:
                    field_raw_labels[field_name] = labels
                break
            values = _get_field_values(field)
            if not len(values):
                continue
            first_frame_index = frame_index
            first_values = values
            field_locations[field_name] = _field_value_key(values[0])[0]
            field_max_components[field_name] = len(
                _value_data_tuple(values[0].data)
            )
            labels = getattr(field, "componentLabels", None)
            if labels:
                field_raw_labels[field_name] = [str(label) for label in labels]
            break

        if field_locations.get(field_name, "NODE") == "NODE":
            continue

        for frame_index, frame in enumerate(filtered_frames):
            if field_name not in frame.fieldOutputs:
                continue
            if frame_index == first_frame_index:
                values = first_values
            else:
                values = _get_field_values(frame.fieldOutputs[field_name])
            for ordinal, value in enumerate(values):
                field_point_sets[field_name].add(_field_value_key(value, ordinal))
                field_max_components[field_name] = max(
                    field_max_components.get(field_name, 0),
                    len(_value_data_tuple(value.data)),
                )

    default_component_count = (
        max(field_max_components.values()) if field_max_components else 0
    )

    field_meta = {}
    point_keys_map = {}
    point_indexes = {}

    for field_name in fields:
        location = field_locations.get(field_name, "NODE")
        component_count = (
            field_max_components.get(field_name, 0) or default_component_count
        )

        raw_labels = field_raw_labels.get(field_name)
        if raw_labels and len(raw_labels) == component_count:
            components = raw_labels
        elif component_count == 1:
            components = [field_name]
        else:
            components = [
                "component_{}".format(i + 1) for i in range(component_count)
            ]

        field_meta[field_name] = {
            "location": location,
            "component_count": component_count,
            "components": components,
        }

        if location == "NODE":
            point_keys = [_node_key(node) for node in nodes]
        else:
            point_keys = sorted(field_point_sets[field_name], key=_sort_key)

        point_keys_map[field_name] = point_keys
        point_indexes[field_name] = {k: i for i, k in enumerate(point_keys)}

    return filtered_frames, frequencies, field_meta, point_keys_map, point_indexes


def _fill_node_field_from_bulk(
    np,
    field,
    frame_index,
    point_index,
    component_count,
    real_data,
    imag_data,
):
    blocks = getattr(field, "bulkDataBlocks", None)
    if blocks is None:
        return None
    prepared = []
    try:
        for block in blocks:
            if str(getattr(block, "position", "")) != "NODAL":
                return None
            labels = getattr(block, "nodeLabels", None)
            if labels is None:
                return None
            block_real = _bulk_block_array(np, block.data, len(labels))
            if block_real.shape[1] != component_count:
                return None
            component_labels = getattr(field, "componentLabels", None)
            if not component_labels:
                component_labels = getattr(block, "componentLabels", None)
            if component_labels and len(component_labels) != component_count:
                return None
            raw_imag = getattr(block, "conjugateData", None)
            if raw_imag is None or not len(raw_imag):
                block_imag = np.zeros(block_real.shape, dtype=float)
            else:
                block_imag = _bulk_block_array(np, raw_imag, len(labels))
            if block_imag.shape[1] != component_count:
                return None
            instance_name = getattr(getattr(block, "instance", None), "name", "")
            rows = []
            outputs = []
            keys = []
            for row_index, label in enumerate(labels):
                key = ("NODE", instance_name, int(label))
                output_index = point_index.get(key)
                if output_index is None:
                    continue
                rows.append(row_index)
                outputs.append(output_index)
                keys.append(key)
            prepared.append((rows, outputs, keys, block_real, block_imag))
    except Exception:
        return None

    seen = set()
    for rows, outputs, keys, block_real, block_imag in prepared:
        if not rows:
            continue
        real_data[frame_index, outputs, :] = block_real[rows, :]
        imag_data[frame_index, outputs, :] = block_imag[rows, :]
        seen.update(keys)
    return seen


def extract_field_arrays(step, nodes, fields, frequency_min=None, frequency_max=None):
    np = _numpy()

    frames, frequencies, field_meta, point_keys_map, point_indexes = (
        _collect_field_metadata(step, fields, nodes, frequency_min, frequency_max)
    )

    node_labels = np.asarray([node.label for node in nodes], dtype=np.int64)
    node_coordinates = np.asarray([node.coordinates for node in nodes], dtype=float)
    warnings = []
    memmap_files = []  # type: list

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
        "_memmap_files": memmap_files,
    }

    for field_name in fields:
        meta = field_meta[field_name]
        location = meta["location"]
        point_keys = point_keys_map[field_name]
        point_index = point_indexes[field_name]
        component_count = meta["component_count"]
        components = meta["components"]
        array_layout = _array_layout_for_location(location)
        real_key = "{}_real".format(field_name)
        imag_key = "{}_imag".format(field_name)

        field_shape = (len(frames), len(point_keys), component_count)
        real_data, real_tmp = _create_memmap_array(np, field_shape)
        imag_data, imag_tmp = _create_memmap_array(np, field_shape)
        real_data.fill(np.nan)
        imag_data.fill(np.nan)
        memmap_files.extend([real_tmp, imag_tmp])

        for frame_index, frame in enumerate(frames):
            if field_name not in frame.fieldOutputs:
                warnings.append(
                    "Field {} is missing from frame {} at frameValue {}.".format(
                        field_name, frame_index, frame.frameValue
                    )
                )
                continue

            field = frame.fieldOutputs[field_name]
            seen = None
            if location == "NODE":
                seen = _fill_node_field_from_bulk(
                    np,
                    field,
                    frame_index,
                    point_index,
                    component_count,
                    real_data,
                    imag_data,
                )
            if seen is None:
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
    total_start = time.time()
    stage_start = total_start
    odb = open_odb_readonly(args.odb)
    stage_start = _log_elapsed("open ODB", stage_start)
    memmap_files = []
    arrays = {}
    try:
        step_name = choose_step_name(odb, args.step)
        step = odb.steps[step_name]
        stage_start = _log_elapsed("choose step", stage_start)
        node_labels = parse_node_label_values(args.node_labels)
        node_set_warnings = []
        nodes = collect_nodes(
            odb,
            instances=args.instances,
            node_labels=node_labels,
            node_set_names=args.node_sets,
            warnings=node_set_warnings,
        )
        stage_start = _log_elapsed("collect nodes", stage_start)
        arrays, extraction_metadata = extract_field_arrays(
            step,
            nodes,
            args.fields,
            frequency_min=args.frequency_min,
            frequency_max=args.frequency_max,
        )
        stage_start = _log_elapsed("extract field arrays", stage_start)
        memmap_files = extraction_metadata.get("_memmap_files", [])
        filters = {
            "instances": list(args.instances or []),
            "node_labels": list(node_labels or []),
            "node_sets": list(args.node_sets or []),
            "frequency_min": args.frequency_min,
            "frequency_max": args.frequency_max,
        }
        command_options = {
            "odb": args.odb,
            "output": args.output,
            "metadata": args.metadata,
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
        stage_start = _log_elapsed("build metadata", stage_start)
        save_npz(args.output, arrays)
        stage_start = _log_elapsed("save NPZ", stage_start)
        save_metadata(args.metadata, metadata)
        stage_start = _log_elapsed("save metadata", stage_start)
    finally:
        odb.close()
        _cleanup_memmap_files(memmap_files, arrays)
    print("Saved NPZ: {}".format(args.output))
    print("Saved metadata: {}".format(args.metadata))
    if metadata["warnings"]:
        print("Warnings: {}".format(len(metadata["warnings"])))
    _log_elapsed("total", total_start)
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


def run_inspect_odb(args):
    odb = open_odb_readonly(args.odb)
    try:
        metadata = inspect_odb(odb, source_odb=args.odb)
    finally:
        odb.close()
    print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
    return metadata


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.inspect_odb:
            run_inspect_odb(args)
        elif args.list_fields:
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
    except Exception as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
