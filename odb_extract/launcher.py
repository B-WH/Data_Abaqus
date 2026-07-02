"""Launcher for odb_extract.extractor.

This script runs under normal Python. It delegates ODB reading to Abaqus Python.
"""

from __future__ import print_function

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading

from odb_extract.extractor import default_csv_output_path, parse_csv_component_specs


ABAQUS_CANDIDATES = ("abaqus", "abq2024", "abq2023", "abq2022")
DEFAULT_EXTRACTOR_MODULE = "odb_extract.extractor"
DEFAULT_FIELD_TEXT = "U UR V VR A AR"
CSV_COMPONENT_OPTIONS = (
    ("1", "1方向"),
    ("2", "2方向"),
    ("3", "3方向"),
    ("total", "总和"),
)
UI_TEXT = {
    "window_title": "Abaqus ODB 数据提取工具",
    "ready": "就绪",
    "running": "运行中",
    "odb_file": "ODB 文件",
    "npz_output": "NPZ 输出",
    "metadata_output": "元数据 JSON",
    "points_file": "目标点 CSV",
    "point_output": "目标点输出 CSV",
    "point_fields": "目标点字段",
    "neighbors": "邻近点数量",
    "exact_tol": "精确命中容差",
    "abaqus_command": "Abaqus 命令",
    "manual_fields": "手动字段",
    "instance_filter": "实例过滤",
    "node_label_filter": "节点编号",
    "frequency_min": "频率下限",
    "frequency_max": "频率上限",
    "refresh_fields": "读取场输出",
    "inspect_odb": "检查 ODB 结构",
    "available_fields": "可用场输出",
    "csv_components": "CSV 分量",
    "csv_component_hint": "读取场输出后可选择 CSV 输出方向。",
    "field_hint": "请选择 ODB 文件以读取场输出。",
    "run_button": "开始提取",
    "browse": "浏览",
    "select_odb_title": "选择 Abaqus ODB 文件",
    "select_npz_title": "选择 NPZ 输出文件",
    "select_metadata_title": "选择元数据 JSON 输出文件",
    "select_points_title": "选择目标点 CSV 文件",
    "select_point_output_title": "选择目标点输出 CSV 文件",
    "no_fields_found": "未找到场输出。",
    "found_fields": "已在 Step {step} 中找到 {count} 个场输出。",
    "select_odb_first": "请先选择 ODB 文件，再读取场输出。",
    "empty_abaqus": "Abaqus 命令为空，已跳过场输出读取。",
    "discovering_fields": "正在读取场输出。",
    "inspecting_odb": "正在检查 ODB 结构。",
    "discovering_node_sets": "正在读取节点集。",
    "field_discovery_failed_log": "读取场输出失败：{error}",
    "field_discovery_failed_title": "读取场输出失败",
    "inspect_odb_failed_log": "检查 ODB 结构失败：{error}",
    "inspect_odb_failed_title": "检查 ODB 结构失败",
    "inspect_odb_finished_log": "ODB 结构：\n{summary}",
    "missing_odb_title": "缺少 ODB 文件",
    "missing_odb_message": "请先选择 ODB 文件。",
    "missing_abaqus_title": "缺少 Abaqus 命令",
    "missing_abaqus_message": "请设置 ABAQUS_COMMAND、将 Abaqus 加入 PATH，或输入 abq2024/abaqus 路径。",
    "no_fields_selected_title": "未选择场输出",
    "no_fields_selected_message": "请至少勾选一个场输出。",
    "invalid_node_labels_title": "节点编号格式错误",
    "invalid_node_labels_message": "节点编号只能填写整数，可用空格、逗号或分号分隔。",
    "invalid_frequency_title": "频率范围格式错误",
    "invalid_frequency_message": "频率上下限必须是数字，或留空。",
    "invalid_neighbors_title": "邻近点数量格式错误",
    "invalid_neighbors_message": "邻近点数量必须是正整数。",
    "invalid_exact_tol_title": "精确命中容差格式错误",
    "invalid_exact_tol_message": "精确命中容差必须是数字，或留空。",
    "starting_extraction": "开始 ODB 数据提取。",
    "starting_point_export": "开始目标点数据导出。",
    "point_export_finished_log": "目标点数据导出完成：{path}",
    "extraction_failed_title": "提取失败",
    "extraction_finished_log": "提取完成。",
    "extraction_finished_title": "提取完成",
    "extraction_finished_message": "ODB 数据提取完成。",
    "extraction_exit_code_log": "提取失败，退出代码为 {code}。",
    "extraction_exit_code_message": "Abaqus 退出代码为 {code}。请检查日志输出。",
    "select_all_fields": "全选",
    "clear_all_fields": "全不选",
    "select_default_fields": "默认字段",
    "node_set_filter": "节点集",
    "node_set_hint": "请选择 ODB 文件以读取节点集。",
    "no_node_sets_found": "未找到节点集。",
    "found_node_sets": "已在 ODB 中找到 {count} 个节点集。",
    "select_all_node_sets": "全选",
    "clear_all_node_sets": "全不选",
    "refresh_node_sets": "读取节点集",
    "node_set_discovery_failed": "读取节点集失败",
    "node_set_discovery_failed_log": "读取节点集失败：{error}",
    "select_odb_for_node_sets": "请先选择 ODB 文件，再读取节点集。",
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Launch Abaqus Python to extract nodal data from an ODB file."
    )
    parser.add_argument("--odb", help="ODB file to extract. Opens a file picker if omitted.")
    parser.add_argument("--output", help="Optional NPZ output path.")
    parser.add_argument("--metadata", help="Optional metadata JSON output path.")
    parser.add_argument("--csv-output", help="Optional node set long-table CSV output path.")
    parser.add_argument(
        "--csv-components",
        nargs="+",
        help="Optional CSV component selections, e.g. V=1,2,3,total.",
    )
    parser.add_argument("--step", help="Optional Abaqus step name.")
    parser.add_argument("--fields", nargs="+", help="Optional field names, e.g. U V A.")
    parser.add_argument("--instances", nargs="+", help="Optional instance names to include.")
    parser.add_argument("--node-labels", nargs="+", help="Optional node labels to include.")
    parser.add_argument(
        "--node-sets",
        nargs="+",
        help="Optional node set names to filter nodes by.",
    )
    parser.add_argument("--frequency-min", type=float, help="Optional minimum frame frequency.")
    parser.add_argument("--frequency-max", type=float, help="Optional maximum frame frequency.")
    parser.add_argument("--points", help="Optional point CSV with point_id,x,y,z columns.")
    parser.add_argument("--point-output", help="Optional interpolated point CSV output path.")
    parser.add_argument(
        "--point-fields",
        nargs="+",
        help="Optional node field names for point interpolation. Defaults to all node fields.",
    )
    parser.add_argument(
        "--neighbors",
        type=int,
        default=4,
        help="Neighbor count for point interpolation.",
    )
    parser.add_argument(
        "--exact-tol",
        type=float,
        default=1.0e-9,
        help="Distance tolerance for exact node hits.",
    )
    parser.add_argument(
        "--abaqus-command",
        help="Abaqus command or .bat path. Defaults to ABAQUS_COMMAND, abaqus, or abq20xx.",
    )
    parser.add_argument(
        "--inspect-odb",
        action="store_true",
        help="Print ODB structure summary as JSON and exit.",
    )
    return parser.parse_args(argv)


def default_extractor_module():
    base_dir = getattr(sys, "_MEIPASS", None)
    if base_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "odb_extract", "extractor.py")


def _abaqus_python_target_args(extractor_target):
    if extractor_target.endswith(".py") or os.path.sep in extractor_target:
        return [extractor_target]
    if os.path.altsep and os.path.altsep in extractor_target:
        return [extractor_target]
    return ["-m", extractor_target]


def parse_field_text(field_text):
    fields = [part for part in re.split(r"[\s,;]+", field_text.strip()) if part]
    return fields or None


def parse_node_label_text(label_text):
    labels = []
    for part in re.split(r"[\s,;]+", label_text.strip()):
        if not part:
            continue
        labels.append(int(part))
    return labels or None


def parse_node_set_text(text):
    """Parse space/comma/semicolon separated node set names from user input."""
    names = [part for part in re.split(r"[\s,;]+", text.strip()) if part]
    return names or None


def format_csv_component_specs(csv_components):
    if not csv_components:
        return []
    return [
        "{}={}".format(field_name, ",".join(csv_components[field_name]))
        for field_name in sorted(csv_components)
        if csv_components[field_name]
    ]


def parse_optional_float(value_text):
    value_text = value_text.strip()
    if not value_text:
        return None
    return float(value_text)


def choose_field_names(fields, mode, default_fields=None):
    fields = sorted(fields)
    if mode == "all":
        return fields
    if mode == "none":
        return []
    if mode == "default":
        if default_fields is None:
            default_fields = parse_field_text(DEFAULT_FIELD_TEXT) or []
        defaults = set(default_fields)
        return [field_name for field_name in fields if field_name in defaults]
    raise ValueError("Unknown field selection mode: {}".format(mode))


def default_output_paths(odb_path, output_dir=None):
    output_dir = output_dir or os.path.join(os.getcwd(), "output")
    base_name = os.path.splitext(os.path.basename(odb_path))[0]
    return (
        os.path.join(output_dir, "{}_point_data.npz".format(base_name)),
        os.path.join(output_dir, "{}_point_metadata.json".format(base_name)),
    )


def default_point_output_path(odb_path, output_dir=None):
    output_dir = output_dir or os.path.join(os.getcwd(), "output")
    base_name = os.path.splitext(os.path.basename(odb_path))[0]
    return os.path.join(output_dir, "{}_interpolated_points.csv".format(base_name))


def find_abaqus_command(explicit_command=None, env=None, which=None):
    env = os.environ if env is None else env
    which = shutil.which if which is None else which

    if explicit_command:
        return explicit_command

    env_command = env.get("ABAQUS_COMMAND")
    if env_command:
        return env_command

    for candidate in ABAQUS_CANDIDATES:
        found = which(candidate)
        if found:
            return found
    return None


def choose_odb_with_dialog():
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    root = tk.Tk()
    root.withdraw()
    try:
        path = filedialog.askopenfilename(
            title=UI_TEXT["select_odb_title"],
            filetypes=(("Abaqus ODB", "*.odb"), ("All files", "*.*")),
        )
    finally:
        root.destroy()
    return path or None


def build_extraction_command(
    abaqus_command,
    odb_path,
    extractor_module=None,
    output_path=None,
    metadata_path=None,
    step_name=None,
    fields=None,
    instances=None,
    node_labels=None,
    frequency_min=None,
    frequency_max=None,
    node_sets=None,
    csv_output_path=None,
    csv_components=None,
):
    extractor_module = extractor_module or default_extractor_module()
    command = [abaqus_command, "python"]
    command.extend(_abaqus_python_target_args(extractor_module))
    command.extend(["--odb", odb_path])
    if output_path:
        command.extend(["--output", output_path])
    if metadata_path:
        command.extend(["--metadata", metadata_path])
    if step_name:
        command.extend(["--step", step_name])
    if fields:
        command.append("--fields")
        command.extend(fields)
    if instances:
        command.append("--instances")
        command.extend(instances)
    if node_labels:
        command.append("--node-labels")
        command.extend(str(label) for label in node_labels)
    if frequency_min is not None:
        command.extend(["--frequency-min", str(frequency_min)])
    if frequency_max is not None:
        command.extend(["--frequency-max", str(frequency_max)])
    if node_sets:
        command.append("--node-sets")
        command.extend(node_sets)
    if csv_output_path:
        command.extend(["--csv-output", csv_output_path])
    component_specs = format_csv_component_specs(csv_components)
    if component_specs:
        command.append("--csv-components")
        command.extend(component_specs)
    return command


def build_field_list_command(abaqus_command, extractor_module, odb_path, step_name=None):
    extractor_module = extractor_module or default_extractor_module()
    command = [
        abaqus_command,
        "python",
    ]
    command.extend(_abaqus_python_target_args(extractor_module))
    command.extend(["--odb", odb_path, "--list-fields"])
    if step_name:
        command.extend(["--step", step_name])
    return command


def build_inspect_odb_command(abaqus_command, extractor_module, odb_path):
    extractor_module = extractor_module or default_extractor_module()
    command = [
        abaqus_command,
        "python",
    ]
    command.extend(_abaqus_python_target_args(extractor_module))
    command.extend(["--odb", odb_path, "--inspect-odb"])
    return command


def parse_field_list_output(output_text):
    return _parse_list_metadata_output(
        output_text,
        "fields",
        "Field list JSON does not contain a fields array.",
        "Could not find field list JSON in Abaqus output.",
    )


def parse_inspect_odb_output(output_text):
    return _parse_metadata_output(
        output_text,
        "steps",
        dict,
        "ODB inspection JSON does not contain a steps object.",
        "Could not find ODB inspection JSON in Abaqus output.",
    )


def _parse_list_metadata_output(output_text, list_key, malformed_message, missing_message):
    return _parse_metadata_output(
        output_text,
        list_key,
        list,
        malformed_message,
        missing_message,
    )


def _parse_metadata_output(
    output_text, required_key, required_type, malformed_message, missing_message
):
    decoder = json.JSONDecoder()
    start = output_text.find("{")
    while start >= 0:
        try:
            metadata, _ = decoder.raw_decode(output_text[start:])
        except ValueError:
            start = output_text.find("{", start + 1)
            continue
        if isinstance(metadata, dict) and required_key in metadata:
            if not isinstance(metadata.get(required_key), required_type):
                raise ValueError(malformed_message)
            return metadata
        start = output_text.find("{", start + 1)
    raise ValueError(missing_message)


def build_node_set_list_command(abaqus_command, extractor_module, odb_path):
    """Build the Abaqus command to list available node sets."""
    extractor_module = extractor_module or default_extractor_module()
    command = [
        abaqus_command,
        "python",
    ]
    command.extend(_abaqus_python_target_args(extractor_module))
    command.extend(["--odb", odb_path, "--list-node-sets"])
    return command


def parse_node_set_list_output(output_text):
    """Parse the JSON line from --list-node-sets output."""
    return _parse_list_metadata_output(
        output_text,
        "node_sets",
        "Node set list JSON does not contain a node_sets array.",
        "Could not find node set list JSON in Abaqus output.",
    )


def discover_node_sets(abaqus_command, extractor_module, odb_path, runner=None):
    """Discover available node sets from an ODB by calling Abaqus Python."""
    runner = run_command_capture if runner is None else runner
    command = build_node_set_list_command(
        abaqus_command=abaqus_command,
        extractor_module=extractor_module,
        odb_path=odb_path,
    )
    code, output = runner(command)
    if code != 0:
        raise RuntimeError(
            "Node set discovery failed with exit code {}.\n{}".format(code, output)
        )
    return parse_node_set_list_output(output)


def run_command(command, log_callback=None):
    if log_callback is None:
        completed = subprocess.run(command)
        return completed.returncode

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    if process.stdout is not None:
        for line in process.stdout:
            log_callback(line.rstrip())
    return process.wait()


def run_command_silent(command):
    completed = subprocess.run(command)
    return completed.returncode


def run_command_capture(command):
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    return completed.returncode, completed.stdout or ""


def discover_fields(
    abaqus_command,
    extractor_module,
    odb_path,
    step_name=None,
    runner=None,
):
    runner = run_command_capture if runner is None else runner
    command = build_field_list_command(
        abaqus_command=abaqus_command,
        extractor_module=extractor_module,
        odb_path=odb_path,
        step_name=step_name,
    )
    code, output = runner(command)
    if code != 0:
        raise RuntimeError(
            "Field discovery failed with exit code {}.\n{}".format(code, output)
        )
    return parse_field_list_output(output)


def inspect_odb_structure(abaqus_command, extractor_module, odb_path, runner=None):
    runner = run_command_capture if runner is None else runner
    command = build_inspect_odb_command(
        abaqus_command=abaqus_command,
        extractor_module=extractor_module,
        odb_path=odb_path,
    )
    code, output = runner(command)
    if code != 0:
        raise RuntimeError(
            "ODB inspection failed with exit code {}.\n{}".format(code, output)
        )
    return parse_inspect_odb_output(output)


def run_extraction(
    abaqus_command,
    odb_path,
    extractor_module=None,
    output_path=None,
    metadata_path=None,
    step_name=None,
    fields=None,
    instances=None,
    node_labels=None,
    frequency_min=None,
    frequency_max=None,
    node_sets=None,
    csv_output_path=None,
    csv_components=None,
    runner=None,
    verbose=True,
    log_callback=None,
):
    runner = run_command if runner is None else runner
    command = build_extraction_command(
        abaqus_command=abaqus_command,
        odb_path=odb_path,
        extractor_module=extractor_module,
        output_path=output_path,
        metadata_path=metadata_path,
        step_name=step_name,
        fields=fields,
        instances=instances,
        node_labels=node_labels,
        frequency_min=frequency_min,
        frequency_max=frequency_max,
        node_sets=node_sets,
        csv_output_path=csv_output_path,
        csv_components=csv_components,
    )
    if verbose:
        print(
            "Running: {}".format(
                " ".join('"{}"'.format(part) if " " in part else part for part in command)
            )
        )
        sys.stdout.flush()
    try:
        return runner(command, log_callback=log_callback)
    except TypeError:
        return runner(command)


def _default_point_runner(**kwargs):
    from odb_extract import interpolate_points

    return interpolate_points.interpolate_files(**kwargs)


def run_workflow(
    abaqus_command,
    odb_path,
    extractor_module=None,
    output_path=None,
    metadata_path=None,
    step_name=None,
    fields=None,
    instances=None,
    node_labels=None,
    frequency_min=None,
    frequency_max=None,
    node_sets=None,
    csv_output_path=None,
    csv_components=None,
    points_path=None,
    point_output_path=None,
    point_fields=None,
    neighbors=4,
    exact_tol=1.0e-9,
    extraction_runner=None,
    point_runner=None,
    verbose=True,
    log_callback=None,
):
    if points_path:
        default_npz, default_metadata = default_output_paths(odb_path)
        output_path = output_path or default_npz
        metadata_path = metadata_path or default_metadata
        point_output_path = point_output_path or default_point_output_path(odb_path)
    if node_sets:
        default_npz, default_metadata = default_output_paths(odb_path)
        output_path = output_path or default_npz
        metadata_path = metadata_path or default_metadata
        if csv_components == {}:
            csv_output_path = None
        else:
            csv_output_path = csv_output_path or default_csv_output_path(output_path)

    if log_callback:
        log_callback(UI_TEXT["starting_extraction"])

    extraction_runner = run_extraction if extraction_runner is None else extraction_runner
    code = extraction_runner(
        abaqus_command=abaqus_command,
        odb_path=odb_path,
        extractor_module=extractor_module or default_extractor_module(),
        output_path=output_path,
        metadata_path=metadata_path,
        step_name=step_name,
        fields=fields,
        instances=instances,
        node_labels=node_labels,
        frequency_min=frequency_min,
        frequency_max=frequency_max,
        node_sets=node_sets,
        csv_output_path=csv_output_path,
        csv_components=csv_components,
        verbose=verbose,
        log_callback=log_callback,
    )
    if code != 0 or not points_path:
        return code

    if log_callback:
        log_callback(UI_TEXT["starting_point_export"])

    point_runner = _default_point_runner if point_runner is None else point_runner
    point_runner(
        data_path=output_path,
        metadata_path=metadata_path,
        points_path=points_path,
        output_path=point_output_path,
        fields=point_fields,
        csv_components=csv_components,
        neighbors=neighbors,
        exact_tol=exact_tol,
    )

    if log_callback:
        log_callback(UI_TEXT["point_export_finished_log"].format(path=point_output_path))
    return 0


def run_cli(argv=None):
    args = parse_args(argv)

    odb_path = args.odb or choose_odb_with_dialog()
    if not odb_path:
        print("ERROR: No ODB file selected. Use --odb path\\to\\file.odb.", file=sys.stderr)
        return 2

    abaqus_command = find_abaqus_command(args.abaqus_command)
    if not abaqus_command:
        print(
            "ERROR: Abaqus command was not found. Add abaqus/abq2024 to PATH, "
            "set ABAQUS_COMMAND, or pass --abaqus-command.",
            file=sys.stderr,
        )
        return 2
    csv_components = parse_csv_component_specs(args.csv_components)

    if args.inspect_odb:
        metadata = inspect_odb_structure(
            abaqus_command=abaqus_command,
            extractor_module=default_extractor_module(),
            odb_path=odb_path,
        )
        print(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    return run_workflow(
        abaqus_command=abaqus_command,
        odb_path=odb_path,
        extractor_module=default_extractor_module(),
        output_path=args.output,
        metadata_path=args.metadata,
        step_name=args.step,
        fields=args.fields,
        instances=args.instances,
        node_labels=args.node_labels,
        frequency_min=args.frequency_min,
        frequency_max=args.frequency_max,
        node_sets=args.node_sets,
        csv_output_path=args.csv_output,
        csv_components=csv_components,
        points_path=args.points,
        point_output_path=args.point_output,
        point_fields=args.point_fields,
        neighbors=args.neighbors,
        exact_tol=args.exact_tol,
    )


class ExtractOdbApp(object):
    def __init__(self, root):
        import tkinter as tk

        self.tk = tk
        self.root = root
        self.root.title(UI_TEXT["window_title"])
        self.root.geometry("880x720")
        self.root.minsize(760, 620)

        self.odb_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.metadata_var = tk.StringVar()
        self.points_var = tk.StringVar()
        self.point_output_var = tk.StringVar()
        self.point_fields_var = tk.StringVar()
        self.neighbors_var = tk.StringVar(value="4")
        self.exact_tol_var = tk.StringVar(value="1e-9")
        self.step_var = tk.StringVar()
        self.fields_var = tk.StringVar(value=DEFAULT_FIELD_TEXT)
        self.instances_var = tk.StringVar()
        self.node_labels_var = tk.StringVar()
        self.frequency_min_var = tk.StringVar()
        self.frequency_max_var = tk.StringVar()
        self.abaqus_var = tk.StringVar(value=find_abaqus_command() or "")
        self.status_var = tk.StringVar(value=UI_TEXT["ready"])
        self._running = False
        self.field_vars = {}
        self.csv_component_vars = {}
        self.node_sets_var = tk.StringVar()
        self.node_set_vars = {}

        self._build_widgets()

    def _build_widgets(self):
        tk = self.tk
        from tkinter import ttk

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.main_canvas = tk.Canvas(self.root, highlightthickness=0)
        self.main_canvas.grid(row=0, column=0, sticky="nsew")
        main_scrollbar = ttk.Scrollbar(
            self.root,
            orient="vertical",
            command=self.main_canvas.yview,
        )
        main_scrollbar.grid(row=0, column=1, sticky="ns")
        self.main_canvas.configure(yscrollcommand=main_scrollbar.set)

        frame = ttk.Frame(self.main_canvas, padding=12)
        self.main_canvas_window = self.main_canvas.create_window(
            (0, 0),
            window=frame,
            anchor="nw",
        )
        frame.bind("<Configure>", self._update_main_scroll_region)
        self.main_canvas.bind("<Configure>", self._resize_main_frame)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(19, weight=1)

        self._add_path_row(frame, 0, UI_TEXT["odb_file"], self.odb_var, self.choose_odb)
        self._add_path_row(frame, 1, UI_TEXT["npz_output"], self.output_var, self.choose_output)
        self._add_path_row(
            frame, 2, UI_TEXT["metadata_output"], self.metadata_var, self.choose_metadata
        )
        self._add_path_row(frame, 3, UI_TEXT["points_file"], self.points_var, self.choose_points)
        self._add_path_row(
            frame,
            4,
            UI_TEXT["point_output"],
            self.point_output_var,
            self.choose_point_output,
        )
        self._add_path_row(frame, 5, UI_TEXT["abaqus_command"], self.abaqus_var, None)
        ttk.Label(frame, text="Step").grid(row=7, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.step_var).grid(
            row=7, column=1, columnspan=2, sticky="ew", pady=4
        )

        ttk.Label(frame, text=UI_TEXT["manual_fields"]).grid(row=8, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.fields_var).grid(
            row=8, column=1, sticky="ew", pady=4, padx=(0, 6)
        )
        self.refresh_button = ttk.Button(
            frame, text=UI_TEXT["refresh_fields"], command=self.refresh_fields
        )
        self.refresh_button.grid(row=8, column=2, sticky="ew", pady=4)

        ttk.Label(frame, text=UI_TEXT["instance_filter"]).grid(row=9, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.instances_var).grid(
            row=9, column=1, columnspan=2, sticky="ew", pady=4
        )

        ttk.Label(frame, text=UI_TEXT["node_label_filter"]).grid(
            row=10, column=0, sticky="w", pady=4
        )
        ttk.Entry(frame, textvariable=self.node_labels_var).grid(
            row=10, column=1, columnspan=2, sticky="ew", pady=4
        )

        self._build_node_set_widgets(frame, 11)

        ttk.Label(frame, text=UI_TEXT["frequency_min"]).grid(row=13, column=0, sticky="w", pady=4)
        frequency_frame = ttk.Frame(frame)
        frequency_frame.grid(row=13, column=1, columnspan=2, sticky="ew", pady=4)
        frequency_frame.columnconfigure(0, weight=1)
        frequency_frame.columnconfigure(2, weight=1)
        ttk.Entry(frequency_frame, textvariable=self.frequency_min_var).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Label(frequency_frame, text=UI_TEXT["frequency_max"]).grid(
            row=0, column=1, padx=8
        )
        ttk.Entry(frequency_frame, textvariable=self.frequency_max_var).grid(
            row=0, column=2, sticky="ew"
        )

        ttk.Label(frame, text=UI_TEXT["point_fields"]).grid(row=14, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.point_fields_var).grid(
            row=14, column=1, columnspan=2, sticky="ew", pady=4
        )

        ttk.Label(frame, text=UI_TEXT["neighbors"]).grid(row=15, column=0, sticky="w", pady=4)
        point_options_frame = ttk.Frame(frame)
        point_options_frame.grid(row=15, column=1, columnspan=2, sticky="ew", pady=4)
        point_options_frame.columnconfigure(0, weight=1)
        point_options_frame.columnconfigure(2, weight=1)
        ttk.Entry(point_options_frame, textvariable=self.neighbors_var).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Label(point_options_frame, text=UI_TEXT["exact_tol"]).grid(
            row=0, column=1, padx=8
        )
        ttk.Entry(point_options_frame, textvariable=self.exact_tol_var).grid(
            row=0, column=2, sticky="ew"
        )

        self.field_box = ttk.LabelFrame(frame, text=UI_TEXT["available_fields"])
        self.field_box.grid(row=16, column=0, columnspan=3, sticky="ew", pady=(4, 8))
        self.field_box.columnconfigure(0, weight=1)
        self.field_box.rowconfigure(1, weight=1)

        field_toolbar = ttk.Frame(self.field_box)
        field_toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 2))
        self.field_selection_buttons = [
            ttk.Button(
                field_toolbar,
                text=UI_TEXT["select_all_fields"],
                command=lambda: self._set_field_selection("all"),
            ),
            ttk.Button(
                field_toolbar,
                text=UI_TEXT["clear_all_fields"],
                command=lambda: self._set_field_selection("none"),
            ),
            ttk.Button(
                field_toolbar,
                text=UI_TEXT["select_default_fields"],
                command=lambda: self._set_field_selection("default"),
            ),
        ]
        for button in self.field_selection_buttons:
            button.pack(side="left", padx=(0, 6))

        self.field_canvas = tk.Canvas(
            self.field_box,
            height=120,
            highlightthickness=0,
        )
        self.field_canvas.grid(row=1, column=0, sticky="nsew", padx=(6, 0), pady=(2, 6))
        field_scrollbar = ttk.Scrollbar(
            self.field_box,
            orient="vertical",
            command=self.field_canvas.yview,
        )
        field_scrollbar.grid(row=1, column=1, sticky="ns", padx=(0, 6), pady=(2, 6))
        self.field_canvas.configure(yscrollcommand=field_scrollbar.set)

        self.field_checks_frame = ttk.Frame(self.field_canvas)
        self.field_canvas_window = self.field_canvas.create_window(
            (0, 0),
            window=self.field_checks_frame,
            anchor="nw",
        )
        self.field_checks_frame.bind("<Configure>", self._update_field_scroll_region)
        self.field_canvas.bind("<Configure>", self._resize_field_checks_frame)
        self.field_hint = ttk.Label(
            self.field_checks_frame,
            text=UI_TEXT["field_hint"],
        )
        self.field_hint.grid(row=0, column=0, sticky="w", padx=8, pady=8)

        self._build_csv_component_widgets(frame, 17)

        button_bar = ttk.Frame(frame)
        button_bar.grid(row=18, column=0, columnspan=3, sticky="ew", pady=(8, 6))
        self.run_button = ttk.Button(button_bar, text=UI_TEXT["run_button"], command=self.run)
        self.run_button.pack(side="left")
        self.inspect_button = ttk.Button(
            button_bar,
            text=UI_TEXT["inspect_odb"],
            command=self.inspect_odb,
        )
        self.inspect_button.pack(side="left", padx=(8, 0))
        ttk.Label(button_bar, textvariable=self.status_var).pack(side="left", padx=12)

        self.log_text = tk.Text(frame, height=12, wrap="word")
        self.log_text.grid(row=19, column=0, columnspan=3, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, command=self.log_text.yview)
        scrollbar.grid(row=19, column=3, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _add_path_row(self, frame, row, label, variable, command):
        from tkinter import ttk

        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=variable).grid(
            row=row, column=1, sticky="ew", pady=4, padx=(0, 6)
        )
        if command is None:
            ttk.Label(frame, text="").grid(row=row, column=2, pady=4)
        else:
            ttk.Button(frame, text=UI_TEXT["browse"], command=command).grid(
                row=row, column=2, sticky="ew", pady=4
            )

    def _build_csv_component_widgets(self, frame, row):
        from tkinter import ttk

        self.csv_component_box = ttk.LabelFrame(frame, text=UI_TEXT["csv_components"])
        self.csv_component_box.grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(0, 8)
        )
        self.csv_component_frame = ttk.Frame(self.csv_component_box)
        self.csv_component_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        self.csv_component_hint = ttk.Label(
            self.csv_component_frame,
            text=UI_TEXT["csv_component_hint"],
        )
        self.csv_component_hint.grid(row=0, column=0, sticky="w")

    def _clear_csv_component_checks(self):
        for child in self.csv_component_frame.winfo_children():
            child.destroy()
        self.csv_component_vars = {}

    def _build_node_set_widgets(self, frame, row_offset):
        """Build node set filter row: label, text entry, and action buttons."""
        tk = self.tk
        from tkinter import ttk

        ttk.Label(frame, text=UI_TEXT["node_set_filter"]).grid(
            row=row_offset, column=0, sticky="w", pady=4
        )
        ttk.Entry(frame, textvariable=self.node_sets_var).grid(
            row=row_offset, column=1, sticky="ew", pady=4, padx=(0, 6)
        )
        nset_button_frame = ttk.Frame(frame)
        nset_button_frame.grid(row=row_offset, column=2, sticky="ew", pady=4)
        self.refresh_nset_button = ttk.Button(
            nset_button_frame,
            text=UI_TEXT["refresh_node_sets"],
            command=self.refresh_node_sets,
        )
        self.refresh_nset_button.pack(side="left", padx=(0, 4))
        self.node_set_selection_buttons = [
            ttk.Button(
                nset_button_frame,
                text=UI_TEXT["select_all_node_sets"],
                command=lambda: self._set_node_set_selection("all"),
            ),
            ttk.Button(
                nset_button_frame,
                text=UI_TEXT["clear_all_node_sets"],
                command=lambda: self._set_node_set_selection("none"),
            ),
        ]
        self.node_set_selection_buttons[0].pack(side="left", padx=(0, 4))
        self.node_set_selection_buttons[1].pack(side="left")

        # Node set checkbox canvas
        self.nset_box = ttk.LabelFrame(frame, text=UI_TEXT["node_set_filter"])
        self.nset_box.grid(
            row=row_offset + 1, column=0, columnspan=3, sticky="ew", pady=(4, 8)
        )
        self.nset_box.columnconfigure(0, weight=1)
        self.nset_box.rowconfigure(0, weight=1)

        self.nset_canvas = tk.Canvas(
            self.nset_box,
            height=80,
            highlightthickness=0,
        )
        self.nset_canvas.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        nset_scrollbar = ttk.Scrollbar(
            self.nset_box,
            orient="vertical",
            command=self.nset_canvas.yview,
        )
        nset_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=6)
        self.nset_canvas.configure(yscrollcommand=nset_scrollbar.set)

        self.nset_checks_frame = ttk.Frame(self.nset_canvas)
        self.nset_canvas_window = self.nset_canvas.create_window(
            (0, 0),
            window=self.nset_checks_frame,
            anchor="nw",
        )
        self.nset_checks_frame.bind("<Configure>", self._update_nset_scroll_region)
        self.nset_canvas.bind("<Configure>", self._resize_nset_checks_frame)
        self.nset_hint = ttk.Label(
            self.nset_checks_frame,
            text=UI_TEXT["node_set_hint"],
        )
        self.nset_hint.grid(row=0, column=0, sticky="w", padx=8, pady=8)

    def choose_odb(self):
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title=UI_TEXT["select_odb_title"],
            filetypes=(("Abaqus ODB", "*.odb"), ("All files", "*.*")),
        )
        if not path:
            return
        self.odb_var.set(path)
        if not self.output_var.get().strip() and not self.metadata_var.get().strip():
            output_path, metadata_path = default_output_paths(path)
            self.output_var.set(output_path)
            self.metadata_var.set(metadata_path)
        if not self.point_output_var.get().strip():
            self.point_output_var.set(default_point_output_path(path))
        self.refresh_fields()
        self.refresh_node_sets()

    def choose_output(self):
        from tkinter import filedialog

        initial = self.output_var.get().strip() or default_output_paths(
            self.odb_var.get().strip() or "odb"
        )[0]
        path = filedialog.asksaveasfilename(
            title=UI_TEXT["select_npz_title"],
            defaultextension=".npz",
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial) or os.getcwd(),
            filetypes=(("Compressed NumPy", "*.npz"), ("All files", "*.*")),
        )
        if path:
            self.output_var.set(path)

    def choose_metadata(self):
        from tkinter import filedialog

        initial = self.metadata_var.get().strip() or default_output_paths(
            self.odb_var.get().strip() or "odb"
        )[1]
        path = filedialog.asksaveasfilename(
            title=UI_TEXT["select_metadata_title"],
            defaultextension=".json",
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial) or os.getcwd(),
            filetypes=(("JSON", "*.json"), ("All files", "*.*")),
        )
        if path:
            self.metadata_var.set(path)

    def choose_points(self):
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title=UI_TEXT["select_points_title"],
            filetypes=(("CSV", "*.csv"), ("All files", "*.*")),
        )
        if path:
            self.points_var.set(path)
            if not self.point_output_var.get().strip():
                self.point_output_var.set(
                    default_point_output_path(self.odb_var.get().strip() or path)
                )

    def choose_point_output(self):
        from tkinter import filedialog

        initial = self.point_output_var.get().strip() or default_point_output_path(
            self.odb_var.get().strip() or "odb"
        )
        path = filedialog.asksaveasfilename(
            title=UI_TEXT["select_point_output_title"],
            defaultextension=".csv",
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial) or os.getcwd(),
            filetypes=(("CSV", "*.csv"), ("All files", "*.*")),
        )
        if path:
            self.point_output_var.set(path)

    def log(self, message):
        self.log_text.insert("end", "{}\n".format(message))
        self.log_text.see("end")

    def _thread_log(self, message):
        self.root.after(0, self.log, message)

    def _set_running(self, running):
        self._running = running
        self.run_button.configure(state="disabled" if running else "normal")
        self.inspect_button.configure(state="disabled" if running else "normal")
        self.refresh_button.configure(state="disabled" if running else "normal")
        for button in self.field_selection_buttons:
            button.configure(state="disabled" if running else "normal")
        self.refresh_nset_button.configure(state="disabled" if running else "normal")
        for button in self.node_set_selection_buttons:
            button.configure(state="disabled" if running else "normal")
        self.status_var.set(UI_TEXT["running"] if running else UI_TEXT["ready"])

    def _update_main_scroll_region(self, _event=None):
        self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

    def _resize_main_frame(self, event):
        self.main_canvas.itemconfigure(self.main_canvas_window, width=event.width)

    def _update_field_scroll_region(self, _event=None):
        self.field_canvas.configure(scrollregion=self.field_canvas.bbox("all"))

    def _resize_field_checks_frame(self, event):
        self.field_canvas.itemconfigure(self.field_canvas_window, width=event.width)

    def _update_nset_scroll_region(self, _event=None):
        self.nset_canvas.configure(scrollregion=self.nset_canvas.bbox("all"))

    def _resize_nset_checks_frame(self, event):
        self.nset_canvas.itemconfigure(self.nset_canvas_window, width=event.width)

    def _clear_node_set_checks(self):
        for child in self.nset_checks_frame.winfo_children():
            child.destroy()
        self.node_set_vars = {}

    def _sync_node_sets_from_checks(self):
        selected = [
            name
            for name, variable in sorted(self.node_set_vars.items())
            if variable.get()
        ]
        self.node_sets_var.set(" ".join(selected))

    def _set_node_set_selection(self, mode):
        if mode == "all":
            for variable in self.node_set_vars.values():
                variable.set(True)
        elif mode == "none":
            for variable in self.node_set_vars.values():
                variable.set(False)
        self._sync_node_sets_from_checks()

    def _show_discovered_node_sets(self, metadata):
        tk = self.tk
        from tkinter import ttk

        node_sets = metadata.get("node_sets", [])
        self._clear_node_set_checks()
        if not node_sets:
            ttk.Label(
                self.nset_checks_frame,
                text=UI_TEXT["no_node_sets_found"],
            ).grid(row=0, column=0, sticky="w", padx=8, pady=8)
            self.node_sets_var.set("")
            return

        for index, name in enumerate(node_sets):
            variable = tk.BooleanVar(value=False)
            self.node_set_vars[name] = variable
            ttk.Checkbutton(
                self.nset_checks_frame,
                text=name,
                variable=variable,
                command=self._sync_node_sets_from_checks,
            ).grid(row=index // 6, column=index % 6, sticky="w", padx=8, pady=4)

        self.nset_canvas.yview_moveto(0)
        self.log(
            UI_TEXT["found_node_sets"].format(count=len(node_sets))
        )

    def _clear_field_checks(self):
        for child in self.field_checks_frame.winfo_children():
            child.destroy()
        self.field_vars = {}

    def _show_csv_component_matrix(self, fields):
        tk = self.tk
        from tkinter import ttk

        self._clear_csv_component_checks()
        if not fields:
            ttk.Label(
                self.csv_component_frame,
                text=UI_TEXT["csv_component_hint"],
            ).grid(row=0, column=0, sticky="w")
            return

        ttk.Label(self.csv_component_frame, text="").grid(row=0, column=0, padx=6, pady=2)
        for column, field_name in enumerate(fields, start=1):
            ttk.Label(self.csv_component_frame, text=field_name).grid(
                row=0, column=column, padx=6, pady=2
            )
            self.csv_component_vars[field_name] = {}

        for row, (key, label) in enumerate(CSV_COMPONENT_OPTIONS, start=1):
            ttk.Label(self.csv_component_frame, text=label).grid(
                row=row, column=0, sticky="w", padx=6, pady=2
            )
            for column, field_name in enumerate(fields, start=1):
                variable = tk.BooleanVar(value=key != "total")
                self.csv_component_vars[field_name][key] = variable
                ttk.Checkbutton(
                    self.csv_component_frame,
                    variable=variable,
                ).grid(row=row, column=column, padx=6, pady=2)

    def _set_field_selection(self, mode):
        selected = set(choose_field_names(self.field_vars.keys(), mode))
        for field_name, variable in self.field_vars.items():
            variable.set(field_name in selected)
        self._sync_fields_from_checks()

    def _sync_fields_from_checks(self):
        selected = [
            field_name
            for field_name, variable in sorted(self.field_vars.items())
            if variable.get()
        ]
        self.fields_var.set(" ".join(selected))

    def _show_discovered_fields(self, metadata):
        tk = self.tk
        from tkinter import ttk

        fields = metadata.get("fields", [])
        self._clear_field_checks()
        self._clear_csv_component_checks()
        if not fields:
            ttk.Label(self.field_checks_frame, text=UI_TEXT["no_fields_found"]).grid(
                row=0, column=0, sticky="w", padx=8, pady=8
            )
            self.fields_var.set("")
            self._show_csv_component_matrix([])
            return

        default_fields = set(parse_field_text(DEFAULT_FIELD_TEXT) or [])
        checked_any = False
        for index, field_name in enumerate(fields):
            checked = field_name in default_fields
            checked_any = checked_any or checked
            variable = tk.BooleanVar(value=checked)
            self.field_vars[field_name] = variable
            ttk.Checkbutton(
                self.field_checks_frame,
                text=field_name,
                variable=variable,
                command=self._sync_fields_from_checks,
            ).grid(row=index // 6, column=index % 6, sticky="w", padx=8, pady=4)

        if not checked_any:
            for variable in self.field_vars.values():
                variable.set(True)
        self._sync_fields_from_checks()
        self._show_csv_component_matrix(fields)
        self.field_canvas.yview_moveto(0)
        self.log(UI_TEXT["found_fields"].format(step=metadata.get("step", ""), count=len(fields)))

    def refresh_fields(self):
        if self._running:
            return
        odb_path = self.odb_var.get().strip()
        if not odb_path:
            self.log(UI_TEXT["select_odb_first"])
            return
        abaqus_command = self.abaqus_var.get().strip()
        if not abaqus_command:
            self.log(UI_TEXT["empty_abaqus"])
            return
        self.log(UI_TEXT["discovering_fields"])
        self._set_running(True)
        worker = threading.Thread(
            target=self._discover_fields_worker,
            args=(
                abaqus_command,
                default_extractor_module(),
                odb_path,
                self.step_var.get().strip() or None,
            ),
        )
        worker.daemon = True
        worker.start()

    def _discover_fields_worker(self, abaqus_command, extractor_module, odb_path, step_name):
        from tkinter import messagebox

        try:
            metadata = discover_fields(
                abaqus_command=abaqus_command,
                extractor_module=extractor_module,
                odb_path=odb_path,
                step_name=step_name,
            )
        except Exception as exc:
            error_message = str(exc)

            def fail():
                self._set_running(False)
                self.log(UI_TEXT["field_discovery_failed_log"].format(error=error_message))
                messagebox.showerror(UI_TEXT["field_discovery_failed_title"], error_message)

            self.root.after(0, fail)
            return

        def finish():
            self._set_running(False)
            self._show_discovered_fields(metadata)

        self.root.after(0, finish)

    def inspect_odb(self):
        if self._running:
            return
        odb_path = self.odb_var.get().strip()
        if not odb_path:
            self.log(UI_TEXT["select_odb_first"])
            return
        abaqus_command = self.abaqus_var.get().strip()
        if not abaqus_command:
            self.log(UI_TEXT["empty_abaqus"])
            return
        self.log(UI_TEXT["inspecting_odb"])
        self._set_running(True)
        worker = threading.Thread(
            target=self._inspect_odb_worker,
            args=(abaqus_command, default_extractor_module(), odb_path),
        )
        worker.daemon = True
        worker.start()

    def _inspect_odb_worker(self, abaqus_command, extractor_module, odb_path):
        from tkinter import messagebox

        try:
            metadata = inspect_odb_structure(
                abaqus_command=abaqus_command,
                extractor_module=extractor_module,
                odb_path=odb_path,
            )
        except Exception as exc:
            error_message = str(exc)

            def fail():
                self._set_running(False)
                self.log(UI_TEXT["inspect_odb_failed_log"].format(error=error_message))
                messagebox.showerror(UI_TEXT["inspect_odb_failed_title"], error_message)

            self.root.after(0, fail)
            return

        summary = json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True)

        def finish():
            self._set_running(False)
            self.log(UI_TEXT["inspect_odb_finished_log"].format(summary=summary))

        self.root.after(0, finish)

    def refresh_node_sets(self):
        """Trigger node set discovery in background thread."""
        if self._running:
            return
        odb_path = self.odb_var.get().strip()
        if not odb_path:
            self.log(UI_TEXT["select_odb_for_node_sets"])
            return
        abaqus_command = self.abaqus_var.get().strip()
        if not abaqus_command:
            self.log(UI_TEXT["empty_abaqus"])
            return
        self.log(UI_TEXT["discovering_node_sets"])
        self._set_running(True)
        worker = threading.Thread(
            target=self._discover_node_sets_worker,
            args=(abaqus_command, default_extractor_module(), odb_path),
        )
        worker.daemon = True
        worker.start()

    def _discover_node_sets_worker(self, abaqus_command, extractor_module, odb_path):
        from tkinter import messagebox

        try:
            metadata = discover_node_sets(
                abaqus_command=abaqus_command,
                extractor_module=extractor_module,
                odb_path=odb_path,
            )
        except Exception as exc:
            error_message = str(exc)

            def fail():
                self._set_running(False)
                self.log(
                    UI_TEXT["node_set_discovery_failed_log"].format(error=error_message)
                )
                messagebox.showerror(
                    UI_TEXT["node_set_discovery_failed"], error_message
                )

            self.root.after(0, fail)
            return

        def finish():
            self._set_running(False)
            self._show_discovered_node_sets(metadata)

        self.root.after(0, finish)

    def _selected_fields(self):
        if self.field_vars:
            return [
                field_name
                for field_name, variable in sorted(self.field_vars.items())
                if variable.get()
            ]
        return parse_field_text(self.fields_var.get())

    def _selected_csv_components(self, fields):
        csv_component_vars = getattr(self, "csv_component_vars", {})
        if not csv_component_vars or not fields:
            return None
        selections = {}
        for field_name in fields:
            component_vars = csv_component_vars.get(field_name)
            if not component_vars:
                continue
            selected = [
                key
                for key, _label in CSV_COMPONENT_OPTIONS
                if key in component_vars and component_vars[key].get()
            ]
            if selected:
                selections[field_name] = selected
        return selections

    def _validate_inputs(self):
        from tkinter import messagebox

        odb_path = self.odb_var.get().strip()
        if not odb_path:
            messagebox.showerror(UI_TEXT["missing_odb_title"], UI_TEXT["missing_odb_message"])
            return None

        abaqus_command = self.abaqus_var.get().strip()
        if not abaqus_command:
            messagebox.showerror(
                UI_TEXT["missing_abaqus_title"],
                UI_TEXT["missing_abaqus_message"],
            )
            return None

        fields = self._selected_fields()
        if self.field_vars and not fields:
            messagebox.showerror(
                UI_TEXT["no_fields_selected_title"],
                UI_TEXT["no_fields_selected_message"],
            )
            return None
        try:
            node_labels = parse_node_label_text(self.node_labels_var.get())
        except ValueError:
            messagebox.showerror(
                UI_TEXT["invalid_node_labels_title"],
                UI_TEXT["invalid_node_labels_message"],
            )
            return None
        try:
            frequency_min = parse_optional_float(self.frequency_min_var.get())
            frequency_max = parse_optional_float(self.frequency_max_var.get())
        except ValueError:
            messagebox.showerror(
                UI_TEXT["invalid_frequency_title"],
                UI_TEXT["invalid_frequency_message"],
            )
            return None
        try:
            neighbors = int(self.neighbors_var.get().strip() or "4")
            if neighbors < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                UI_TEXT["invalid_neighbors_title"],
                UI_TEXT["invalid_neighbors_message"],
            )
            return None
        try:
            exact_tol = parse_optional_float(self.exact_tol_var.get())
        except ValueError:
            messagebox.showerror(
                UI_TEXT["invalid_exact_tol_title"],
                UI_TEXT["invalid_exact_tol_message"],
            )
            return None
        node_sets = parse_node_set_text(self.node_sets_var.get())
        instances = parse_field_text(self.instances_var.get())
        output_path = self.output_var.get().strip() or None
        metadata_path = self.metadata_var.get().strip() or None
        step_name = self.step_var.get().strip() or None
        points_path = self.points_var.get().strip() or None
        point_output_path = self.point_output_var.get().strip() or None
        point_fields = parse_field_text(self.point_fields_var.get())
        csv_components = self._selected_csv_components(fields)
        return {
            "abaqus_command": abaqus_command,
            "odb_path": odb_path,
            "extractor_module": default_extractor_module(),
            "output_path": output_path,
            "metadata_path": metadata_path,
            "step_name": step_name,
            "fields": fields,
            "instances": instances,
            "node_labels": node_labels,
            "frequency_min": frequency_min,
            "frequency_max": frequency_max,
            "node_sets": node_sets,
            "csv_components": csv_components,
            "points_path": points_path,
            "point_output_path": point_output_path,
            "point_fields": point_fields,
            "neighbors": neighbors,
            "exact_tol": exact_tol if exact_tol is not None else 1.0e-9,
        }

    def run(self):
        if self._running:
            return
        options = self._validate_inputs()
        if options is None:
            return

        self._set_running(True)
        worker = threading.Thread(target=self._run_worker, args=(options,))
        worker.daemon = True
        worker.start()

    def _run_worker(self, options):
        from tkinter import messagebox

        try:
            code = run_workflow(
                verbose=False,
                log_callback=self._thread_log,
                **options
            )
        except Exception as exc:
            self.root.after(0, self._set_running, False)
            self.root.after(0, self.log, "ERROR: {}".format(exc))
            self.root.after(0, messagebox.showerror, UI_TEXT["extraction_failed_title"], str(exc))
            return

        def finish():
            self._set_running(False)
            if code == 0:
                self.log(UI_TEXT["extraction_finished_log"])
                messagebox.showinfo(
                    UI_TEXT["extraction_finished_title"],
                    UI_TEXT["extraction_finished_message"],
                )
            else:
                self.log(UI_TEXT["extraction_exit_code_log"].format(code=code))
                messagebox.showerror(
                    UI_TEXT["extraction_failed_title"],
                    UI_TEXT["extraction_exit_code_message"].format(code=code),
                )

        self.root.after(0, finish)


def run_gui():
    import tkinter as tk

    root = tk.Tk()
    ExtractOdbApp(root)
    root.mainloop()
    return 0


def main(argv=None, gui_runner=None):
    if argv is None:
        argv = sys.argv[1:]
    gui_runner = run_gui if gui_runner is None else gui_runner
    if not argv:
        return gui_runner()
    return run_cli(argv)


if __name__ == "__main__":
    sys.exit(main())
