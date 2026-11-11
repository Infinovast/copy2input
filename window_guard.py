"""Small Windows foreground checks. Unknown controls and failed queries pass."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import sys


GUARD_DEFAULTS = {
    'pause_on_focus_loss': True,
    'block_untypable_windows': True,
}


@dataclass(frozen=True)
class WindowState:
    window: tuple[int, int] | None = None
    blocked_reason: str | None = None


class _GuiThreadInfo(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                ('hwndActive', wintypes.HWND), ('hwndFocus', wintypes.HWND),
                ('hwndCapture', wintypes.HWND), ('hwndMenuOwner', wintypes.HWND),
                ('hwndMoveSize', wintypes.HWND), ('hwndCaret', wintypes.HWND),
                ('rcCaret', wintypes.RECT)]


class _WindowsAPI:
    def __init__(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        signatures = {
            'GetForegroundWindow': ((), wintypes.HWND),
            'GetWindowThreadProcessId': ((wintypes.HWND, ctypes.POINTER(wintypes.DWORD)), wintypes.DWORD),
            'GetGUIThreadInfo': ((wintypes.DWORD, ctypes.POINTER(_GuiThreadInfo)), wintypes.BOOL),
            'GetClassNameW': ((wintypes.HWND, wintypes.LPWSTR, ctypes.c_int), ctypes.c_int),
            'GetWindowLongW': ((wintypes.HWND, ctypes.c_int), wintypes.LONG),
            'IsWindow': ((wintypes.HWND,), wintypes.BOOL),
            'IsWindowVisible': ((wintypes.HWND,), wintypes.BOOL),
            'IsWindowEnabled': ((wintypes.HWND,), wintypes.BOOL),
            'IsIconic': ((wintypes.HWND,), wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes = args
            function.restype = result

    def foreground(self):
        hwnd = self.user.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return (hwnd, pid.value)

    def class_name(self, hwnd):
        buffer = ctypes.create_unicode_buffer(256)
        self.user.GetClassNameW(hwnd, buffer, len(buffer))
        return buffer.value.casefold()

    def inspect(self):
        window = self.foreground()
        if window is None:
            return WindowState(blocked_reason='未检测到前台窗口')
        hwnd, pid = window
        reason = None
        if not self.user.IsWindow(hwnd):
            reason = '目标窗口已关闭'
        elif pid == os.getpid():
            reason = '当前为 Copy2Input 窗口'
        elif self.class_name(hwnd) in ('progman', 'workerw', 'shell_traywnd', 'shell_secondarytraywnd'):
            reason = '桌面或任务栏不能输入文本'
        elif not self.user.IsWindowEnabled(hwnd) or not self.user.IsWindowVisible(hwnd) or self.user.IsIconic(hwnd):
            reason = '目标窗口不可输入'
        else:
            info = _GuiThreadInfo(cbSize=ctypes.sizeof(_GuiThreadInfo))
            thread = self.user.GetWindowThreadProcessId(hwnd, None)
            if thread and self.user.GetGUIThreadInfo(thread, ctypes.byref(info)):
                if info.flags & 0x1e:  # Menu modes or moving/resizing a window.
                    reason = '当前菜单或窗口操作不能输入文本'
                elif not info.hwndFocus:
                    reason = '未检测到输入焦点'
                elif not self.user.IsWindowEnabled(info.hwndFocus):
                    reason = '当前控件已禁用'
                else:
                    name = self.class_name(info.hwndFocus)
                    if name in ('button', 'static', 'scrollbar', 'msctls_trackbar32', 'msctls_progress32'):
                        reason = '当前控件不能输入文本'
                    elif name == 'edit' or name.startswith('richedit'):
                        if self.user.GetWindowLongW(info.hwndFocus, -16) & 0x800:  # ES_READONLY
                            reason = '当前文本框为只读'
        return WindowState(window, reason)


_api = None


def _windows_api():
    global _api
    if _api is None:
        _api = _WindowsAPI()
    return _api


def foreground_window():
    if sys.platform == 'win32':
        try:
            return _windows_api().foreground()
        except Exception:
            pass
    return None


def inspect_foreground_window():
    if sys.platform == 'win32':
        try:
            return _windows_api().inspect()
        except Exception:
            pass
    return WindowState()
