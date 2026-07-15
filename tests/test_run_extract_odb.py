import contextlib
import inspect
import json
import os
import unittest
from unittest import mock

import numpy as np

from odb_extract import launcher, merge_gui, npz_export


class LauncherTests(unittest.TestCase):
    class FakeVar(object):
        def __init__(self, value=""):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    def _write_cache_source(self, name="cache-source"):
        directory = self._cache_validator_test_dir(name)
        data_path = os.path.join(directory, "model_point_data.npz")
        metadata_path = os.path.join(directory, "model_point_metadata.json")
        np.savez_compressed(
            data_path,
            frequencies=np.array([5.0]),
            node_labels=np.array([1]),
            node_coordinates=np.array([[0.0, 0.0, 0.0]]),
            U_real=np.array([[[1.0]]]),
            U_imag=np.array([[[0.0]]]),
            node_set_0000_indices=np.array([0], dtype=np.int64),
        )
        metadata = {
            "fields": ["U"],
            "nodes": [{"instance": "PART-1-1", "label": 1}],
            "array_shapes": {
                "frequencies": [1],
                "node_labels": [1],
                "node_coordinates": [1, 3],
                "U_real": [1, 1, 1],
                "U_imag": [1, 1, 1],
                "node_set_0000_indices": [1],
            },
            "field_outputs": {
                "U": {
                    "location": "NODE",
                    "components": ["U1"],
                    "points": [{"instance": "PART-1-1", "node_label": 1}],
                }
            },
            "node_sets": {
                "SET_A": {"indices_key": "node_set_0000_indices", "member_count": 1}
            },
        }
        with open(metadata_path, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream)
        return data_path, metadata_path

    def _write_full_cache_metadata(self, path, odb_path, array_shapes):
        metadata = {
            "source_odb": os.path.abspath(odb_path),
            "step": "Step-1",
            "command_options": {"step": None},
            "fields": ["POR"],
            "array_shapes": array_shapes,
            "filters": {
                "instances": [],
                "node_labels": [],
                "node_sets": [],
                "frequency_min": None,
                "frequency_max": None,
            },
        }
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(metadata, stream)

    def _cache_validator_test_dir(self, name):
        path = os.path.abspath(
            os.path.join("work", "test-output", "cache-validator-tests", name)
        )
        os.makedirs(path, exist_ok=True)
        return path

    def test_build_widgets_uses_scrollable_main_canvas(self):
        build_source = inspect.getsource(launcher.ExtractOdbApp._build_widgets)
        update_source = inspect.getsource(launcher.ExtractOdbApp._update_main_scroll_region)

        self.assertIn("self.main_canvas", build_source)
        self.assertIn("yscrollcommand", build_source)
        self.assertIn("scrollregion", update_source)

    def test_build_widgets_has_inspect_odb_button(self):
        build_source = inspect.getsource(launcher.ExtractOdbApp._build_widgets)

        self.assertIn('UI_TEXT["inspect_odb"]', build_source)
        self.assertIn("command=self.inspect_odb", build_source)

    def test_build_widgets_has_merge_results_button(self):
        build_source = inspect.getsource(launcher.ExtractOdbApp._build_widgets)

        self.assertIn('UI_TEXT["merge_results"]', build_source)
        self.assertIn("command=self.open_merge_window", build_source)

    def test_build_widgets_has_npz_magnitude_export_button(self):
        build_source = inspect.getsource(launcher.ExtractOdbApp._build_widgets)

        self.assertIn('UI_TEXT["npz_magnitude_export"]', build_source)
        self.assertIn("command=self.open_npz_export_window", build_source)

    def test_open_npz_export_window_uses_converter_window(self):
        source = inspect.getsource(launcher.ExtractOdbApp.open_npz_export_window)

        self.assertIn("npz_export.MagnitudeCsvWindow(self.root)", source)

    def test_npz_export_window_reuses_core_functions(self):
        source = inspect.getsource(npz_export.MagnitudeCsvWindow)

        self.assertIn("inspect_source(", source)
        self.assertIn("estimate_export_rows(", source)
        self.assertIn("export_magnitude_csv(", source)

    def test_npz_export_filter_text_accepts_common_separators(self):
        self.assertEqual(
            npz_export._parse_filter_text("U1; U2, POR"),
            ["U1", "U2", "POR"],
        )

    def test_build_widgets_has_selected_field_cache_checkbox(self):
        build_source = inspect.getsource(launcher.ExtractOdbApp._build_widgets)

        self.assertIn('UI_TEXT["keep_full_cache"]', build_source)
        self.assertIn("self.keep_full_cache_var", build_source)

    def test_build_widgets_has_explicit_cache_source_controls(self):
        build_source = inspect.getsource(launcher.ExtractOdbApp._build_widgets)

        self.assertIn("self.source_mode_var", build_source)
        self.assertIn('UI_TEXT["cache_file"]', build_source)
        self.assertIn("self.choose_cache", build_source)

    def test_build_widgets_does_not_expose_metadata_path(self):
        build_source = inspect.getsource(launcher.ExtractOdbApp._build_widgets)

        self.assertNotIn('UI_TEXT["metadata_output"]', build_source)
        self.assertNotIn("self.choose_metadata", build_source)

    def test_build_widgets_only_exposes_checkbox_field_selection(self):
        build_source = inspect.getsource(launcher.ExtractOdbApp._build_widgets)

        self.assertNotIn('UI_TEXT["manual_fields"]', build_source)
        self.assertNotIn('UI_TEXT["point_fields"]', build_source)
        self.assertNotIn('UI_TEXT["select_default_fields"]', build_source)

    def test_discovered_fields_start_unchecked(self):
        source = inspect.getsource(launcher.ExtractOdbApp._show_discovered_fields)

        self.assertIn("BooleanVar(value=False)", source)
        self.assertNotIn("checked_any", source)
        self.assertNotIn("DEFAULT_FIELD_TEXT", source)

    def test_selected_fields_ignores_legacy_manual_text(self):
        app = object.__new__(launcher.ExtractOdbApp)
        app.field_vars = {}
        app.fields_var = self.FakeVar("POR")

        self.assertEqual(app._selected_fields(), [])

    def test_build_widgets_does_not_expose_csv_outputs(self):
        build_source = inspect.getsource(launcher.ExtractOdbApp._build_widgets)

        self.assertNotIn("point_output", build_source)
        self.assertNotIn("_build_csv_component_widgets", build_source)

    def test_node_set_worker_schedules_ui_update(self):
        worker_source = inspect.getsource(launcher.ExtractOdbApp._discover_node_sets_worker)

        self.assertIn("self._show_discovered_node_sets(metadata)", worker_source)
        self.assertIn("self.root.after(0, finish)", worker_source)

    def test_build_extraction_command_includes_abaqus_python_module_and_options(self):
        command = launcher.build_extraction_command(
            abaqus_command="abq2024",
            extractor_module="odb_extract.extractor",
            odb_path=r"D:\work\data\test1.odb",
            output_path=r"D:\work\output\data.npz",
            metadata_path=r"D:\work\output\meta.json",
            step_name="HARMONIC_RESPONSE",
            fields=["U", "A"],
            instances=["PART-1-1"],
            node_labels=[25, 30],
            frequency_min=5.0,
            frequency_max=50.0,
        )

        self.assertEqual(
            command,
            [
                "abq2024",
                "python",
                "-m",
                "odb_extract.extractor",
                "--odb",
                r"D:\work\data\test1.odb",
                "--output",
                r"D:\work\output\data.npz",
                "--metadata",
                r"D:\work\output\meta.json",
                "--step",
                "HARMONIC_RESPONSE",
                "--fields",
                "U",
                "A",
                "--instances",
                "PART-1-1",
                "--node-labels",
                "25",
                "30",
                "--frequency-min",
                "5.0",
                "--frequency-max",
                "50.0",
            ],
        )

    def test_build_extraction_command_omits_optional_arguments_when_not_set(self):
        command = launcher.build_extraction_command(
            abaqus_command="abaqus",
            extractor_module="odb_extract.extractor",
            odb_path="data/test1.odb",
        )

        self.assertEqual(
            command,
            ["abaqus", "python", "-m", "odb_extract.extractor", "--odb", "data/test1.odb"],
        )

    def test_default_extraction_command_uses_script_path_for_other_workdirs(self):
        command = launcher.build_extraction_command(
            abaqus_command="abaqus",
            odb_path="data/test1.odb",
        )

        self.assertEqual(command[:2], ["abaqus", "python"])
        self.assertNotIn("-m", command)
        self.assertEqual(os.path.basename(command[2]), "extractor.py")
        self.assertTrue(os.path.isabs(command[2]))

    def test_build_field_list_command_includes_list_fields_flag(self):
        command = launcher.build_field_list_command(
            abaqus_command="abaqus",
            extractor_module="odb_extract.extractor",
            odb_path="data/test1.odb",
            step_name="Step-1",
        )

        self.assertEqual(
            command,
            [
                "abaqus",
                "python",
                "-m",
                "odb_extract.extractor",
                "--odb",
                "data/test1.odb",
                "--list-fields",
                "--step",
                "Step-1",
            ],
        )

    def test_build_inspect_odb_command_includes_inspect_flag(self):
        command = launcher.build_inspect_odb_command(
            abaqus_command="abaqus",
            extractor_module="odb_extract.extractor",
            odb_path="data/test1.odb",
        )

        self.assertEqual(
            command,
            [
                "abaqus",
                "python",
                "-m",
                "odb_extract.extractor",
                "--odb",
                "data/test1.odb",
                "--inspect-odb",
            ],
        )

    def test_default_field_list_command_uses_script_path_for_other_workdirs(self):
        command = launcher.build_field_list_command(
            abaqus_command="abaqus",
            extractor_module=None,
            odb_path="data/test1.odb",
        )

        self.assertEqual(command[:2], ["abaqus", "python"])
        self.assertNotIn("-m", command)
        self.assertEqual(os.path.basename(command[2]), "extractor.py")
        self.assertTrue(os.path.isabs(command[2]))
        self.assertIn("--list-fields", command)

    def test_find_abaqus_command_prefers_explicit_value(self):
        self.assertEqual(
            launcher.find_abaqus_command(
                explicit_command="C:/SIMULIA/Commands/abaqus.bat",
                env={},
                which=lambda name: None,
            ),
            "C:/SIMULIA/Commands/abaqus.bat",
        )

    def test_find_abaqus_command_uses_path_candidates(self):
        def fake_which(name):
            if name == "abq2024":
                return r"C:\SIMULIA\Commands\abq2024.bat"
            return None

        self.assertEqual(
            launcher.find_abaqus_command(
                explicit_command=None,
                env={},
                which=fake_which,
            ),
            r"C:\SIMULIA\Commands\abq2024.bat",
        )

    def test_run_extraction_invokes_runner_and_returns_code(self):
        calls = []

        def fake_runner(command):
            calls.append(command)
            return 7

        code = launcher.run_extraction(
            abaqus_command="abaqus",
            extractor_module="odb_extract.extractor",
            odb_path="data/test1.odb",
            output_path=None,
            metadata_path=None,
            step_name=None,
            fields=None,
            runner=fake_runner,
            verbose=False,
        )

        self.assertEqual(code, 7)
        self.assertEqual(
            calls,
            [["abaqus", "python", "-m", "odb_extract.extractor", "--odb", "data/test1.odb"]],
        )

    def test_run_command_treats_logged_error_as_failure_when_process_returns_zero(self):
        messages = []

        class FakeProcess(object):
            stdout = ["startup\n", "ERROR: extraction failed\n"]

            def wait(self):
                return 0

        with mock.patch.object(launcher.subprocess, "Popen", return_value=FakeProcess()):
            code = launcher.run_command(["abaqus", "python", "extractor.py"], messages.append)

        self.assertEqual(code, 1)
        self.assertEqual(messages, ["startup", "ERROR: extraction failed"])

    def test_inspect_odb_structure_calls_runner_and_returns_metadata(self):
        calls = []

        def fake_runner(command):
            calls.append(command)
            return 0, '{"steps": {"Step-1": {"frame_count": 2}}}'

        metadata = launcher.inspect_odb_structure(
            abaqus_command="abaqus",
            extractor_module="odb_extract.extractor",
            odb_path="data/test1.odb",
            runner=fake_runner,
        )

        self.assertEqual(metadata["steps"]["Step-1"]["frame_count"], 2)
        self.assertEqual(
            calls,
            [
                [
                    "abaqus",
                    "python",
                    "-m",
                    "odb_extract.extractor",
                    "--odb",
                    "data/test1.odb",
                    "--inspect-odb",
                ]
            ],
        )

    def test_default_extractor_module_points_to_script_path(self):
        path = launcher.default_extractor_module()

        self.assertEqual(os.path.basename(path), "extractor.py")
        self.assertTrue(os.path.isabs(path))
        self.assertTrue(os.path.exists(path))

    def test_root_entrypoint_scripts_are_removed(self):
        project_root = os.path.dirname(os.path.dirname(__file__))
        self.assertFalse(os.path.exists(os.path.join(project_root, "Extract_data_ODB.py")))
        self.assertFalse(os.path.exists(os.path.join(project_root, "run_extract_odb.py")))
        self.assertFalse(os.path.exists(os.path.join(project_root, "interpolate_odb_points.py")))

    def test_parse_field_text_accepts_commas_and_whitespace(self):
        self.assertEqual(
            launcher.parse_field_text("U, UR  V\nA"),
            ["U", "UR", "V", "A"],
        )

    def test_parse_field_text_returns_none_for_blank_text(self):
        self.assertIsNone(launcher.parse_field_text("  ,  "))

    def test_parse_node_label_text_accepts_commas_and_whitespace(self):
        self.assertEqual(launcher.parse_node_label_text("25, 30\n45"), [25, 30, 45])

    def test_parse_node_label_text_returns_none_for_blank_text(self):
        self.assertIsNone(launcher.parse_node_label_text("  ,  "))

    def test_parse_node_label_text_rejects_non_integer(self):
        with self.assertRaises(ValueError):
            launcher.parse_node_label_text("25 A")

    def test_parse_optional_float_accepts_blank_and_number(self):
        self.assertIsNone(launcher.parse_optional_float("  "))
        self.assertEqual(launcher.parse_optional_float("12.5"), 12.5)

    def test_parse_optional_float_rejects_invalid_text(self):
        with self.assertRaises(ValueError):
            launcher.parse_optional_float("low")

    def test_parse_field_list_output_reads_json_line(self):
        metadata = launcher.parse_field_list_output(
            'Abaqus startup text\n{"fields": ["A", "U", "V"], "step": "Step-1"}\n'
        )

        self.assertEqual(metadata["fields"], ["A", "U", "V"])
        self.assertEqual(metadata["step"], "Step-1")

    def test_parse_field_list_output_reads_embedded_json(self):
        metadata = launcher.parse_field_list_output(
            'Abaqus startup text {"fields": ["U"], "step": "Step-1"}\n'
        )

        self.assertEqual(metadata["fields"], ["U"])

    def test_discover_fields_includes_output_when_json_is_missing(self):
        def fake_runner(command):
            return 0, "Abaqus startup\nERROR: script path not found\n"

        with self.assertRaises(ValueError) as context:
            launcher.discover_fields(
                abaqus_command="abaqus",
                extractor_module="odb_extract.extractor",
                odb_path="data/test1.odb",
                runner=fake_runner,
            )

        self.assertIn("script path not found", str(context.exception))

    def test_parse_inspect_odb_output_reads_embedded_json(self):
        metadata = launcher.parse_inspect_odb_output(
            'Abaqus startup text {"source_odb": "x.odb", "steps": {"Step-1": {"frame_count": 2}}}\n'
        )

        self.assertEqual(metadata["steps"]["Step-1"]["frame_count"], 2)

    def test_parse_node_set_list_output_reads_embedded_json(self):
        metadata = launcher.parse_node_set_list_output(
            'Abaqus startup text {"node_sets": ["PROBE_NODE"]}\n'
        )

        self.assertEqual(metadata["node_sets"], ["PROBE_NODE"])

    def test_parse_args_accepts_point_export_options(self):
        args = launcher.parse_args(
            [
                "--odb",
                "data/test1.odb",
                "--points",
                "points.xlsx",
                "--neighbors",
                "6",
                "--exact-tol",
                "1e-8",
            ]
        )

        self.assertEqual(args.points, "points.xlsx")
        self.assertEqual(args.neighbors, 6)
        self.assertEqual(args.exact_tol, 1.0e-8)

    def test_parse_args_rejects_csv_output(self):
        with self.assertRaises(SystemExit):
            launcher.parse_args(
                [
                    "--odb",
                    "data/test1.odb",
                    "--csv-output",
                    "output/node_set_data.csv",
                ]
            )

    def test_parse_args_rejects_csv_components(self):
        with self.assertRaises(SystemExit):
            launcher.parse_args(
                [
                    "--odb",
                    "data/test1.odb",
                    "--csv-components",
                    "V=1,3,total",
                ]
            )

    def test_parse_args_accepts_inspect_odb(self):
        args = launcher.parse_args(["--odb", "data/test1.odb", "--inspect-odb"])

        self.assertTrue(args.inspect_odb)

    def test_ui_text_is_chinese(self):
        self.assertEqual(launcher.UI_TEXT["window_title"], "Abaqus ODB 数据提取工具")
        self.assertEqual(launcher.UI_TEXT["run_button"], "开始提取")
        self.assertEqual(launcher.UI_TEXT["refresh_fields"], "读取场输出")
        self.assertEqual(launcher.UI_TEXT["select_all_fields"], "全选")
        self.assertEqual(launcher.UI_TEXT["clear_all_fields"], "全不选")
        self.assertEqual(
            launcher.UI_TEXT["keep_full_cache"],
            "保留并复用全模型已选场缓存",
        )

    def test_default_output_paths_use_odb_base_name(self):
        output_path, metadata_path = launcher.default_output_paths(
            r"D:\work\data\test1.odb",
            output_dir=r"D:\work\output",
        )

        self.assertEqual(output_path, r"D:\work\output\test1_point_data.npz")
        self.assertEqual(metadata_path, r"D:\work\output\test1_point_metadata.json")

    def test_default_output_paths_use_odb_directory_when_output_dir_is_omitted(self):
        output_path, metadata_path = launcher.default_output_paths(
            r"D:\work\data\test1.odb"
        )

        self.assertEqual(output_path, r"D:\work\data\output\test1_point_data.npz")
        self.assertEqual(
            metadata_path, r"D:\work\data\output\test1_point_metadata.json"
        )

    def test_metadata_path_for_output_pairs_data_and_metadata_names(self):
        self.assertEqual(
            launcher.metadata_path_for_output(
                r"D:\results\surface_point_data.npz"
            ),
            r"D:\results\surface_point_metadata.json",
        )
        self.assertEqual(
            launcher.metadata_path_for_output(r"D:\results\surface.npz"),
            r"D:\results\surface_metadata.json",
        )

    def test_launcher_rejects_removed_point_fields_option(self):
        with self.assertRaises(SystemExit):
            launcher.parse_args(
                [
                    "--odb",
                    "model.odb",
                    "--points",
                    "points.xlsx",
                    "--point-fields",
                    "POR",
                ]
            )

    def test_run_workflow_has_no_point_fields_parameter(self):
        self.assertNotIn(
            "point_fields",
            inspect.signature(launcher.run_workflow).parameters,
        )

    def test_default_full_cache_paths_are_next_to_point_output(self):
        data_path, metadata_path = launcher.default_full_cache_paths(
            r"D:\work\model.odb",
            r"D:\results\surface_points.npz",
        )

        self.assertEqual(data_path, r"D:\results\model_full_field_data.npz")
        self.assertEqual(metadata_path, r"D:\results\model_full_field_metadata.json")

    def test_default_cache_query_output_uses_point_file_name_in_cache_directory(self):
        output_path = launcher.default_cache_query_output_path(
            r"D:\cache\model_full_field_data.npz",
            r"D:\queries\surface.csv",
        )

        self.assertEqual(output_path, r"D:\cache\surface_point_data.npz")

    def test_load_cache_source_returns_node_fields_and_node_sets(self):
        data_path, metadata_path = self._write_cache_source("load-cache-source")

        source = launcher.load_cache_source(data_path)

        self.assertEqual(source["metadata_path"], metadata_path)
        self.assertEqual(source["fields"], ["U"])
        self.assertEqual(source["node_sets"], ["SET_A"])

    def test_load_cache_source_rejects_invalid_node_set_index(self):
        data_path, _metadata_path = self._write_cache_source("bad-cache-node-set")
        with np.load(data_path) as source:
            arrays = {key: source[key] for key in source.files}
        arrays["node_set_0000_indices"] = np.array([9], dtype=np.int64)
        np.savez_compressed(data_path, **arrays)

        with self.assertRaisesRegex(ValueError, "SET_A"):
            launcher.load_cache_source(data_path)

    def test_run_cached_query_dispatches_point_interpolation(self):
        calls = []

        code = launcher.run_cached_query(
            data_path="cache.npz",
            metadata_path="cache_metadata.json",
            points_path="points.csv",
            output_path="points_point_data.npz",
            metadata_output_path="points_point_metadata.json",
            fields=["U"],
            node_sets=["SET_A"],
            point_runner=lambda **kwargs: calls.append(kwargs),
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["data_path"], "cache.npz")
        self.assertEqual(calls[0]["points_path"], "points.csv")
        self.assertEqual(calls[0]["node_sets"], ["SET_A"])

    def test_run_cached_query_dispatches_node_set_subset_without_points(self):
        calls = []

        code = launcher.run_cached_query(
            data_path="cache.npz",
            metadata_path="cache_metadata.json",
            output_path="set_point_data.npz",
            metadata_output_path="set_point_metadata.json",
            fields=["U"],
            node_sets=["SET_A"],
            subset_runner=lambda **kwargs: calls.append(kwargs),
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["node_sets"], ["SET_A"])
        self.assertNotIn("points_path", calls[0])

    def test_run_cached_point_query_preserves_legacy_positional_signature(self):
        calls = []
        logs = []

        code = launcher.run_cached_point_query(
            "cache.npz",
            "cache_metadata.json",
            "points.csv",
            "points_point_data.npz",
            "points_point_metadata.json",
            ["U"],
            ["SET_A"],
            6,
            1.0e-8,
            lambda **kwargs: calls.append(kwargs),
            logs.append,
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["points_path"], "points.csv")
        self.assertEqual(calls[0]["output_path"], "points_point_data.npz")
        self.assertEqual(calls[0]["fields"], ["U"])
        self.assertEqual(calls[0]["neighbors"], 6)
        self.assertEqual(calls[0]["exact_tol"], 1.0e-8)
        self.assertEqual(logs, [launcher.UI_TEXT["starting_cache_query"]])

    def test_full_cache_is_invalid_when_selected_fields_change(self):
        metadata = {
            "source_odb": os.path.abspath("model.odb"),
            "step": "Step-1",
            "command_options": {"step": "Step-1"},
            "fields": ["POR"],
            "filters": {
                "instances": [],
                "node_labels": [],
                "node_sets": [],
                "frequency_min": None,
                "frequency_max": None,
            },
        }
        with mock.patch.object(launcher.os.path, "isfile", return_value=True), \
             mock.patch.object(
                 launcher.os.path, "getmtime", side_effect=[1.0, 2.0, 2.0]
             ), \
             mock.patch(
                 "builtins.open", mock.mock_open(read_data=json.dumps(metadata))
             ):
            valid = launcher._full_cache_is_valid(
                "model.odb",
                "cache.npz",
                "cache.json",
                "Step-1",
                ["POR", "U"],
                None,
                None,
                None,
                None,
                None,
            )

        self.assertFalse(valid)

    def test_full_cache_is_valid_for_default_step_selector(self):
        metadata = {
            "source_odb": os.path.abspath("model.odb"),
            "step": "Step-1",
            "command_options": {"step": None},
            "fields": ["POR", "U"],
            "array_shapes": {"POR_real": [1, 2, 1]},
            "filters": {
                "instances": [],
                "node_labels": [],
                "node_sets": [],
                "frequency_min": None,
                "frequency_max": None,
            },
        }
        with mock.patch.object(launcher.os.path, "isfile", return_value=True), \
             mock.patch.object(
                 launcher.os.path, "getmtime", side_effect=[1.0, 2.0, 2.0]
             ), \
             mock.patch(
                 "builtins.open", mock.mock_open(read_data=json.dumps(metadata))
             ), \
             mock.patch.object(launcher, "_npz_shapes_match", return_value=True):
            valid = launcher._full_cache_is_valid(
                "model.odb",
                "cache.npz",
                "cache.json",
                None,
                ["POR", "U"],
                None,
                None,
                None,
                None,
                None,
            )

        self.assertTrue(valid)

    def test_full_cache_is_invalid_without_raising_for_mixed_field_types(self):
        metadata = {
            "source_odb": os.path.abspath("model.odb"),
            "step": "Step-1",
            "command_options": {"step": None},
            "fields": ["POR", 1],
            "filters": {
                "instances": [],
                "node_labels": [],
                "node_sets": [],
                "frequency_min": None,
                "frequency_max": None,
            },
        }
        with mock.patch.object(launcher.os.path, "isfile", return_value=True), \
             mock.patch.object(
                 launcher.os.path, "getmtime", side_effect=[1.0, 2.0, 2.0]
             ), \
             mock.patch(
                 "builtins.open", mock.mock_open(read_data=json.dumps(metadata))
             ):
            valid = launcher._full_cache_is_valid(
                "model.odb",
                "cache.npz",
                "cache.json",
                None,
                ["POR", "U"],
                None,
                None,
                None,
                None,
                None,
            )

        self.assertFalse(valid)

    def test_full_cache_is_invalid_when_step_selector_changes(self):
        metadata = {
            "source_odb": os.path.abspath("model.odb"),
            "step": "Step-1",
            "command_options": {"step": "Step-1"},
            "fields": ["POR", "U"],
            "filters": {
                "instances": [],
                "node_labels": [],
                "node_sets": [],
                "frequency_min": None,
                "frequency_max": None,
            },
        }
        with mock.patch.object(launcher.os.path, "isfile", return_value=True), \
             mock.patch.object(
                 launcher.os.path, "getmtime", side_effect=[1.0, 2.0, 2.0]
             ), \
             mock.patch(
                 "builtins.open", mock.mock_open(read_data=json.dumps(metadata))
             ):
            valid = launcher._full_cache_is_valid(
                "model.odb",
                "cache.npz",
                "cache.json",
                None,
                ["POR", "U"],
                None,
                None,
                None,
                None,
                None,
            )

        self.assertFalse(valid)

    def test_full_cache_is_invalid_for_non_npz_data(self):
        with contextlib.nullcontext(
            self._cache_validator_test_dir("non-npz")
        ) as temp_dir:
            odb_path = os.path.join(temp_dir, "model.odb")
            data_path = os.path.join(temp_dir, "cache.npz")
            metadata_path = os.path.join(temp_dir, "cache.json")
            open(odb_path, "wb").close()
            with open(data_path, "wb") as stream:
                stream.write(b"not an npz")
            self._write_full_cache_metadata(
                metadata_path, odb_path, {"POR_real": [1, 2, 1]}
            )

            valid = launcher._full_cache_is_valid(
                odb_path,
                data_path,
                metadata_path,
                None,
                ["POR"],
                None,
                None,
                None,
                None,
                None,
            )

        self.assertFalse(valid)

    def test_full_cache_is_invalid_when_npz_key_is_missing(self):
        with contextlib.nullcontext(
            self._cache_validator_test_dir("missing-key")
        ) as temp_dir:
            odb_path = os.path.join(temp_dir, "model.odb")
            data_path = os.path.join(temp_dir, "cache.npz")
            metadata_path = os.path.join(temp_dir, "cache.json")
            open(odb_path, "wb").close()
            np.savez_compressed(data_path, POR_real=np.zeros((1, 2, 1)))
            self._write_full_cache_metadata(
                metadata_path,
                odb_path,
                {"POR_real": [1, 2, 1], "POR_imag": [1, 2, 1]},
            )

            valid = launcher._full_cache_is_valid(
                odb_path,
                data_path,
                metadata_path,
                None,
                ["POR"],
                None,
                None,
                None,
                None,
                None,
            )

        self.assertFalse(valid)

    def test_full_cache_is_invalid_when_npz_shape_differs_from_metadata(self):
        with contextlib.nullcontext(
            self._cache_validator_test_dir("shape-mismatch")
        ) as temp_dir:
            odb_path = os.path.join(temp_dir, "model.odb")
            data_path = os.path.join(temp_dir, "cache.npz")
            metadata_path = os.path.join(temp_dir, "cache.json")
            open(odb_path, "wb").close()
            np.savez_compressed(data_path, POR_real=np.zeros((1, 2, 1)))
            self._write_full_cache_metadata(
                metadata_path, odb_path, {"POR_real": [1, 3, 1]}
            )

            valid = launcher._full_cache_is_valid(
                odb_path,
                data_path,
                metadata_path,
                None,
                ["POR"],
                None,
                None,
                None,
                None,
                None,
            )

        self.assertFalse(valid)

    def test_run_workflow_extracts_then_interpolates_points(self):
        calls = []

        def fake_extraction(**kwargs):
            calls.append(("extract", kwargs))
            return 0

        def fake_points(**kwargs):
            calls.append(("points", kwargs))
            return [{"point_id": "p1"}]

        code = launcher.run_workflow(
            abaqus_command="abaqus",
            extractor_module="odb_extract.extractor",
            odb_path=r"D:\work\data\test1.odb",
            output_path=r"D:\work\output\data.npz",
            metadata_path=r"D:\work\output\meta.json",
            fields=["U"],
            points_path=r"D:\work\points.csv",
            neighbors=5,
            exact_tol=1.0e-8,
            extraction_runner=fake_extraction,
            point_runner=fake_points,
            verbose=False,
        )

        self.assertEqual(code, 0)
        self.assertEqual([call[0] for call in calls], ["extract", "points"])
        self.assertEqual(calls[0][1]["fields"], ["U"])
        self.assertNotEqual(calls[0][1]["output_path"], r"D:\work\output\data.npz")
        self.assertNotEqual(calls[0][1]["metadata_path"], r"D:\work\output\meta.json")
        self.assertEqual(calls[1][1]["output_path"], r"D:\work\output\data.npz")
        self.assertEqual(calls[1][1]["metadata_output_path"], r"D:\work\output\meta.json")
        self.assertEqual(calls[1][1]["points_path"], r"D:\work\points.csv")
        self.assertIsNone(calls[1][1]["fields"])
        self.assertEqual(calls[1][1]["neighbors"], 5)
        self.assertEqual(calls[1][1]["exact_tol"], 1.0e-8)

    def test_run_workflow_reuses_valid_full_cache_without_extraction(self):
        calls = []

        def extraction_runner(**kwargs):
            calls.append(("extract", kwargs))
            return 0

        def point_runner(**kwargs):
            calls.append(("points", kwargs))

        with contextlib.nullcontext(
            self._cache_validator_test_dir("valid-hit")
        ) as temp_dir:
            odb_path = os.path.join(temp_dir, "model.odb")
            point_output_path = os.path.join(temp_dir, "surface_points.npz")
            point_metadata_path = os.path.join(temp_dir, "surface_points.json")
            cache_path, cache_metadata_path = launcher.default_full_cache_paths(
                odb_path, point_output_path
            )
            open(odb_path, "wb").close()
            np.savez_compressed(cache_path, POR_real=np.zeros((1, 2, 1)))
            self._write_full_cache_metadata(
                cache_metadata_path, odb_path, {"POR_real": [1, 2, 1]}
            )

            code = launcher.run_workflow(
                abaqus_command="abaqus",
                odb_path=odb_path,
                output_path=point_output_path,
                metadata_path=point_metadata_path,
                fields=["POR"],
                points_path=r"D:\work\points.csv",
                keep_full_cache=True,
                extraction_runner=extraction_runner,
                point_runner=point_runner,
                verbose=False,
            )

        self.assertEqual(code, 0)
        self.assertEqual([name for name, _kwargs in calls], ["points"])
        self.assertEqual(calls[0][1]["data_path"], cache_path)
        self.assertEqual(calls[0][1]["fields"], None)

    def test_run_workflow_skips_point_export_when_extraction_fails(self):
        point_calls = []

        def fake_extraction(**_kwargs):
            return 3

        def fake_points(**kwargs):
            point_calls.append(kwargs)

        code = launcher.run_workflow(
            abaqus_command="abaqus",
            extractor_module="odb_extract.extractor",
            odb_path="data/test1.odb",
            points_path="points.csv",
            extraction_runner=fake_extraction,
            point_runner=fake_points,
            verbose=False,
        )

        self.assertEqual(code, 3)
        self.assertEqual(point_calls, [])

    def test_run_workflow_reports_missing_extraction_outputs_before_point_export(self):
        def fake_extraction(**_kwargs):
            return 0

        with self.assertRaises(RuntimeError) as context:
            launcher.run_workflow(
                abaqus_command="abaqus",
                extractor_module="odb_extract.extractor",
                odb_path=r"D:\work\data\test1.odb",
                output_path=r"D:\work\output\missing.npz",
                metadata_path=r"D:\work\output\missing.json",
                points_path=r"D:\work\points.csv",
                extraction_runner=fake_extraction,
                verbose=False,
            )

        self.assertIn("提取阶段未生成", str(context.exception))
        self.assertIn("odb_extract_missing", str(context.exception))

    def test_run_workflow_supplies_default_data_paths_for_point_export(self):
        calls = []

        def fake_extraction(**kwargs):
            calls.append(("extract", kwargs))
            return 0

        def fake_points(**kwargs):
            calls.append(("points", kwargs))
            return []

        code = launcher.run_workflow(
            abaqus_command="abaqus",
            extractor_module="odb_extract.extractor",
            odb_path=r"D:\work\data\test1.odb",
            output_path=None,
            metadata_path=None,
            points_path=r"D:\work\points.csv",
            extraction_runner=fake_extraction,
            point_runner=fake_points,
            verbose=False,
        )

        self.assertEqual(code, 0)
        default_npz, default_metadata = launcher.default_output_paths(r"D:\work\data\test1.odb")
        self.assertNotEqual(calls[0][1]["output_path"], default_npz)
        self.assertNotEqual(calls[0][1]["metadata_path"], default_metadata)
        self.assertEqual(calls[1][1]["output_path"], default_npz)
        self.assertEqual(calls[1][1]["metadata_output_path"], default_metadata)

    def test_run_workflow_supplies_default_paths_for_node_set_filter(self):
        calls = []

        def fake_extraction(**kwargs):
            calls.append(kwargs)
            return 0

        code = launcher.run_workflow(
            abaqus_command="abaqus",
            extractor_module="odb_extract.extractor",
            odb_path=r"D:\work\data\test1.odb",
            output_path=None,
            metadata_path=None,
            node_sets=["NSET_TOP"],
            extraction_runner=fake_extraction,
            verbose=False,
        )

        default_npz, default_metadata = launcher.default_output_paths(
            r"D:\work\data\test1.odb"
        )
        self.assertEqual(code, 0)
        self.assertEqual(calls[0]["output_path"], default_npz)
        self.assertEqual(calls[0]["metadata_path"], default_metadata)
        self.assertNotIn("csv_output_path", calls[0])

    def test_run_workflow_rejects_node_sets_with_points(self):
        with self.assertRaises(ValueError) as context:
            launcher.run_workflow(
                abaqus_command="abaqus",
                extractor_module="odb_extract.extractor",
                odb_path=r"D:\work\data\test1.odb",
                node_sets=["NSET_TOP"],
                points_path=r"D:\work\points.xlsx",
                extraction_runner=lambda **_kwargs: 0,
                point_runner=lambda **_kwargs: None,
                verbose=False,
            )

        self.assertIn("cannot be used together", str(context.exception))

    def test_validate_inputs_includes_point_export_options(self):
        app = object.__new__(launcher.ExtractOdbApp)
        app.odb_var = self.FakeVar("data/test1.odb")
        app.output_var = self.FakeVar("output/data.npz")
        app.step_var = self.FakeVar("Step-1")
        app.instances_var = self.FakeVar("PART-1-1")
        app.node_labels_var = self.FakeVar("1 2")
        app.frequency_min_var = self.FakeVar("5")
        app.frequency_max_var = self.FakeVar("50")
        app.points_var = self.FakeVar("points.csv")
        app.neighbors_var = self.FakeVar("6")
        app.exact_tol_var = self.FakeVar("1e-8")
        app.abaqus_var = self.FakeVar("abaqus")
        app.keep_full_cache_var = self.FakeVar(False)
        app.field_vars = {"U": self.FakeVar(True), "V": self.FakeVar(True)}
        app.node_sets_var = self.FakeVar("")
        app.node_set_vars = {}

        options = app._validate_inputs()

        self.assertEqual(options["points_path"], "points.csv")
        self.assertEqual(options["metadata_path"], "output/data_metadata.json")
        self.assertNotIn("point_output_path", options)
        self.assertNotIn("csv_components", options)
        self.assertNotIn("point_fields", options)
        self.assertEqual(options["neighbors"], 6)
        self.assertEqual(options["exact_tol"], 1.0e-8)

    def test_validate_inputs_includes_full_cache_option(self):
        app = launcher.ExtractOdbApp.__new__(launcher.ExtractOdbApp)
        app.odb_var = self.FakeVar("model.odb")
        app.abaqus_var = self.FakeVar("abaqus")
        app.field_vars = {"POR": self.FakeVar(True), "U": self.FakeVar(True)}
        app.node_labels_var = self.FakeVar("")
        app.frequency_min_var = self.FakeVar("")
        app.frequency_max_var = self.FakeVar("")
        app.neighbors_var = self.FakeVar("4")
        app.exact_tol_var = self.FakeVar("1e-9")
        app.node_sets_var = self.FakeVar("")
        app.instances_var = self.FakeVar("")
        app.output_var = self.FakeVar("points.npz")
        app.step_var = self.FakeVar("")
        app.points_var = self.FakeVar("points.csv")
        app.keep_full_cache_var = self.FakeVar(True)

        options = app._validate_inputs()

        self.assertTrue(options["keep_full_cache"])

    def test_validate_inputs_accepts_cache_mode_without_odb_or_abaqus(self):
        data_path, metadata_path = self._write_cache_source("validate-cache-mode")
        app = launcher.ExtractOdbApp.__new__(launcher.ExtractOdbApp)
        app.source_mode_var = self.FakeVar("cache")
        app.cache_var = self.FakeVar(data_path)
        app.output_var = self.FakeVar(os.path.join(os.path.dirname(data_path), "query.npz"))
        app.points_var = self.FakeVar("points.csv")
        app.neighbors_var = self.FakeVar("4")
        app.exact_tol_var = self.FakeVar("1e-9")
        app.field_vars = {"U": self.FakeVar(True)}
        app.node_sets_var = self.FakeVar("SET_A")

        options = app._validate_inputs()

        self.assertEqual(options["source_mode"], "cache")
        self.assertEqual(options["data_path"], data_path)
        self.assertEqual(options["metadata_path"], metadata_path)
        self.assertEqual(options["node_sets"], ["SET_A"])

    def test_validate_inputs_accepts_cache_node_set_without_points(self):
        data_path, metadata_path = self._write_cache_source("cache-node-set-mode")
        app = launcher.ExtractOdbApp.__new__(launcher.ExtractOdbApp)
        app.source_mode_var = self.FakeVar("cache")
        app.cache_var = self.FakeVar(data_path)
        app.output_var = self.FakeVar(
            os.path.join(os.path.dirname(data_path), "set_subset_data.npz")
        )
        app.points_var = self.FakeVar("")
        app.neighbors_var = self.FakeVar("not-used")
        app.exact_tol_var = self.FakeVar("not-used")
        app.field_vars = {"U": self.FakeVar(True)}
        app.node_sets_var = self.FakeVar("SET_A")

        with mock.patch("tkinter.messagebox.showerror"):
            options = app._validate_inputs()

        self.assertIsNotNone(options)
        self.assertEqual(options["source_mode"], "cache")
        self.assertIsNone(options["points_path"])
        self.assertEqual(options["metadata_path"], metadata_path)
        self.assertEqual(options["node_sets"], ["SET_A"])

    def test_validate_inputs_rejects_cache_output_overwriting_source(self):
        data_path, _metadata_path = self._write_cache_source("reject-cache-overwrite")
        app = launcher.ExtractOdbApp.__new__(launcher.ExtractOdbApp)
        app.source_mode_var = self.FakeVar("cache")
        app.cache_var = self.FakeVar(data_path)
        app.output_var = self.FakeVar(data_path)
        app.points_var = self.FakeVar("points.csv")
        app.neighbors_var = self.FakeVar("4")
        app.exact_tol_var = self.FakeVar("1e-9")
        app.field_vars = {"U": self.FakeVar(True)}
        app.node_sets_var = self.FakeVar("")

        with mock.patch("tkinter.messagebox.showerror") as showerror:
            options = app._validate_inputs()

        self.assertIsNone(options)
        self.assertTrue(showerror.called)

    def test_main_without_arguments_runs_gui(self):
        calls = []

        def fake_gui():
            calls.append("gui")
            return 0

        code = launcher.main([], gui_runner=fake_gui)

        self.assertEqual(code, 0)
        self.assertEqual(calls, ["gui"])

    def test_main_with_arguments_runs_cli(self):
        with mock.patch.object(launcher, "find_abaqus_command", return_value="abaqus"):
            with mock.patch.object(
                launcher, "run_workflow", return_value=0
            ) as run_workflow:
                code = launcher.main(["--odb", "data/test1.odb"])

        self.assertEqual(code, 0)
        self.assertEqual(run_workflow.call_count, 1)

    def test_cli_disables_verbose_output_without_console(self):
        with mock.patch.object(launcher.sys, "stdout", None):
            with mock.patch.object(launcher, "find_abaqus_command", return_value="abaqus"):
                with mock.patch.object(
                    launcher, "run_workflow", return_value=0
                ) as run_workflow:
                    code = launcher.run_cli(["--odb", "data/test1.odb"])

        self.assertEqual(code, 0)
        self.assertFalse(run_workflow.call_args[1]["verbose"])

    def test_main_with_points_runs_integrated_workflow(self):
        with mock.patch.object(launcher, "find_abaqus_command", return_value="abaqus"):
            with mock.patch.object(
                launcher, "run_workflow", return_value=0
            ) as run_workflow:
                code = launcher.main(
                    [
                        "--odb",
                        "data/test1.odb",
                        "--points",
                        "points.xlsx",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(run_workflow.call_args[1]["points_path"], "points.xlsx")
        self.assertNotIn("point_output_path", run_workflow.call_args[1])

    # --- Node set parsing ---

    def test_parse_node_set_text_accepts_spaces_and_commas(self):
        self.assertEqual(
            launcher.parse_node_set_text("NSET_TOP, NSET_BOTTOM  NSET_SIDE"),
            ["NSET_TOP", "NSET_BOTTOM", "NSET_SIDE"],
        )

    def test_parse_node_set_text_returns_none_for_blank(self):
        self.assertIsNone(launcher.parse_node_set_text("  ,  "))

    def test_build_node_set_list_command_includes_list_node_sets_flag(self):
        command = launcher.build_node_set_list_command(
            abaqus_command="abaqus",
            extractor_module="odb_extract.extractor",
            odb_path="data/test1.odb",
        )

        self.assertEqual(
            command,
            [
                "abaqus",
                "python",
                "-m",
                "odb_extract.extractor",
                "--odb",
                "data/test1.odb",
                "--list-node-sets",
            ],
        )

    def test_parse_node_set_list_output_reads_json_line(self):
        metadata = launcher.parse_node_set_list_output(
            'Abaqus startup text\n{"node_sets": ["NSET_TOP", "NSET_BOTTOM"], "source_odb": "test.odb"}\n'
        )

        self.assertEqual(metadata["node_sets"], ["NSET_TOP", "NSET_BOTTOM"])
        self.assertEqual(metadata["source_odb"], "test.odb")

    def test_parse_node_set_list_output_raises_on_missing_array(self):
        with self.assertRaises(ValueError):
            launcher.parse_node_set_list_output(
                '{"node_sets": "not_a_list"}\n'
            )

    def test_parse_node_set_list_output_raises_on_no_json(self):
        with self.assertRaises(ValueError) as context:
            launcher.parse_node_set_list_output("No JSON here.\n")

        self.assertIn("No JSON here.", str(context.exception))

    def test_discover_node_sets_includes_output_when_json_is_missing(self):
        def fake_runner(command):
            return 0, "Abaqus startup\nERROR: script path not found\n"

        with self.assertRaises(ValueError) as context:
            launcher.discover_node_sets(
                abaqus_command="abaqus",
                extractor_module="odb_extract.extractor",
                odb_path="data/test1.odb",
                runner=fake_runner,
            )

        self.assertIn("script path not found", str(context.exception))

    def test_discover_node_sets_calls_runner_and_returns_metadata(self):
        def fake_runner(command):
            return 0, '{"node_sets": ["NSET_A", "NSET_B"]}\n'

        metadata = launcher.discover_node_sets(
            abaqus_command="abaqus",
            extractor_module="odb_extract.extractor",
            odb_path="data/test1.odb",
            runner=fake_runner,
        )

        self.assertEqual(metadata["node_sets"], ["NSET_A", "NSET_B"])

    def test_discover_node_sets_raises_on_nonzero_exit(self):
        def fake_runner(command):
            return 1, "Error: ODB not found\n"

        with self.assertRaises(RuntimeError) as context:
            launcher.discover_node_sets(
                abaqus_command="abaqus",
                extractor_module="odb_extract.extractor",
                odb_path="data/test1.odb",
                runner=fake_runner,
            )

        self.assertIn("exit code 1", str(context.exception))

    # --- Command building with node sets ---

    def test_build_extraction_command_includes_node_sets(self):
        command = launcher.build_extraction_command(
            abaqus_command="abq2024",
            extractor_module="odb_extract.extractor",
            odb_path=r"D:\work\data\test1.odb",
            node_sets=["NSET_TOP", "NSET_BOTTOM"],
        )

        self.assertIn("--node-sets", command)
        nset_index = command.index("--node-sets")
        self.assertEqual(command[nset_index + 1], "NSET_TOP")
        self.assertEqual(command[nset_index + 2], "NSET_BOTTOM")
        self.assertNotIn("--csv-output", command)
        self.assertNotIn("--csv-components", command)

    def test_ui_text_has_node_set_labels(self):
        self.assertEqual(launcher.UI_TEXT["node_set_filter"], "节点集")
        self.assertEqual(launcher.UI_TEXT["refresh_node_sets"], "读取节点集")
        self.assertEqual(launcher.UI_TEXT["select_all_node_sets"], "全选")
        self.assertEqual(launcher.UI_TEXT["clear_all_node_sets"], "全不选")
        self.assertEqual(
            launcher.UI_TEXT["node_set_hint"],
            "请选择 ODB 文件以读取节点集。",
        )
        self.assertEqual(
            launcher.UI_TEXT["no_node_sets_found"],
            "未找到节点集。",
        )
        self.assertEqual(
            launcher.UI_TEXT["found_node_sets"],
            "已在 ODB 中找到 {count} 个节点集。",
        )

    def test_validate_inputs_includes_node_sets(self):
        app = object.__new__(launcher.ExtractOdbApp)
        app.odb_var = self.FakeVar("data/test1.odb")
        app.output_var = self.FakeVar("output/data.npz")
        app.step_var = self.FakeVar("Step-1")
        app.instances_var = self.FakeVar("PART-1-1")
        app.node_labels_var = self.FakeVar("")
        app.node_sets_var = self.FakeVar("NSET_TOP NSET_BOTTOM")
        app.frequency_min_var = self.FakeVar("")
        app.frequency_max_var = self.FakeVar("")
        app.points_var = self.FakeVar("")
        app.neighbors_var = self.FakeVar("4")
        app.exact_tol_var = self.FakeVar("")
        app.abaqus_var = self.FakeVar("abaqus")
        app.keep_full_cache_var = self.FakeVar(False)
        app.field_vars = {"U": self.FakeVar(True), "V": self.FakeVar(True)}

        options = app._validate_inputs()

        self.assertEqual(options["node_sets"], ["NSET_TOP", "NSET_BOTTOM"])

    def test_validate_inputs_rejects_node_sets_with_points(self):
        app = object.__new__(launcher.ExtractOdbApp)
        app.odb_var = self.FakeVar("data/test1.odb")
        app.output_var = self.FakeVar("output/data.npz")
        app.step_var = self.FakeVar("Step-1")
        app.instances_var = self.FakeVar("")
        app.node_labels_var = self.FakeVar("")
        app.node_sets_var = self.FakeVar("NSET_TOP")
        app.frequency_min_var = self.FakeVar("")
        app.frequency_max_var = self.FakeVar("")
        app.points_var = self.FakeVar("points.xlsx")
        app.neighbors_var = self.FakeVar("4")
        app.exact_tol_var = self.FakeVar("")
        app.abaqus_var = self.FakeVar("abaqus")
        app.field_vars = {"U": self.FakeVar(True), "V": self.FakeVar(True)}

        with mock.patch("tkinter.messagebox.showerror") as showerror:
            options = app._validate_inputs()

        self.assertIsNone(options)
        self.assertTrue(showerror.called)

    def test_run_merge_point_data_calls_runner(self):
        calls = []

        def runner(**kwargs):
            calls.append(kwargs)
            return {"frequencies": [1.0, 2.0]}, {
                "merge": {"frequency_min": 1.0, "frequency_max": 2.0}
            }

        logs = []
        result = merge_gui.run_merge_point_data(
            data_paths=["a_point_data.npz", "b_point_data.npz"],
            output_path="merged_point_data.npz",
            metadata_output_path="merged_point_metadata.json",
            duplicate_frequency_tolerance=1.0e-7,
            merge_runner=runner,
            log_callback=logs.append,
        )

        self.assertEqual(result["frequency_count"], 2)
        self.assertEqual(calls[0]["data_paths"], ["a_point_data.npz", "b_point_data.npz"])
        self.assertEqual(calls[0]["output_path"], "merged_point_data.npz")
        self.assertEqual(calls[0]["metadata_output_path"], "merged_point_metadata.json")
        self.assertEqual(calls[0]["duplicate_frequency_tolerance"], 1.0e-7)
        self.assertTrue(any("merged_point_data.npz" in message for message in logs))

    def test_merge_window_validate_inputs_requires_two_npz_files(self):
        window = object.__new__(merge_gui.MergePointDataWindow)
        window.data_paths = ["a_point_data.npz"]
        window.output_var = self.FakeVar("merged_point_data.npz")
        window.metadata_var = self.FakeVar("merged_point_metadata.json")
        window.duplicate_tol_var = self.FakeVar("1e-8")

        with mock.patch("tkinter.messagebox.showerror") as showerror:
            self.assertIsNone(window._validate_inputs())

        self.assertTrue(showerror.called)

    def test_merge_window_validate_inputs_requires_output_paths(self):
        window = object.__new__(merge_gui.MergePointDataWindow)
        window.data_paths = ["a_point_data.npz", "b_point_data.npz"]
        window.output_var = self.FakeVar("")
        window.metadata_var = self.FakeVar("merged_point_metadata.json")
        window.duplicate_tol_var = self.FakeVar("1e-8")

        with mock.patch("tkinter.messagebox.showerror") as showerror:
            self.assertIsNone(window._validate_inputs())

        self.assertTrue(showerror.called)

    def test_merge_window_validate_inputs_requires_paired_metadata(self):
        window = object.__new__(merge_gui.MergePointDataWindow)
        window.data_paths = [
            r"D:\work\a_point_data.npz",
            r"D:\work\b_point_data.npz",
        ]
        window.output_var = self.FakeVar("merged_point_data.npz")
        window.metadata_var = self.FakeVar("merged_point_metadata.json")
        window.duplicate_tol_var = self.FakeVar("1e-8")

        def exists(path):
            return not path.endswith("b_point_metadata.json")

        with mock.patch("os.path.exists", side_effect=exists):
            with mock.patch("tkinter.messagebox.showerror") as showerror:
                self.assertIsNone(window._validate_inputs())

        self.assertTrue(showerror.called)

    def test_merge_window_validate_inputs_rejects_invalid_tolerance(self):
        window = object.__new__(merge_gui.MergePointDataWindow)
        window.data_paths = ["a_point_data.npz", "b_point_data.npz"]
        window.output_var = self.FakeVar("merged_point_data.npz")
        window.metadata_var = self.FakeVar("merged_point_metadata.json")
        window.duplicate_tol_var = self.FakeVar("not-a-number")

        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("tkinter.messagebox.showerror") as showerror:
                self.assertIsNone(window._validate_inputs())

        self.assertTrue(showerror.called)


if __name__ == "__main__":
    unittest.main()
