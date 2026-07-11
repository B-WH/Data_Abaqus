import io
import json
import importlib
import os
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from odb_extract import extractor


class FakeNode(object):
    def __init__(self, label, coordinates=None):
        self.label = label
        self.coordinates = coordinates or (float(label), 0.0, 0.0)


class FakeInstance(object):
    def __init__(self, nodes, elements=None):
        self.nodes = nodes
        self.elements = elements or []


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
    def __init__(self, values, component_labels=None):
        self._values = values
        if component_labels is not None:
            self.componentLabels = component_labels

    def getSubset(self, region=None):
        return FakeSubset(self._values)


class FakeBulkBlock(object):
    def __init__(
        self,
        instance_name,
        node_labels,
        data,
        conjugate_data=None,
        component_labels=None,
        position="NODAL",
    ):
        self.instance = type("InstanceRef", (), {"name": instance_name})()
        self.nodeLabels = node_labels
        self.data = data
        self.position = position
        if conjugate_data is not None:
            self.conjugateData = conjugate_data
        if component_labels is not None:
            self.componentLabels = component_labels


class BulkOnlyFieldOutput(object):
    def __init__(self, blocks, component_labels=None):
        self.bulkDataBlocks = blocks
        if component_labels is not None:
            self.componentLabels = component_labels

    @property
    def values(self):
        raise AssertionError("field.values must not be read for a bulk node field")


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
    def __init__(self, frames, history_regions=None):
        self.frames = frames
        self.historyRegions = history_regions or {}


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

        self.assertIn(r"abaqus python .\odb_extract\extractor.py", str(context.exception))

    def test_main_reports_unexpected_list_fields_error_as_nonzero(self):
        stream = io.StringIO()

        with mock.patch.object(
            extractor,
            "run_list_fields",
            side_effect=RuntimeError("The database is from a previous release of Abaqus."),
        ):
            with mock.patch("sys.stderr", stream):
                code = extractor.main(["--odb", "old.odb", "--list-fields"])

        self.assertEqual(code, 1)
        self.assertIn("previous release of Abaqus", stream.getvalue())

    def test_extractor_avoids_python3_only_runtime_calls_for_abaqus_614(self):
        source_path = os.path.join(os.path.dirname(extractor.__file__), "extractor.py")
        with open(source_path, "r", encoding="utf-8") as stream:
            source = stream.read()

        self.assertNotIn(" from exc", source)
        self.assertNotIn('with open(metadata_path, "w", encoding=', source)
        self.assertNotIn("timespec=", source)

    def test_removed_legacy_helpers_are_absent(self):
        from odb_extract import interpolate_points, launcher

        extractor_names = (
            "_full_array",
            "_component_count_from_step",
            "_component_count_for_field",
            "_component_labels_for_field",
            "_field_location_from_step",
            "_collect_field_point_keys",
            "_filter_frames_by_frequency",
        )
        for name in extractor_names:
            self.assertFalse(hasattr(extractor, name), name)
        self.assertFalse(hasattr(launcher, "run_command_silent"))
        self.assertFalse(hasattr(interpolate_points, "read_query_points"))

    def test_cleanup_memmap_files_closes_mapping_before_delete(self):
        array, path = extractor._create_memmap_array(np, (2, 2))
        try:
            self.assertTrue(os.path.isfile(path))

            extractor._cleanup_memmap_files([path], {"values": array})

            self.assertFalse(os.path.exists(path))
        finally:
            mmap = getattr(array, "_mmap", None)
            if mmap is not None and not mmap.closed:
                mmap.close()
            if os.path.isfile(path):
                os.remove(path)

    def test_log_elapsed_prints_timing_and_returns_current_time(self):
        stream = io.StringIO()

        with mock.patch("sys.stdout", stream):
            current_time = extractor._log_elapsed("open ODB", 10.0, now=12.3456)

        self.assertEqual(current_time, 12.3456)
        self.assertEqual(stream.getvalue(), "[timing] open ODB: 2.346 s\n")

    def test_collect_nodes_returns_sorted_instance_node_pairs(self):
        nodes = extractor.collect_nodes(FakeOdb())

        self.assertEqual(
            nodes,
            [
                extractor.NodeRef("PART-1-1", 1, (1.0, 0.0, 0.0)),
                extractor.NodeRef("PART-1-1", 2, (2.0, 0.0, 0.0)),
                extractor.NodeRef("PART-2-1", 3, (3.0, 0.0, 0.0)),
            ],
        )

    def test_collect_nodes_can_filter_instances_and_node_labels(self):
        nodes = extractor.collect_nodes(
            FakeOdb(),
            instances=["PART-1-1"],
            node_labels=[2],
        )

        self.assertEqual(nodes, [extractor.NodeRef("PART-1-1", 2, (2.0, 0.0, 0.0))])

    def test_collect_field_names_returns_sorted_unique_frame_outputs(self):
        step = FakeStep(
            [
                FakeFrame(5.0, {"U": object(), "A": object()}),
                FakeFrame(10.0, {"U": object(), "V": object()}),
            ]
        )

        self.assertEqual(extractor.collect_field_names(step), ["A", "U", "V"])

    def test_collect_field_metadata_does_not_scan_later_node_frames(self):
        class MustNotReadField(object):
            def getSubset(self, region=None):
                raise AssertionError("later node frame was scanned")

        nodes = [extractor.NodeRef("PART-1-1", 1, (0.0, 0.0, 0.0))]
        step = FakeStep(
            [
                FakeFrame(
                    5.0,
                    {
                        "U": FakeFieldOutput(
                            [FakeValue("PART-1-1", 1, (1.0, 2.0, 3.0))],
                            component_labels=("U1", "U2", "U3"),
                        )
                    },
                ),
                FakeFrame(10.0, {"U": MustNotReadField()}),
            ]
        )

        frames, frequencies, field_meta, point_keys, _indexes = (
            extractor._collect_field_metadata(step, ["U"], nodes, None, None)
        )

        self.assertEqual(len(frames), 2)
        self.assertEqual(frequencies.tolist(), [5.0, 10.0])
        self.assertEqual(field_meta["U"]["location"], "NODE")
        self.assertEqual(field_meta["U"]["components"], ["U1", "U2", "U3"])
        self.assertEqual(point_keys["U"], [("NODE", "PART-1-1", 1)])

    def test_inspect_odb_reports_structure_without_extracting_arrays(self):
        class HistoryRegion(object):
            def __init__(self):
                self.historyOutputs = {"RF1": object(), "U1": object()}

        class InspectAssembly(object):
            def __init__(self):
                self.instances = {
                    "PART-1-1": FakeInstance(
                        [FakeNode(1), FakeNode(2)],
                        elements=[object(), object(), object()],
                    )
                }
                self.nodeSets = {"PROBE_NODE": object()}
                self.elementSets = {"SHAFT": object()}

        class InspectOdb(object):
            def __init__(self):
                self.rootAssembly = InspectAssembly()
                self.steps = {
                    "Step-1": FakeStep(
                        [
                            FakeFrame(
                                5.0,
                                {
                                    "U": FakeFieldOutput(
                                        [FakeValue("PART-1-1", 1, (1.0, 2.0, 3.0))],
                                        component_labels=("U1", "U2", "U3"),
                                    ),
                                    "S": FakeFieldOutput(
                                        [
                                            FakeElementValue(
                                                "PART-1-1",
                                                10,
                                                (1.0,),
                                                integration_point=1,
                                            )
                                        ]
                                    ),
                                },
                            ),
                            FakeFrame(10.0, {"U": FakeFieldOutput([])}),
                        ],
                        history_regions={"Node PART-1-1.1": HistoryRegion()},
                    )
                }

        metadata = extractor.inspect_odb(InspectOdb())

        self.assertEqual(metadata["instances"]["PART-1-1"]["node_count"], 2)
        self.assertEqual(metadata["instances"]["PART-1-1"]["element_count"], 3)
        self.assertEqual(metadata["node_sets"], ["PROBE_NODE"])
        self.assertEqual(metadata["element_sets"], ["SHAFT"])
        self.assertEqual(metadata["steps"]["Step-1"]["frame_count"], 2)
        self.assertEqual(metadata["steps"]["Step-1"]["frame_value_range"], [5.0, 10.0])
        self.assertEqual(metadata["steps"]["Step-1"]["fields"]["U"]["location"], "NODE")
        self.assertEqual(
            metadata["steps"]["Step-1"]["fields"]["U"]["components"],
            ["U1", "U2", "U3"],
        )
        self.assertEqual(
            metadata["steps"]["Step-1"]["fields"]["S"]["location"],
            "INTEGRATION_POINT",
        )
        self.assertEqual(
            metadata["steps"]["Step-1"]["history_regions"]["Node PART-1-1.1"],
            ["RF1", "U1"],
        )

    def test_extract_field_arrays_preserves_real_imaginary_and_marks_missing_values(self):
        nodes = [
            extractor.NodeRef("PART-1-1", 1, (0.0, 0.0, 0.0)),
            extractor.NodeRef("PART-1-1", 2, (1.0, 0.0, 0.0)),
        ]
        step = FakeStep(
            [
                FakeFrame(
                    5.0,
                    {
                        "U": FakeFieldOutput(
                            [
                                FakeValue("PART-1-1", 1, (1.0, 2.0, 3.0), (0.1, 0.2, 0.3)),
                            ],
                            component_labels=("U1", "U2", "U3"),
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
                            ],
                            component_labels=("U1", "U2", "U3"),
                        )
                    },
                ),
            ]
        )

        arrays, metadata = extractor.extract_field_arrays(step, nodes, ["U", "A"])

        self.assertEqual(arrays["frequencies"].tolist(), [5.0, 10.0])
        self.assertEqual(arrays["node_labels"].tolist(), [1, 2])
        self.assertEqual(arrays["node_coordinates"].tolist(), [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
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
        self.assertEqual(metadata["array_shapes"]["node_coordinates"], [2, 3])
        self.assertEqual(metadata["array_layouts"]["U_real"], ["frame", "node", "component"])
        self.assertEqual(metadata["array_layouts"]["U_imag"], ["frame", "node", "component"])
        self.assertEqual(metadata["array_layouts"]["node_coordinates"], ["node", "coordinate"])
        self.assertEqual(metadata["field_outputs"]["U"]["components"], ["U1", "U2", "U3"])
        self.assertEqual(
            metadata["field_outputs"]["U"]["array_layout"],
            ["frame", "node", "component"],
        )

    def test_extract_field_arrays_uses_bulk_blocks_for_all_selected_node_fields(self):
        nodes = [
            extractor.NodeRef("PART-1-1", 1, (0.0, 0.0, 0.0)),
            extractor.NodeRef("PART-2-1", 2, (1.0, 0.0, 0.0)),
        ]
        step = FakeStep(
            [
                FakeFrame(
                    5.0,
                    {
                        "POR": BulkOnlyFieldOutput(
                            [
                                FakeBulkBlock("PART-1-1", [1], [[12.5]], [[0.25]], ["POR"]),
                                FakeBulkBlock("PART-2-1", [2], [[25.0]], component_labels=["POR"]),
                            ],
                            component_labels=("POR",),
                        ),
                        "U": BulkOnlyFieldOutput(
                            [
                                FakeBulkBlock(
                                    "PART-1-1", [1], [[1.0, 2.0, 3.0]], [[0.1, 0.2, 0.3]], ["U1", "U2", "U3"]
                                ),
                                FakeBulkBlock(
                                    "PART-2-1", [2], [[4.0, 5.0, 6.0]], [[0.4, 0.5, 0.6]], ["U1", "U2", "U3"]
                                ),
                            ],
                            component_labels=("U1", "U2", "U3"),
                        ),
                        "A": object(),
                    },
                )
            ]
        )

        arrays, metadata = extractor.extract_field_arrays(step, nodes, ["POR", "U"])

        np.testing.assert_allclose(arrays["POR_real"][0, :, 0], [12.5, 25.0])
        np.testing.assert_allclose(arrays["POR_imag"][0, :, 0], [0.25, 0.0])
        np.testing.assert_allclose(arrays["U_real"][0], [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        np.testing.assert_allclose(arrays["U_imag"][0], [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        self.assertEqual(sorted(metadata["field_outputs"]), ["POR", "U"])
        self.assertNotIn("A_real", arrays)

    def test_extract_field_arrays_falls_back_for_element_nodal_bulk_blocks(self):
        nodes = [extractor.NodeRef("PART-1-1", 1, (0.0, 0.0, 0.0))]
        field = FakeFieldOutput(
            [FakeValue("PART-1-1", 1, 12.5, 0.25)],
            component_labels=("POR",),
        )
        field.bulkDataBlocks = [
            FakeBulkBlock(
                "PART-1-1",
                [1],
                [[99.0]],
                [[9.9]],
                ["POR"],
                position="ELEMENT_NODAL",
            )
        ]
        step = FakeStep([FakeFrame(5.0, {"POR": field})])

        arrays, metadata = extractor.extract_field_arrays(step, nodes, ["POR"])

        self.assertEqual(arrays["POR_real"][0, 0, 0], 12.5)
        self.assertEqual(arrays["POR_imag"][0, 0, 0], 0.25)
        self.assertEqual(metadata["field_outputs"]["POR"]["location"], "NODE")

    def test_extract_field_arrays_falls_back_when_bulk_real_width_is_inconsistent(self):
        nodes = [extractor.NodeRef("PART-1-1", 1, (0.0, 0.0, 0.0))]
        field = FakeFieldOutput(
            [FakeValue("PART-1-1", 1, (4.0, 5.0, 6.0), (0.4, 0.5, 0.6))],
            component_labels=("U1", "U2", "U3"),
        )
        field.bulkDataBlocks = [
            FakeBulkBlock(
                "PART-1-1",
                [1],
                [[90.0, 91.0]],
                [[9.0, 9.1]],
                ["U1", "U2", "U3"],
            )
        ]
        step = FakeStep([FakeFrame(5.0, {"U": field})])

        arrays, metadata = extractor.extract_field_arrays(step, nodes, ["U"])

        np.testing.assert_allclose(arrays["U_real"][0, 0], [4.0, 5.0, 6.0])
        np.testing.assert_allclose(arrays["U_imag"][0, 0], [0.4, 0.5, 0.6])
        self.assertEqual(metadata["field_outputs"]["U"]["components"], ["U1", "U2", "U3"])

    def test_extract_field_arrays_falls_back_when_bulk_conjugate_width_is_inconsistent(self):
        nodes = [extractor.NodeRef("PART-1-1", 1, (0.0, 0.0, 0.0))]
        field = FakeFieldOutput(
            [FakeValue("PART-1-1", 1, (7.0, 8.0, 9.0), (0.7, 0.8, 0.9))],
            component_labels=("U1", "U2", "U3"),
        )
        field.bulkDataBlocks = [
            FakeBulkBlock(
                "PART-1-1",
                [1],
                [[70.0, 71.0, 72.0]],
                [[9.7, 9.8]],
                ["U1", "U2", "U3"],
            )
        ]
        step = FakeStep([FakeFrame(5.0, {"U": field})])

        arrays, metadata = extractor.extract_field_arrays(step, nodes, ["U"])

        np.testing.assert_allclose(arrays["U_real"][0, 0], [7.0, 8.0, 9.0])
        np.testing.assert_allclose(arrays["U_imag"][0, 0], [0.7, 0.8, 0.9])
        self.assertEqual(metadata["field_outputs"]["U"]["components"], ["U1", "U2", "U3"])

    def test_extract_field_arrays_can_filter_frequency_range(self):
        nodes = [extractor.NodeRef("PART-1-1", 1, (0.0, 0.0, 0.0))]
        step = FakeStep(
            [
                FakeFrame(
                    5.0,
                    {"U": FakeFieldOutput([FakeValue("PART-1-1", 1, (1.0, 2.0, 3.0))])},
                ),
                FakeFrame(
                    10.0,
                    {"U": FakeFieldOutput([FakeValue("PART-1-1", 1, (4.0, 5.0, 6.0))])},
                ),
                FakeFrame(
                    15.0,
                    {"U": FakeFieldOutput([FakeValue("PART-1-1", 1, (7.0, 8.0, 9.0))])},
                ),
            ]
        )

        arrays, metadata = extractor.extract_field_arrays(
            step,
            nodes,
            ["U"],
            frequency_min=7.5,
            frequency_max=12.5,
        )

        self.assertEqual(arrays["frequencies"].tolist(), [10.0])
        self.assertEqual(arrays["U_real"].shape, (1, 1, 3))
        self.assertEqual(arrays["U_real"][0, 0].tolist(), [4.0, 5.0, 6.0])
        self.assertEqual(metadata["array_shapes"]["frequencies"], [1])

    def test_extract_field_arrays_reads_all_values_without_passing_none_region(self):
        nodes = [extractor.NodeRef("PART-1-1", 1, (0.0, 0.0, 0.0))]
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
        nodes = [extractor.NodeRef("PART-1-1", 1, (0.0, 0.0, 0.0))]
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
        self.assertEqual(metadata["field_outputs"]["POR"]["components"], ["POR"])
        self.assertEqual(metadata["array_layouts"]["POR_real"], ["frame", "node", "component"])

    def test_extract_field_arrays_supports_element_integration_point_outputs(self):
        nodes = [extractor.NodeRef("PART-1-1", 1, (0.0, 0.0, 0.0))]
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
                            ],
                            component_labels=("S11", "S22", "S33", "S12", "S13", "S23"),
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
                            ],
                            component_labels=("S11", "S22", "S33", "S12", "S13", "S23"),
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
            metadata["field_outputs"]["S"]["components"],
            ["S11", "S22", "S33", "S12", "S13", "S23"],
        )
        self.assertEqual(
            metadata["field_outputs"]["S"]["array_layout"],
            ["frame", "element_point", "component"],
        )
        self.assertEqual(
            metadata["array_layouts"]["S_real"],
            ["frame", "element_point", "component"],
        )
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
            "node_coordinates": np.array([[1.2, 0.0, 0.0]]),
            "U_real": np.array([[[1.0, 2.0, 3.0]]]),
            "U_imag": np.array([[[0.1, 0.2, 0.3]]]),
        }
        metadata = {
            "source_odb": "data/test1.odb",
            "step": "HARMONIC_RESPONSE",
            "fields": ["U"],
            "array_layouts": {"U_real": ["frame", "node", "component"]},
            "warnings": [],
        }

        tmpdir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "unit_test")
        npz_path = os.path.join(tmpdir, "nested", "data.npz")
        json_path = os.path.join(tmpdir, "nested", "metadata.json")

        extractor.save_npz(npz_path, arrays)
        extractor.save_metadata(json_path, metadata)

        loaded = np.load(npz_path)
        self.assertEqual(loaded["node_labels"].tolist(), [25])
        self.assertEqual(loaded["node_coordinates"].tolist(), [[1.2, 0.0, 0.0]])
        with open(json_path, "r", encoding="utf-8") as stream:
            saved_metadata = json.load(stream)
        self.assertEqual(saved_metadata["fields"], ["U"])
        self.assertEqual(saved_metadata["step"], "HARMONIC_RESPONSE")

    def test_csv_output_arguments_are_not_supported(self):
        with self.assertRaises(SystemExit):
            extractor.parse_args(["--csv-output", "node_set_data.csv"])

        with self.assertRaises(SystemExit):
            extractor.parse_args(["--csv-components", "V=1,total"])

    def test_build_metadata_records_node_coordinates_once(self):
        nodes = [
            extractor.NodeRef("PART-1-1", 1, (0.0, 0.0, 0.0)),
            extractor.NodeRef("PART-1-1", 2, (1.0, 2.0, 3.0)),
        ]
        arrays = {
            "frequencies": np.array([5.0]),
            "node_labels": np.array([1, 2]),
            "node_coordinates": np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]]),
        }
        extraction_metadata = {
            "array_shapes": {
                "frequencies": [1],
                "node_labels": [2],
                "node_coordinates": [2, 3],
            },
            "array_layouts": {
                "frequencies": ["frame"],
                "node_labels": ["node"],
                "node_coordinates": ["node", "coordinate"],
            },
            "field_outputs": {},
            "warnings": [],
        }

        metadata = extractor.build_metadata(
            "data/test1.odb",
            "HARMONIC_RESPONSE",
            [],
            nodes,
            arrays,
            extraction_metadata,
        )

        self.assertEqual(metadata["nodes"][0]["coordinates"], [0.0, 0.0, 0.0])
        self.assertEqual(metadata["nodes"][1]["coordinates"], [1.0, 2.0, 3.0])
        self.assertNotIn("node_labels", metadata)
        self.assertNotIn("node_coordinates", metadata)
        self.assertNotIn("frequencies", metadata)
        self.assertEqual(metadata["array_layouts"]["node_coordinates"], ["node", "coordinate"])

    def test_build_metadata_records_tool_and_command_provenance(self):
        nodes = [extractor.NodeRef("PART-1-1", 1, (0.0, 0.0, 0.0))]
        arrays = {
            "frequencies": np.array([5.0]),
            "node_labels": np.array([1]),
            "node_coordinates": np.array([[0.0, 0.0, 0.0]]),
        }
        extraction_metadata = {
            "array_shapes": {
                "frequencies": [1],
                "node_labels": [1],
                "node_coordinates": [1, 3],
            },
            "array_layouts": {
                "frequencies": ["frame"],
                "node_labels": ["node"],
                "node_coordinates": ["node", "coordinate"],
            },
            "field_outputs": {},
            "warnings": [],
        }

        metadata = extractor.build_metadata(
            "data/test1.odb",
            "HARMONIC_RESPONSE",
            ["U"],
            nodes,
            arrays,
            extraction_metadata,
            command_options={
                "fields": ["U"],
                "frequency_min": 5.0,
                "frequency_max": 50.0,
            },
        )

        self.assertEqual(metadata["tool"]["name"], "odb_extract.extractor")
        self.assertEqual(metadata["tool"]["metadata_schema_version"], 2)
        self.assertEqual(metadata["command_options"]["fields"], ["U"])
        self.assertEqual(metadata["command_options"]["frequency_min"], 5.0)
        self.assertEqual(metadata["command_options"]["frequency_max"], 50.0)

    def test_node_sets_argument_parsing(self):
        from odb_extract.extractor import parse_args

        args = parse_args(["--node-sets", "NSET_TOP", "NSET_BOTTOM"])
        self.assertEqual(args.node_sets, ["NSET_TOP", "NSET_BOTTOM"])

    def test_list_node_sets_argument_parsing(self):
        from odb_extract.extractor import parse_args

        args = parse_args(["--list-node-sets"])
        self.assertTrue(args.list_node_sets)

    def test_node_sets_default_is_none(self):
        from odb_extract.extractor import parse_args

        args = parse_args([])
        self.assertIsNone(args.node_sets)
        self.assertFalse(args.list_node_sets)

    def test_collect_nodes_filters_by_node_set(self):
        from odb_extract.extractor import collect_nodes

        # Build a minimal mock ODB
        fake_node_a = mock.Mock()
        fake_node_a.label = 1
        fake_node_a.coordinates = (0.0, 0.0, 0.0)
        fake_node_a.instanceName = "PART-1-1"

        fake_node_b = mock.Mock()
        fake_node_b.label = 2
        fake_node_b.coordinates = (1.0, 0.0, 0.0)
        fake_node_b.instanceName = "PART-1-1"

        fake_instance = mock.Mock()
        fake_instance.nodes = [fake_node_a, fake_node_b]

        fake_nset = mock.Mock()
        fake_nset.nodes = [fake_node_a]  # only node 1 is in the set

        fake_assembly = mock.Mock()
        fake_assembly.instances = {"PART-1-1": fake_instance}
        fake_assembly.nodeSets = {"NSET_TOP": fake_nset}

        fake_odb = mock.Mock()
        fake_odb.rootAssembly = fake_assembly

        warnings = []
        nodes = collect_nodes(
            fake_odb,
            node_set_names=["NSET_TOP"],
            warnings=warnings,
        )

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].label, 1)
        self.assertEqual(warnings, [])

    def test_collect_nodes_filters_by_node_set_node_arrays(self):
        from odb_extract.extractor import collect_nodes

        class FakeNodeArray(object):
            def __init__(self, nodes, instance_name):
                self.nodes = nodes
                self.instanceName = instance_name

            def __iter__(self):
                return iter(self.nodes)

        fake_node_a = FakeNode(1, (0.0, 0.0, 0.0))
        fake_node_b = FakeNode(2, (1.0, 0.0, 0.0))

        fake_instance = mock.Mock()
        fake_instance.nodes = [fake_node_a, fake_node_b]

        fake_nset = mock.Mock()
        fake_nset.nodes = [FakeNodeArray([fake_node_a], "PART-1-1")]

        fake_assembly = mock.Mock()
        fake_assembly.instances = {"PART-1-1": fake_instance}
        fake_assembly.nodeSets = {"NSET_TOP": fake_nset}

        fake_odb = mock.Mock()
        fake_odb.rootAssembly = fake_assembly

        nodes = collect_nodes(fake_odb, node_set_names=["NSET_TOP"])

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].label, 1)

    def test_collect_nodes_and_combines_filters(self):
        from odb_extract.extractor import collect_nodes

        fake_node_a = mock.Mock()
        fake_node_a.label = 1
        fake_node_a.coordinates = (0.0, 0.0, 0.0)
        fake_node_a.instanceName = "PART-1-1"

        fake_node_b = mock.Mock()
        fake_node_b.label = 2
        fake_node_b.coordinates = (1.0, 0.0, 0.0)
        fake_node_b.instanceName = "PART-1-2"

        fake_node_c = mock.Mock()
        fake_node_c.label = 3
        fake_node_c.coordinates = (2.0, 0.0, 0.0)
        fake_node_c.instanceName = "PART-1-1"

        inst1 = mock.Mock()
        inst1.nodes = [fake_node_a, fake_node_c]
        inst2 = mock.Mock()
        inst2.nodes = [fake_node_b]

        fake_nset = mock.Mock()
        fake_nset.nodes = [fake_node_a, fake_node_b]  # across two instances

        fake_assembly = mock.Mock()
        fake_assembly.instances = {"PART-1-1": inst1, "PART-1-2": inst2}
        fake_assembly.nodeSets = {"NSET_ALL": fake_nset}

        fake_odb = mock.Mock()
        fake_odb.rootAssembly = fake_assembly

        # Filter: only PART-1-1 instances AND node labels 1,3 AND NSET_ALL
        nodes = collect_nodes(
            fake_odb,
            instances=["PART-1-1"],
            node_labels=[1, 3],
            node_set_names=["NSET_ALL"],
        )

        # node_a: PART-1-1 + label 1 + in NSET_ALL → included
        # node_c: PART-1-1 + label 3 + NOT in NSET_ALL → excluded
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].label, 1)

    def test_node_set_not_found_emits_warning(self):
        from odb_extract.extractor import collect_nodes

        fake_node = mock.Mock()
        fake_node.label = 1
        fake_node.coordinates = (0.0, 0.0, 0.0)
        fake_node.instanceName = "PART-1-1"

        fake_instance = mock.Mock()
        fake_instance.nodes = [fake_node]

        fake_assembly = mock.Mock()
        fake_assembly.instances = {"PART-1-1": fake_instance}
        fake_assembly.nodeSets = {}  # empty node sets

        fake_odb = mock.Mock()
        fake_odb.rootAssembly = fake_assembly

        warnings = []
        nodes = collect_nodes(
            fake_odb,
            node_set_names=["NONEXISTENT"],
            warnings=warnings,
        )

        self.assertEqual(len(nodes), 0)
        self.assertEqual(len(warnings), 1)
        self.assertIn("NONEXISTENT", warnings[0])

    def test_collect_nodes_without_node_set_returns_all(self):
        from odb_extract.extractor import collect_nodes

        fake_node_a = mock.Mock()
        fake_node_a.label = 1
        fake_node_a.coordinates = (0.0, 0.0, 0.0)
        fake_node_a.instanceName = "PART-1-1"

        fake_node_b = mock.Mock()
        fake_node_b.label = 2
        fake_node_b.coordinates = (1.0, 0.0, 0.0)
        fake_node_b.instanceName = "PART-1-1"

        fake_instance = mock.Mock()
        fake_instance.nodes = [fake_node_a, fake_node_b]

        fake_assembly = mock.Mock()
        fake_assembly.instances = {"PART-1-1": fake_instance}
        fake_assembly.nodeSets = {}

        fake_odb = mock.Mock()
        fake_odb.rootAssembly = fake_assembly

        nodes = collect_nodes(fake_odb, node_set_names=None)
        self.assertEqual(len(nodes), 2)


if __name__ == "__main__":
    unittest.main()
