# -*- mode: python ; coding: utf-8 -*-

block_cipher = None


a = Analysis(['main.py'],
             pathex=['C:\\Python\\3.7\\Lib\\site-packages', 'C:\\Users\\terry\\PycharmProjects\\OnlineExperiment', 'C:/Program Files/VideoLAN/VLC/'],
             binaries=[("C:/Program Files/VideoLAN/VLC/plugins/*", "plugins")],
             datas=[('./resources/libvlc.dll', '.'), ('./resources/axvlc.dll', '.'), ('./resources/libvlccore.dll', '.'), ('./resources/npvlc.dll', '.')],
             hiddenimports=[],
             hookspath=[],
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
          a.binaries + [("libVLC.dll", "C:/Program Files/VideoLAN/VLC/libvlc.dll", "BINARY")],
          a.zipfiles,
          a.datas,
          [],
          name='main',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=False,
          upx_exclude=[],
          runtime_tmpdir=None,
          console=False,
          icon="./resources/nmsl_logo_yellow.ico")
