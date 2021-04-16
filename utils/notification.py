import sys
import os


def open_settings():
    if sys.platform == 'win32':
        os.system("start \"\" ms-settings:quiethours")
    else:
        pass
