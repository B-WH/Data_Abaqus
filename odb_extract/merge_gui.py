"""Tkinter GUI helpers for merging exported ODB point-data files."""

from __future__ import print_function

import os
import threading


UI_TEXT = {
    "ready": "就绪",
    "running": "运行中",
    "browse": "浏览",
    "merge_window_title": "合并频率段结果",
    "merge_inputs": "NPZ 输入",
    "add_merge_inputs": "添加文件",
    "remove_merge_input": "移除",
    "move_merge_input_up": "上移",
    "move_merge_input_down": "下移",
    "merge_output_npz": "合并 NPZ",
    "merge_output_metadata": "合并元数据 JSON",
    "select_merge_inputs_title": "选择要合并的 NPZ 文件",
    "select_merge_output_title": "选择合并 NPZ 输出文件",
    "select_merge_metadata_title": "选择合并元数据 JSON 输出文件",
    "duplicate_frequency_tolerance": "重复频率容差",
    "start_merge": "开始合并",
    "merge_running": "正在合并。",
    "merge_finished_title": "合并完成",
    "merge_finished_message": "频率段结果合并完成。",
    "merge_finished_log": "合并完成：{output}",
    "merge_failed_title": "合并失败",
    "merge_input_count_error": "请至少选择两个 NPZ 文件。",
    "merge_output_missing_error": "请设置合并 NPZ 和元数据 JSON 输出路径。",
    "merge_metadata_missing_error": "找不到配套元数据文件：{path}",
    "merge_invalid_tolerance_error": "重复频率容差必须是正数，或留空使用默认值。",
}


def _parse_optional_float(text):
    text = (text or "").strip()
    if not text:
        return None
    return float(text)


def _default_merge_runner(**kwargs):
    from odb_extract import merge_point_data

    return merge_point_data.merge_files(**kwargs)


def run_merge_point_data(
    data_paths,
    output_path,
    metadata_output_path,
    duplicate_frequency_tolerance=1.0e-8,
    merge_runner=None,
    log_callback=None,
):
    merge_runner = _default_merge_runner if merge_runner is None else merge_runner
    if log_callback:
        log_callback(UI_TEXT["merge_running"])
        for path in data_paths:
            log_callback(path)
    arrays, metadata = merge_runner(
        data_paths=data_paths,
        output_path=output_path,
        metadata_output_path=metadata_output_path,
        duplicate_frequency_tolerance=duplicate_frequency_tolerance,
    )
    result = {
        "frequency_count": int(len(arrays["frequencies"])),
        "frequency_min": metadata.get("merge", {}).get("frequency_min"),
        "frequency_max": metadata.get("merge", {}).get("frequency_max"),
        "output_path": output_path,
        "metadata_output_path": metadata_output_path,
    }
    if log_callback:
        log_callback(UI_TEXT["merge_finished_log"].format(output=output_path))
    return result


class MergePointDataWindow(object):
    def __init__(self, parent, merge_runner=None):
        import tkinter as tk

        self.tk = tk
        self.parent = parent
        self.root = tk.Toplevel(parent)
        self.root.title(UI_TEXT["merge_window_title"])
        self.root.geometry("760x520")
        self.root.minsize(680, 480)
        self.merge_runner = merge_runner
        self.data_paths = []
        self.output_var = tk.StringVar()
        self.metadata_var = tk.StringVar()
        self.duplicate_tol_var = tk.StringVar(value="1e-8")
        self.status_var = tk.StringVar(value=UI_TEXT["ready"])
        self._running = False
        self._build_widgets()

    def _build_widgets(self):
        tk = self.tk
        from tkinter import ttk

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        input_box = ttk.LabelFrame(frame, text=UI_TEXT["merge_inputs"])
        input_box.grid(row=0, column=0, columnspan=3, sticky="nsew", pady=(0, 8))
        input_box.columnconfigure(0, weight=1)
        input_box.rowconfigure(0, weight=1)

        self.listbox = tk.Listbox(input_box, height=8)
        self.listbox.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        list_scrollbar = ttk.Scrollbar(input_box, command=self.listbox.yview)
        list_scrollbar.grid(row=0, column=1, sticky="ns", pady=8)
        self.listbox.configure(yscrollcommand=list_scrollbar.set)

        list_buttons = ttk.Frame(input_box)
        list_buttons.grid(row=0, column=2, sticky="ns", padx=8, pady=8)
        self.add_button = ttk.Button(
            list_buttons,
            text=UI_TEXT["add_merge_inputs"],
            command=self.add_files,
        )
        self.add_button.pack(fill="x", pady=(0, 4))
        self.remove_button = ttk.Button(
            list_buttons,
            text=UI_TEXT["remove_merge_input"],
            command=self.remove_selected,
        )
        self.remove_button.pack(fill="x", pady=(0, 4))
        self.up_button = ttk.Button(
            list_buttons,
            text=UI_TEXT["move_merge_input_up"],
            command=lambda: self.move_selected(-1),
        )
        self.up_button.pack(fill="x", pady=(0, 4))
        self.down_button = ttk.Button(
            list_buttons,
            text=UI_TEXT["move_merge_input_down"],
            command=lambda: self.move_selected(1),
        )
        self.down_button.pack(fill="x")

        self._add_path_row(frame, 1, UI_TEXT["merge_output_npz"], self.output_var, self.choose_output)
        self._add_path_row(
            frame,
            2,
            UI_TEXT["merge_output_metadata"],
            self.metadata_var,
            self.choose_metadata,
        )
        ttk.Label(frame, text=UI_TEXT["duplicate_frequency_tolerance"]).grid(
            row=3,
            column=0,
            sticky="w",
            pady=4,
        )
        ttk.Entry(frame, textvariable=self.duplicate_tol_var).grid(
            row=3,
            column=1,
            columnspan=2,
            sticky="ew",
            pady=4,
        )

        button_bar = ttk.Frame(frame)
        button_bar.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 6))
        self.run_button = ttk.Button(button_bar, text=UI_TEXT["start_merge"], command=self.run)
        self.run_button.pack(side="left")
        ttk.Label(button_bar, textvariable=self.status_var).pack(side="left", padx=12)

        self.log_text = tk.Text(frame, height=9, wrap="word")
        self.log_text.grid(row=5, column=0, columnspan=3, sticky="nsew")
        log_scrollbar = ttk.Scrollbar(frame, command=self.log_text.yview)
        log_scrollbar.grid(row=5, column=3, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scrollbar.set)

    def _add_path_row(self, frame, row, label, variable, command):
        from tkinter import ttk

        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=variable).grid(
            row=row,
            column=1,
            sticky="ew",
            pady=4,
            padx=(0, 6),
        )
        ttk.Button(frame, text=UI_TEXT["browse"], command=command).grid(
            row=row,
            column=2,
            sticky="ew",
            pady=4,
        )

    def add_files(self):
        from tkinter import filedialog

        paths = filedialog.askopenfilenames(
            title=UI_TEXT["select_merge_inputs_title"],
            filetypes=(("Compressed NumPy", "*.npz"), ("All files", "*.*")),
        )
        for path in paths:
            if path and path not in self.data_paths:
                self.data_paths.append(path)
        if self.data_paths and not self.output_var.get().strip():
            output_path, metadata_path = self._default_output_paths(self.data_paths[0])
            self.output_var.set(output_path)
            self.metadata_var.set(metadata_path)
        self._refresh_listbox()

    def remove_selected(self):
        selected = list(self.listbox.curselection())
        for index in reversed(selected):
            del self.data_paths[index]
        self._refresh_listbox()

    def move_selected(self, delta):
        selected = self.listbox.curselection()
        if not selected:
            return
        index = selected[0]
        new_index = index + delta
        if new_index < 0 or new_index >= len(self.data_paths):
            return
        self.data_paths[index], self.data_paths[new_index] = (
            self.data_paths[new_index],
            self.data_paths[index],
        )
        self._refresh_listbox()
        self.listbox.selection_set(new_index)

    def choose_output(self):
        from tkinter import filedialog

        initial = self.output_var.get().strip() or "merged_point_data.npz"
        path = filedialog.asksaveasfilename(
            title=UI_TEXT["select_merge_output_title"],
            defaultextension=".npz",
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial) or os.getcwd(),
            filetypes=(("Compressed NumPy", "*.npz"), ("All files", "*.*")),
        )
        if path:
            self.output_var.set(path)

    def choose_metadata(self):
        from tkinter import filedialog

        initial = self.metadata_var.get().strip() or "merged_point_metadata.json"
        path = filedialog.asksaveasfilename(
            title=UI_TEXT["select_merge_metadata_title"],
            defaultextension=".json",
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial) or os.getcwd(),
            filetypes=(("JSON", "*.json"), ("All files", "*.*")),
        )
        if path:
            self.metadata_var.set(path)

    def _refresh_listbox(self):
        self.listbox.delete(0, "end")
        for path in self.data_paths:
            self.listbox.insert("end", path)

    def _default_output_paths(self, first_data_path):
        output_dir = os.path.dirname(first_data_path) or os.getcwd()
        return (
            os.path.join(output_dir, "merged_point_data.npz"),
            os.path.join(output_dir, "merged_point_metadata.json"),
        )

    def _validate_inputs(self):
        from tkinter import messagebox
        from odb_extract import merge_point_data

        if len(self.data_paths) < 2:
            messagebox.showerror(UI_TEXT["merge_failed_title"], UI_TEXT["merge_input_count_error"])
            return None
        output_path = self.output_var.get().strip()
        metadata_output_path = self.metadata_var.get().strip()
        if not output_path or not metadata_output_path:
            messagebox.showerror(UI_TEXT["merge_failed_title"], UI_TEXT["merge_output_missing_error"])
            return None
        try:
            duplicate_tolerance = _parse_optional_float(self.duplicate_tol_var.get())
        except ValueError:
            messagebox.showerror(
                UI_TEXT["merge_failed_title"],
                UI_TEXT["merge_invalid_tolerance_error"],
            )
            return None
        if duplicate_tolerance is None:
            duplicate_tolerance = 1.0e-8
        if duplicate_tolerance <= 0:
            messagebox.showerror(
                UI_TEXT["merge_failed_title"],
                UI_TEXT["merge_invalid_tolerance_error"],
            )
            return None
        for data_path in self.data_paths:
            try:
                metadata_path = merge_point_data.infer_metadata_path(data_path)
            except ValueError as exc:
                messagebox.showerror(UI_TEXT["merge_failed_title"], str(exc))
                return None
            if not os.path.exists(metadata_path):
                messagebox.showerror(
                    UI_TEXT["merge_failed_title"],
                    UI_TEXT["merge_metadata_missing_error"].format(path=metadata_path),
                )
                return None
        try:
            merge_point_data.validate_output_paths(
                self.data_paths,
                output_path,
                metadata_output_path,
            )
        except ValueError as exc:
            messagebox.showerror(UI_TEXT["merge_failed_title"], str(exc))
            return None
        return {
            "data_paths": list(self.data_paths),
            "output_path": output_path,
            "metadata_output_path": metadata_output_path,
            "duplicate_frequency_tolerance": duplicate_tolerance,
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
            result = run_merge_point_data(
                merge_runner=self.merge_runner,
                log_callback=self._thread_log,
                **options
            )
        except Exception as exc:
            error_message = str(exc)

            def fail():
                self._set_running(False)
                self.log(error_message)
                messagebox.showerror(UI_TEXT["merge_failed_title"], error_message)

            self.root.after(0, fail)
            return

        def finish():
            self._set_running(False)
            self.log(
                "{}: {} Hz - {} Hz".format(
                    result["frequency_count"],
                    result["frequency_min"],
                    result["frequency_max"],
                )
            )
            messagebox.showinfo(
                UI_TEXT["merge_finished_title"],
                UI_TEXT["merge_finished_message"],
            )

        self.root.after(0, finish)

    def _set_running(self, running):
        state = "disabled" if running else "normal"
        self._running = running
        self.run_button.configure(state=state)
        self.add_button.configure(state=state)
        self.remove_button.configure(state=state)
        self.up_button.configure(state=state)
        self.down_button.configure(state=state)
        self.status_var.set(UI_TEXT["running"] if running else UI_TEXT["ready"])

    def log(self, message):
        self.log_text.insert("end", "{}\n".format(message))
        self.log_text.see("end")

    def _thread_log(self, message):
        self.root.after(0, self.log, message)
