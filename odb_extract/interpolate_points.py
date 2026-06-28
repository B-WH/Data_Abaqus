"""Interpolate exported Abaqus ODB node-field data at requested coordinates."""

from __future__ import print_function

import argparse
import csv
import json
import os
import sys

import numpy as np


OUTPUT_COLUMNS = [
    "point_id",
    "x",
    "y",
    "z",
    "frequency",
    "field",
    "component",
    "real",
    "imag",
    "method",
    "neighbor_labels",
    "neighbor_weights",
    "neighbor_distances",
]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Interpolate extracted Abaqus ODB node data at coordinate points."
    )
    parser.add_argument("--data", required=True, help="Input NPZ from Extract_data_ODB.py.")
    parser.add_argument("--metadata", required=True, help="Input metadata JSON.")
    parser.add_argument("--points", required=True, help="CSV containing point_id,x,y,z rows.")
    parser.add_argument("--output", required=True, help="Output CSV path.")
    parser.add_argument("--fields", nargs="+", default=None, help="Optional field names.")
    parser.add_argument("--neighbors", type=int, default=4, help="Neighbor count for interpolation.")
    parser.add_argument(
        "--exact-tol",
        type=float,
        default=1.0e-9,
        help="Distance tolerance for treating a query point as an exact node hit.",
    )
    return parser.parse_args(argv)


def load_metadata(path):
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(stream)


def ensure_parent_dir(path):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)


def _float_text(value):
    return "{:.17g}".format(float(value))


def _joined_float_text(values):
    return ";".join(_float_text(value) for value in values)


def read_query_points(path):
    points = []
    with open(path, newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames or []
        missing = [name for name in ("x", "y", "z") if name not in fieldnames]
        if missing:
            raise ValueError("Point CSV is missing required column(s): {}".format(", ".join(missing)))
        for row_index, row in enumerate(reader, start=1):
            point_id = (row.get("point_id") or "").strip() or str(row_index)
            points.append(
                {
                    "point_id": point_id,
                    "coordinates": np.asarray(
                        [float(row["x"]), float(row["y"]), float(row["z"])],
                        dtype=float,
                    ),
                }
            )
    return points


def _node_coordinate_lookup(data, metadata):
    if "node_coordinates" not in data:
        raise ValueError(
            "NPZ does not contain node_coordinates. Re-run Extract_data_ODB.py with the updated extractor."
        )
    coordinates = np.asarray(data["node_coordinates"], dtype=float)
    nodes = metadata.get("nodes") or []
    if len(nodes) != len(coordinates):
        raise ValueError(
            "Metadata nodes count ({}) does not match node_coordinates rows ({}).".format(
                len(nodes),
                len(coordinates),
            )
        )
    lookup = {}
    for index, node in enumerate(nodes):
        key = (node.get("instance", ""), int(node.get("label")))
        lookup[key] = coordinates[index]
    return lookup


def _available_fields(metadata):
    field_outputs = metadata.get("field_outputs") or {}
    if field_outputs:
        return sorted(field_outputs.keys())
    return sorted(metadata.get("fields") or [])


def _available_node_fields(metadata):
    field_outputs = metadata.get("field_outputs") or {}
    if not field_outputs:
        return _available_fields(metadata)
    return sorted(
        field_name
        for field_name, field_metadata in field_outputs.items()
        if field_metadata.get("location") == "NODE"
    )


def _validate_field(metadata, field_name):
    field_outputs = metadata.get("field_outputs") or {}
    field_metadata = field_outputs.get(field_name)
    if field_metadata is None:
        raise ValueError("Field {} is not present in metadata.".format(field_name))
    if field_metadata.get("location") != "NODE":
        raise ValueError("Field {} is not a node field.".format(field_name))
    return field_metadata


def _coordinates_for_field(field_metadata, coordinate_lookup):
    coordinates = []
    labels = []
    for point in field_metadata.get("points") or []:
        key = (point.get("instance", ""), int(point.get("node_label")))
        if key not in coordinate_lookup:
            raise ValueError(
                "Node coordinates are missing for instance {} node {}.".format(
                    key[0],
                    key[1],
                )
            )
        labels.append(int(key[1]))
        coordinates.append(coordinate_lookup[key])
    if not coordinates:
        raise ValueError("Field has no node points to interpolate.")
    return np.asarray(coordinates, dtype=float), np.asarray(labels, dtype=np.int64)


def _neighbor_weights(node_coordinates, query_coordinates, neighbors, exact_tol):
    if neighbors < 1:
        raise ValueError("--neighbors must be at least 1.")
    distances = np.linalg.norm(node_coordinates - query_coordinates, axis=1)
    nearest_order = np.argsort(distances)
    nearest_index = int(nearest_order[0])
    if float(distances[nearest_index]) <= exact_tol:
        return (
            np.asarray([nearest_index], dtype=np.int64),
            np.asarray([1.0], dtype=float),
            np.asarray([float(distances[nearest_index])], dtype=float),
            "exact",
        )

    count = min(int(neighbors), len(nearest_order))
    indices = nearest_order[:count].astype(np.int64)
    selected_distances = distances[indices].astype(float)
    inverse_distances = 1.0 / selected_distances
    weights = inverse_distances / np.sum(inverse_distances)
    return indices, weights, selected_distances, "weighted"


def _weighted_values(values, indices, weights):
    return np.tensordot(values[:, indices, :], weights, axes=([1], [0]))


def _write_rows(output_path, rows):
    ensure_parent_dir(output_path)
    with open(output_path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def interpolate_files(
    data_path,
    metadata_path,
    points_path,
    output_path,
    fields=None,
    neighbors=4,
    exact_tol=1.0e-9,
):
    metadata = load_metadata(metadata_path)
    data = np.load(data_path)
    requested_fields = list(fields if fields is not None else _available_node_fields(metadata))
    field_metadata_by_name = {
        field_name: _validate_field(metadata, field_name) for field_name in requested_fields
    }
    coordinate_lookup = _node_coordinate_lookup(data, metadata)
    query_points = read_query_points(points_path)
    frequencies = np.asarray(data["frequencies"], dtype=float)
    rows = []

    for field_name in requested_fields:
        field_metadata = field_metadata_by_name[field_name]
        node_coordinates, node_labels = _coordinates_for_field(field_metadata, coordinate_lookup)
        components = field_metadata.get("components") or [
            "component_{}".format(index + 1) for index in range(data["{}_real".format(field_name)].shape[2])
        ]
        real_data = np.asarray(data["{}_real".format(field_name)], dtype=float)
        imag_data = np.asarray(data["{}_imag".format(field_name)], dtype=float)

        for point in query_points:
            indices, weights, distances, method = _neighbor_weights(
                node_coordinates,
                point["coordinates"],
                neighbors,
                exact_tol,
            )
            real_values = _weighted_values(real_data, indices, weights)
            imag_values = _weighted_values(imag_data, indices, weights)
            neighbor_labels = node_labels[indices].tolist()
            for frame_index, frequency in enumerate(frequencies):
                for component_index, component in enumerate(components):
                    rows.append(
                        {
                            "point_id": point["point_id"],
                            "x": _float_text(point["coordinates"][0]),
                            "y": _float_text(point["coordinates"][1]),
                            "z": _float_text(point["coordinates"][2]),
                            "frequency": _float_text(frequency),
                            "field": field_name,
                            "component": str(component),
                            "real": _float_text(real_values[frame_index, component_index]),
                            "imag": _float_text(imag_values[frame_index, component_index]),
                            "method": method,
                            "neighbor_labels": ";".join(str(int(label)) for label in neighbor_labels),
                            "neighbor_weights": _joined_float_text(weights),
                            "neighbor_distances": _joined_float_text(distances),
                        }
                    )

    _write_rows(output_path, rows)
    return rows


def main(argv=None):
    args = parse_args(argv)
    try:
        interpolate_files(
            data_path=args.data,
            metadata_path=args.metadata,
            points_path=args.points,
            output_path=args.output,
            fields=args.fields,
            neighbors=args.neighbors,
            exact_tol=args.exact_tol,
        )
    except (OSError, KeyError, ValueError) as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
