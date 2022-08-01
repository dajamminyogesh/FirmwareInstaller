# -*- mode: python ; coding: utf-8 -*-


block_cipher = None

binaries = [
   ('C:\\Windows\\System32\\libusb0.dll', '.'),
   ('C:\\Windows\\System32\\libusbK.dll', '.'),
   ('C:\\Windows\\System32\\libusb-1.0.dll', '.'),
   ('C:\\Windows\\System32\\winusb.dll', '.'),
   ('C:\\Windows\\System32\\WinUSBCoInstaller2.dll', '.'),
   ('C:\\Windows\\System32\\drivers\\libusbK.sys', '.'),
   ('C:\\Windows\\System32\\drivers\\usbser.sys', '.')
]
a = Analysis(['src\\firmwareInstaller.py'],
             pathex=['D:\\Work\\Project\\FirmwareInstaller'],
             binaries=binaries,
             datas=[('src\\ico.ico', '.')],
             hiddenimports=['usb'],
             hookspath=[],
             hooksconfig={},
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)

exe = EXE(pyz,
          a.scripts, 
          [],
          exclude_binaries=True,
          name='Installer',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=False,
          disable_windowed_traceback=False,
          target_arch=None,
          codesign_identity=None,
          entitlements_file=None , version='file_version_info.txt', icon='src\\ico.ico')
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas, 
               strip=False,
               upx=True,
               upx_exclude=[],
               name='Installer')
