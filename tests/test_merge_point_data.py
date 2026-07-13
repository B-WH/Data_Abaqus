import json
import os
import unittest

import numpy as np

from odb_extract import merge_point_data


class MergePointDataTests(unittest.TestCase):
    def _arrays(self, frequencies, offset=0.0):
        frame_count = len(frequencies)
        values = np.arange(frame_count * 2 * 3, dtype=float).reshape(frame_count, 2, 3)
        values = values + offset
        return {
            "frequencies": np.asarray(frequencies, dtype=float),
            "node_labels": np.asarray([1, 2], dtype=np.int64),
            "node_coordinates": np.asarray(
                [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
                dtype=float,
            ),
            "U_real": values,
            "U_imag": values * 0.1,
        }

    def _metadata(self, frequencies, source_odb="part.odb"):
        return {
            "tool": {"name": "odb_extract.extractor", "metadata_schema_version": 2},
            "source_odb": source_odb,
            "step": "HARMONIC_RESPONSE",
            "fields": ["U"],
            "generated_at": "2026-07-08T00:00:00",
            "node_count": 2,
            "nodes": [
                {"instance": "PART-1-1", "label": 1, "coordinates": [0.0, 0.0, 0.0]},
                {"instance": "PART-1-1", "label": 2, "coordinates": [1.0, 0.0, 0.0]},
            ],
            "array_shapes": {
                "frequencies": [len(frequencies)],
                "node_labels": [2],
                "node_coordinates": [2, 3],
                "U_real": [len(frequencies), 2, 3],
                "U_imag": [len(frequencies), 2, 3],
            },
            "array_layouts": {
                "frequencies": ["frame"],
                "node_labels": ["node"],
                "node_coordinates": ["node", "coordinate"],
                "U_real": ["frame", "node", "component"],
                "U_imag": ["frame", "node", "component"],
            },
            "field_outputs": {
                "U": {
                    "location": "NODE",
                    "component_count": 3,
                    "components": ["U1", "U2", "U3"],
                    "array_layout": ["frame", "node", "component"],
                    "points": [
                        {"instance": "PART-1-1", "node_label": 1},
                        {"instance": "PART-1-1", "node_label": 2},
                    ],
                }
            },
            "filters": {"frequency_min": min(frequencies), "frequency_max": max(frequencies)},
            "command_options": {},
            "warnings": [],
        }

    def _part(self, frequencies, offset=0.0, source_odb="part.odb"):
        return {
            "data_path": source_odb.replace(".odb", "_point_data.npz"),
            "metadata_path": source_odb.replace(".odb", "_point_metadata.json"),
            "arrays": self._arrays(frequencies, offset=offset),
            "metadata": self._metadata(frequencies, source_odb=source_odb),
        }

    def _with_node_set(self, part, indices):
        part["arrays"]["node_set_0000_indices"] = np.asarray(indices, dtype=np.int64)
        part["metadata"]["tool"]["metadata_schema_version"] = 3
        part["metadata"]["array_shapes"]["node_set_0000_indices"] = [len(indices)]
        part["metadata"]["array_layouts"]["node_set_0000_indices"] = ["node_set_member"]
        part["metadata"]["node_sets"] = {
            "SET_A": {
                "indices_key": "node_set_0000_indices",
                "member_count": len(indices),
            }
        }
        return part

    def test_merge_parts_concatenates_frequency_frames(self):
        arrays, metadata = merge_point_data.merge_parts(
            [
                self._part([1.0, 2.0], offset=10.0, source_odb="a.odb"),
                self._part([3.0, 4.0], offset=30.0, source_odb="b.odb"),
            ]
        )

        self.assertEqual(arrays["frequencies"].tolist(), [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(arrays["U_real"].shape, (4, 2, 3))
        np.testing.assert_allclose(arrays["U_real"][0], self._arrays([1.0], 10.0)["U_real"][0])
        np.testing.assert_allclose(arrays["U_real"][2], self._arrays([3.0], 30.0)["U_real"][0])
        self.assertEqual(metadata["array_shapes"]["U_real"], [4, 2, 3])
        self.assertEqual(len(metadata["source_parts"]), 2)
        self.assertEqual(metadata["merge"]["frequency_min"], 1.0)
        self.assertEqual(metadata["merge"]["frequency_max"], 4.0)

    def test_merge_parts_combines_source_warnings(self):
        first = self._part([1.0], source_odb="a.odb")
        second = self._part([2.0], source_odb="b.odb")
        first["metadata"]["warnings"] = ["first warning"]
        second["metadata"]["warnings"] = ["second warning"]

        _arrays, metadata = merge_point_data.merge_parts([first, second])

        self.assertEqual(
            metadata["warnings"],
            [
                "a_point_data.npz: first warning",
                "b_point_data.npz: second warning",
            ],
        )

    def test_merge_parts_sorts_frequency_frames(self):
        arrays, _metadata = merge_point_data.merge_parts(
            [
                self._part([3.0, 4.0], offset=30.0, source_odb="b.odb"),
                self._part([1.0, 2.0], offset=10.0, source_odb="a.odb"),
            ]
        )

        self.assertEqual(arrays["frequencies"].tolist(), [1.0, 2.0, 3.0, 4.0])
        np.testing.assert_allclose(arrays["U_real"][0], self._arrays([1.0], 10.0)["U_real"][0])

    def test_merge_parts_deduplicates_equal_boundary_frequency(self):
        first = self._part([1.0, 2.0], offset=10.0, source_odb="a.odb")
        second = self._part([2.0, 3.0], offset=20.0, source_odb="b.odb")
        second["arrays"]["U_real"][0] = first["arrays"]["U_real"][1]
        second["arrays"]["U_imag"][0] = first["arrays"]["U_imag"][1]

        arrays, _metadata = merge_point_data.merge_parts([first, second])

        self.assertEqual(arrays["frequencies"].tolist(), [1.0, 2.0, 3.0])
        np.testing.assert_allclose(arrays["U_real"][1], first["arrays"]["U_real"][1])

    def test_merge_parts_rejects_conflicting_duplicate_frequency(self):
        first = self._part([1.0, 2.0], offset=10.0, source_odb="a.odb")
        second = self._part([2.0, 3.0], offset=20.0, source_odb="b.odb")

        with self.assertRaisesRegex(ValueError, "2.0.*U_real"):
            merge_point_data.merge_parts([first, second])

    def test_merge_parts_rejects_mismatched_nodes(self):
        first = self._part([1.0], source_odb="a.odb")
        second = self._part([2.0], source_odb="b.odb")
        second["metadata"]["nodes"][1]["label"] = 99

        with self.assertRaisesRegex(ValueError, "nodes"):
            merge_point_data.merge_parts([first, second])

    def test_merge_parts_rejects_mismatched_coordinates(self):
        first = self._part([1.0], source_odb="a.odb")
        second = self._part([2.0], source_odb="b.odb")
        second["arrays"]["node_coordinates"][1, 0] = 2.0

        with self.assertRaisesRegex(ValueError, "node_coordinates"):
            merge_point_data.merge_parts([first, second])

    def test_merge_parts_preserves_matching_node_set_membership(self):
        first = self._with_node_set(self._part([1.0], source_odb="a.odb"), [0])
        second = self._with_node_set(self._part([2.0], source_odb="b.odb"), [0])

        arrays, metadata = merge_point_data.merge_parts([first, second])

        self.assertEqual(arrays["node_set_0000_indices"].tolist(), [0])
        self.assertEqual(metadata["node_sets"]["SET_A"]["member_count"], 1)

    def test_merge_parts_rejects_mismatched_node_set_membership(self):
        first = self._with_node_set(self._part([1.0], source_odb="a.odb"), [0])
        second = self._with_node_set(self._part([2.0], source_odb="b.odb"), [1])

        with self.assertRaisesRegex(ValueError, "node_set_0000_indices"):
            merge_point_data.merge_parts([first, second])

    def test_merge_parts_rejects_mismatched_node_set_metadata(self):
        first = self._with_node_set(self._part([1.0], source_odb="a.odb"), [0])
        second = self._with_node_set(self._part([2.0], source_odb="b.odb"), [0])
        second["metadata"]["node_sets"] = {
            "SET_OTHER": {
                "indices_key": "node_set_0000_indices",
                "member_count": 1,
            }
        }

        with self.assertRaisesRegex(ValueError, "node_sets"):
            merge_point_data.merge_parts([first, second])

    def test_merge_parts_rejects_mismatched_fields(self):
        first = self._part([1.0], source_odb="a.odb")
        second = self._part([2.0], source_odb="b.odb")
        second["metadata"]["fields"] = ["A"]

        with self.assertRaisesRegex(ValueError, "fields"):
            merge_point_data.merge_parts([first, second])

    def test_merge_parts_rejects_mismatched_layouts(self):
        first = self._part([1.0], source_odb="a.odb")
        second = self._part([2.0], source_odb="b.odb")
        second["metadata"]["array_layouts"]["U_real"] = ["frame", "value", "component"]

        with self.assertRaisesRegex(ValueError, "array_layouts"):
            merge_point_data.merge_parts([first, second])

    def test_infer_metadata_path_supports_general_npz_names(self):
        cases = (
            (r"D:\work\j-test_100_data.npz", r"D:\work\j-test_100_metadata.json"),
            (r"D:\work\a_point_data.npz", r"D:\work\a_point_metadata.json"),
            (r"D:\work\band-100.npz", r"D:\work\band-100.json"),
        )
        for data_path, expected in cases:
            with self.subTest(data_path=data_path):
                self.assertEqual(merge_point_data.infer_metadata_path(data_path), expected)

    def test_infer_metadata_path_rejects_non_npz_path(self):
        with self.assertRaisesRegex(ValueError, "\\.npz"):
            merge_point_data.infer_metadata_path(r"D:\work\band-100.dat")

    def test_validate_output_paths_rejects_data_output_overwriting_input(self):
        with self.assertRaisesRegex(ValueError, "input NPZ"):
            merge_point_data.validate_output_paths(
                [r"D:\work\a_point_data.npz"],
                r"D:\work\a_point_data.npz",
                r"D:\work\merged_point_metadata.json",
            )

    def test_validate_output_paths_rejects_metadata_output_overwriting_input(self):
        with self.assertRaisesRegex(ValueError, "input metadata"):
            merge_point_data.validate_output_paths(
                [r"D:\work\a_point_data.npz"],
                r"D:\work\merged_point_data.npz",
                r"D:\work\a_point_metadata.json",
            )

    def test_merge_files_writes_npz_and_metadata(self):
        work_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "work",
            "test-output",
            "merge_point_data",
        )
        if not os.path.isdir(work_dir):
            os.makedirs(work_dir)
        first_data = os.path.join(work_dir, "a_point_data.npz")
        second_data = os.path.join(work_dir, "b_point_data.npz")
        output_data = os.path.join(work_dir, "merged_point_data.npz")
        output_metadata = os.path.join(work_dir, "merged_point_metadata.json")

        for data_path, frequencies, source_odb in (
            (first_data, [1.0, 2.0], "a.odb"),
            (second_data, [3.0, 4.0], "b.odb"),
        ):
            np.savez_compressed(data_path, **self._arrays(frequencies))
            with open(merge_point_data.infer_metadata_path(data_path), "w", encoding="utf-8") as stream:
                json.dump(self._metadata(frequencies, source_odb=source_odb), stream)

        merge_point_data.merge_files([first_data, second_data], output_data, output_metadata)

        with np.load(output_data) as loaded:
            self.assertEqual(loaded["frequencies"].tolist(), [1.0, 2.0, 3.0, 4.0])
        with open(output_metadata, "r", encoding="utf-8") as stream:
            metadata = json.load(stream)
        self.assertEqual(len(metadata["source_parts"]), 2)
        self.assertEqual(metadata["array_shapes"]["frequencies"], [4])


if __name__ == "__main__":
    unittest.main()
