# mesh_convert GUI 可执行文件

在项目根目录运行以下命令构建 Windows GUI 可执行文件：

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller
.\packaging\build_mesh_convert_exe.ps1
```

如果当前 PowerShell 会话阻止脚本执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\packaging\build_mesh_convert_exe.ps1
```

预期输出：

```text
dist\mesh_convert_gui\mesh_convert_gui.exe
```

打包脚本不会删除文件或目录。如果目标构建输出已经存在，脚本会停止。若要保留
旧的失败构建目录，同时继续生成 `mesh_convert_gui.exe`：

```powershell
.\packaging\build_mesh_convert_exe.ps1 -WorkName mesh_convert_gui_retry
```

若要生成不同名称的可执行文件：

```powershell
.\packaging\build_mesh_convert_exe.ps1 -BuildName mesh_convert_gui_test
```

如果需要清理旧的 `build` 或 `dist` 输出，请手动删除明确路径的具体文件。
