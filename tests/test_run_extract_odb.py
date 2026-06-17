import os
import unittest
from unittest import mock

import run_extract_odb as launcher


class LauncherTests(unittest.TestCase):
    def test_build_extraction_command_includes_abaqus_python_script_and_options(self):
        command = launcher.build_extraction_command(
            abaqus_command="abq2024",
            script_path=r"D:\work\Extract_data_ODB.py",
            odb_path=r"D:\work\data\test1.odb",
            output_path=r"D:\work\output\data.npz",
            metadata_path=r"D:\work\output\meta.json",
            step_name="HARMONIC_RESPONSE",
            fields=["U", "A"],
        )

        self.assertEqual(
            command,
            [
                "abq2024",
                "python",
                r"D:\work\Extract_data_ODB.py",
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
            ],
        )

    def test_build_extraction_command_omits_optional_arguments_when_not_set(self):
        command = launcher.build_extraction_command(
            abaqus_command="abaqus",
            script_path="Extract_data_ODB.py",
            odb_path="data/test1.odb",
        )

        self.assertEqual(
            command,
            ["abaqus", "python", "Extract_data_ODB.py", "--odb", "data/test1.odb"],
        )

    def test_build_field_list_command_includes_list_fields_flag(self):
        command = launcher.build_field_list_command(
            abaqus_command="abaqus",
            script_path="Extract_data_ODB.py",
            odb_path="data/test1.odb",
            step_name="Step-1",
        )

        self.assertEqual(
            command,
            [
                "abaqus",
                "python",
                "Extract_data_ODB.py",
                "--odb",
                "data/test1.odb",
                "--list-fields",
                "--step",
                "Step-1",
            ],
        )

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
            script_path="Extract_data_ODB.py",
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
            [["abaqus", "python", "Extract_data_ODB.py", "--odb", "data/test1.odb"]],
        )

    def test_default_extractor_script_points_to_project_script(self):
        script_path = launcher.default_extractor_script()

        self.assertEqual(os.path.basename(script_path), "Extract_data_ODB.py")

    def test_parse_field_text_accepts_commas_and_whitespace(self):
        self.assertEqual(
            launcher.parse_field_text("U, UR  V\nA"),
            ["U", "UR", "V", "A"],
        )

    def test_parse_field_text_returns_none_for_blank_text(self):
        self.assertIsNone(launcher.parse_field_text("  ,  "))

    def test_parse_field_list_output_reads_json_line(self):
        metadata = launcher.parse_field_list_output(
            'Abaqus startup text\n{"fields": ["A", "U", "V"], "step": "Step-1"}\n'
        )

        self.assertEqual(metadata["fields"], ["A", "U", "V"])
        self.assertEqual(metadata["step"], "Step-1")

    def test_ui_text_is_chinese(self):
        self.assertEqual(launcher.UI_TEXT["window_title"], "Abaqus ODB 数据提取工具")
        self.assertEqual(launcher.UI_TEXT["run_button"], "开始提取")
        self.assertEqual(launcher.UI_TEXT["refresh_fields"], "读取场输出")

    def test_default_output_paths_use_odb_base_name(self):
        output_path, metadata_path = launcher.default_output_paths(
            r"D:\work\data\test1.odb",
            output_dir=r"D:\work\output",
        )

        self.assertEqual(output_path, r"D:\work\output\test1_point_data.npz")
        self.assertEqual(metadata_path, r"D:\work\output\test1_point_metadata.json")

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
                launcher, "run_extraction", return_value=0
            ) as run_extraction:
                code = launcher.main(["--odb", "data/test1.odb"])

        self.assertEqual(code, 0)
        self.assertEqual(run_extraction.call_count, 1)


if __name__ == "__main__":
    unittest.main()
