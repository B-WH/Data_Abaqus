import csv
import json
import math
import os
import unittest

import numpy as np

from odb_extract import npz_export


class NpzExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output_dir = os.path.abspath(
            os.path.join("work", "test-output", "npz-export")
        )
        os.makedirs(cls.output_dir, exist_ok=True)

    def write_node_source(self, name="node-source", bad_imag_shape=False):
        data_path = os.path.join(self.output_dir, name + "_data.npz")
        metadata_path = os.path.join(self.output_dir, name + "_metadata.json")
        imag = np.array([[[4.0], [0.0]], [[0.0], [np.nan]]])
        if bad_imag_shape:
            imag = imag[:, :1, :]
        np.savez_compressed(
            data_path,
            frequencies=np.array([10.0, 20.0]),
            node_labels=np.array([1, 2]),
            node_coordinates=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
            U_real=np.array([[[3.0], [5.0]], [[8.0], [np.nan]]]),
            U_imag=imag,
        )
        metadata = {
            "fields": ["U"],
            "nodes": [
                {
                    "instance": "PART-1-1",
                    "label": 1,
                    "coordinates": [0.0, 0.0, 0.0],
                },
                {
                    "instance": "PART-1-1",
                    "label": 2,
                    "coordinates": [1.0, 0.0, 0.0],
                },
            ],
            "array_layouts": {
                "frequencies": ["frame"],
                "U_real": ["frame", "node", "component"],
                "U_imag": ["frame", "node", "component"],
            },
            "field_outputs": {
                "U": {
                    "location": "NODE",
                    "components": ["U1"],
                    "points": [
                        {"instance": "PART-1-1", "node_label": 1},
                        {"instance": "PART-1-1", "node_label": 2},
                    ],
                }
            },
        }
        with open(metadata_path, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream)
        return data_path, metadata_path

    def test_inspect_source_reports_arrays_and_fields(self):
        data_path, metadata_path = self.write_node_source()

        result = npz_export.inspect_source(data_path)

        self.assertEqual(result["metadata_path"], metadata_path)
        self.assertEqual(result["fields"], ["U"])
        self.assertEqual(result["arrays"]["U_real"]["shape"], [2, 2, 1])
        self.assertEqual(result["arrays"]["U_real"]["nan_count"], 1)

    def test_export_writes_only_magnitude_and_honors_filters(self):
        data_path, metadata_path = self.write_node_source()
        output_path = os.path.join(self.output_dir, "filtered.csv")

        result = npz_export.export_magnitude_csv(
            data_path,
            output_path,
            metadata_path=metadata_path,
            fields=["U"],
            frequency_min=10.0,
            frequency_max=10.0,
            entity_ids=["1"],
        )

        with open(output_path, newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(rows[0]["magnitude"], "5.0")
        self.assertNotIn("real", rows[0])
        self.assertNotIn("imag", rows[0])
        self.assertNotIn("phase", rows[0])

    def test_estimate_export_rows_uses_the_same_filters(self):
        data_path, metadata_path = self.write_node_source()

        row_count = npz_export.estimate_export_rows(
            data_path,
            metadata_path=metadata_path,
            fields=["U"],
            components=["U1"],
            frequency_min=20.0,
            entity_ids=["2"],
        )

        self.assertEqual(row_count, 1)

    def test_export_preserves_nan_magnitude(self):
        data_path, metadata_path = self.write_node_source()
        output_path = os.path.join(self.output_dir, "nan.csv")

        npz_export.export_magnitude_csv(
            data_path,
            output_path,
            metadata_path=metadata_path,
        )

        with open(output_path, newline="", encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertTrue(math.isnan(float(rows[-1]["magnitude"])))

    def test_export_rejects_mismatched_shapes_without_replacing_output(self):
        data_path, metadata_path = self.write_node_source(
            "bad-shape", bad_imag_shape=True
        )
        output_path = os.path.join(self.output_dir, "bad-shape.csv")
        with open(output_path, "w", encoding="utf-8") as stream:
            stream.write("keep me")

        with self.assertRaisesRegex(ValueError, "shapes"):
            npz_export.export_magnitude_csv(
                data_path,
                output_path,
                metadata_path=metadata_path,
            )

        with open(output_path, "r", encoding="utf-8") as stream:
            self.assertEqual(stream.read(), "keep me")

    def write_location_source(
        self, name, field_name, location, entity_axis, identity, extra_arrays=None
    ):
        data_path = os.path.join(self.output_dir, name + "_data.npz")
        metadata_path = os.path.join(self.output_dir, name + "_metadata.json")
        arrays = {
            "frequencies": np.array([10.0]),
            field_name + "_real": np.array([[[3.0]]]),
            field_name + "_imag": np.array([[[4.0]]]),
        }
        arrays.update(extra_arrays or {})
        np.savez_compressed(data_path, **arrays)
        metadata = {
            "array_layouts": {
                field_name + "_real": ["frame", entity_axis, "component"],
                field_name + "_imag": ["frame", entity_axis, "component"],
            },
            "field_outputs": {
                field_name: {
                    "location": location,
                    "components": [field_name],
                    "points": [identity],
                }
            },
        }
        if location == "POINT":
            metadata["points"] = [identity]
        with open(metadata_path, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream)
        return data_path, metadata_path

    def test_export_supports_interpolated_point_identity(self):
        data_path, metadata_path = self.write_location_source(
            "point-source",
            "POR",
            "POINT",
            "point",
            {"point_id": "p1", "coordinates": [1.0, 2.0, 3.0]},
            extra_arrays={
                "point_ids": np.array(["p1"]),
                "point_coordinates": np.array([[1.0, 2.0, 3.0]]),
            },
        )
        output_path = os.path.join(self.output_dir, "point.csv")

        npz_export.export_magnitude_csv(
            data_path, output_path, metadata_path=metadata_path
        )

        with open(output_path, newline="", encoding="utf-8-sig") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["point_id"], "p1")
        self.assertEqual(row["magnitude"], "5.0")

    def test_export_supports_element_identity(self):
        data_path, metadata_path = self.write_location_source(
            "element-source",
            "S",
            "ELEMENT",
            "element_point",
            {
                "instance": "PART-1-1",
                "element_label": 10,
                "integration_point": 1,
            },
        )
        output_path = os.path.join(self.output_dir, "element.csv")

        npz_export.export_magnitude_csv(
            data_path, output_path, metadata_path=metadata_path
        )

        with open(output_path, newline="", encoding="utf-8-sig") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["element_label"], "10")
        self.assertEqual(row["integration_point"], "1")

    def test_export_supports_generic_value_identity(self):
        data_path, metadata_path = self.write_location_source(
            "value-source",
            "A",
            "VALUE",
            "value",
            {"instance": "PART-1-1", "value_index": 0},
        )
        output_path = os.path.join(self.output_dir, "value.csv")

        npz_export.export_magnitude_csv(
            data_path, output_path, metadata_path=metadata_path
        )

        with open(output_path, newline="", encoding="utf-8-sig") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["value_index"], "0")
        self.assertEqual(row["magnitude"], "5.0")


if __name__ == "__main__":
    unittest.main()
