# -*- mode: python ; coding: utf-8 -*-
#.\.venv\Scripts\pyinstaller.exe --clean --noconfirm .\Extract_ODB.spec

a = Analysis(
    ['odb_extract/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[('odb_extract/extractor.py', 'odb_extract')],
    hiddenimports=[
        'odb_extract.extractor',
        'odb_extract.interpolate_points',
        'odb_extract.merge_gui',
        'odb_extract.merge_point_data',
        'odb_extract.npz_export',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Extract_ODB',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
