"""Launcher for odb_extract.extractor.

This script runs under normal Python. It delegates ODB reading to Abaqus Python.
"""

from __future__ import print_function

import argparse
import contextlib
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile


ABAQUS_CANDIDATES = ("abaqus", "abq2024", "abq2023", "abq2022")
DEFAULT_EXTRACTOR_MODULE = "odb_extract.extractor"
UI_TEXT = {
    "window_title": "Abaqus ODB 数据提取工具",
    "ready": "就绪",
    "running": "运行中",
    "odb_file": "ODB 文件",
    "source_mode": "数据来源",
    "source_odb": "ODB 提取",
    "source_cache": "已有缓存",
    "cache_file": "缓存 NPZ",
    "npz_output": "NPZ 输出",
    "points_file": "目标点坐标文件",
    "neighbors": "邻近点数量",
    "exact_tol": "精确命中容差",
    "abaqus_command": "Abaqus 命令",
    "instance_filter": "实例过滤",
    "node_label_filter": "节点编号",
    "frequency_min": "频率下限",
    "frequency_max": "频率上限",
    "refresh_fields": "读取场输出",
    "inspect_odb": "检查 ODB 结构",
    "merge_results": "合并结果",
    "available_fields": "可用场输出",
    "field_hint": "请选择 ODB 文件以读取场输出。",
    "run_button": "开始提取",
    "run_cache_button": "开始查询",
    "browse": "浏览",
    "select_odb_title": "选择 Abaqus ODB 文件",
    "select_npz_title": "选择 NPZ 输出文件",
    "select_points_title": "选择目标点坐标文件",
    "select_cache_title": "选择节点数据缓存",
    "refresh_cache_fields": "读取缓存字段",
    "cache_loaded": "已读取缓存：{fields} 个节点场，{node_sets} 个节点集。",
    "cache_without_node_sets": "此缓存不包含节点集成员信息，将使用全部缓存节点。",
    "invalid_cache_title": "缓存文件无效",
    "missing_cache_message": "请选择兼容的节点数据 NPZ 缓存。",
    "missing_cache_selection": "请选择目标点 CSV/Excel 文件，或至少选择一个节点集。",
    "missing_output_for_cache": "缓存处理必须设置 NPZ 输出路径。",
    "cache_output_conflict": "缓存输出不能覆盖源缓存 NPZ 或配套 metadata。",
    "starting_cache_query": "开始从缓存查询目标点。",
    "starting_cache_subset": "开始从缓存按节点集提取原始节点。",
    "cache_query_finished": "缓存数据处理完成。",
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
    "exclusive_points_node_sets_title": "输入互斥",
    "exclusive_points_node_sets_message": "节点集和目标点坐标文件不能同时使用。",
    "starting_extraction": "开始 ODB 数据提取。",
    "keep_full_cache": "保留并复用全模型已选场缓存",
    "full_cache_hit": "复用全模型场缓存：{path}",
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
    parser.add_argument("--points", help="Optional point CSV/XLSX with point_id,x,y,z columns.")
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
    args = parser.parse_args(argv)
    if args.node_sets and args.points:
        parser.error("--node-sets and --points cannot be used together.")
    return args


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


def parse_optional_float(value_text):
    value_text = value_text.strip()
    if not value_text:
        return None
    return float(value_text)


def _default_output_dir(odb_path):
    return os.path.join(os.path.dirname(os.path.abspath(odb_path)), "output")


def default_output_paths(odb_path, output_dir=None):
    output_dir = output_dir or _default_output_dir(odb_path)
    base_name = os.path.splitext(os.path.basename(odb_path))[0]
    return (
        os.path.join(output_dir, "{}_point_data.npz".format(base_name)),
        os.path.join(output_dir, "{}_point_metadata.json".format(base_name)),
    )


def metadata_path_for_output(data_path):
    suffix = "_data.npz"
    if data_path.lower().endswith(suffix):
        return data_path[: -len(suffix)] + "_metadata.json"
    return os.path.splitext(data_path)[0] + "_metadata.json"


def default_cache_query_output_path(cache_path, points_path):
    point_name = os.path.splitext(os.path.basename(points_path))[0]
    return os.path.join(
        os.path.dirname(os.path.abspath(cache_path)),
        "{}_point_data.npz".format(point_name),
    )


def _same_path(first, second):
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def load_cache_source(data_path):
    from odb_extract import interpolate_points

    if not os.path.isfile(data_path):
        raise ValueError("缓存 NPZ 不存在：{}".format(data_path))
    metadata_path = metadata_path_for_output(data_path)
    if not os.path.isfile(metadata_path):
        raise ValueError("找不到配套 metadata：{}".format(metadata_path))
    metadata = interpolate_points.load_metadata(metadata_path)
    fields = interpolate_points._available_node_fields(metadata)
    if not fields:
        raise ValueError("缓存中没有可用于目标点查询的节点场。")
    nodes = metadata.get("nodes") or []
    shapes = metadata.get("array_shapes") or {}
    if not _npz_shapes_match(data_path, shapes):
        raise ValueError("缓存数组与 metadata 记录的形状不一致。")
    required = ["frequencies", "node_labels", "node_coordinates"]
    required.extend(
        key for field in fields for key in ("{}_real".format(field), "{}_imag".format(field))
    )
    missing = [key for key in required if key not in shapes]
    if missing:
        raise ValueError("缓存缺少数组：{}".format(", ".join(missing)))
    coordinate_shape = shapes["node_coordinates"]
    if coordinate_shape != [len(nodes), 3] or shapes["node_labels"] != [len(nodes)]:
        raise ValueError("缓存节点坐标与 metadata 不一致。")
    frequency_count = shapes["frequencies"][0]
    for field in fields:
        point_count = len(metadata["field_outputs"][field].get("points") or [])
        real_shape = shapes["{}_real".format(field)]
        imag_shape = shapes["{}_imag".format(field)]
        if (
            real_shape != imag_shape
            or len(real_shape) != 3
            or real_shape[0] != frequency_count
            or real_shape[1] != point_count
        ):
            raise ValueError("缓存场 {} 的数组形状与 metadata 不一致。".format(field))
    node_sets = interpolate_points.available_node_sets(metadata)
    with interpolate_points.np.load(data_path) as data:
        for name in node_sets:
            interpolate_points._selected_node_keys(data, metadata, [name])
    return {
        "data_path": data_path,
        "metadata_path": metadata_path,
        "metadata": metadata,
        "fields": fields,
        "node_sets": node_sets,
    }


def default_full_cache_paths(odb_path, output_path=None):
    output_dir = (
        os.path.dirname(os.path.abspath(output_path))
        if output_path
        else _default_output_dir(odb_path)
    )
    base_name = os.path.splitext(os.path.basename(odb_path))[0]
    return (
        os.path.join(output_dir, "{}_full_field_data.npz".format(base_name)),
        os.path.join(output_dir, "{}_full_field_metadata.json".format(base_name)),
    )


def _normalized_cache_fields(fields):
    selected = fields
    if selected is None:
        from odb_extract.extractor import DEFAULT_FIELDS

        selected = DEFAULT_FIELDS
    return sorted(selected)


def _npz_shapes_match(data_path, expected_shapes):
    from numpy.lib import format as np_format

    if not isinstance(expected_shapes, dict):
        return False
    with zipfile.ZipFile(data_path) as archive:
        members = archive.infolist()
        keys = [member.filename[:-4] for member in members]
        if (
            any(member.is_dir() or not member.filename.endswith(".npy") for member in members)
            or len(keys) != len(set(keys))
            or set(keys) != set(expected_shapes)
        ):
            return False
        for member, key in zip(members, keys):
            expected_shape = expected_shapes[key]
            if not isinstance(expected_shape, list):
                return False
            with archive.open(member) as stream:
                version = np_format.read_magic(stream)
                if version == (1, 0):
                    shape = np_format.read_array_header_1_0(stream)[0]
                elif version == (2, 0):
                    shape = np_format.read_array_header_2_0(stream)[0]
                else:
                    return False
            if tuple(expected_shape) != shape:
                return False
    return True


def _full_cache_is_valid(
    odb_path,
    data_path,
    metadata_path,
    step_name,
    fields,
    instances,
    node_labels,
    frequency_min,
    frequency_max,
    node_sets,
):
    try:
        if not os.path.isfile(data_path) or not os.path.isfile(metadata_path):
            return False
        odb_mtime = os.path.getmtime(odb_path)
        if min(os.path.getmtime(data_path), os.path.getmtime(metadata_path)) < odb_mtime:
            return False
        with open(metadata_path, "r", encoding="utf-8") as stream:
            metadata = json.load(stream)
        if not isinstance(metadata, dict):
            return False
        source_odb = metadata.get("source_odb")
        if not isinstance(source_odb, str):
            return False
        if os.path.normcase(os.path.abspath(source_odb)) != os.path.normcase(
            os.path.abspath(odb_path)
        ):
            return False
        actual_step = metadata.get("step")
        if not isinstance(actual_step, str) or not actual_step:
            return False
        command_options = metadata.get("command_options")
        if not isinstance(command_options, dict):
            return False
        if command_options.get("step") != step_name:
            return False
        if step_name and actual_step != step_name:
            return False
        cached_fields = metadata.get("fields")
        if not isinstance(cached_fields, list):
            return False
        if sorted(cached_fields) != _normalized_cache_fields(fields):
            return False
        expected_filters = {
            "instances": list(instances or []),
            "node_labels": list(node_labels or []),
            "node_sets": list(node_sets or []),
            "frequency_min": frequency_min,
            "frequency_max": frequency_max,
        }
        if metadata.get("filters") != expected_filters:
            return False
        return _npz_shapes_match(data_path, metadata.get("array_shapes"))
    except Exception:
        return False


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
    raise ValueError(_format_parse_error(missing_message, output_text))


def _format_parse_error(message, output_text, max_chars=2000):
    output_text = (output_text or "").strip()
    if not output_text:
        return "{}\nAbaqus output was empty.".format(message)
    if len(output_text) > max_chars:
        output_text = output_text[-max_chars:]
    return "{}\nAbaqus output tail:\n{}".format(message, output_text)


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


@contextlib.contextmanager
def _external_program_dll_context():
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if sys.platform != "win32" or not bundle_dir:
        yield
        return
    ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        yield
    finally:
        ctypes.windll.kernel32.SetDllDirectoryW(bundle_dir)


def run_command(command, log_callback=None):
    if log_callback is None:
        with _external_program_dll_context():
            completed = subprocess.run(command)
        return completed.returncode

    with _external_program_dll_context():
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
    saw_error = False
    if process.stdout is not None:
        for line in process.stdout:
            text = line.rstrip()
            if "error:" in text.lower():
                saw_error = True
            log_callback(text)
    code = process.wait()
    return code if code != 0 or not saw_error else 1


def run_command_capture(command):
    with _external_program_dll_context():
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


def _default_subset_runner(**kwargs):
    from odb_extract import interpolate_points

    return interpolate_points.subset_node_sets_files(**kwargs)


def run_cached_query(
    data_path,
    metadata_path,
    output_path,
    metadata_output_path,
    fields,
    points_path=None,
    node_sets=None,
    neighbors=4,
    exact_tol=1.0e-9,
    point_runner=None,
    subset_runner=None,
    log_callback=None,
):
    if points_path:
        if log_callback:
            log_callback(UI_TEXT["starting_cache_query"])
        runner = _default_point_runner if point_runner is None else point_runner
        runner(
            data_path=data_path,
            metadata_path=metadata_path,
            points_path=points_path,
            output_path=output_path,
            metadata_output_path=metadata_output_path,
            fields=fields,
            node_sets=node_sets,
            neighbors=neighbors,
            exact_tol=exact_tol,
        )
    else:
        if log_callback:
            log_callback(UI_TEXT["starting_cache_subset"])
        runner = _default_subset_runner if subset_runner is None else subset_runner
        runner(
            data_path=data_path,
            metadata_path=metadata_path,
            output_path=output_path,
            metadata_output_path=metadata_output_path,
            fields=fields,
            node_sets=node_sets,
        )
    return 0


run_cached_point_query = run_cached_query


def _missing_file_paths(paths):
    return [path for path in paths if path and not os.path.isfile(path)]


def _temporary_output_pair(output_path):
    output_dir = tempfile.gettempdir()
    base_name = os.path.splitext(os.path.basename(output_path))[0] or "points"
    npz_fd, npz_path = tempfile.mkstemp(
        prefix="odb_extract_{}_".format(base_name), suffix=".npz", dir=output_dir
    )
    json_fd, json_path = tempfile.mkstemp(
        prefix="odb_extract_{}_".format(base_name), suffix=".json", dir=output_dir
    )
    os.close(npz_fd)
    os.close(json_fd)
    _remove_file_if_exists(npz_path)
    _remove_file_if_exists(json_path)
    return npz_path, json_path


def _remove_file_if_exists(path):
    if path and os.path.isfile(path):
        os.remove(path)


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
    points_path=None,
    neighbors=4,
    exact_tol=1.0e-9,
    extraction_runner=None,
    point_runner=None,
    verbose=True,
    log_callback=None,
    keep_full_cache=False,
):
    if node_sets and points_path:
        raise ValueError("--node-sets and --points cannot be used together.")

    uses_default_point_runner = point_runner is None
    temp_output_path = None
    temp_metadata_path = None
    cache_is_valid = False
    if points_path:
        default_npz, default_metadata = default_output_paths(odb_path)
        output_path = output_path or default_npz
        metadata_path = metadata_path or default_metadata
        if keep_full_cache:
            extraction_output_path, extraction_metadata_path = default_full_cache_paths(
                odb_path, output_path
            )
            cache_is_valid = _full_cache_is_valid(
                odb_path,
                extraction_output_path,
                extraction_metadata_path,
                step_name,
                fields,
                instances,
                node_labels,
                frequency_min,
                frequency_max,
                node_sets,
            )
        else:
            temp_output_path, temp_metadata_path = _temporary_output_pair(output_path)
            extraction_output_path = temp_output_path
            extraction_metadata_path = temp_metadata_path
    else:
        extraction_output_path = output_path
        extraction_metadata_path = metadata_path
    if node_sets:
        default_npz, default_metadata = default_output_paths(odb_path)
        output_path = output_path or default_npz
        metadata_path = metadata_path or default_metadata
        extraction_output_path = output_path
        extraction_metadata_path = metadata_path

    extraction_runner = run_extraction if extraction_runner is None else extraction_runner
    try:
        if cache_is_valid:
            code = 0
            if log_callback:
                log_callback(
                    UI_TEXT["full_cache_hit"].format(path=extraction_output_path)
                )
        else:
            if log_callback:
                log_callback(UI_TEXT["starting_extraction"])
            code = extraction_runner(
                abaqus_command=abaqus_command,
                odb_path=odb_path,
                extractor_module=extractor_module or default_extractor_module(),
                output_path=extraction_output_path,
                metadata_path=extraction_metadata_path,
                step_name=step_name,
                fields=fields,
                instances=instances,
                node_labels=node_labels,
                frequency_min=frequency_min,
                frequency_max=frequency_max,
                node_sets=node_sets,
                verbose=verbose,
                log_callback=log_callback,
            )
        if code != 0 or not points_path:
            return code

        if uses_default_point_runner:
            missing_paths = _missing_file_paths(
                [extraction_output_path, extraction_metadata_path]
            )
            if missing_paths:
                raise RuntimeError(
                    "Abaqus 返回成功，但提取阶段未生成目标点导出需要的文件：{}。"
                    "请检查上方 Abaqus 日志，或手动指定 NPZ 输出和元数据 JSON。".format(
                        ", ".join(missing_paths)
                    )
                )

        if log_callback:
            log_callback(UI_TEXT["starting_point_export"])

        point_runner = _default_point_runner if uses_default_point_runner else point_runner
        point_runner(
            data_path=extraction_output_path,
            metadata_path=extraction_metadata_path,
            points_path=points_path,
            output_path=output_path,
            metadata_output_path=metadata_path,
            fields=None,
            neighbors=neighbors,
            exact_tol=exact_tol,
        )

        if log_callback:
            log_callback(UI_TEXT["point_export_finished_log"].format(path=output_path))
        return 0
    finally:
        _remove_file_if_exists(temp_output_path)
        _remove_file_if_exists(temp_metadata_path)


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
        points_path=args.points,
        neighbors=args.neighbors,
        exact_tol=args.exact_tol,
        verbose=sys.stdout is not None,
    )


class ExtractOdbApp(object):
    def __init__(self, root):
        import tkinter as tk

        self.tk = tk
        self.root = root
        self.root.title(UI_TEXT["window_title"])
        self.root.geometry("880x720")
        self.root.minsize(760, 620)

        self.source_mode_var = tk.StringVar(value="odb")
        self.odb_var = tk.StringVar()
        self.cache_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.points_var = tk.StringVar()
        self.neighbors_var = tk.StringVar(value="4")
        self.exact_tol_var = tk.StringVar(value="1e-9")
        self.step_var = tk.StringVar()
        self.instances_var = tk.StringVar()
        self.node_labels_var = tk.StringVar()
        self.frequency_min_var = tk.StringVar()
        self.frequency_max_var = tk.StringVar()
        self.abaqus_var = tk.StringVar(value=find_abaqus_command() or "")
        self.keep_full_cache_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value=UI_TEXT["ready"])
        self._running = False
        self.field_vars = {}
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

        ttk.Label(frame, text=UI_TEXT["source_mode"]).grid(row=0, column=0, sticky="w", pady=4)
        source_frame = ttk.Frame(frame)
        source_frame.grid(row=0, column=1, columnspan=2, sticky="w", pady=4)
        source_odb_button = ttk.Radiobutton(
            source_frame,
            text=UI_TEXT["source_odb"],
            variable=self.source_mode_var,
            value="odb",
            command=self._update_source_mode,
        )
        source_odb_button.pack(side="left")
        source_cache_button = ttk.Radiobutton(
            source_frame,
            text=UI_TEXT["source_cache"],
            variable=self.source_mode_var,
            value="cache",
            command=self._update_source_mode,
        )
        source_cache_button.pack(side="left", padx=(12, 0))
        self.source_buttons = [source_odb_button, source_cache_button]

        self.odb_entry, self.odb_browse_button = self._add_path_row(
            frame, 1, UI_TEXT["odb_file"], self.odb_var, self.choose_odb
        )
        self.cache_entry, cache_browse_button = self._add_path_row(
            frame, 2, UI_TEXT["cache_file"], self.cache_var, self.choose_cache
        )
        assert cache_browse_button is not None
        self.cache_browse_button = cache_browse_button
        self.output_entry, self.output_browse_button = self._add_path_row(
            frame, 3, UI_TEXT["npz_output"], self.output_var, self.choose_output
        )
        self.points_entry, self.points_browse_button = self._add_path_row(
            frame, 4, UI_TEXT["points_file"], self.points_var, self.choose_points
        )
        self.abaqus_entry, _unused_button = self._add_path_row(
            frame, 5, UI_TEXT["abaqus_command"], self.abaqus_var, None
        )
        ttk.Label(frame, text="Step").grid(row=7, column=0, sticky="w", pady=4)
        self.step_entry = ttk.Entry(frame, textvariable=self.step_var)
        self.step_entry.grid(
            row=7, column=1, columnspan=2, sticky="ew", pady=4
        )

        self.refresh_button = ttk.Button(
            frame, text=UI_TEXT["refresh_fields"], command=self.refresh_fields
        )
        self.refresh_button.grid(
            row=8, column=0, columnspan=3, sticky="ew", pady=4
        )

        ttk.Label(frame, text=UI_TEXT["instance_filter"]).grid(row=9, column=0, sticky="w", pady=4)
        self.instances_entry = ttk.Entry(frame, textvariable=self.instances_var)
        self.instances_entry.grid(
            row=9, column=1, columnspan=2, sticky="ew", pady=4
        )

        ttk.Label(frame, text=UI_TEXT["node_label_filter"]).grid(
            row=10, column=0, sticky="w", pady=4
        )
        self.node_labels_entry = ttk.Entry(frame, textvariable=self.node_labels_var)
        self.node_labels_entry.grid(
            row=10, column=1, columnspan=2, sticky="ew", pady=4
        )

        self._build_node_set_widgets(frame, 11)

        ttk.Label(frame, text=UI_TEXT["frequency_min"]).grid(row=13, column=0, sticky="w", pady=4)
        frequency_frame = ttk.Frame(frame)
        frequency_frame.grid(row=13, column=1, columnspan=2, sticky="ew", pady=4)
        frequency_frame.columnconfigure(0, weight=1)
        frequency_frame.columnconfigure(2, weight=1)
        self.frequency_min_entry = ttk.Entry(
            frequency_frame, textvariable=self.frequency_min_var
        )
        self.frequency_min_entry.grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Label(frequency_frame, text=UI_TEXT["frequency_max"]).grid(
            row=0, column=1, padx=8
        )
        self.frequency_max_entry = ttk.Entry(
            frequency_frame, textvariable=self.frequency_max_var
        )
        self.frequency_max_entry.grid(
            row=0, column=2, sticky="ew"
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

        self.keep_full_cache_check = ttk.Checkbutton(
            frame,
            text=UI_TEXT["keep_full_cache"],
            variable=self.keep_full_cache_var,
        )
        self.keep_full_cache_check.grid(
            row=17, column=0, columnspan=3, sticky="w", pady=(2, 4)
        )

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
        self.merge_button = ttk.Button(
            button_bar,
            text=UI_TEXT["merge_results"],
            command=self.open_merge_window,
        )
        self.merge_button.pack(side="left", padx=(8, 0))
        ttk.Label(button_bar, textvariable=self.status_var).pack(side="left", padx=12)

        self.log_text = tk.Text(frame, height=12, wrap="word")
        self.log_text.grid(row=19, column=0, columnspan=3, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, command=self.log_text.yview)
        scrollbar.grid(row=19, column=3, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self._update_source_mode(reset=False)

    def _add_path_row(self, frame, row, label, variable, command):
        from tkinter import ttk

        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
        entry = ttk.Entry(frame, textvariable=variable)
        entry.grid(
            row=row, column=1, sticky="ew", pady=4, padx=(0, 6)
        )
        button = None
        if command is None:
            ttk.Label(frame, text="").grid(row=row, column=2, pady=4)
        else:
            button = ttk.Button(frame, text=UI_TEXT["browse"], command=command)
            button.grid(
                row=row, column=2, sticky="ew", pady=4
            )
        return entry, button

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
        if not self.output_var.get().strip():
            output_path, _metadata_path = default_output_paths(path)
            self.output_var.set(output_path)
        self.refresh_fields()
        self.refresh_node_sets()

    def choose_cache(self):
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title=UI_TEXT["select_cache_title"],
            filetypes=(("Compressed NumPy", "*.npz"), ("All files", "*.*")),
        )
        if not path:
            return
        self.cache_var.set(path)
        self._load_cache_selection()
        points_path = self.points_var.get().strip()
        if points_path:
            self.output_var.set(default_cache_query_output_path(path, points_path))

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

    def choose_points(self):
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title=UI_TEXT["select_points_title"],
            filetypes=(
                ("Point files", "*.csv *.xlsx *.xlsm"),
                ("CSV", "*.csv"),
                ("Excel", "*.xlsx *.xlsm"),
                ("All files", "*.*"),
            ),
        )
        if path:
            self.points_var.set(path)
            if self.source_mode_var.get() == "cache" and self.cache_var.get().strip():
                self.output_var.set(
                    default_cache_query_output_path(self.cache_var.get().strip(), path)
                )

    def _load_cache_selection(self):
        from tkinter import messagebox

        try:
            source = load_cache_source(self.cache_var.get().strip())
        except Exception as exc:
            self.log(str(exc))
            messagebox.showerror(UI_TEXT["invalid_cache_title"], str(exc))
            return None
        self._show_discovered_fields({"step": "cache", "fields": source["fields"]})
        self._show_discovered_node_sets({"node_sets": source["node_sets"]})
        self.log(
            UI_TEXT["cache_loaded"].format(
                fields=len(source["fields"]), node_sets=len(source["node_sets"])
            )
        )
        if not source["node_sets"]:
            self.log(UI_TEXT["cache_without_node_sets"])
        return source

    def _update_source_mode(self, reset=True):
        cache_mode = self.source_mode_var.get() == "cache"
        odb_state = "disabled" if cache_mode else "normal"
        cache_state = "normal" if cache_mode else "disabled"
        for widget in (
            self.odb_entry,
            self.odb_browse_button,
            self.abaqus_entry,
            self.step_entry,
            self.instances_entry,
            self.node_labels_entry,
            self.frequency_min_entry,
            self.frequency_max_entry,
            self.refresh_nset_button,
            self.inspect_button,
            self.keep_full_cache_check,
        ):
            if widget is not None:
                widget.configure(state=odb_state)
        self.cache_entry.configure(state=cache_state)
        self.cache_browse_button.configure(state=cache_state)
        self.refresh_button.configure(
            text=UI_TEXT["refresh_cache_fields"] if cache_mode else UI_TEXT["refresh_fields"]
        )
        self.run_button.configure(
            text=UI_TEXT["run_cache_button"] if cache_mode else UI_TEXT["run_button"]
        )
        if not reset:
            return
        self._clear_field_checks()
        self._clear_node_set_checks()
        self.node_sets_var.set("")
        if cache_mode and self.cache_var.get().strip():
            self._load_cache_selection()

    def log(self, message):
        self.log_text.insert("end", "{}\n".format(message))
        self.log_text.see("end")

    def _thread_log(self, message):
        self.root.after(0, self.log, message)

    def _set_running(self, running):
        self._running = running
        for button in self.source_buttons:
            button.configure(state="disabled" if running else "normal")
        self.cache_browse_button.configure(state="disabled" if running else "normal")
        self.run_button.configure(state="disabled" if running else "normal")
        self.inspect_button.configure(state="disabled" if running else "normal")
        self.merge_button.configure(state="disabled" if running else "normal")
        self.refresh_button.configure(state="disabled" if running else "normal")
        for button in self.field_selection_buttons:
            button.configure(state="disabled" if running else "normal")
        self.refresh_nset_button.configure(state="disabled" if running else "normal")
        for button in self.node_set_selection_buttons:
            button.configure(state="disabled" if running else "normal")
        self.status_var.set(UI_TEXT["running"] if running else UI_TEXT["ready"])
        if not running:
            self._update_source_mode(reset=False)

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

    def _set_field_selection(self, mode):
        if mode not in ("all", "none"):
            raise ValueError("Unknown field selection mode: {}".format(mode))
        selected = mode == "all"
        for variable in self.field_vars.values():
            variable.set(selected)

    def _show_discovered_fields(self, metadata):
        tk = self.tk
        from tkinter import ttk

        fields = metadata.get("fields", [])
        self._clear_field_checks()
        if not fields:
            ttk.Label(self.field_checks_frame, text=UI_TEXT["no_fields_found"]).grid(
                row=0, column=0, sticky="w", padx=8, pady=8
            )
            return

        for index, field_name in enumerate(fields):
            variable = tk.BooleanVar(value=False)
            self.field_vars[field_name] = variable
            ttk.Checkbutton(
                self.field_checks_frame,
                text=field_name,
                variable=variable,
            ).grid(row=index // 6, column=index % 6, sticky="w", padx=8, pady=4)

        self.field_canvas.yview_moveto(0)
        self.log(UI_TEXT["found_fields"].format(step=metadata.get("step", ""), count=len(fields)))

    def refresh_fields(self):
        if self._running:
            return
        if self.source_mode_var.get() == "cache":
            if not self.cache_var.get().strip():
                self.log(UI_TEXT["missing_cache_message"])
                return
            self._load_cache_selection()
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

    def open_merge_window(self):
        from odb_extract import merge_gui

        merge_gui.MergePointDataWindow(self.root)

    def _selected_fields(self):
        return [
            field_name
            for field_name, variable in sorted(self.field_vars.items())
            if variable.get()
        ]

    def _validate_cache_inputs(self):
        from tkinter import messagebox

        cache_path = self.cache_var.get().strip()
        if not cache_path:
            messagebox.showerror(UI_TEXT["invalid_cache_title"], UI_TEXT["missing_cache_message"])
            return None
        try:
            source = load_cache_source(cache_path)
        except Exception as exc:
            messagebox.showerror(UI_TEXT["invalid_cache_title"], str(exc))
            return None
        points_path = self.points_var.get().strip() or None
        node_sets = parse_node_set_text(self.node_sets_var.get())
        if not points_path and not node_sets:
            messagebox.showerror(
                UI_TEXT["invalid_cache_title"], UI_TEXT["missing_cache_selection"]
            )
            return None
        output_path = self.output_var.get().strip()
        if not output_path:
            messagebox.showerror(
                UI_TEXT["invalid_cache_title"], UI_TEXT["missing_output_for_cache"]
            )
            return None
        metadata_output_path = metadata_path_for_output(output_path)
        if _same_path(output_path, cache_path) or _same_path(
            metadata_output_path, source["metadata_path"]
        ):
            messagebox.showerror(
                UI_TEXT["invalid_cache_title"], UI_TEXT["cache_output_conflict"]
            )
            return None
        fields = self._selected_fields()
        if not fields:
            messagebox.showerror(
                UI_TEXT["no_fields_selected_title"], UI_TEXT["no_fields_selected_message"]
            )
            return None
        if any(field not in source["fields"] for field in fields):
            messagebox.showerror(
                UI_TEXT["invalid_cache_title"], "所选场输出不在缓存中。"
            )
            return None
        if any(name not in source["node_sets"] for name in (node_sets or [])):
            messagebox.showerror(
                UI_TEXT["invalid_cache_title"], "所选节点集不在缓存中。"
            )
            return None
        neighbors = 4
        exact_tol = 1.0e-9
        if points_path:
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
                parsed_tol = parse_optional_float(self.exact_tol_var.get())
            except ValueError:
                messagebox.showerror(
                    UI_TEXT["invalid_exact_tol_title"],
                    UI_TEXT["invalid_exact_tol_message"],
                )
                return None
            exact_tol = parsed_tol if parsed_tol is not None else 1.0e-9
        return {
            "source_mode": "cache",
            "data_path": cache_path,
            "metadata_path": source["metadata_path"],
            "points_path": points_path,
            "output_path": output_path,
            "metadata_output_path": metadata_output_path,
            "fields": fields,
            "node_sets": node_sets,
            "neighbors": neighbors,
            "exact_tol": exact_tol,
        }

    def _validate_inputs(self):
        from tkinter import messagebox

        source_mode_var = getattr(self, "source_mode_var", None)
        if source_mode_var is not None and source_mode_var.get() == "cache":
            return self._validate_cache_inputs()

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
        if not fields:
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
        metadata_path = metadata_path_for_output(output_path) if output_path else None
        step_name = self.step_var.get().strip() or None
        points_path = self.points_var.get().strip() or None
        if node_sets and points_path:
            messagebox.showerror(
                UI_TEXT["exclusive_points_node_sets_title"],
                UI_TEXT["exclusive_points_node_sets_message"],
            )
            return None
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
            "points_path": points_path,
            "neighbors": neighbors,
            "exact_tol": exact_tol if exact_tol is not None else 1.0e-9,
            "keep_full_cache": bool(self.keep_full_cache_var.get()),
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

        cache_mode = options.get("source_mode") == "cache"
        try:
            if cache_mode:
                cache_options = dict(options)
                cache_options.pop("source_mode", None)
                code = run_cached_query(
                    log_callback=self._thread_log,
                    **cache_options
                )
            else:
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
                self.log(
                    UI_TEXT["cache_query_finished"]
                    if cache_mode
                    else UI_TEXT["extraction_finished_log"]
                )
                messagebox.showinfo(
                    UI_TEXT["extraction_finished_title"],
                    UI_TEXT["cache_query_finished"]
                    if cache_mode
                    else UI_TEXT["extraction_finished_message"],
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
