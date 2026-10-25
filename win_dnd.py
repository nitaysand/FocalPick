"""
win_dnd.py - drag files and folders from Explorer onto the window (Windows only, no extra packages).

enable_file_drop(root, callback) makes the window accept dropped files. callback(paths, x, y) is called
with the list of dropped paths and the screen position of the drop. Returns True when it is active;
on other systems, or if anything goes wrong, it returns False and the app simply works without it.
"""
import sys


def enable_file_drop(root, callback):
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
        WM_DROPFILES, WM_COPYGLOBALDATA, GWLP_WNDPROC = 0x0233, 0x0049, -4
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        root.update_idletasks()
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()

        set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        set_long.restype = ctypes.c_void_p
        set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        call = user32.CallWindowProcW
        call.restype = LRESULT
        call.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragQueryPoint.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.POINT)]
        shell32.DragFinish.argtypes = [ctypes.c_void_p]
        user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]

        old = {}

        def proc(h, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                try:
                    n = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                    paths = []
                    for i in range(n):
                        buf = ctypes.create_unicode_buffer(shell32.DragQueryFileW(wparam, i, None, 0) + 1)
                        shell32.DragQueryFileW(wparam, i, buf, len(buf))
                        paths.append(buf.value)
                    pt = wintypes.POINT()
                    shell32.DragQueryPoint(wparam, ctypes.byref(pt))
                    user32.ClientToScreen(h, ctypes.byref(pt))
                    shell32.DragFinish(wparam)
                    # do the real work after leaving the window procedure
                    root.after(10, lambda: callback(paths, pt.x, pt.y))
                except Exception:
                    pass
                return 0
            return call(old["proc"], h, msg, wparam, lparam)

        cb = WNDPROC(proc)
        old["proc"] = set_long(hwnd, GWLP_WNDPROC, ctypes.cast(cb, ctypes.c_void_p))
        root._drop_proc = cb                     # keep a reference, or Python would free it
        shell32.DragAcceptFiles(hwnd, True)
        try:                                     # also accept drops when the app runs as administrator
            for m in (WM_DROPFILES, WM_COPYGLOBALDATA):
                user32.ChangeWindowMessageFilterEx(hwnd, m, 1, None)
        except Exception:
            pass
        return True
    except Exception:
        return False
