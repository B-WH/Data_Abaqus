import contextlib
import io
import json
import os
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk

from . import cli


DIM_OPTIONS = ("自动", "二维", "三维")
DIM_VALUE_MAP = {
    "自动": "auto",
    "二维": "2d",
    "三维": "3d",
    "auto": "auto",
    "2d": "2d",
    "3d": "3d",
}
TARGET_OPTIONS = ("六面体", "四边形", "混合")
TARGET_VALUE_MAP = {
    "六面体": "hex",
    "四边形": "quad",
    "混合": "mixed",
    "hex": "hex",
    "quad": "quad",
    "mixed": "mixed",
}


@dataclass(frozen=True)
class RecommendedPaths:
    output_path: str
    log_path: str
    report_path: str


def recommend_paths_from_input(input_path):
    base, _ = os.path.splitext(input_path)
    return RecommendedPaths(
        output_path=base + ".inp",
        log_path=base + ".log",
        report_path=base + "_report.json",
    )


def recommend_auxiliary_paths(output_path):
    base, _ = os.path.splitext(output_path)
    return RecommendedPaths(
        output_path=output_path,
        log_path=base + ".log",
        report_path=base + "_report.json",
    )


def format_friendly_failure(text):
    lower_text = str(text or "").lower()
    hints = []
    if "gmsh python package is required" in lower_text or "pip install gmsh" in lower_text:
        hints.append(
            "缺少 gmsh Python 包。请在当前 Python 环境中安装：python -m pip install gmsh"
        )
    if ".ins" in lower_text and "iso-10303" in lower_text:
        hints.append(
            "选择的 .ins 文件不是 STEP/ISO-10303 几何文件。请改选 .step/.stp 文件，"
            "或先把 INS 内容导出为 STEP 格式。"
        )
    if "3d mode was requested" in lower_text and "no solid volumes" in lower_text:
        hints.append(
            "当前选择了三维网格，但几何里没有实体体积。若是面模型，请把维度模式改为二维；"
            "若需要实体网格，请导出封闭实体。"
        )
    if "use --allow-degrade" in lower_text or "non-hex element types" in lower_text:
        hints.append(
            "目标六面体/四边形网格生成了 mixed 网格。如果混合单元可以接受，"
            "请勾选“允许混合单元降级”。"
        )
    if not hints:
        return ""
    lines = ["", "友好报错提示："]
    lines.extend("- {}".format(hint) for hint in hints)
    return "\n".join(lines) + "\n"


def format_report_summary(report):
    status = str(report.get("status", "")).lower()
    element_counts = report.get("element_counts") or {}
    total_elements = sum(int(count) for count in element_counts.values())
    element_text = ", ".join(
        "{}={}".format(name, element_counts[name]) for name in sorted(element_counts)
    )
    if not element_text:
        element_text = "无"
    warnings = [str(warning) for warning in report.get("warnings") or []]

    lines = [
        "",
        "报告摘要：",
        "是否成功：{}".format("是" if status == "ok" else "否"),
        "节点数：{}".format(int(report.get("node_count") or 0)),
        "单元数：{}".format(total_elements),
        "单元类型统计：{}".format(element_text),
        "是否发生 mixed 降级：{}".format("是" if report.get("degraded") else "否"),
    ]
    if warnings:
        lines.append("警告信息：")
        lines.extend("- {}".format(warning) for warning in warnings)
    else:
        lines.append("警告信息：无")
    return "\n".join(lines) + "\n"


def _mapped_value(value, mapping):
    return mapping.get(str(value).strip(), str(value).strip())


class MeshConvertApp:
    def __init__(self, root, cli_runner=cli.main):
        self.root = root
        self.cli_runner = cli_runner
        self.root.title("网格转换工具")
        self.root.minsize(780, 560)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.size_var = tk.StringVar(value="1.0")
        self.dim_var = tk.StringVar(value="自动")
        self.target_var = tk.StringVar(value="六面体")
        self.element_type_var = tk.StringVar(value="")
        self.allow_degrade_var = tk.BooleanVar(value=False)
        self.log_var = tk.StringVar()
        self.report_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")

        self._build_widgets()

    def _build_widgets(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(8, weight=1)

        self._add_path_row(outer, 0, "输入 STEP/INS", self.input_var, self._browse_input)
        self._add_path_row(outer, 1, "输出 INP", self.output_var, self._browse_output)
        self._add_path_row(outer, 2, "日志文件", self.log_var, self._browse_log)
        self._add_path_row(outer, 3, "报告 JSON", self.report_var, self._browse_report)

        options = ttk.LabelFrame(outer, text="网格参数", padding=10)
        options.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        for column in range(8):
            options.columnconfigure(column, weight=1)

        ttk.Label(options, text="网格尺寸").grid(row=0, column=0, sticky="w")
        ttk.Entry(options, textvariable=self.size_var, width=10).grid(
            row=0, column=1, sticky="ew", padx=(4, 12)
        )
        ttk.Label(options, text="维度模式").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            options,
            textvariable=self.dim_var,
            values=DIM_OPTIONS,
            state="readonly",
            width=8,
        ).grid(row=0, column=3, sticky="ew", padx=(4, 12))
        ttk.Label(options, text="目标单元").grid(row=0, column=4, sticky="w")
        ttk.Combobox(
            options,
            textvariable=self.target_var,
            values=TARGET_OPTIONS,
            state="readonly",
            width=8,
        ).grid(row=0, column=5, sticky="ew", padx=(4, 12))
        ttk.Label(options, text="Abaqus 类型").grid(row=0, column=6, sticky="w")
        ttk.Combobox(
            options,
            textvariable=self.element_type_var,
            values=("", "C3D8", "C3D8R", "S4", "S4R"),
            width=10,
        ).grid(row=0, column=7, sticky="ew", padx=(4, 0))
        ttk.Checkbutton(
            options,
            text="允许混合单元降级",
            variable=self.allow_degrade_var,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

        actions = ttk.Frame(outer)
        actions.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self.run_button = ttk.Button(actions, text="生成网格", command=self._run_clicked)
        self.run_button.pack(side="left")
        ttk.Button(actions, text="打开输出文件夹", command=self._open_output_folder).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(actions, textvariable=self.status_var).pack(side="right")

        ttk.Label(outer, text="运行信息").grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(12, 4)
        )
        self.messages = tk.Text(outer, height=14, wrap="word")
        self.messages.grid(row=8, column=0, columnspan=3, sticky="nsew")
        scrollbar = ttk.Scrollbar(outer, command=self.messages.yview)
        scrollbar.grid(row=8, column=3, sticky="ns")
        self.messages.configure(yscrollcommand=scrollbar.set)

    def _add_path_row(self, parent, row, label, variable, command):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", padx=(8, 8), pady=3
        )
        ttk.Button(parent, text="浏览", command=command).grid(row=row, column=2, pady=3)

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="选择几何文件",
            filetypes=(
                ("STEP 几何文件", "*.step *.stp *.ins"),
                ("所有文件", "*.*"),
            ),
        )
        if path:
            self.input_var.set(path)
            paths = recommend_paths_from_input(path)
            self.output_var.set(paths.output_path)
            self.log_var.set(paths.log_path)
            self.report_var.set(paths.report_path)

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="选择 Abaqus INP 输出文件",
            defaultextension=".inp",
            filetypes=(("Abaqus INP", "*.inp"), ("所有文件", "*.*")),
        )
        if path:
            self.output_var.set(path)
            paths = recommend_auxiliary_paths(path)
            self.log_var.set(paths.log_path)
            self.report_var.set(paths.report_path)

    def _browse_log(self):
        path = filedialog.asksaveasfilename(
            title="选择日志文件",
            defaultextension=".log",
            filetypes=(("日志文件", "*.log"), ("所有文件", "*.*")),
        )
        if path:
            self.log_var.set(path)

    def _browse_report(self):
        path = filedialog.asksaveasfilename(
            title="选择报告 JSON 文件",
            defaultextension=".json",
            filetypes=(("JSON 报告", "*.json"), ("所有文件", "*.*")),
        )
        if path:
            self.report_var.set(path)

    def _fill_default_auxiliary_paths(self):
        output_path = self.output_var.get().strip()
        if not output_path:
            return
        paths = recommend_auxiliary_paths(output_path)
        if not self.log_var.get().strip():
            self.log_var.set(paths.log_path)
        if not self.report_var.get().strip():
            self.report_var.set(paths.report_path)

    def _build_cli_args(self):
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()
        size_text = self.size_var.get().strip()
        if not input_path:
            raise ValueError("请选择输入 STEP/STP/INS 文件。")
        if not output_path:
            raise ValueError("请选择输出 INP 文件。")
        try:
            size_value = float(size_text)
        except ValueError as exc:
            raise ValueError("网格尺寸必须是数字。") from exc
        if size_value <= 0:
            raise ValueError("网格尺寸必须大于 0。")

        args = [
            input_path,
            output_path,
            "--size",
            size_text,
            "--dim",
            _mapped_value(self.dim_var.get(), DIM_VALUE_MAP),
            "--target",
            _mapped_value(self.target_var.get(), TARGET_VALUE_MAP),
        ]
        element_type = self.element_type_var.get().strip()
        if element_type:
            args.extend(["--element-type", element_type])
        if self.allow_degrade_var.get():
            args.append("--allow-degrade")
        log_path = self.log_var.get().strip()
        if log_path:
            args.extend(["--log", log_path])
        report_path = self.report_var.get().strip()
        if report_path:
            args.extend(["--report", report_path])
        return args

    def _run_clicked(self):
        try:
            args = self._build_cli_args()
        except ValueError as exc:
            messagebox.showerror("输入无效", str(exc))
            return

        self._append_message("正在运行：python -m mesh_convert {}\n".format(" ".join(args)))
        self.status_var.set("运行中")
        self.run_button.configure(state="disabled")
        thread = threading.Thread(target=self._run_conversion, args=(args,), daemon=True)
        thread.start()

    def _run_conversion(self, args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = self.cli_runner(args)
            except Exception as exc:
                code = 1
                stderr.write("mesh_convert: error: {}\n".format(exc))
        self.root.after(0, self._finish_conversion, code, stdout.getvalue(), stderr.getvalue())

    def _finish_conversion(self, code, stdout_text, stderr_text):
        if stdout_text:
            self._append_message(stdout_text)
        if stderr_text:
            self._append_message(stderr_text)
        self._append_report_summary_if_available()
        if code == 0:
            self.status_var.set("完成")
            self._append_message("网格转换完成。\n")
            messagebox.showinfo("完成", "网格转换完成。")
        else:
            self.status_var.set("失败")
            friendly_message = format_friendly_failure(stdout_text + "\n" + stderr_text)
            if friendly_message:
                self._append_message(friendly_message)
            self._append_message("网格转换失败，退出代码：{}。\n".format(code))
            dialog_message = (
                friendly_message.strip()
                if friendly_message
                else "请检查运行信息、日志和报告。"
            )
            messagebox.showerror(
                "失败",
                "网格转换失败，退出代码：{}。\n\n{}".format(code, dialog_message),
            )
        self.run_button.configure(state="normal")

    def _append_report_summary_if_available(self):
        report_path = self.report_var.get().strip()
        if not report_path or not os.path.isfile(report_path):
            return
        try:
            with open(report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
        except (OSError, ValueError) as exc:
            self._append_message("\n无法读取报告 JSON：{}\n".format(exc))
            return
        self._append_message(format_report_summary(report))

    def _append_message(self, text):
        self.messages.insert("end", text)
        self.messages.see("end")

    def _open_output_folder(self):
        output_path = self.output_var.get().strip()
        if not output_path:
            messagebox.showinfo("输出文件夹", "请先选择输出 INP 文件。")
            return
        folder = os.path.dirname(os.path.abspath(output_path))
        if not os.path.isdir(folder):
            messagebox.showinfo("输出文件夹", "输出文件夹尚不存在。")
            return
        os.startfile(folder)


def run():
    root = tk.Tk()
    MeshConvertApp(root)
    root.mainloop()
    return 0
