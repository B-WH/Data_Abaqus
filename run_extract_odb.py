"""Launcher for Extract_data_ODB.py.

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


ABAQUS_CANDIDATES = ("abaqus", "abq2024", "abq2023", "abq2022")
DEFAULT_FIELD_TEXT = "U UR V VR A AR"
UI_TEXT = {
    "window_title": "Abaqus ODB 数据提取工具",
    "ready": "就绪",
    "running": "运行中",
    "odb_file": "ODB 文件",
    "npz_output": "NPZ 输出",
    "metadata_output": "元数据 JSON",
    "abaqus_command": "Abaqus 命令",
    "extractor_script": "提取脚本",
    "manual_fields": "手动字段",
    "refresh_fields": "读取场输出",
    "available_fields": "可用场输出",
    "field_hint": "请选择 ODB 文件以读取场输出。",
    "run_button": "开始提取",
    "browse": "浏览",
    "select_odb_title": "选择 Abaqus ODB 文件",
    "select_npz_title": "选择 NPZ 输出文件",
    "select_metadata_title": "选择元数据 JSON 输出文件",
    "select_script_title": "选择 Extract_data_ODB.py",
    "no_fields_found": "未找到场输出。",
    "found_fields": "已在 Step {step} 中找到 {count} 个场输出。",
    "select_odb_first": "请先选择 ODB 文件，再读取场输出。",
    "empty_abaqus": "Abaqus 命令为空，已跳过场输出读取。",
    "missing_script_log": "提取脚本不存在，已跳过场输出读取。",
    "discovering_fields": "正在读取场输出。",
    "field_discovery_failed_log": "读取场输出失败：{error}",
    "field_discovery_failed_title": "读取场输出失败",
    "missing_odb_title": "缺少 ODB 文件",
    "missing_odb_message": "请先选择 ODB 文件。",
    "missing_abaqus_title": "缺少 Abaqus 命令",
    "missing_abaqus_message": "请设置 ABAQUS_COMMAND、将 Abaqus 加入 PATH，或输入 abq2024/abaqus 路径。",
    "missing_script_title": "缺少提取脚本",
    "missing_script_message": "未找到提取脚本。",
    "no_fields_selected_title": "未选择场输出",
    "no_fields_selected_message": "请至少勾选一个场输出。",
    "starting_extraction": "开始提取。",
    "extraction_failed_title": "提取失败",
    "extraction_finished_log": "提取完成。",
    "extraction_finished_title": "提取完成",
    "extraction_finished_message": "ODB 数据提取完成。",
    "extraction_exit_code_log": "提取失败，退出代码为 {code}。",
    "extraction_exit_code_message": "Abaqus 退出代码为 {code}。请检查日志输出。",
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
    parser.add_argument(
        "--abaqus-command",
        help="Abaqus command or .bat path. Defaults to ABAQUS_COMMAND, abaqus, or abq20xx.",
    )
    parser.add_argument(
        "--script",
        default=None,
        help="Path to Extract_data_ODB.py. Defaults to the launcher directory.",
    )
    return parser.parse_args(argv)


def default_extractor_script():
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "Extract_data_ODB.py")


def parse_field_text(field_text):
    fields = [part for part in re.split(r"[\s,;]+", field_text.strip()) if part]
    return fields or None


def default_output_paths(odb_path, output_dir=None):
    output_dir = output_dir or os.path.join(os.getcwd(), "output")
    base_name = os.path.splitext(os.path.basename(odb_path))[0]
    return (
        os.path.join(output_dir, "{}_point_data.npz".format(base_name)),
        os.path.join(output_dir, "{}_point_metadata.json".format(base_name)),
    )


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
    script_path,
    odb_path,
    output_path=None,
    metadata_path=None,
    step_name=None,
    fields=None,
):
    command = [abaqus_command, "python", script_path, "--odb", odb_path]
    if output_path:
        command.extend(["--output", output_path])
    if metadata_path:
        command.extend(["--metadata", metadata_path])
    if step_name:
        command.extend(["--step", step_name])
    if fields:
        command.append("--fields")
        command.extend(fields)
    return command


def build_field_list_command(abaqus_command, script_path, odb_path, step_name=None):
    command = [abaqus_command, "python", script_path, "--odb", odb_path, "--list-fields"]
    if step_name:
        command.extend(["--step", step_name])
    return command


def parse_field_list_output(output_text):
    for line in output_text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        metadata = json.loads(line)
        fields = metadata.get("fields")
        if not isinstance(fields, list):
            raise ValueError("Field list JSON does not contain a fields array.")
        return metadata
    raise ValueError("Could not find field list JSON in Abaqus output.")


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
    script_path,
    odb_path,
    step_name=None,
    runner=None,
):
    runner = run_command_capture if runner is None else runner
    command = build_field_list_command(
        abaqus_command=abaqus_command,
        script_path=script_path,
        odb_path=odb_path,
        step_name=step_name,
    )
    code, output = runner(command)
    if code != 0:
        raise RuntimeError(
            "Field discovery failed with exit code {}.\n{}".format(code, output)
        )
    return parse_field_list_output(output)


def run_extraction(
    abaqus_command,
    script_path,
    odb_path,
    output_path=None,
    metadata_path=None,
    step_name=None,
    fields=None,
    runner=None,
    verbose=True,
    log_callback=None,
):
    runner = run_command if runner is None else runner
    command = build_extraction_command(
        abaqus_command=abaqus_command,
        script_path=script_path,
        odb_path=odb_path,
        output_path=output_path,
        metadata_path=metadata_path,
        step_name=step_name,
        fields=fields,
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

    script_path = args.script or default_extractor_script()
    if not os.path.exists(script_path):
        print("ERROR: Extractor script not found: {}".format(script_path), file=sys.stderr)
        return 2

    return run_extraction(
        abaqus_command=abaqus_command,
        script_path=script_path,
        odb_path=odb_path,
        output_path=args.output,
        metadata_path=args.metadata,
        step_name=args.step,
        fields=args.fields,
    )


class ExtractOdbApp(object):
    def __init__(self, root):
        import tkinter as tk

        self.tk = tk
        self.root = root
        self.root.title(UI_TEXT["window_title"])
        self.root.geometry("820x560")
        self.root.minsize(720, 500)

        self.odb_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.metadata_var = tk.StringVar()
        self.step_var = tk.StringVar()
        self.fields_var = tk.StringVar(value=DEFAULT_FIELD_TEXT)
        self.abaqus_var = tk.StringVar(value=find_abaqus_command() or "")
        self.script_var = tk.StringVar(value=default_extractor_script())
        self.status_var = tk.StringVar(value=UI_TEXT["ready"])
        self._running = False
        self.field_vars = {}

        self._build_widgets()

    def _build_widgets(self):
        tk = self.tk
        from tkinter import ttk

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(9, weight=1)

        self._add_path_row(frame, 0, UI_TEXT["odb_file"], self.odb_var, self.choose_odb)
        self._add_path_row(frame, 1, UI_TEXT["npz_output"], self.output_var, self.choose_output)
        self._add_path_row(
            frame, 2, UI_TEXT["metadata_output"], self.metadata_var, self.choose_metadata
        )
        self._add_path_row(frame, 3, UI_TEXT["abaqus_command"], self.abaqus_var, None)
        self._add_path_row(frame, 4, UI_TEXT["extractor_script"], self.script_var, self.choose_script)

        ttk.Label(frame, text="Step").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.step_var).grid(
            row=5, column=1, columnspan=2, sticky="ew", pady=4
        )

        ttk.Label(frame, text=UI_TEXT["manual_fields"]).grid(row=6, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.fields_var).grid(
            row=6, column=1, sticky="ew", pady=4, padx=(0, 6)
        )
        self.refresh_button = ttk.Button(
            frame, text=UI_TEXT["refresh_fields"], command=self.refresh_fields
        )
        self.refresh_button.grid(row=6, column=2, sticky="ew", pady=4)

        self.field_box = ttk.LabelFrame(frame, text=UI_TEXT["available_fields"])
        self.field_box.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(4, 8))
        self.field_box.columnconfigure(0, weight=1)
        self.field_hint = ttk.Label(self.field_box, text=UI_TEXT["field_hint"])
        self.field_hint.grid(row=0, column=0, sticky="w", padx=8, pady=8)

        button_bar = ttk.Frame(frame)
        button_bar.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(8, 6))
        self.run_button = ttk.Button(button_bar, text=UI_TEXT["run_button"], command=self.run)
        self.run_button.pack(side="left")
        ttk.Label(button_bar, textvariable=self.status_var).pack(side="left", padx=12)

        self.log_text = tk.Text(frame, height=12, wrap="word")
        self.log_text.grid(row=9, column=0, columnspan=3, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, command=self.log_text.yview)
        scrollbar.grid(row=9, column=3, sticky="ns")
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
        self.refresh_fields()

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

    def choose_script(self):
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title=UI_TEXT["select_script_title"],
            filetypes=(("Python", "*.py"), ("All files", "*.*")),
        )
        if path:
            self.script_var.set(path)

    def log(self, message):
        self.log_text.insert("end", "{}\n".format(message))
        self.log_text.see("end")

    def _thread_log(self, message):
        self.root.after(0, self.log, message)

    def _set_running(self, running):
        self._running = running
        self.run_button.configure(state="disabled" if running else "normal")
        self.refresh_button.configure(state="disabled" if running else "normal")
        self.status_var.set(UI_TEXT["running"] if running else UI_TEXT["ready"])

    def _clear_field_checks(self):
        for child in self.field_box.winfo_children():
            child.destroy()
        self.field_vars = {}

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
        if not fields:
            ttk.Label(self.field_box, text=UI_TEXT["no_fields_found"]).grid(
                row=0, column=0, sticky="w", padx=8, pady=8
            )
            self.fields_var.set("")
            return

        default_fields = set(parse_field_text(DEFAULT_FIELD_TEXT) or [])
        checked_any = False
        for index, field_name in enumerate(fields):
            checked = field_name in default_fields
            checked_any = checked_any or checked
            variable = tk.BooleanVar(value=checked)
            self.field_vars[field_name] = variable
            ttk.Checkbutton(
                self.field_box,
                text=field_name,
                variable=variable,
                command=self._sync_fields_from_checks,
            ).grid(row=index // 6, column=index % 6, sticky="w", padx=8, pady=4)

        if not checked_any:
            for variable in self.field_vars.values():
                variable.set(True)
        self._sync_fields_from_checks()
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
        script_path = self.script_var.get().strip()
        if not os.path.exists(script_path):
            self.log(UI_TEXT["missing_script_log"])
            return

        self.log(UI_TEXT["discovering_fields"])
        self._set_running(True)
        worker = threading.Thread(
            target=self._discover_fields_worker,
            args=(abaqus_command, script_path, odb_path, self.step_var.get().strip() or None),
        )
        worker.daemon = True
        worker.start()

    def _discover_fields_worker(self, abaqus_command, script_path, odb_path, step_name):
        from tkinter import messagebox

        try:
            metadata = discover_fields(
                abaqus_command=abaqus_command,
                script_path=script_path,
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

    def _selected_fields(self):
        if self.field_vars:
            return [
                field_name
                for field_name, variable in sorted(self.field_vars.items())
                if variable.get()
            ]
        return parse_field_text(self.fields_var.get())

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

        script_path = self.script_var.get().strip()
        if not os.path.exists(script_path):
            messagebox.showerror(UI_TEXT["missing_script_title"], UI_TEXT["missing_script_message"])
            return None

        fields = self._selected_fields()
        if self.field_vars and not fields:
            messagebox.showerror(
                UI_TEXT["no_fields_selected_title"],
                UI_TEXT["no_fields_selected_message"],
            )
            return None
        output_path = self.output_var.get().strip() or None
        metadata_path = self.metadata_var.get().strip() or None
        step_name = self.step_var.get().strip() or None
        return {
            "abaqus_command": abaqus_command,
            "script_path": script_path,
            "odb_path": odb_path,
            "output_path": output_path,
            "metadata_path": metadata_path,
            "step_name": step_name,
            "fields": fields,
        }

    def run(self):
        if self._running:
            return
        options = self._validate_inputs()
        if options is None:
            return

        self.log(UI_TEXT["starting_extraction"])
        self._set_running(True)
        worker = threading.Thread(target=self._run_worker, args=(options,))
        worker.daemon = True
        worker.start()

    def _run_worker(self, options):
        from tkinter import messagebox

        try:
            code = run_extraction(
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
