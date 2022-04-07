# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Please configure below ###############################
username = "user"
python_path = 'C:/Users/%s/.conda/envs/pafe_app/libs'%username
python_package_path = 'C:/Users/%s/.conda/envs/pafe_app/Lib/site-packages'%username
python_cv2_path = 'C:/Users/%s/.conda/envs/pafe_app/Lib/site-packages/cv2'
vlc_path = 'C:/Program Files/VideoLAN/VLC/'
vlc_plugins_path = "C:/Program Files/VideoLAN/VLC/plugins/*"
app_icon_path = "./resources/nmsl_logo_yellow.ico"
########################################################


a = Analysis(['main.py'],
             pathex=[python_path, python_package_path, python_cv2_path, vlc_path],
             binaries=[(vlc_plugins_path, "plugins")],
             datas=[('./resources/libvlc.dll', '.'), ('./resources/axvlc.dll', '.'), ('./resources/libvlccore.dll', '.'), ('./resources/npvlc.dll', '.')],
             hiddenimports=["pynput.keyboard._win32", "pynput.mouse._win32"],
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
          a.binaries + [("libVLC.dll", vlc_path+"libvlc.dll", "BINARY")],
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
          icon=app_icon_path)
