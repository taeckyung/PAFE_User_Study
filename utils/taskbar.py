import sys

hide_taskbar = lambda _: None
unhide_taskbar = lambda _: None

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32")

    SW_HIDE = 0
    SW_SHOW = 5

    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = (
        wintypes.LPCWSTR,  # lpClassName
        wintypes.LPCWSTR)  # lpWindowName

    user32.ShowWindow.argtypes = (
        wintypes.HWND,  # hWnd
        ctypes.c_int)  # nCmdShow


    def _hide_taskbar():
        hWnd = user32.FindWindowW(u"Shell_traywnd", None)
        user32.ShowWindow(hWnd, SW_HIDE)

    hide_taskbar = _hide_taskbar

    def _unhide_taskbar():
        hWnd = user32.FindWindowW(u"Shell_traywnd", None)
        user32.ShowWindow(hWnd, SW_SHOW)

    unhide_taskbar = _unhide_taskbar
