import csv
import json
import os
import sys
import unittest

import numpy as np
from openpyxl import Workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from odb_extract import interpolate_points as interp


class InterpolateOdbPointsTests(unittest.TestCase):
    def setUp(self):
        self.work_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "output",
            "interpolate_unit_test",
            self._testMethodName,
        )
        if not os.path.isdir(self.work_dir):
            os.makedirs(self.work_dir)
        self.data_path = os.path.join(self.work_dir, "sample.npz")
        self.metadata_path = os.path.join(self.work_dir, "sample_metadata.json")
        self.points_path = os.path.join(self.work_dir, "points.csv")
        self.xlsx_points_path = os.path.join(self.work_dir, "points.xlsx")
        self.output_path = os.path.join(self.work_dir, "result_point_data.npz")
        self.metadata_output_path = os.path.join(
            self.work_dir, "result_point_metadata.json"
        )
        self._write_sample_inputs()

    def _write_sample_inputs(self):
        np.savez_compressed(
            self.data_path,
            frequencies=np.array([5.0]),
            node_labels=np.array([1, 2, 3, 4]),
            node_coordinates=np.array(
                [
                    [0.0, 0.0, 0.0],
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                    [0.0, 0.0, 1.0],
                ],
                dtype=float,
            ),
            U_real=np.array([[[10.0], [20.0], [30.0], [40.0]]]),
            U_imag=np.array([[[1.0], [2.0], [3.0], [4.0]]]),
            V_real=np.array([[[100.0], [200.0], [300.0], [400.0]]]),
            V_imag=np.array([[[0.0], [0.0], [0.0], [0.0]]]),
            S_real=np.array([[[7.0]]]),
            S_imag=np.array([[[0.0]]]),
            node_set_0000_indices=np.array([0], dtype=np.int64),
            node_set_0001_indices=np.array([1], dtype=np.int64),
            node_set_0002_indices=np.array([2], dtype=np.int64),
        )
        metadata = {
            "fields": ["U", "V", "S"],
            "frequencies": [5.0],
            "nodes": [
                {"instance": "PART-1-1", "label": 1, "coordinates": [0.0, 0.0, 0.0]},
                {"instance": "PART-1-1", "label": 2, "coordinates": [1.0, 0.0, 0.0]},
                {"instance": "PART-1-1", "label": 3, "coordinates": [0.0, 1.0, 0.0]},
                {"instance": "PART-1-1", "label": 4, "coordinates": [0.0, 0.0, 1.0]},
            ],
            "array_layouts": {
                "frequencies": ["frame"],
                "node_labels": ["node"],
                "node_coordinates": ["node", "coordinate"],
                "U_real": ["frame", "node", "component"],
                "U_imag": ["frame", "node", "component"],
                "V_real": ["frame", "node", "component"],
                "V_imag": ["frame", "node", "component"],
                "S_real": ["frame", "element_point", "component"],
                "S_imag": ["frame", "element_point", "component"],
            },
            "field_outputs": {
                "U": {
                    "location": "NODE",
                    "components": ["U1"],
                    "points": [
                        {"instance": "PART-1-1", "node_label": 1},
                        {"instance": "PART-1-1", "node_label": 2},
                        {"instance": "PART-1-1", "node_label": 3},
                        {"instance": "PART-1-1", "node_label": 4},
                    ],
                },
                "V": {
                    "location": "NODE",
                    "components": ["V1"],
                    "points": [
                        {"instance": "PART-1-1", "node_label": 1},
                        {"instance": "PART-1-1", "node_label": 2},
                        {"instance": "PART-1-1", "node_label": 3},
                        {"instance": "PART-1-1", "node_label": 4},
                    ],
                },
                "S": {
                    "location": "ELEMENT",
                    "components": ["S11"],
                    "points": [{"instance": "PART-1-1", "element_label": 1}],
                },
            },
            "node_sets": {
                "SET_ORIGIN": {"indices_key": "node_set_0000_indices", "member_count": 1},
                "SET_RIGHT": {"indices_key": "node_set_0001_indices", "member_count": 1},
                "SET_UP": {"indices_key": "node_set_0002_indices", "member_count": 1},
            },
        }
        with open(self.metadata_path, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream)

    def _write_three_component_v_inputs(self):
        np.savez_compressed(
            self.data_path,
            frequencies=np.array([5.0]),
            node_labels=np.array([1]),
            node_coordinates=np.array([[0.0, 0.0, 0.0]], dtype=float),
            V_real=np.array([[[3.0, 4.0, 12.0]]]),
            V_imag=np.array([[[1.0, 2.0, 2.0]]]),
        )
        metadata = {
            "fields": ["V"],
            "frequencies": [5.0],
            "nodes": [
                {"instance": "PART-1-1", "label": 1, "coordinates": [0.0, 0.0, 0.0]},
            ],
            "array_layouts": {
                "frequencies": ["frame"],
                "node_labels": ["node"],
                "node_coordinates": ["node", "coordinate"],
                "V_real": ["frame", "node", "component"],
                "V_imag": ["frame", "node", "component"],
            },
            "field_outputs": {
                "V": {
                    "location": "NODE",
                    "components": ["V1", "V2", "V3"],
                    "points": [{"instance": "PART-1-1", "node_label": 1}],
                },
            },
        }
        with open(self.metadata_path, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream)

    def _write_points(self, rows):
        with open(self.points_path, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["point_id", "x", "y", "z"])
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _write_xlsx_points(self, rows):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["point_id", "x", "y", "z"])
        for row in rows:
            sheet.append([row.get("point_id"), row["x"], row["y"], row["z"]])
        workbook.save(self.xlsx_points_path)

    def _read_outputs(self):
        data = np.load(self.output_path)
        with open(self.metadata_output_path, "r", encoding="utf-8") as stream:
            metadata = json.load(stream)
        return data, metadata

    def test_exact_coordinate_uses_matching_node_value(self):
        self._write_points([{"point_id": "p1", "x": "1.0", "y": "0.0", "z": "0.0"}])

        code = interp.main(
            [
                "--data",
                self.data_path,
                "--metadata",
                self.metadata_path,
                "--points",
                self.points_path,
                "--output",
                self.output_path,
                "--metadata-output",
                self.metadata_output_path,
                "--fields",
                "U",
            ]
        )

        self.assertEqual(code, 0)
        data, metadata = self._read_outputs()
        self.assertEqual(data["point_ids"].tolist(), ["p1"])
        self.assertEqual(data["point_coordinates"].tolist(), [[1.0, 0.0, 0.0]])
        self.assertEqual(data["frequencies"].tolist(), [5.0])
        self.assertEqual(data["U_real"].shape, (1, 1, 1))
        self.assertEqual(float(data["U_real"][0, 0, 0]), 20.0)
        self.assertEqual(float(data["U_imag"][0, 0, 0]), 2.0)
        self.assertEqual(metadata["array_layouts"]["U_real"], ["frame", "point", "component"])
        self.assertEqual(metadata["points"][0]["method"], "exact")
        self.assertEqual(metadata["points"][0]["neighbor_labels"], [2])
        self.assertEqual(metadata["points"][0]["neighbor_weights"], [1.0])
        self.assertEqual(metadata["points"][0]["fields"]["U"]["neighbor_labels"], [2])

    def test_non_node_coordinate_uses_inverse_distance_neighbors(self):
        self._write_points([{"point_id": "p2", "x": "0.25", "y": "0.25", "z": "0.25"}])

        interp.interpolate_files(
            data_path=self.data_path,
            metadata_path=self.metadata_path,
            points_path=self.points_path,
            output_path=self.output_path,
            metadata_output_path=self.metadata_output_path,
            fields=["U"],
        )

        data, metadata = self._read_outputs()
        distances = np.array([0.4330127018922193, 0.82915619758885, 0.82915619758885, 0.82915619758885])
        weights = (1.0 / distances) / np.sum(1.0 / distances)
        expected_real = float(np.dot(weights, np.array([10.0, 20.0, 30.0, 40.0])))
        expected_imag = float(np.dot(weights, np.array([1.0, 2.0, 3.0, 4.0])))

        self.assertEqual(metadata["points"][0]["method"], "weighted")
        self.assertEqual(metadata["points"][0]["neighbor_labels"], [1, 2, 3, 4])
        self.assertEqual(metadata["points"][0]["fields"]["U"]["neighbor_labels"], [1, 2, 3, 4])
        self.assertAlmostEqual(float(data["U_real"][0, 0, 0]), expected_real)
        self.assertAlmostEqual(float(data["U_imag"][0, 0, 0]), expected_imag)

    def test_empty_points_file_is_rejected(self):
        self._write_points([])

        with self.assertRaises(ValueError) as context:
            interp.interpolate_files(
                data_path=self.data_path,
                metadata_path=self.metadata_path,
                points_path=self.points_path,
                output_path=self.output_path,
                metadata_output_path=self.metadata_output_path,
                fields=["U"],
            )

        self.assertIn("does not contain any coordinate rows", str(context.exception))

    def test_neighbor_search_uses_partial_selection_for_requested_count(self):
        original_argpartition = interp.np.argpartition
        calls = []

        def recording_argpartition(values, kth):
            calls.append(kth)
            return original_argpartition(values, kth)

        interp.np.argpartition = recording_argpartition
        try:
            indices, _weights, distances, method = interp._neighbor_weights(
                np.array(
                    [
                        [0.0, 0.0, 0.0],
                        [5.0, 0.0, 0.0],
                        [2.0, 0.0, 0.0],
                        [1.0, 0.0, 0.0],
                    ],
                    dtype=float,
                ),
                np.array([0.1, 0.0, 0.0], dtype=float),
                neighbors=2,
                exact_tol=1.0e-12,
            )
        finally:
            interp.np.argpartition = original_argpartition

        self.assertEqual(calls, [1])
        self.assertEqual(indices.tolist(), [0, 3])
        self.assertEqual(method, "weighted")
        self.assertLessEqual(distances[0], distances[1])

    def test_fields_option_limits_output_fields(self):
        self._write_points([{"point_id": "p1", "x": "0.0", "y": "0.0", "z": "0.0"}])

        interp.main(
            [
                "--data",
                self.data_path,
                "--metadata",
                self.metadata_path,
                "--points",
                self.points_path,
                "--output",
                self.output_path,
                "--metadata-output",
                self.metadata_output_path,
                "--fields",
                "V",
            ]
        )

        data, metadata = self._read_outputs()
        self.assertIn("V_real", data.files)
        self.assertNotIn("U_real", data.files)
        self.assertEqual(metadata["fields"], ["V"])
        self.assertEqual(float(data["V_real"][0, 0, 0]), 100.0)

    def test_three_component_field_outputs_all_components(self):
        self._write_three_component_v_inputs()
        self._write_points([{"point_id": "p1", "x": "0.0", "y": "0.0", "z": "0.0"}])

        interp.interpolate_files(
            data_path=self.data_path,
            metadata_path=self.metadata_path,
            points_path=self.points_path,
            output_path=self.output_path,
            metadata_output_path=self.metadata_output_path,
            fields=["V"],
        )

        data, metadata = self._read_outputs()
        self.assertEqual(data["V_real"].shape, (1, 1, 3))
        self.assertEqual(data["V_real"][0, 0].tolist(), [3.0, 4.0, 12.0])
        self.assertEqual(metadata["field_outputs"]["V"]["components"], ["V1", "V2", "V3"])

    def test_default_fields_skip_non_node_outputs(self):
        self._write_points([{"point_id": "p1", "x": "0.0", "y": "0.0", "z": "0.0"}])

        metadata = interp.interpolate_files(
            data_path=self.data_path,
            metadata_path=self.metadata_path,
            points_path=self.points_path,
            output_path=self.output_path,
            metadata_output_path=self.metadata_output_path,
            fields=None,
        )

        data, saved_metadata = self._read_outputs()
        self.assertEqual(metadata["fields"], ["U", "V"])
        self.assertEqual(saved_metadata["fields"], ["U", "V"])
        self.assertIn("U_real", data.files)
        self.assertIn("V_real", data.files)
        self.assertNotIn("S_real", data.files)
        self.assertEqual(float(data["U_real"][0, 0, 0]), 10.0)
        self.assertEqual(float(data["V_real"][0, 0, 0]), 100.0)

    def test_node_set_limits_interpolation_candidates(self):
        self._write_points([{"point_id": "p1", "x": "1.0", "y": "0.0", "z": "0.0"}])

        metadata = interp.interpolate_files(
            data_path=self.data_path,
            metadata_path=self.metadata_path,
            points_path=self.points_path,
            output_path=self.output_path,
            metadata_output_path=self.metadata_output_path,
            fields=["U"],
            node_sets=["SET_ORIGIN"],
            neighbors=1,
        )

        data, _saved_metadata = self._read_outputs()
        self.assertEqual(float(data["U_real"][0, 0, 0]), 10.0)
        self.assertEqual(metadata["points"][0]["neighbor_labels"], [1])
        self.assertEqual(metadata["interpolation"]["node_sets"], ["SET_ORIGIN"])

    def test_multiple_node_sets_use_union_of_members(self):
        self._write_points([{"point_id": "p1", "x": "0.5", "y": "0.5", "z": "0.0"}])

        metadata = interp.interpolate_files(
            data_path=self.data_path,
            metadata_path=self.metadata_path,
            points_path=self.points_path,
            output_path=self.output_path,
            metadata_output_path=self.metadata_output_path,
            fields=["U"],
            node_sets=["SET_RIGHT", "SET_UP"],
            neighbors=2,
        )

        self.assertEqual(metadata["points"][0]["neighbor_labels"], [2, 3])

    def test_node_set_rejects_out_of_range_cached_index(self):
        with np.load(self.data_path) as source:
            arrays = {key: source[key] for key in source.files}
        arrays["node_set_0003_indices"] = np.array([99], dtype=np.int64)
        np.savez_compressed(self.data_path, **arrays)
        with open(self.metadata_path, "r", encoding="utf-8") as stream:
            metadata = json.load(stream)
        metadata["node_sets"]["SET_BAD"] = {
            "indices_key": "node_set_0003_indices",
            "member_count": 1,
        }
        with open(self.metadata_path, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream)
        self._write_points([{"point_id": "p1", "x": "0", "y": "0", "z": "0"}])

        with self.assertRaisesRegex(ValueError, "SET_BAD"):
            interp.interpolate_files(
                data_path=self.data_path,
                metadata_path=self.metadata_path,
                points_path=self.points_path,
                output_path=self.output_path,
                metadata_output_path=self.metadata_output_path,
                fields=["U"],
                node_sets=["SET_BAD"],
            )

    def test_xlsx_points_input_writes_same_npz_contract(self):
        self._write_xlsx_points([{"point_id": "p1", "x": 1.0, "y": 0.0, "z": 0.0}])

        interp.interpolate_files(
            data_path=self.data_path,
            metadata_path=self.metadata_path,
            points_path=self.xlsx_points_path,
            output_path=self.output_path,
            metadata_output_path=self.metadata_output_path,
            fields=["U"],
        )

        data, metadata = self._read_outputs()
        self.assertEqual(data["point_ids"].tolist(), ["p1"])
        self.assertEqual(float(data["U_real"][0, 0, 0]), 20.0)
        self.assertEqual(metadata["point_input"]["worksheet"], "Sheet")

    def test_interpolate_files_closes_loaded_npz(self):
        self._write_points([{"point_id": "p1", "x": "0.0", "y": "0.0", "z": "0.0"}])
        loaded = np.load(self.data_path)
        original_load = interp.np.load

        def fake_load(_path):
            return loaded

        interp.np.load = fake_load
        try:
            interp.interpolate_files(
                data_path=self.data_path,
                metadata_path=self.metadata_path,
                points_path=self.points_path,
                output_path=self.output_path,
                metadata_output_path=self.metadata_output_path,
                fields=["U"],
            )
        finally:
            interp.np.load = original_load

        self.assertIsNone(loaded.zip)

    def test_element_field_is_rejected(self):
        self._write_points([{"point_id": "p1", "x": "0.0", "y": "0.0", "z": "0.0"}])

        with self.assertRaises(ValueError) as context:
            interp.interpolate_files(
                data_path=self.data_path,
                metadata_path=self.metadata_path,
                points_path=self.points_path,
                output_path=self.output_path,
                metadata_output_path=self.metadata_output_path,
                fields=["S"],
            )

        self.assertIn("Field S is not a node field", str(context.exception))


if __name__ == "__main__":
    unittest.main()
