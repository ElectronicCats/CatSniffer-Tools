# catnip_windows.spec
# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules
from PyInstaller.utils.hooks import get_package_paths

# Windows-specific configuration
datas = []
binaries = []
hiddenimports = []

# Main dependencies
hiddenimports.extend([
    'click',
    'usb',
    'usb.backend.libusb1',
    'magic',
    'serial',
    'serial.tools.list_ports',
    'win32file',
    'win32pipe',
    'win32event',
    'win32security',
    'win32api',
    'pywintypes',
    'scapy.layers.all',
    'charset_normalizer.md__mypyc',
    'pycparser',
])

# Collect hidden imports from main libraries
for package in ['scapy', 'textual', 'meshtastic', 'rich', 'matplotlib',
                'cryptography', 'numpy', 'intelhex', 'requests']:
    tmp_ret = collect_all(package)
    datas.extend(tmp_ret[0])
    binaries.extend(tmp_ret[1])
    hiddenimports.extend(tmp_ret[2])

# Collect matplotlib-specific data
if 'matplotlib' in sys.modules:
    import matplotlib
    mpl_data_dir = os.path.join(os.path.dirname(matplotlib.__file__), 'mpl-data')
    if os.path.exists(mpl_data_dir):
        datas.append((mpl_data_dir, 'matplotlib/mpl-data'))

# Include project-specific modules
module_dirs = [
    ('modules', 'modules'),
    ('protocol', 'protocol'),
]

for src, dst in module_dirs:
    if os.path.exists(src):
        for root, dirs, files in os.walk(src):
            for file in files:
                if file.endswith('.py') and not file.startswith('__pycache__'):
                    src_path = os.path.join(root, file)
                    dst_path = os.path.join(dst, os.path.relpath(src_path, src))
                    datas.append((src_path, dst_path))

# Include additional resource files
extra_files = [
    ('README.md', '.'),
    ('LICENSE', '.'),
]

for src, dst in extra_files:
    if os.path.exists(src):
        datas.append((src, dst))

# Find and add libusb-1.0.dll (64-bit version)
libusb_dll = None
if os.path.exists('libusb'):
    for root, dirs, files in os.walk('libusb'):
        for file in files:
            if file == 'libusb-1.0.dll' and ('MS64' in root or 'x64' in root or 'x86_64' in root or 'VS2019-x64' in root):
                libusb_dll = os.path.join(root, file)
                break
        if libusb_dll:
            break

if libusb_dll:
    binaries.append((libusb_dll, '.'))

# Find and bundle OpenOCD (downloaded by CI to openocd_dist/)
_openocd_dist = 'openocd_dist'
if os.path.exists(_openocd_dist):
    _openocd_bin = os.path.join(_openocd_dist, 'bin')
    _openocd_scripts = os.path.join(_openocd_dist, 'share', 'openocd', 'scripts')
    if os.path.exists(_openocd_bin):
        for _f in os.listdir(_openocd_bin):
            if _f.endswith('.exe') or _f.endswith('.dll'):
                binaries.append((os.path.join(_openocd_bin, _f), '.'))
    if os.path.exists(_openocd_scripts):
        datas.append((_openocd_scripts, 'openocd_scripts'))

# Analysis configuration
a = Analysis(
    ['catnip.py', 'lora_extcap.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pywin32'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# Create executable for catnip (CLI)
exe_catnip = EXE(
    pyz,
    a.scripts,
    [('catnip.py', 'catnip', 'PYMODULE')],
    exclude_binaries=True,
    name='catnip',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None
)

# Create executable for lora_extcap (extcap plugin)
exe_extcap = EXE(
    pyz,
    a.scripts,
    [('lora_extcap.py', 'lora_extcap', 'PYMODULE')],
    exclude_binaries=True,
    name='lora_extcap',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe_catnip,
    exe_extcap,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='catnip',
)
