import io
import json
import os
import tempfile
import unittest
from unittest import mock

from mesh_convert import cli
from mesh_convert import __main__ as mesh_main
from mesh_convert.config import DimMode, ElementTarget, MeshConfig, resolve_element_type
from mesh_convert.errors import MeshConversionError, UnsupportedFormatError
from mesh_convert.geometry_import import detect_input_format
from mesh_convert.inp_writer import ElementBlock, MeshData, write_inp
from mesh_convert.mesh_generator import enforce_target_policy
from mesh_convert.report import ConversionReport


class FormatDetectionTests(unittest.TestCase):
    def write_temp_file(self, suffix, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False)
        try:
            handle.write(text)
            return handle.name
        finally:
            handle.close()

    def test_step_extensions_are_accepted(self):
        path = self.write_temp_file(".step", "not inspected for regular step files")
        try:
            self.assertEqual(detect_input_format(path), "step")
        finally:
            os.remove(path)

    def test_ins_with_step_header_is_accepted_as_step(self):
        path = self.write_temp_file(
            ".ins",
            "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('sample'),'2;1');\n",
        )
        try:
            self.assertEqual(detect_input_format(path), "step")
        finally:
            os.remove(path)

    def test_unrecognized_ins_raises_clear_error(self):
        path = self.write_temp_file(".ins", "*NODE\n1, 0, 0, 0\n")
        try:
            with self.assertRaises(UnsupportedFormatError) as context:
                detect_input_format(path)
        finally:
            os.remove(path)

        self.assertIn(".ins", str(context.exception))
        self.assertIn("ISO-10303", str(context.exception))


class ConfigTests(unittest.TestCase):
    def test_resolve_element_type_uses_dimension_defaults(self):
        self.assertEqual(resolve_element_type(DimMode.THREE_D, None), "C3D8R")
        self.assertEqual(resolve_element_type(DimMode.TWO_D, None), "S4R")

    def test_resolve_element_type_rejects_shell_type_for_3d(self):
        with self.assertRaises(MeshConversionError):
            resolve_element_type(DimMode.THREE_D, "S4R")

    def test_cli_rejects_second_order_meshes_with_clear_exit_code(self):
        stderr = io.StringIO()
        with mock.patch("sys.stderr", stderr):
            code = cli.main(["input.step", "out.inp", "--order", "2"])

        self.assertEqual(code, 2)
        self.assertIn("Only first-order meshes are currently supported", stderr.getvalue())

    def test_cli_reports_missing_gmsh_dependency(self):
        stderr = io.StringIO()
        with mock.patch("sys.stderr", stderr):
            code = cli.main(["input.step", "out.inp"], gmsh_module=None)

        self.assertEqual(code, 3)
        self.assertIn("pip install gmsh", stderr.getvalue())

    def test_cli_reports_unrecognized_ins_before_gmsh_dependency(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".ins", delete=False)
        try:
            handle.write("*NODE\n1, 0, 0, 0\n")
            handle.close()
            stderr = io.StringIO()
            with mock.patch("sys.stderr", stderr):
                code = cli.main([handle.name, "out.inp"], gmsh_module=None)
        finally:
            os.remove(handle.name)

        self.assertEqual(code, 2)
        self.assertIn("ISO-10303", stderr.getvalue())

    def test_cli_treats_system_exit_without_code_as_success(self):
        class Parser:
            def parse_args(self, argv):
                raise SystemExit(None)

        with mock.patch("mesh_convert.cli.build_parser", return_value=Parser()):
            code = cli.main([])

        self.assertEqual(code, 0)


class MeshConvertLauncherTests(unittest.TestCase):
    def test_main_without_arguments_runs_gui(self):
        calls = []

        def fake_gui():
            calls.append("gui")
            return 0

        code = mesh_main.main([], gui_runner=fake_gui)

        self.assertEqual(code, 0)
        self.assertEqual(calls, ["gui"])

    def test_main_with_arguments_runs_cli(self):
        calls = []

        def fake_cli(argv):
            calls.append(list(argv))
            return 0

        code = mesh_main.main(["input.step", "out.inp"], cli_runner=fake_cli)

        self.assertEqual(code, 0)
        self.assertEqual(calls, [["input.step", "out.inp"]])


class MeshConvertGuiTests(unittest.TestCase):
    class FakeVar:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    def test_build_cli_args_from_gui_inputs(self):
        from mesh_convert.gui import MeshConvertApp

        app = object.__new__(MeshConvertApp)
        app.input_var = self.FakeVar("model.step")
        app.output_var = self.FakeVar("mesh.inp")
        app.size_var = self.FakeVar("2.5")
        app.dim_var = self.FakeVar("3d")
        app.target_var = self.FakeVar("hex")
        app.element_type_var = self.FakeVar("C3D8R")
        app.allow_degrade_var = self.FakeVar(True)
        app.log_var = self.FakeVar("mesh.log")
        app.report_var = self.FakeVar("mesh_report.json")

        args = app._build_cli_args()

        self.assertEqual(
            args,
            [
                "model.step",
                "mesh.inp",
                "--size",
                "2.5",
                "--dim",
                "3d",
                "--target",
                "hex",
                "--element-type",
                "C3D8R",
                "--allow-degrade",
                "--log",
                "mesh.log",
                "--report",
                "mesh_report.json",
            ],
        )

    def test_format_report_summary_shows_mesh_result_details(self):
        from mesh_convert.gui import format_report_summary

        summary = format_report_summary(
            {
                "status": "ok",
                "node_count": 12,
                "element_counts": {"C3D4": 2, "C3D8R": 4},
                "degraded": True,
                "warnings": ["3D hex target produced non-hex element types: C3D4."],
            }
        )

        self.assertIn("是否成功：是", summary)
        self.assertIn("节点数：12", summary)
        self.assertIn("单元数：6", summary)
        self.assertIn("单元类型统计：C3D4=2, C3D8R=4", summary)
        self.assertIn("是否发生 mixed 降级：是", summary)
        self.assertIn("警告信息：", summary)
        self.assertIn("3D hex target produced non-hex", summary)

    def test_build_cli_args_accepts_chinese_combo_values(self):
        from mesh_convert.gui import MeshConvertApp

        app = object.__new__(MeshConvertApp)
        app.input_var = self.FakeVar("model.step")
        app.output_var = self.FakeVar("mesh.inp")
        app.size_var = self.FakeVar("2.5")
        app.dim_var = self.FakeVar("三维")
        app.target_var = self.FakeVar("六面体")
        app.element_type_var = self.FakeVar("")
        app.allow_degrade_var = self.FakeVar(False)
        app.log_var = self.FakeVar("")
        app.report_var = self.FakeVar("")

        args = app._build_cli_args()

        self.assertIn("3d", args)
        self.assertIn("hex", args)

    def test_recommend_output_paths_from_input_file(self):
        from mesh_convert.gui import recommend_paths_from_input

        paths = recommend_paths_from_input("model.step")

        self.assertEqual(paths.output_path, "model.inp")
        self.assertEqual(paths.log_path, "model.log")
        self.assertEqual(paths.report_path, "model_report.json")

    def test_recommend_auxiliary_paths_from_output_file(self):
        from mesh_convert.gui import recommend_auxiliary_paths

        paths = recommend_auxiliary_paths("mesh_output.inp")

        self.assertEqual(paths.log_path, "mesh_output.log")
        self.assertEqual(paths.report_path, "mesh_output_report.json")

    def test_friendly_failure_message_explains_missing_gmsh(self):
        from mesh_convert.gui import format_friendly_failure

        message = format_friendly_failure(
            "mesh_convert: error: The gmsh Python package is required. "
            "Install it with: pip install gmsh"
        )

        self.assertIn("缺少 gmsh Python 包", message)
        self.assertIn("pip install gmsh", message)

    def test_friendly_failure_message_explains_mixed_fallback(self):
        from mesh_convert.gui import format_friendly_failure

        message = format_friendly_failure(
            "3D hex target produced non-hex element types: C3D4. "
            "Use --allow-degrade to write an explained mixed mesh."
        )

        self.assertIn("允许混合单元降级", message)
        self.assertIn("mixed 网格", message)


class MeshConvertPackagingTests(unittest.TestCase):
    def test_packaging_script_and_entrypoint_are_present(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script_path = os.path.join(root, "packaging", "build_mesh_convert_exe.ps1")
        entry_path = os.path.join(root, "packaging", "mesh_convert_gui_entry.py")

        self.assertTrue(os.path.isfile(script_path))
        self.assertTrue(os.path.isfile(entry_path))
        with open(script_path, "r", encoding="utf-8") as handle:
            script_text = handle.read()

        self.assertIn("PyInstaller", script_text)
        self.assertIn("mesh_convert_gui_entry.py", script_text)
        self.assertNotIn("Remove-Item -Recurse", script_text)
        self.assertNotIn("rm -rf", script_text)


class InpWriterTests(unittest.TestCase):
    def test_write_3d_hex_mesh_as_c3d8r(self):
        data = MeshData(
            nodes={
                1: (0.0, 0.0, 0.0),
                2: (1.0, 0.0, 0.0),
                3: (1.0, 1.0, 0.0),
                4: (0.0, 1.0, 0.0),
                5: (0.0, 0.0, 1.0),
                6: (1.0, 0.0, 1.0),
                7: (1.0, 1.0, 1.0),
                8: (0.0, 1.0, 1.0),
            },
            element_blocks=[
                ElementBlock("C3D8R", {1: (1, 2, 3, 4, 5, 6, 7, 8)}, "VOL_1")
            ],
            node_sets={"ALLNODES": [1, 2, 3, 4, 5, 6, 7, 8]},
            element_sets={"VOL_1": [1]},
            metadata={"target": "hex", "degraded": False},
        )
        fd, path = tempfile.mkstemp(suffix=".inp")
        os.close(fd)
        try:
            write_inp(path, data)
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        finally:
            os.remove(path)

        self.assertIn("*NODE", text)
        self.assertIn("*PART, NAME=MESH_CONVERT", text)
        self.assertIn("*ELEMENT, TYPE=C3D8R, ELSET=VOL_1", text)
        self.assertIn("1, 1, 2, 3, 4, 5, 6, 7, 8", text)
        self.assertIn("*NSET, NSET=ALLNODES", text)
        self.assertIn("*ELSET, ELSET=VOL_1", text)

    def test_write_2d_quad_mesh_as_s4r(self):
        data = MeshData(
            nodes={
                1: (0.0, 0.0, 0.0),
                2: (1.0, 0.0, 0.0),
                3: (1.0, 1.0, 0.0),
                4: (0.0, 1.0, 0.0),
            },
            element_blocks=[ElementBlock("S4R", {1: (1, 2, 3, 4)}, "SURF_1")],
            node_sets={"ALLNODES": [1, 2, 3, 4]},
            element_sets={"SURF_1": [1]},
            metadata={"target": "quad", "degraded": False},
        )
        fd, path = tempfile.mkstemp(suffix=".inp")
        os.close(fd)
        try:
            write_inp(path, data)
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        finally:
            os.remove(path)

        self.assertIn("*ELEMENT, TYPE=S4R, ELSET=SURF_1", text)
        self.assertIn("1, 1, 2, 3, 4", text)


class TargetPolicyTests(unittest.TestCase):
    def test_hex_target_fails_on_mixed_elements_without_degrade(self):
        report = ConversionReport()
        config = MeshConfig(
            input_path="input.step",
            output_path="out.inp",
            dim=DimMode.THREE_D,
            target=ElementTarget.HEX,
            size=1.0,
            allow_degrade=False,
        )

        with self.assertRaises(MeshConversionError):
            enforce_target_policy(config, {"C3D8R": 1, "C3D4": 3}, report)

    def test_hex_target_allows_mixed_elements_with_degrade_and_report_warning(self):
        report = ConversionReport()
        config = MeshConfig(
            input_path="input.step",
            output_path="out.inp",
            dim=DimMode.THREE_D,
            target=ElementTarget.HEX,
            size=1.0,
            allow_degrade=True,
        )

        enforce_target_policy(config, {"C3D8R": 1, "C3D4": 3}, report)

        self.assertTrue(report.degraded)
        self.assertTrue(any("hex" in warning.lower() for warning in report.warnings))


class ReportTests(unittest.TestCase):
    def test_report_writes_json(self):
        report = ConversionReport()
        report.add_warning("triangle fallback")
        report.element_counts["S3"] = 2
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            report.write_json(path)
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.loads(handle.read())
        finally:
            os.remove(path)

        self.assertEqual(payload["warnings"], ["triangle fallback"])
        self.assertEqual(payload["element_counts"], {"S3": 2})


if __name__ == "__main__":
    unittest.main()
