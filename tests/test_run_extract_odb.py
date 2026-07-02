import os
import inspect
import unittest
from unittest import mock

from odb_extract import launcher


class LauncherTests(unittest.TestCase):
    class FakeVar(object):
        def __init__(self, value=""):
            self.value = value

        def get(self):
            return self.value

    def test_build_widgets_uses_scrollable_main_canvas(self):
        build_source = inspect.getsource(launcher.ExtractOdbApp._build_widgets)
        update_source = inspect.getsource(launcher.ExtractOdbApp._update_main_scroll_region)

        self.assertIn("self.main_canvas", build_source)
        self.assertIn("yscrollcommand", build_source)
        self.assertIn("scrollregion", update_source)

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
                "points.csv",
                "--point-output",
                "output/points.csv",
                "--point-fields",
                "U",
                "V",
                "--neighbors",
                "6",
                "--exact-tol",
                "1e-8",
            ]
        )

        self.assertEqual(args.points, "points.csv")
        self.assertEqual(args.point_output, "output/points.csv")
        self.assertEqual(args.point_fields, ["U", "V"])
        self.assertEqual(args.neighbors, 6)
        self.assertEqual(args.exact_tol, 1.0e-8)

    def test_parse_args_accepts_csv_output(self):
        args = launcher.parse_args(
            [
                "--odb",
                "data/test1.odb",
                "--csv-output",
                "output/node_set_data.csv",
            ]
        )

        self.assertEqual(args.csv_output, "output/node_set_data.csv")

    def test_parse_args_accepts_csv_components(self):
        args = launcher.parse_args(
            [
                "--odb",
                "data/test1.odb",
                "--csv-components",
                "V=1,3,total",
                "U=2",
            ]
        )

        self.assertEqual(args.csv_components, ["V=1,3,total", "U=2"])

    def test_ui_text_is_chinese(self):
        self.assertEqual(launcher.UI_TEXT["window_title"], "Abaqus ODB 数据提取工具")
        self.assertEqual(launcher.UI_TEXT["run_button"], "开始提取")
        self.assertEqual(launcher.UI_TEXT["refresh_fields"], "读取场输出")
        self.assertEqual(launcher.UI_TEXT["select_all_fields"], "全选")
        self.assertEqual(launcher.UI_TEXT["clear_all_fields"], "全不选")
        self.assertEqual(launcher.UI_TEXT["select_default_fields"], "默认字段")

    def test_choose_field_names_supports_all_none_and_default_modes(self):
        fields = ["A", "LE", "S", "U"]

        self.assertEqual(
            launcher.choose_field_names(fields, "all"),
            ["A", "LE", "S", "U"],
        )
        self.assertEqual(launcher.choose_field_names(fields, "none"), [])
        self.assertEqual(
            launcher.choose_field_names(fields, "default"),
            ["A", "U"],
        )

    def test_choose_field_names_handles_empty_default_field_text(self):
        with mock.patch.object(launcher, "DEFAULT_FIELD_TEXT", "  ,  "):
            self.assertEqual(
                launcher.choose_field_names(["A", "U"], "default"),
                [],
            )

    def test_choose_field_names_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            launcher.choose_field_names(["U"], "invalid")

    def test_default_output_paths_use_odb_base_name(self):
        output_path, metadata_path = launcher.default_output_paths(
            r"D:\work\data\test1.odb",
            output_dir=r"D:\work\output",
        )

        self.assertEqual(output_path, r"D:\work\output\test1_point_data.npz")
        self.assertEqual(metadata_path, r"D:\work\output\test1_point_metadata.json")

    def test_default_point_output_path_uses_odb_base_name(self):
        output_path = launcher.default_point_output_path(
            r"D:\work\data\test1.odb",
            output_dir=r"D:\work\output",
        )

        self.assertEqual(output_path, r"D:\work\output\test1_interpolated_points.csv")

    def test_default_csv_output_path_uses_odb_base_name(self):
        output_path = launcher.default_csv_output_path(
            r"D:\work\output\test1_point_data.npz"
        )

        self.assertEqual(output_path, r"D:\work\output\test1_node_set_data.csv")

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
            point_output_path=r"D:\work\output\points.csv",
            point_fields=["U"],
            neighbors=5,
            exact_tol=1.0e-8,
            extraction_runner=fake_extraction,
            point_runner=fake_points,
            verbose=False,
        )

        self.assertEqual(code, 0)
        self.assertEqual([call[0] for call in calls], ["extract", "points"])
        self.assertEqual(calls[0][1]["fields"], ["U"])
        self.assertEqual(calls[1][1]["data_path"], r"D:\work\output\data.npz")
        self.assertEqual(calls[1][1]["metadata_path"], r"D:\work\output\meta.json")
        self.assertEqual(calls[1][1]["points_path"], r"D:\work\points.csv")
        self.assertEqual(calls[1][1]["output_path"], r"D:\work\output\points.csv")
        self.assertEqual(calls[1][1]["fields"], ["U"])
        self.assertEqual(calls[1][1]["neighbors"], 5)
        self.assertEqual(calls[1][1]["exact_tol"], 1.0e-8)

    def test_run_workflow_passes_csv_components_to_point_export(self):
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
            output_path=r"D:\work\output\data.npz",
            metadata_path=r"D:\work\output\meta.json",
            fields=["V"],
            points_path=r"D:\work\points.csv",
            point_output_path=r"D:\work\output\points.csv",
            csv_components={"V": ["1", "total"]},
            extraction_runner=fake_extraction,
            point_runner=fake_points,
            verbose=False,
        )

        self.assertEqual(code, 0)
        self.assertEqual(calls[0][1]["csv_components"], {"V": ["1", "total"]})
        self.assertEqual(calls[1][1]["csv_components"], {"V": ["1", "total"]})

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
            point_output_path=None,
            extraction_runner=fake_extraction,
            point_runner=fake_points,
            verbose=False,
        )

        self.assertEqual(code, 0)
        self.assertEqual(calls[0][1]["output_path"], launcher.default_output_paths(r"D:\work\data\test1.odb")[0])
        self.assertEqual(calls[0][1]["metadata_path"], launcher.default_output_paths(r"D:\work\data\test1.odb")[1])
        self.assertEqual(calls[1][1]["output_path"], launcher.default_point_output_path(r"D:\work\data\test1.odb"))

    def test_run_workflow_supplies_default_csv_path_for_node_set_export(self):
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
        self.assertEqual(
            calls[0]["csv_output_path"],
            launcher.default_csv_output_path(default_npz),
        )

    def test_validate_inputs_includes_point_export_options(self):
        app = object.__new__(launcher.ExtractOdbApp)
        app.odb_var = self.FakeVar("data/test1.odb")
        app.output_var = self.FakeVar("output/data.npz")
        app.metadata_var = self.FakeVar("output/meta.json")
        app.step_var = self.FakeVar("Step-1")
        app.fields_var = self.FakeVar("U V")
        app.instances_var = self.FakeVar("PART-1-1")
        app.node_labels_var = self.FakeVar("1 2")
        app.frequency_min_var = self.FakeVar("5")
        app.frequency_max_var = self.FakeVar("50")
        app.points_var = self.FakeVar("points.csv")
        app.point_output_var = self.FakeVar("output/points.csv")
        app.point_fields_var = self.FakeVar("U")
        app.neighbors_var = self.FakeVar("6")
        app.exact_tol_var = self.FakeVar("1e-8")
        app.abaqus_var = self.FakeVar("abaqus")
        app.field_vars = {}
        app.node_sets_var = self.FakeVar("")
        app.node_set_vars = {}

        options = app._validate_inputs()

        self.assertEqual(options["points_path"], "points.csv")
        self.assertEqual(options["point_output_path"], "output/points.csv")
        self.assertEqual(options["point_fields"], ["U"])
        self.assertEqual(options["neighbors"], 6)
        self.assertEqual(options["exact_tol"], 1.0e-8)

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
                        "points.csv",
                        "--point-output",
                        "output/points.csv",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(run_workflow.call_args[1]["points_path"], "points.csv")
        self.assertEqual(run_workflow.call_args[1]["point_output_path"], "output/points.csv")

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
        with self.assertRaises(ValueError):
            launcher.parse_node_set_list_output("No JSON here.\n")

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

    def test_build_extraction_command_includes_csv_output(self):
        command = launcher.build_extraction_command(
            abaqus_command="abq2024",
            extractor_module="odb_extract.extractor",
            odb_path=r"D:\work\data\test1.odb",
            csv_output_path=r"D:\work\output\node_set_data.csv",
        )

        self.assertIn("--csv-output", command)
        csv_index = command.index("--csv-output")
        self.assertEqual(command[csv_index + 1], r"D:\work\output\node_set_data.csv")

    def test_build_extraction_command_includes_csv_components(self):
        command = launcher.build_extraction_command(
            abaqus_command="abq2024",
            extractor_module="odb_extract.extractor",
            odb_path=r"D:\work\data\test1.odb",
            csv_components={"V": ["1", "total"], "U": ["2"]},
        )

        self.assertIn("--csv-components", command)
        component_index = command.index("--csv-components")
        self.assertEqual(command[component_index + 1], "U=2")
        self.assertEqual(command[component_index + 2], "V=1,total")

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
        app.metadata_var = self.FakeVar("output/meta.json")
        app.step_var = self.FakeVar("Step-1")
        app.fields_var = self.FakeVar("U V")
        app.instances_var = self.FakeVar("PART-1-1")
        app.node_labels_var = self.FakeVar("")
        app.node_sets_var = self.FakeVar("NSET_TOP NSET_BOTTOM")
        app.frequency_min_var = self.FakeVar("")
        app.frequency_max_var = self.FakeVar("")
        app.points_var = self.FakeVar("")
        app.point_output_var = self.FakeVar("")
        app.point_fields_var = self.FakeVar("")
        app.neighbors_var = self.FakeVar("4")
        app.exact_tol_var = self.FakeVar("")
        app.abaqus_var = self.FakeVar("abaqus")
        app.field_vars = {}

        options = app._validate_inputs()

        self.assertEqual(options["node_sets"], ["NSET_TOP", "NSET_BOTTOM"])

    def test_validate_inputs_includes_csv_component_selection(self):
        app = object.__new__(launcher.ExtractOdbApp)
        app.odb_var = self.FakeVar("data/test1.odb")
        app.output_var = self.FakeVar("output/data.npz")
        app.metadata_var = self.FakeVar("output/meta.json")
        app.step_var = self.FakeVar("Step-1")
        app.fields_var = self.FakeVar("U V")
        app.instances_var = self.FakeVar("")
        app.node_labels_var = self.FakeVar("")
        app.node_sets_var = self.FakeVar("")
        app.frequency_min_var = self.FakeVar("")
        app.frequency_max_var = self.FakeVar("")
        app.points_var = self.FakeVar("")
        app.point_output_var = self.FakeVar("")
        app.point_fields_var = self.FakeVar("")
        app.neighbors_var = self.FakeVar("4")
        app.exact_tol_var = self.FakeVar("")
        app.abaqus_var = self.FakeVar("abaqus")
        app.field_vars = {"U": self.FakeVar(False), "V": self.FakeVar(True)}
        app.csv_component_vars = {
            "V": {
                "1": self.FakeVar(True),
                "2": self.FakeVar(False),
                "3": self.FakeVar(True),
                "total": self.FakeVar(True),
            }
        }

        options = app._validate_inputs()

        self.assertEqual(options["fields"], ["V"])
        self.assertEqual(options["csv_components"], {"V": ["1", "3", "total"]})


if __name__ == "__main__":
    unittest.main()
