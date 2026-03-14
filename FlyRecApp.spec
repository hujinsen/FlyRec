# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for FlyRec (目录模式)
# 运行: pyinstaller FlyRecApp.spec

import os
from PyInstaller.utils.hooks import copy_metadata

block_cipher = None

app_name = "FlyRecApp"

# 收集静态资源
assets_dir = 'assets'
datas = []
if os.path.isdir(assets_dir):
    for fn in os.listdir(assets_dir):
        if fn.lower().endswith('.wav'):
            datas.append((os.path.join(assets_dir, fn), 'assets'))

# 初始配置文件 (允许用户修改的 config.json 作为模板复制；仍放根目录)
if os.path.exists('config.json'):
    datas.append(('config.json', '.'))

# 常见需要的元数据 (按需保留，可减少某些警告)
try:
    datas += copy_metadata('requests')
    datas += copy_metadata('dashscope')
except Exception:
    pass

hiddenimports = [
    'pystray._win32',
    'PIL._tkinter_finder',
    # 某些库可能动态导入，可在出现 ImportError 时追加
]

excludes = [
    # 仅排除明显不需要的测试/构建模块，避免误伤 urllib 等被依赖的标准库。
    'tkinter.test', 'unittest', 'distutils'
]

analysis = Analysis(
    ['flyrec_gui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    name=app_name,
    icon=None,          # 可放 .ico 文件后改成 'assets/app.ico'
    debug=False,
    strip=False,
    upx=True,           # 没安装 UPX 或想减少误报可改 False
    console=False,       # 调试阶段开启控制台，便于查看错误
    disable_windowed_traceback=False,
)

# 目录模式 (onedir)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=True,
    name=app_name,
)
