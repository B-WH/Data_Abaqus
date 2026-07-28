"""Inspect project NPZ files and export field magnitudes to CSV."""

from __future__ import print_function

import csv
import json
import os
import re
import tempfile
import threading

import numpy as np


COMMON_COLUMNS = ("frequency", "field", "component")


def _metadata_path(data_path, metadata_path=None):
    if metadata_path is None:
        from odb_extract.launcher import metadata_path_for_output

        metadata_path = metadata_path_for_output(data_path)
    return os.path.abspath(metadata_path)


def _load_metadata(data_path, metadata_path=None):
    resolved = _metadata_path(data_path, metadata_path)
    if not os.path.isfile(resolved):
        raise ValueError("Metadata JSON does not exist: {}".format(resolved))
    try:
        with open(resolved, "r", encoding="utf-8") as stream:
            metadata = json.load(stream)
    except (OSError, ValueError) as exc:
        raise ValueError("Cannot read metadata JSON {}: {}".format(resolved, exc))
    if not isinstance(metadata, dict):
        raise ValueError("Metadata JSON must contain an object: {}".format(resolved))
    return resolved, metadata


def inspect_source(data_path, metadata_path=None, preview_count=8):
    """Return field names and compact per-array summaries."""
    data_path = os.path.abspath(data_path)
    resolved_metadata, metadata = _load_metadata(data_path, metadata_path)
    summaries = {}
    try:
        with np.load(data_path) as data:
            for name in sorted(data.files):
                values = np.asarray(data[name])
                nan_count = (
                    int(np.isnan(values).sum())
                    if np.issubdtype(values.dtype, np.inexact)
                    else 0
                )
                summaries[name] = {
                    "shape": list(values.shape),
                    "dtype": str(values.dtype),
                    "size": int(values.size),
                    "nan_count": nan_count,
                    "preview": values.reshape(-1)[: int(preview_count)].tolist(),
                }
    except (OSError, ValueError) as exc:
        raise ValueError("Cannot read NPZ {}: {}".format(data_path, exc))
    fields = sorted((metadata.get("field_outputs") or {}).keys())
    return {
        "data_path": data_path,
        "metadata_path": resolved_metadata,
        "fields": fields,
        "arrays": summaries,
    }


def _normalize_selection(values):
    if values is None:
        return None
    return {str(value) for value in values}


def _node_identities(data, metadata, field_metadata, entity_count):
    nodes = metadata.get("nodes") or []
    points = field_metadata.get("points") or nodes
    if len(points) != entity_count:
        raise ValueError("NODE identity count does not match field shape.")

    coordinates = None
    if "node_coordinates" in data:
        coordinates = np.asarray(data["node_coordinates"])
    coordinate_lookup = {}
    for index, node in enumerate(nodes):
        label = node.get("node_label", node.get("label"))
        coordinate = node.get("coordinates")
        if coordinate is None and coordinates is not None and index < len(coordinates):
            coordinate = coordinates[index]
        if label is not None and coordinate is not None:
            coordinate_lookup[(node.get("instance"), int(label))] = coordinate

    identities = []
    for index, point in enumerate(points):
        label = point.get("node_label", point.get("label"))
        if label is None:
            raise ValueError("NODE identity is missing node_label.")
        instance = point.get("instance")
        coordinate = point.get("coordinates")
        if coordinate is None:
            coordinate = coordinate_lookup.get((instance, int(label)))
        if coordinate is None and coordinates is not None and len(points) == len(coordinates):
            coordinate = coordinates[index]
        if coordinate is None or len(coordinate) < 3:
            raise ValueError("NODE identity is missing coordinates.")
        identities.append(
            {
                "instance": instance,
                "node_label": int(label),
                "x": float(coordinate[0]),
                "y": float(coordinate[1]),
                "z": float(coordinate[2]),
            }
        )
    return identities


def _point_identities(data, metadata, entity_count):
    points = metadata.get("points") or []
    point_ids = np.asarray(data["point_ids"]) if "point_ids" in data else None
    coordinates = (
        np.asarray(data["point_coordinates"])
        if "point_coordinates" in data
        else None
    )
    if points and len(points) != entity_count:
        raise ValueError("POINT identity count does not match field shape.")
    if not points and (point_ids is None or coordinates is None):
        raise ValueError("POINT identities are missing.")

    identities = []
    for index in range(entity_count):
        point = points[index] if points else {}
        point_id = point.get("point_id")
        if point_id is None and point_ids is not None:
            point_id = point_ids[index].item()
        coordinate = point.get("coordinates")
        if coordinate is None and coordinates is not None:
            coordinate = coordinates[index]
        if point_id is None or coordinate is None or len(coordinate) < 3:
            raise ValueError("POINT identity is incomplete.")
        identities.append(
            {
                "point_id": point_id,
                "x": float(coordinate[0]),
                "y": float(coordinate[1]),
                "z": float(coordinate[2]),
            }
        )
    return identities


def _element_identities(field_metadata, entity_count):
    points = field_metadata.get("points") or []
    if len(points) != entity_count:
        raise ValueError("ELEMENT identity count does not match field shape.")
    identities = []
    for point in points:
        label = point.get("element_label")
        if label is None:
            raise ValueError("ELEMENT identity is missing element_label.")
        identities.append(
            {
                "instance": point.get("instance"),
                "element_label": int(label),
                "integration_point": point.get("integration_point"),
                "section_point": point.get("section_point"),
            }
        )
    return identities


def _value_identities(field_metadata, entity_count):
    points = field_metadata.get("points") or []
    if len(points) != entity_count:
        raise ValueError("VALUE identity count does not match field shape.")
    identities = []
    for point in points:
        value_index = point.get("value_index")
        if value_index is None:
            raise ValueError("VALUE identity is missing value_index.")
        identities.append(
            {"instance": point.get("instance"), "value_index": int(value_index)}
        )
    return identities


def _field_identities(data, metadata, field_metadata, entity_count):
    location = str(field_metadata.get("location") or "VALUE").upper()
    if location == "NODE":
        return location, _node_identities(
            data, metadata, field_metadata, entity_count
        )
    if location == "POINT":
        return location, _point_identities(data, metadata, entity_count)
    if location in ("ELEMENT", "INTEGRATION_POINT"):
        return "ELEMENT", _element_identities(field_metadata, entity_count)
    return "VALUE", _value_identities(field_metadata, entity_count)


def _primary_identity(identity):
    for name in ("node_label", "point_id", "element_label", "value_index"):
        if identity.get(name) is not None:
            return str(identity[name])
    return ""


def _prepare_export(
    data,
    metadata,
    fields=None,
    components=None,
    frequency_min=None,
    frequency_max=None,
    entity_ids=None,
):
    if "frequencies" not in data:
        raise ValueError("NPZ is missing frequencies.")
    frequencies = np.asarray(data["frequencies"], dtype=float)
    if frequencies.ndim != 1:
        raise ValueError("frequencies must be one-dimensional.")
    frame_indexes = [
        index
        for index, frequency in enumerate(frequencies)
        if (frequency_min is None or frequency >= frequency_min)
        and (frequency_max is None or frequency <= frequency_max)
    ]

    field_outputs = metadata.get("field_outputs") or {}
    selected_fields = list(fields) if fields is not None else sorted(field_outputs)
    if not selected_fields:
        raise ValueError("At least one field is required.")
    component_filter = _normalize_selection(components)
    entity_filter = _normalize_selection(entity_ids)
    array_layouts = metadata.get("array_layouts") or {}
    specs = []
    for field_name in selected_fields:
        field_metadata = field_outputs.get(field_name)
        if not isinstance(field_metadata, dict):
            raise ValueError("Field {} is missing from metadata.".format(field_name))
        real_key = "{}_real".format(field_name)
        imag_key = "{}_imag".format(field_name)
        if real_key not in data or imag_key not in data:
            raise ValueError("Field {} is missing real or imaginary data.".format(field_name))
        real = np.asarray(data[real_key])
        imag = np.asarray(data[imag_key])
        if real.shape != imag.shape:
            raise ValueError(
                "Field {} real and imaginary shapes do not match.".format(field_name)
            )
        if real.ndim != 3 or real.shape[0] != len(frequencies):
            raise ValueError(
                "Field {} must use frame, entity, component shapes.".format(
                    field_name
                )
            )
        layout = array_layouts.get(real_key) or field_metadata.get("array_layout")
        if not layout or len(layout) != 3 or layout[0] != "frame" or layout[2] != "component":
            raise ValueError("Field {} has an unsupported array layout.".format(field_name))
        component_names = field_metadata.get("components") or [
            "component_{}".format(index + 1) for index in range(real.shape[2])
        ]
        if len(component_names) != real.shape[2]:
            raise ValueError("Field {} component count does not match shape.".format(field_name))
        component_indexes = [
            index
            for index, name in enumerate(component_names)
            if component_filter is None or str(name) in component_filter
        ]
        if not component_indexes:
            continue
        location, identities = _field_identities(
            data, metadata, field_metadata, real.shape[1]
        )
        entity_indexes = [
            index
            for index, identity in enumerate(identities)
            if entity_filter is None
            or _primary_identity(identity) in entity_filter
        ]
        specs.append(
            {
                "name": field_name,
                "location": location,
                "real": real,
                "imag": imag,
                "components": list(component_names),
                "component_indexes": component_indexes,
                "identities": identities,
                "entity_indexes": entity_indexes,
            }
        )
    if not specs:
        raise ValueError("No field components match the selection.")
    return frequencies, frame_indexes, specs


def _entity_columns(spec):
    columns = [
        (_primary_identity(spec["identities"][index]), index)
        for index in spec["entity_indexes"]
    ]
    names = [name for name, _index in columns]
    if len(names) != len(set(names)):
        raise ValueError(
            "Field {} has duplicate entity identifiers.".format(spec["name"])
        )
    conflicts = sorted(set(names).intersection(COMMON_COLUMNS))
    if conflicts:
        raise ValueError(
            "Entity identifier conflicts with CSV column: {}".format(conflicts[0])
        )
    return columns


def _selected_columns(specs):
    columns = list(COMMON_COLUMNS)
    used = set(columns)
    for spec in specs:
        for name, _index in _entity_columns(spec):
            if name not in used:
                columns.append(name)
                used.add(name)
    return columns


def _coordinate_rows(specs):
    coordinates = {}
    for spec in specs:
        for column, entity_index in _entity_columns(spec):
            identity = spec["identities"][entity_index]
            if not all(axis in identity for axis in ("x", "y", "z")):
                continue
            values = tuple(float(identity[axis]) for axis in ("x", "y", "z"))
            if column in coordinates and coordinates[column] != values:
                raise ValueError(
                    "Entity {} has inconsistent coordinates.".format(column)
                )
            coordinates[column] = values
    if not coordinates:
        return []
    rows = []
    for coordinate_index, axis in enumerate(("x", "y", "z")):
        row = {"frequency": axis}
        row.update(
            {
                column: values[coordinate_index]
                for column, values in coordinates.items()
            }
        )
        rows.append(row)
    return rows


def _iter_selected_rows(frequencies, frame_indexes, specs):
    for spec in specs:
        entity_columns = _entity_columns(spec)
        if not entity_columns:
            continue
        for frame_index in frame_indexes:
            for component_index in spec["component_indexes"]:
                row = {
                    "frequency": float(frequencies[frame_index]),
                    "field": spec["name"],
                    "component": spec["components"][component_index],
                }
                for column, entity_index in entity_columns:
                    row[column] = float(
                        np.hypot(
                            spec["real"][frame_index, entity_index, component_index],
                            spec["imag"][frame_index, entity_index, component_index],
                        )
                    )
                yield row


def estimate_export_rows(
    data_path,
    metadata_path=None,
    fields=None,
    components=None,
    frequency_min=None,
    frequency_max=None,
    entity_ids=None,
):
    """Return the selected wide-table row count."""
    _resolved_metadata, metadata = _load_metadata(data_path, metadata_path)
    with np.load(data_path) as data:
        _frequencies, frame_indexes, specs = _prepare_export(
            data,
            metadata,
            fields=fields,
            components=components,
            frequency_min=frequency_min,
            frequency_max=frequency_max,
            entity_ids=entity_ids,
        )
        return len(_coordinate_rows(specs)) + sum(
            len(frame_indexes)
            * len(spec["component_indexes"])
            for spec in specs
            if spec["entity_indexes"]
        )


def export_magnitude_csv(
    data_path,
    output_path,
    metadata_path=None,
    fields=None,
    components=None,
    frequency_min=None,
    frequency_max=None,
    entity_ids=None,
):
    """Atomically export selected magnitudes with entity IDs as CSV columns."""
    data_path = os.path.abspath(data_path)
    output_path = os.path.abspath(output_path)
    resolved_metadata, metadata = _load_metadata(data_path, metadata_path)
    if os.path.normcase(output_path) in {
        os.path.normcase(data_path),
        os.path.normcase(resolved_metadata),
    }:
        raise ValueError("CSV output must not overwrite NPZ or metadata input.")

    output_dir = os.path.dirname(output_path) or os.getcwd()
    os.makedirs(output_dir, exist_ok=True)
    temporary_path = None
    row_count = 0
    try:
        with np.load(data_path) as data:
            frequencies, frame_indexes, specs = _prepare_export(
                data,
                metadata,
                fields=fields,
                components=components,
                frequency_min=frequency_min,
                frequency_max=frequency_max,
                entity_ids=entity_ids,
            )
            descriptor, temporary_path = tempfile.mkstemp(
                prefix=".npz-export-", suffix=".csv", dir=output_dir
            )
            os.close(descriptor)
            with open(
                temporary_path, "w", newline="", encoding="utf-8-sig"
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=_selected_columns(specs))
                writer.writeheader()
                for row in _coordinate_rows(specs):
                    writer.writerow(row)
                    row_count += 1
                for row in _iter_selected_rows(frequencies, frame_indexes, specs):
                    writer.writerow(row)
                    row_count += 1
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path and os.path.isfile(temporary_path):
            os.remove(temporary_path)
    return {
        "output_path": output_path,
        "metadata_path": resolved_metadata,
        "row_count": row_count,
    }


EXCEL_ROW_LIMIT = 1_048_576


def _parse_filter_text(text):
    values = [value for value in re.split(r"[,;\s]+", (text or "").strip()) if value]
    return values or None


class MagnitudeCsvWindow(object):
    """Tkinter window for inspecting NPZ arrays and exporting magnitudes."""

    def __init__(self, parent):
        import tkinter as tk

        self.tk = tk
        self.root = tk.Toplevel(parent)
        self.root.title("查看/转换 NPZ")
        self.root.geometry("900x700")
        self.root.minsize(760, 600)
        self.data_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.components_var = tk.StringVar()
        self.entities_var = tk.StringVar()
        self.frequency_min_var = tk.StringVar()
        self.frequency_max_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")
        self.source = None
        self._running = False
        self._build_widgets()

    def _build_widgets(self):
        tk = self.tk
        from tkinter import ttk

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)

        self._add_path_row(frame, 0, "NPZ 文件", self.data_var, self.choose_input)
        self._add_path_row(frame, 1, "CSV 输出", self.output_var, self.choose_output)
        self.load_button = ttk.Button(frame, text="读取并预览", command=self.load_source)
        self.load_button.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(4, 8))

        filter_box = ttk.LabelFrame(frame, text="导出筛选（留空表示全部）")
        filter_box.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        for column in range(4):
            filter_box.columnconfigure(column, weight=1)
        ttk.Label(filter_box, text="字段（可多选）").grid(
            row=0, column=0, sticky="w", padx=6, pady=(6, 2)
        )
        ttk.Label(filter_box, text="分量").grid(
            row=0, column=1, sticky="w", padx=6, pady=(6, 2)
        )
        ttk.Label(filter_box, text="节点/点/单元编号").grid(
            row=0, column=2, sticky="w", padx=6, pady=(6, 2)
        )
        ttk.Label(filter_box, text="频率范围").grid(
            row=0, column=3, sticky="w", padx=6, pady=(6, 2)
        )
        self.field_list = tk.Listbox(
            filter_box, selectmode="extended", exportselection=False, height=5
        )
        self.field_list.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        ttk.Entry(filter_box, textvariable=self.components_var).grid(
            row=1, column=1, sticky="new", padx=6, pady=(0, 6)
        )
        ttk.Entry(filter_box, textvariable=self.entities_var).grid(
            row=1, column=2, sticky="new", padx=6, pady=(0, 6)
        )
        frequency_box = ttk.Frame(filter_box)
        frequency_box.grid(row=1, column=3, sticky="new", padx=6, pady=(0, 6))
        frequency_box.columnconfigure(0, weight=1)
        frequency_box.columnconfigure(2, weight=1)
        ttk.Entry(frequency_box, textvariable=self.frequency_min_var).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Label(frequency_box, text="至").grid(row=0, column=1, padx=4)
        ttk.Entry(frequency_box, textvariable=self.frequency_max_var).grid(
            row=0, column=2, sticky="ew"
        )

        ttk.Label(frame, text="数组摘要").grid(row=4, column=0, sticky="w")
        columns = ("shape", "dtype", "size", "nan")
        self.array_tree = ttk.Treeview(
            frame, columns=columns, show="tree headings", height=9
        )
        self.array_tree.heading("#0", text="数组")
        self.array_tree.heading("shape", text="形状")
        self.array_tree.heading("dtype", text="类型")
        self.array_tree.heading("size", text="元素数")
        self.array_tree.heading("nan", text="NaN 数")
        self.array_tree.column("#0", width=220)
        self.array_tree.column("shape", width=150)
        self.array_tree.column("dtype", width=90)
        self.array_tree.column("size", width=100)
        self.array_tree.column("nan", width=90)
        self.array_tree.grid(row=5, column=0, columnspan=3, sticky="nsew")
        array_scrollbar = ttk.Scrollbar(frame, command=self.array_tree.yview)
        array_scrollbar.grid(row=5, column=3, sticky="ns")
        self.array_tree.configure(yscrollcommand=array_scrollbar.set)
        self.array_tree.bind("<<TreeviewSelect>>", self.show_preview)

        ttk.Label(frame, text="数组前 8 个值").grid(
            row=6, column=0, sticky="w", pady=(8, 0)
        )
        self.preview_text = tk.Text(frame, height=4, wrap="word")
        self.preview_text.grid(row=7, column=0, columnspan=3, sticky="ew")
        self.preview_text.configure(state="disabled")

        button_bar = ttk.Frame(frame)
        button_bar.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.export_button = ttk.Button(
            button_bar, text="导出幅值 CSV", command=self.start_export
        )
        self.export_button.pack(side="left")
        ttk.Label(button_bar, textvariable=self.status_var).pack(side="left", padx=12)

    def _add_path_row(self, frame, row, label, variable, command):
        from tkinter import ttk

        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=variable).grid(
            row=row, column=1, sticky="ew", padx=(0, 6), pady=4
        )
        ttk.Button(frame, text="浏览", command=command).grid(
            row=row, column=2, sticky="ew", pady=4
        )

    def choose_input(self):
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="选择 NPZ 文件",
            filetypes=(("Compressed NumPy", "*.npz"), ("All files", "*.*")),
        )
        if not path:
            return
        self.data_var.set(path)
        self.output_var.set(os.path.splitext(path)[0] + "_magnitude.csv")
        self.load_source()

    def choose_output(self):
        from tkinter import filedialog

        current = self.output_var.get().strip() or "magnitude.csv"
        path = filedialog.asksaveasfilename(
            title="选择幅值 CSV 输出",
            defaultextension=".csv",
            initialdir=os.path.dirname(current) or os.getcwd(),
            initialfile=os.path.basename(current),
            confirmoverwrite=True,
            filetypes=(("CSV", "*.csv"), ("All files", "*.*")),
        )
        if path:
            self.output_var.set(path)

    def load_source(self):
        from tkinter import messagebox

        data_path = self.data_var.get().strip()
        if not data_path:
            messagebox.showerror("读取失败", "请选择 NPZ 文件。")
            return False
        try:
            source = inspect_source(data_path)
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))
            return False
        self.source = source
        self.field_list.delete(0, "end")
        for field_name in source["fields"]:
            self.field_list.insert("end", field_name)
        if source["fields"]:
            self.field_list.selection_set(0, "end")
        for item in self.array_tree.get_children():
            self.array_tree.delete(item)
        for name, summary in source["arrays"].items():
            self.array_tree.insert(
                "",
                "end",
                iid=name,
                text=name,
                values=(
                    " × ".join(str(value) for value in summary["shape"]),
                    summary["dtype"],
                    summary["size"],
                    summary["nan_count"],
                ),
            )
        children = self.array_tree.get_children()
        if children:
            self.array_tree.selection_set(children[0])
            self.show_preview()
        self.status_var.set(
            "已读取 {} 个数组、{} 个字段".format(
                len(source["arrays"]), len(source["fields"])
            )
        )
        return True

    def show_preview(self, _event=None):
        if not self.source:
            return
        selected = self.array_tree.selection()
        if not selected:
            return
        preview = self.source["arrays"][selected[0]]["preview"]
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("end", repr(preview))
        self.preview_text.configure(state="disabled")

    def _selected_fields(self):
        return [self.field_list.get(index) for index in self.field_list.curselection()]

    def _export_options(self):
        data_path = self.data_var.get().strip()
        output_path = self.output_var.get().strip()
        if (
            not self.source
            or os.path.normcase(os.path.abspath(data_path))
            != os.path.normcase(self.source["data_path"])
        ):
            raise ValueError("请先读取当前 NPZ 文件。")
        fields = self._selected_fields()
        if not fields:
            raise ValueError("请至少选择一个字段。")
        if not output_path:
            raise ValueError("请设置 CSV 输出路径。")
        minimum_text = self.frequency_min_var.get().strip()
        maximum_text = self.frequency_max_var.get().strip()
        frequency_min = float(minimum_text) if minimum_text else None
        frequency_max = float(maximum_text) if maximum_text else None
        if (
            frequency_min is not None
            and frequency_max is not None
            and frequency_min > frequency_max
        ):
            raise ValueError("频率下限不能大于上限。")
        return {
            "data_path": data_path,
            "output_path": output_path,
            "metadata_path": self.source["metadata_path"],
            "fields": fields,
            "components": _parse_filter_text(self.components_var.get()),
            "frequency_min": frequency_min,
            "frequency_max": frequency_max,
            "entity_ids": _parse_filter_text(self.entities_var.get()),
        }

    def start_export(self):
        from tkinter import messagebox

        if self._running:
            return
        try:
            options = self._export_options()
            estimate_options = dict(options)
            estimate_options.pop("output_path")
            row_count = estimate_export_rows(**estimate_options)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        if row_count + 1 > EXCEL_ROW_LIMIT and not messagebox.askyesno(
            "数据量较大",
            "预计导出 {:,} 行，超过 Excel 单工作表上限。是否继续？".format(
                row_count
            ),
        ):
            return
        if os.path.exists(options["output_path"]) and not messagebox.askyesno(
            "覆盖文件", "CSV 已存在，是否覆盖？"
        ):
            return
        self._set_running(True)
        worker = threading.Thread(target=self._export_worker, args=(options,))
        worker.daemon = True
        worker.start()

    def _export_worker(self, options):
        from tkinter import messagebox

        try:
            result = export_magnitude_csv(**options)
        except Exception as exc:
            error_message = str(exc)

            def fail():
                self._set_running(False)
                messagebox.showerror("导出失败", error_message)

            self.root.after(0, fail)
            return

        def finish():
            self._set_running(False)
            self.status_var.set("已导出 {:,} 行".format(result["row_count"]))
            messagebox.showinfo(
                "导出完成",
                "幅值 CSV 已保存：\n{}".format(result["output_path"]),
            )

        self.root.after(0, finish)

    def _set_running(self, running):
        self._running = running
        state = "disabled" if running else "normal"
        self.load_button.configure(state=state)
        self.export_button.configure(state=state)
        self.status_var.set("正在导出" if running else "就绪")
