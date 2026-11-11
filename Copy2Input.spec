# -*- mode: python ; coding: utf-8 -*-

from importlib.util import find_spec

missing = [name for name in ('keyboard', 'pyperclip', 'pystray', 'PIL', '_tkinter') if find_spec(name) is None]
if missing:
    raise SystemExit(
        '缺少打包依赖: ' + ', '.join(missing)
        + '\n请先运行: python -m pip install -r requirements.txt'
    )

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/*.png', 'assets'), ('assets/Copy2Input.ico', 'assets'), ('LICENSE', '.')],
    hiddenimports=['keyboard', 'keyboard._winkeyboard', 'pyperclip', 'pystray', 'pystray._win32', 'PIL.Image'],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'numpy',
        'scipy',
        'matplotlib',
        'PIL.ImageQt',
        'PIL.ImageTk',
        'PIL.ImageWin',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'PIL.ImageText',
        'PIL.ImageCms',
        'PIL.ImageShow',
        'PIL.TiffImagePlugin',
        'PIL._avif',
        'PIL._webp',
        'PIL._imagingft',
        'PIL._imagingcms',
        'keyboard._darwinkeyboard',
        'keyboard._nixkeyboard',
        'keyboard._nixcommon',
        'pystray._xorg',
        'pystray._darwin',
        'pystray._gtk',
        'pystray._appindicator',
        'pystray._util.gtk',
        'pystray._util.notify_dbus',
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name='Copy2Input',
    icon='assets/Copy2Input.ico',
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
