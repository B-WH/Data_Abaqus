import json
import importlib
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import Extract_data_ODB as extractor


class FakeNode(object):
    def __init__(self, label):
        self.label = label


class FakeInstance(object):
    def __init__(self, nodes):
        self.nodes = nodes


class FakeAssembly(object):
    def __init__(self):
        self.instances = {
            "PART-1-1": FakeInstance([FakeNode(2), FakeNode(1)]),
            "PART-2-1": FakeInstance([FakeNode(3)]),
        }


class FakeOdb(object):
    def __init__(self):
        self.rootAssembly = FakeAssembly()


class FakeValue(object):
    def __init__(self, instance_name, node_label, data, conjugate_data=None):
        self.instance = type("InstanceRef", (), {"name": instance_name})()
        self.nodeLabel = node_label
        self.data = data
        if conjugate_data is not None:
            self.conjugateData = conjugate_data


class FakeElementValue(object):
    def __init__(
        self,
        instance_name,
        element_label,
        data,
        conjugate_data=None,
        integration_point=None,
    ):
        self.instance = type("InstanceRef", (), {"name": instance_name})()
        self.elementLabel = element_label
        self.data = data
        if conjugate_data is not None:
            self.conjugateData = conjugate_data
        if integration_point is not None:
            self.integrationPoint = integration_point


class FakeSubset(object):
    def __init__(self, values):
        self.values = values


class FakeFieldOutput(object):
    def __init__(self, values):
        self._values = values

    def getSubset(self, region=None):
        return FakeSubset(self._values)


class StrictFakeFieldOutput(object):
    def __init__(self, values):
        self.values = values

    def getSubset(self, region=None):
        if region is None:
            raise TypeError("region; found None, expecting OdbInstance")
        return FakeSubset(self.values)


class FakeFrame(object):
    def __init__(self, frame_value, field_outputs):
        self.frameValue = frame_value
        self.fieldOutputs = field_outputs


class FakeStep(object):
    def __init__(self, frames):
        self.frames = frames


class ExtractorTests(unittest.TestCase):
    def test_open_odb_readonly_reports_plain_python_environment(self):
        original_import_module = importlib.import_module

        def fake_import_module(name):
            if name == "odbAccess":
                raise ModuleNotFoundError("No module named 'odbAccess'")
            return original_import_module(name)

        importlib.import_module = fake_import_module
        try:
            with self.assertRaises(extractor.OdbAccessUnavailableError) as context:
                extractor.open_odb_readonly("data/test1.odb")
        finally:
            importlib.import_module = original_import_module

        self.assertIn("abaqus python Extract_data_ODB.py", str(context.exception))

    def test_collect_nodes_returns_sorted_instance_node_pairs(self):
        nodes = extractor.collect_nodes(FakeOdb())

        self.assertEqual(
            nodes,
            [
                extractor.NodeRef("PART-1-1", 1),
                extractor.NodeRef("PART-1-1", 2),
                extractor.NodeRef("PART-2-1", 3),
            ],
        )

    def test_collect_field_names_returns_sorted_unique_frame_outputs(self):
        step = FakeStep(
            [
                FakeFrame(5.0, {"U": object(), "A": object()}),
                FakeFrame(10.0, {"U": object(), "V": object()}),
            ]
        )

        self.assertEqual(extractor.collect_field_names(step), ["A", "U", "V"])

    def test_extract_field_arrays_preserves_real_imaginary_and_marks_missing_values(self):
        nodes = [
            extractor.NodeRef("PART-1-1", 1),
            extractor.NodeRef("PART-1-1", 2),
        ]
        step = FakeStep(
            [
                FakeFrame(
                    5.0,
                    {
                        "U": FakeFieldOutput(
                            [
                                FakeValue("PART-1-1", 1, (1.0, 2.0, 3.0), (0.1, 0.2, 0.3)),
                            ]
                        )
                    },
                ),
                FakeFrame(
                    10.0,
                    {
                        "U": FakeFieldOutput(
                            [
                                FakeValue("PART-1-1", 1, (4.0, 5.0, 6.0)),
                                FakeValue("PART-1-1", 2, (7.0, 8.0, 9.0), (0.7, 0.8, 0.9)),
                            ]
                        )
                    },
                ),
            ]
        )

        arrays, metadata = extractor.extract_field_arrays(step, nodes, ["U", "A"])

        self.assertEqual(arrays["frequencies"].tolist(), [5.0, 10.0])
        self.assertEqual(arrays["node_labels"].tolist(), [1, 2])
        self.assertEqual(arrays["U_real"].shape, (2, 2, 3))
        self.assertEqual(arrays["U_imag"].shape, (2, 2, 3))
        self.assertEqual(arrays["U_real"][0, 0].tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(arrays["U_imag"][0, 0].tolist(), [0.1, 0.2, 0.3])
        self.assertTrue(np.isnan(arrays["U_real"][0, 1, 0]))
        self.assertEqual(arrays["U_imag"][1, 0].tolist(), [0.0, 0.0, 0.0])
        self.assertTrue(np.isnan(arrays["A_real"]).all())
        self.assertTrue(
            any(
                "Field A is missing from frame 0" in warning
                for warning in metadata["warnings"]
            )
        )
        self.assertEqual(metadata["array_shapes"]["U_real"], [2, 2, 3])

    def test_extract_field_arrays_reads_all_values_without_passing_none_region(self):
        nodes = [extractor.NodeRef("PART-1-1", 1)]
        step = FakeStep(
            [
                FakeFrame(
                    5.0,
                    {
                        "U": StrictFakeFieldOutput(
                            [
                                FakeValue("PART-1-1", 1, (1.0, 2.0, 3.0), (0.1, 0.2, 0.3)),
                            ]
                        )
                    },
                )
            ]
        )

        arrays, metadata = extractor.extract_field_arrays(step, nodes, ["U"])

        self.assertEqual(arrays["U_real"][0, 0].tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(metadata["warnings"], [])

    def test_extract_field_arrays_supports_scalar_node_field_outputs(self):
        nodes = [extractor.NodeRef("PART-1-1", 1)]
        step = FakeStep(
            [
                FakeFrame(
                    5.0,
                    {
                        "POR": FakeFieldOutput(
                            [
                                FakeValue("PART-1-1", 1, 12.5, 0.25),
                            ]
                        )
                    },
                )
            ]
        )

        arrays, metadata = extractor.extract_field_arrays(step, nodes, ["POR"])

        self.assertEqual(arrays["POR_real"].shape, (1, 1, 1))
        self.assertEqual(arrays["POR_imag"].shape, (1, 1, 1))
        self.assertEqual(arrays["POR_real"][0, 0, 0], 12.5)
        self.assertEqual(arrays["POR_imag"][0, 0, 0], 0.25)
        self.assertEqual(metadata["field_outputs"]["POR"]["location"], "NODE")

    def test_extract_field_arrays_supports_element_integration_point_outputs(self):
        nodes = [extractor.NodeRef("PART-1-1", 1)]
        step = FakeStep(
            [
                FakeFrame(
                    5.0,
                    {
                        "S": FakeFieldOutput(
                            [
                                FakeElementValue(
                                    "PART-1-1",
                                    10,
                                    (1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
                                    integration_point=1,
                                ),
                            ]
                        )
                    },
                ),
                FakeFrame(
                    10.0,
                    {
                        "S": FakeFieldOutput(
                            [
                                FakeElementValue(
                                    "PART-1-1",
                                    10,
                                    (7.0, 8.0, 9.0, 10.0, 11.0, 12.0),
                                    integration_point=1,
                                ),
                            ]
                        )
                    },
                ),
            ]
        )

        arrays, metadata = extractor.extract_field_arrays(step, nodes, ["S"])

        self.assertEqual(arrays["S_real"].shape, (2, 1, 6))
        self.assertEqual(arrays["S_imag"].shape, (2, 1, 6))
        self.assertEqual(arrays["S_real"][0, 0].tolist(), [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        self.assertEqual(arrays["S_imag"][0, 0].tolist(), [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual(metadata["field_outputs"]["S"]["location"], "ELEMENT")
        self.assertEqual(
            metadata["field_outputs"]["S"]["points"],
            [
                {
                    "instance": "PART-1-1",
                    "element_label": 10,
                    "integration_point": 1,
                }
            ],
        )

    def test_save_outputs_create_parent_directories_and_metadata_json(self):
        arrays = {
            "frequencies": np.array([5.0]),
            "node_labels": np.array([25]),
            "U_real": np.array([[[1.0, 2.0, 3.0]]]),
            "U_imag": np.array([[[0.1, 0.2, 0.3]]]),
        }
        metadata = {
            "source_odb": "data/test1.odb",
            "step": "HARMONIC_RESPONSE",
            "fields": ["U"],
            "warnings": [],
        }

        tmpdir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "unit_test")
        npz_path = os.path.join(tmpdir, "nested", "data.npz")
        json_path = os.path.join(tmpdir, "nested", "metadata.json")

        extractor.save_npz(npz_path, arrays)
        extractor.save_metadata(json_path, metadata)

        loaded = np.load(npz_path)
        self.assertEqual(loaded["node_labels"].tolist(), [25])
        with open(json_path, "r", encoding="utf-8") as stream:
            saved_metadata = json.load(stream)
        self.assertEqual(saved_metadata["fields"], ["U"])
        self.assertEqual(saved_metadata["step"], "HARMONIC_RESPONSE")


if __name__ == "__main__":
    unittest.main()
