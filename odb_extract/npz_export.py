"""Inspect project NPZ files and export field magnitudes to CSV."""

from __future__ import print_function

import csv
import json
import os
import tempfile

import numpy as np


COMMON_COLUMNS = ("frequency", "field", "component")
VALUE_COLUMN = "magnitude"
IDENTITY_COLUMNS = {
    "NODE": ("instance", "node_label", "x", "y", "z"),
    "POINT": ("point_id", "x", "y", "z"),
    "ELEMENT": (
        "instance",
        "element_label",
        "integration_point",
        "section_point",
    ),
    "VALUE": ("instance", "value_index"),
}
IDENTITY_COLUMN_ORDER = (
    "instance",
    "node_label",
    "point_id",
    "element_label",
    "integration_point",
    "section_point",
    "value_index",
    "x",
    "y",
    "z",
)


def _metadata_path(data_path, metadata_path=None):
    if metadata_path is None:
        from odb_extract.launcher import metadata_path_for_output

        metadata_path = metadata_path_for_output(data_path)
    return os.path.abspath(metadata_path)


def _load_metadata(data_path, metadata_path=None):
    resolved = _metadata_path(data_path, metadata_path)
    if not os.path.isfile(resolved):
        raise ValueError("Metadata JSON does not exist: {}".format(resolved))
    try:
        with open(resolved, "r", encoding="utf-8") as stream:
            metadata = json.load(stream)
    except (OSError, ValueError) as exc:
        raise ValueError("Cannot read metadata JSON {}: {}".format(resolved, exc))
    if not isinstance(metadata, dict):
        raise ValueError("Metadata JSON must contain an object: {}".format(resolved))
    return resolved, metadata


def inspect_source(data_path, metadata_path=None, preview_count=8):
    """Return field names and compact per-array summaries."""
    data_path = os.path.abspath(data_path)
    resolved_metadata, metadata = _load_metadata(data_path, metadata_path)
    summaries = {}
    try:
        with np.load(data_path) as data:
            for name in sorted(data.files):
                values = np.asarray(data[name])
                nan_count = (
                    int(np.isnan(values).sum())
                    if np.issubdtype(values.dtype, np.inexact)
                    else 0
                )
                summaries[name] = {
                    "shape": list(values.shape),
                    "dtype": str(values.dtype),
                    "size": int(values.size),
                    "nan_count": nan_count,
                    "preview": values.reshape(-1)[: int(preview_count)].tolist(),
                }
    except (OSError, ValueError) as exc:
        raise ValueError("Cannot read NPZ {}: {}".format(data_path, exc))
    fields = sorted((metadata.get("field_outputs") or {}).keys())
    return {
        "data_path": data_path,
        "metadata_path": resolved_metadata,
        "fields": fields,
        "arrays": summaries,
    }


def _normalize_selection(values):
    if values is None:
        return None
    return {str(value) for value in values}


def _node_identities(data, metadata, field_metadata, entity_count):
    nodes = metadata.get("nodes") or []
    points = field_metadata.get("points") or nodes
    if len(points) != entity_count:
        raise ValueError("NODE identity count does not match field shape.")

    coordinates = None
    if "node_coordinates" in data:
        coordinates = np.asarray(data["node_coordinates"])
    coordinate_lookup = {}
    for index, node in enumerate(nodes):
        label = node.get("node_label", node.get("label"))
        coordinate = node.get("coordinates")
        if coordinate is None and coordinates is not None and index < len(coordinates):
            coordinate = coordinates[index]
        if label is not None and coordinate is not None:
            coordinate_lookup[(node.get("instance"), int(label))] = coordinate

    identities = []
    for index, point in enumerate(points):
        label = point.get("node_label", point.get("label"))
        if label is None:
            raise ValueError("NODE identity is missing node_label.")
        instance = point.get("instance")
        coordinate = point.get("coordinates")
        if coordinate is None:
            coordinate = coordinate_lookup.get((instance, int(label)))
        if coordinate is None and coordinates is not None and len(points) == len(coordinates):
            coordinate = coordinates[index]
        if coordinate is None or len(coordinate) < 3:
            raise ValueError("NODE identity is missing coordinates.")
        identities.append(
            {
                "instance": instance,
                "node_label": int(label),
                "x": float(coordinate[0]),
                "y": float(coordinate[1]),
                "z": float(coordinate[2]),
            }
        )
    return identities


def _point_identities(data, metadata, entity_count):
    points = metadata.get("points") or []
    point_ids = np.asarray(data["point_ids"]) if "point_ids" in data else None
    coordinates = (
        np.asarray(data["point_coordinates"])
        if "point_coordinates" in data
        else None
    )
    if points and len(points) != entity_count:
        raise ValueError("POINT identity count does not match field shape.")
    if not points and (point_ids is None or coordinates is None):
        raise ValueError("POINT identities are missing.")

    identities = []
    for index in range(entity_count):
        point = points[index] if points else {}
        point_id = point.get("point_id")
        if point_id is None and point_ids is not None:
            point_id = point_ids[index].item()
        coordinate = point.get("coordinates")
        if coordinate is None and coordinates is not None:
            coordinate = coordinates[index]
        if point_id is None or coordinate is None or len(coordinate) < 3:
            raise ValueError("POINT identity is incomplete.")
        identities.append(
            {
                "point_id": point_id,
                "x": float(coordinate[0]),
                "y": float(coordinate[1]),
                "z": float(coordinate[2]),
            }
        )
    return identities


def _element_identities(field_metadata, entity_count):
    points = field_metadata.get("points") or []
    if len(points) != entity_count:
        raise ValueError("ELEMENT identity count does not match field shape.")
    identities = []
    for point in points:
        label = point.get("element_label")
        if label is None:
            raise ValueError("ELEMENT identity is missing element_label.")
        identities.append(
            {
                "instance": point.get("instance"),
                "element_label": int(label),
                "integration_point": point.get("integration_point"),
                "section_point": point.get("section_point"),
            }
        )
    return identities


def _value_identities(field_metadata, entity_count):
    points = field_metadata.get("points") or []
    if len(points) != entity_count:
        raise ValueError("VALUE identity count does not match field shape.")
    identities = []
    for point in points:
        value_index = point.get("value_index")
        if value_index is None:
            raise ValueError("VALUE identity is missing value_index.")
        identities.append(
            {"instance": point.get("instance"), "value_index": int(value_index)}
        )
    return identities


def _field_identities(data, metadata, field_metadata, entity_count):
    location = str(field_metadata.get("location") or "VALUE").upper()
    if location == "NODE":
        return location, _node_identities(
            data, metadata, field_metadata, entity_count
        )
    if location == "POINT":
        return location, _point_identities(data, metadata, entity_count)
    if location in ("ELEMENT", "INTEGRATION_POINT"):
        return "ELEMENT", _element_identities(field_metadata, entity_count)
    return "VALUE", _value_identities(field_metadata, entity_count)


def _primary_identity(identity):
    for name in ("node_label", "point_id", "element_label", "value_index"):
        if identity.get(name) is not None:
            return str(identity[name])
    return ""


def _prepare_export(
    data,
    metadata,
    fields=None,
    components=None,
    frequency_min=None,
    frequency_max=None,
    entity_ids=None,
):
    if "frequencies" not in data:
        raise ValueError("NPZ is missing frequencies.")
    frequencies = np.asarray(data["frequencies"], dtype=float)
    if frequencies.ndim != 1:
        raise ValueError("frequencies must be one-dimensional.")
    frame_indexes = [
        index
        for index, frequency in enumerate(frequencies)
        if (frequency_min is None or frequency >= frequency_min)
        and (frequency_max is None or frequency <= frequency_max)
    ]

    field_outputs = metadata.get("field_outputs") or {}
    selected_fields = list(fields) if fields is not None else sorted(field_outputs)
    if not selected_fields:
        raise ValueError("At least one field is required.")
    component_filter = _normalize_selection(components)
    entity_filter = _normalize_selection(entity_ids)
    array_layouts = metadata.get("array_layouts") or {}
    specs = []
    for field_name in selected_fields:
        field_metadata = field_outputs.get(field_name)
        if not isinstance(field_metadata, dict):
            raise ValueError("Field {} is missing from metadata.".format(field_name))
        real_key = "{}_real".format(field_name)
        imag_key = "{}_imag".format(field_name)
        if real_key not in data or imag_key not in data:
            raise ValueError("Field {} is missing real or imaginary data.".format(field_name))
        real = np.asarray(data[real_key])
        imag = np.asarray(data[imag_key])
        if real.shape != imag.shape:
            raise ValueError(
                "Field {} real and imaginary shapes do not match.".format(field_name)
            )
        if real.ndim != 3 or real.shape[0] != len(frequencies):
            raise ValueError(
                "Field {} must use frame, entity, component shapes.".format(
                    field_name
                )
            )
        layout = array_layouts.get(real_key) or field_metadata.get("array_layout")
        if not layout or len(layout) != 3 or layout[0] != "frame" or layout[2] != "component":
            raise ValueError("Field {} has an unsupported array layout.".format(field_name))
        component_names = field_metadata.get("components") or [
            "component_{}".format(index + 1) for index in range(real.shape[2])
        ]
        if len(component_names) != real.shape[2]:
            raise ValueError("Field {} component count does not match shape.".format(field_name))
        component_indexes = [
            index
            for index, name in enumerate(component_names)
            if component_filter is None or str(name) in component_filter
        ]
        if not component_indexes:
            continue
        location, identities = _field_identities(
            data, metadata, field_metadata, real.shape[1]
        )
        entity_indexes = [
            index
            for index, identity in enumerate(identities)
            if entity_filter is None
            or _primary_identity(identity) in entity_filter
        ]
        specs.append(
            {
                "name": field_name,
                "location": location,
                "real": real,
                "imag": imag,
                "components": list(component_names),
                "component_indexes": component_indexes,
                "identities": identities,
                "entity_indexes": entity_indexes,
            }
        )
    if not specs:
        raise ValueError("No field components match the selection.")
    return frequencies, frame_indexes, specs


def _selected_columns(specs):
    used = set()
    for spec in specs:
        used.update(IDENTITY_COLUMNS[spec["location"]])
    identity_columns = [name for name in IDENTITY_COLUMN_ORDER if name in used]
    return list(COMMON_COLUMNS) + identity_columns + [VALUE_COLUMN]


def _iter_selected_rows(frequencies, frame_indexes, specs):
    for spec in specs:
        for frame_index in frame_indexes:
            for entity_index in spec["entity_indexes"]:
                identity = spec["identities"][entity_index]
                for component_index in spec["component_indexes"]:
                    row = {
                        "frequency": float(frequencies[frame_index]),
                        "field": spec["name"],
                        "component": spec["components"][component_index],
                        VALUE_COLUMN: float(
                            np.hypot(
                                spec["real"][frame_index, entity_index, component_index],
                                spec["imag"][frame_index, entity_index, component_index],
                            )
                        ),
                    }
                    row.update(identity)
                    yield row


def estimate_export_rows(
    data_path,
    metadata_path=None,
    fields=None,
    components=None,
    frequency_min=None,
    frequency_max=None,
    entity_ids=None,
):
    """Return the selected long-table row count."""
    _resolved_metadata, metadata = _load_metadata(data_path, metadata_path)
    with np.load(data_path) as data:
        _frequencies, frame_indexes, specs = _prepare_export(
            data,
            metadata,
            fields=fields,
            components=components,
            frequency_min=frequency_min,
            frequency_max=frequency_max,
            entity_ids=entity_ids,
        )
        return sum(
            len(frame_indexes)
            * len(spec["entity_indexes"])
            * len(spec["component_indexes"])
            for spec in specs
        )


def export_magnitude_csv(
    data_path,
    output_path,
    metadata_path=None,
    fields=None,
    components=None,
    frequency_min=None,
    frequency_max=None,
    entity_ids=None,
):
    """Atomically export selected complex-field magnitudes to CSV."""
    data_path = os.path.abspath(data_path)
    output_path = os.path.abspath(output_path)
    resolved_metadata, metadata = _load_metadata(data_path, metadata_path)
    if os.path.normcase(output_path) in {
        os.path.normcase(data_path),
        os.path.normcase(resolved_metadata),
    }:
        raise ValueError("CSV output must not overwrite NPZ or metadata input.")

    output_dir = os.path.dirname(output_path) or os.getcwd()
    os.makedirs(output_dir, exist_ok=True)
    temporary_path = None
    row_count = 0
    try:
        with np.load(data_path) as data:
            frequencies, frame_indexes, specs = _prepare_export(
                data,
                metadata,
                fields=fields,
                components=components,
                frequency_min=frequency_min,
                frequency_max=frequency_max,
                entity_ids=entity_ids,
            )
            descriptor, temporary_path = tempfile.mkstemp(
                prefix=".npz-export-", suffix=".csv", dir=output_dir
            )
            os.close(descriptor)
            with open(
                temporary_path, "w", newline="", encoding="utf-8-sig"
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=_selected_columns(specs))
                writer.writeheader()
                for row in _iter_selected_rows(frequencies, frame_indexes, specs):
                    writer.writerow(row)
                    row_count += 1
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path and os.path.isfile(temporary_path):
            os.remove(temporary_path)
    return {
        "output_path": output_path,
        "metadata_path": resolved_metadata,
        "row_count": row_count,
    }
