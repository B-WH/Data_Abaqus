import csv
import json
import os
import sys
import unittest

import numpy as np

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
        self.output_path = os.path.join(self.work_dir, "result.csv")
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
        }
        with open(self.metadata_path, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream)

    def _write_points(self, rows):
        with open(self.points_path, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["point_id", "x", "y", "z"])
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _read_output(self):
        with open(self.output_path, newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

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
                "--fields",
                "U",
            ]
        )

        self.assertEqual(code, 0)
        rows = self._read_output()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["method"], "exact")
        self.assertEqual(rows[0]["neighbor_labels"], "2")
        self.assertEqual(float(rows[0]["real"]), 20.0)
        self.assertEqual(float(rows[0]["imag"]), 2.0)

    def test_non_node_coordinate_uses_inverse_distance_neighbors(self):
        self._write_points([{"point_id": "p2", "x": "0.25", "y": "0.25", "z": "0.25"}])

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
                "--fields",
                "U",
            ]
        )

        rows = self._read_output()
        distances = np.array([0.4330127018922193, 0.82915619758885, 0.82915619758885, 0.82915619758885])
        weights = (1.0 / distances) / np.sum(1.0 / distances)
        expected_real = float(np.dot(weights, np.array([10.0, 20.0, 30.0, 40.0])))
        expected_imag = float(np.dot(weights, np.array([1.0, 2.0, 3.0, 4.0])))

        self.assertEqual(rows[0]["method"], "weighted")
        self.assertEqual(rows[0]["neighbor_labels"], "1;2;3;4")
        self.assertAlmostEqual(float(rows[0]["real"]), expected_real)
        self.assertAlmostEqual(float(rows[0]["imag"]), expected_imag)

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
                "--fields",
                "V",
            ]
        )

        rows = self._read_output()
        self.assertEqual([row["field"] for row in rows], ["V"])
        self.assertEqual(float(rows[0]["real"]), 100.0)

    def test_default_fields_skip_non_node_outputs(self):
        self._write_points([{"point_id": "p1", "x": "0.0", "y": "0.0", "z": "0.0"}])

        rows = interp.interpolate_files(
            data_path=self.data_path,
            metadata_path=self.metadata_path,
            points_path=self.points_path,
            output_path=self.output_path,
            fields=None,
        )

        self.assertEqual([row["field"] for row in rows], ["U", "V"])
        self.assertEqual(float(rows[0]["real"]), 10.0)
        self.assertEqual(float(rows[1]["real"]), 100.0)

    def test_element_field_is_rejected(self):
        self._write_points([{"point_id": "p1", "x": "0.0", "y": "0.0", "z": "0.0"}])

        with self.assertRaises(ValueError) as context:
            interp.interpolate_files(
                data_path=self.data_path,
                metadata_path=self.metadata_path,
                points_path=self.points_path,
                output_path=self.output_path,
                fields=["S"],
            )

        self.assertIn("Field S is not a node field", str(context.exception))


if __name__ == "__main__":
    unittest.main()
