#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键启动 - 模拟器 / 自动化脚本
纯 Python 标准库实现，无需安装任何额外组件。
"""

import os
import re
import sys
import json
import time
import shlex
import base64
import queue
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import ctypes
from ctypes import wintypes
APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
ICON_PATH = os.path.join(APP_DIR, "icon.ico")
ICON_PNG = os.path.join(APP_DIR, "icon.png")

DEFAULT_GEOMETRY = "1160x700"
MIN_W, MIN_H = 760, 560

# 任务栏图标分组标识：不设的话，本程序会被并入 pythonw.exe，
# 任务栏显示的永远是 Python 自己的图标。
APP_ID = "WangXiao.GameLauncher.OneClick"
TRAY_CLASS = "GameLauncherTrayClass"
MUTEX_NAME = "Local\\WangXiao_GameLauncher_SingleInstance"
ERROR_ALREADY_EXISTS = 183

sys.path.insert(0, APP_DIR)

# ============ Win32 相关 ============
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259

if ctypes.sizeof(ctypes.c_void_p) == 8:
    _WPARAM_T = ctypes.c_ulonglong
    _LPARAM_T = ctypes.c_longlong
    _LRESULT_T = ctypes.c_longlong
else:
    _WPARAM_T = ctypes.c_ulong
    _LPARAM_T = ctypes.c_long
    _LRESULT_T = ctypes.c_long

HANDLE = wintypes.HANDLE
BOOL = wintypes.BOOL
DWORD_T = wintypes.DWORD
UINT_T = wintypes.UINT
HWND_T = wintypes.HWND
LPWSTR = wintypes.LPCWSTR


def _declare_winapi():
    """显式声明 Win32 函数原型，避免 64 位参数传参溢出"""
    f = _kernel32.GetModuleHandleW
    f.argtypes = [LPWSTR]
    f.restype = wintypes.HMODULE

    f = _kernel32.OpenProcess
    f.argtypes = [DWORD_T, BOOL, DWORD_T]
    f.restype = HANDLE

    f = _kernel32.GetExitCodeProcess
    f.argtypes = [HANDLE, ctypes.POINTER(DWORD_T)]
    f.restype = BOOL

    f = _kernel32.CloseHandle
    f.argtypes = [HANDLE]
    f.restype = BOOL

    f = _kernel32.GetProcessId
    f.argtypes = [HANDLE]
    f.restype = DWORD_T

    f = _user32.RegisterClassW
    f.argtypes = [ctypes.c_void_p]
    f.restype = ctypes.c_ushort

    f = _user32.CreateWindowExW
    f.argtypes = [DWORD_T, LPWSTR, LPWSTR, DWORD_T, ctypes.c_int, ctypes.c_int,
                  ctypes.c_int, ctypes.c_int, HWND_T, ctypes.c_void_p,
                  ctypes.c_void_p, ctypes.c_void_p]
    f.restype = HWND_T

    f = _user32.DestroyWindow
    f.argtypes = [HWND_T]
    f.restype = BOOL

    f = _user32.DefWindowProcW
    f.argtypes = [HWND_T, UINT_T, _WPARAM_T, _LPARAM_T]
    f.restype = _LRESULT_T

    f = _user32.GetMessageW
    f.argtypes = [ctypes.c_void_p, HWND_T, UINT_T, UINT_T]
    f.restype = BOOL

    f = _user32.TranslateMessage
    f.argtypes = [ctypes.c_void_p]
    f.restype = BOOL

    f = _user32.DispatchMessageW
    f.argtypes = [ctypes.c_void_p]
    f.restype = _LRESULT_T

    f = _user32.PostQuitMessage
    f.argtypes = [ctypes.c_int]
    f.restype = None

    f = _user32.LoadIconW
    f.argtypes = [ctypes.c_void_p, LPWSTR]
    f.restype = wintypes.HICON

    f = _user32.LoadImageW
    f.argtypes = [ctypes.c_void_p, LPWSTR, UINT_T, ctypes.c_int, ctypes.c_int, UINT_T]
    f.restype = wintypes.HANDLE

    f = _user32.GetCursorPos
    f.argtypes = [ctypes.c_void_p]
    f.restype = BOOL

    f = _shell32.Shell_NotifyIconW
    f.argtypes = [DWORD_T, ctypes.c_void_p]
    f.restype = BOOL

    f = _shell32.ShellExecuteExW
    f.argtypes = [ctypes.c_void_p]
    f.restype = BOOL

    f = _kernel32.CreateMutexW
    f.argtypes = [ctypes.c_void_p, BOOL, LPWSTR]
    f.restype = HANDLE

    f = _user32.FindWindowW
    f.argtypes = [LPWSTR, LPWSTR]
    f.restype = HWND_T

    f = _user32.PostMessageW
    f.argtypes = [HWND_T, UINT_T, _WPARAM_T, _LPARAM_T]
    f.restype = BOOL

    f = _shell32.SetCurrentProcessExplicitAppUserModelID
    f.argtypes = [LPWSTR]
    f.restype = ctypes.c_long


_declare_winapi()

_mutex_handle = None


def set_taskbar_app_id():
    """给进程一个独立的 AppUserModelID，任务栏才会采用窗口自己的图标"""
    try:
        _shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def single_instance_guard():
    """已有实例在跑：把它的窗口唤起来，返回 True（调用方应直接退出）"""
    global _mutex_handle
    try:
        _mutex_handle = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not _mutex_handle:
            return False
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            hwnd = _user32.FindWindowW(TRAY_CLASS, None)
            if hwnd:
                _user32.PostMessageW(hwnd, WM_WAKE, 0, 0)
            return True
        return False
    except Exception:
        return False


def _is_pid_alive(pid):
    """判断进程是否还活着（不依赖任何第三方库）"""
    if not pid:
        return False
    h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        ok = _kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        if not ok:
            return False
        return code.value == STILL_ACTIVE
    finally:
        _kernel32.CloseHandle(h)


class SHELLEXECUTEINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hKeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_ulong),
        ("hIcon", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_SHOWNORMAL = 1


def shell_start(path, workdir=None, params=None):
    """用 ShellExecuteEx 启动（支持 .lnk 快捷方式），返回进程 PID"""
    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "open"
    info.lpFile = path
    info.lpParameters = params or None
    info.lpDirectory = workdir or None
    info.nShow = SW_SHOWNORMAL
    if not _shell32.ShellExecuteExW(ctypes.byref(info)):
        return None
    if not info.hProcess:
        return None
    pid = _kernel32.GetProcessId(ctypes.c_void_p(info.hProcess))
    _kernel32.CloseHandle(ctypes.c_void_p(info.hProcess))
    return pid or None


def find_exe(names, candidates=()):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


# ============ 配置 ============
def new_item():
    return {
        "id": os.urandom(8).hex(),
        "name": "",
        "path": "",
        "workdir": "",
        "args": "",
        "delay": 5,
        "enabled": True,
    }


def normalize_item(d):
    it = new_item()
    if isinstance(d, dict):
        for k in ("id", "name", "path", "workdir", "args", "delay", "enabled"):
            if k in d and d[k] is not None:
                it[k] = d[k]
    try:
        it["delay"] = max(0, int(float(it["delay"])))
    except Exception:
        it["delay"] = 5
    it["enabled"] = bool(it["enabled"])
    return it


SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
DEFAULT_SETTINGS = {"auto_minimize": True}


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    if os.path.isfile(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                s.update(data)
        except Exception:
            pass
    return s


def save_settings(settings):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_config():
    items = []
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                items = [normalize_item(x) for x in data]
        except Exception as e:
            print("配置读取失败:", e)
    return items


def save_config(items):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print("配置保存失败:", e)
        return False


# ============ 启动单项 ============
def build_command(item):
    """返回 (mode, payload)；mode 可为 'popen' / 'shell' / 'none'"""
    path = item.get("path", "").strip()
    if not path:
        return "none", "路径为空"
    if not os.path.exists(path):
        return "none", "文件不存在"

    ext = os.path.splitext(path)[1].lower()
    try:
        extra = shlex.split(item.get("args", ""), posix=False)
    except Exception:
        extra = []
    workdir = item.get("workdir", "").strip() or os.path.dirname(path)
    if not os.path.isdir(workdir):
        workdir = os.path.dirname(path)

    if ext == ".exe":
        return "popen", ([path] + extra, workdir)
    if ext == ".lnk":
        return "shell", (path, workdir, item.get("args", "").strip() or None)
    if ext in (".bat", ".cmd"):
        return "popen", (["cmd", "/c", path] + extra, workdir)
    if ext in (".py", ".pyw"):
        if ext == ".pyw":
            guess = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            py = guess if os.path.isfile(guess) else sys.executable
        else:
            py = sys.executable
        return "popen", ([py, path] + extra, workdir)
    if ext == ".js":
        node = find_exe(["node"], [r"C:\Program Files\nodejs\node.exe"])
        if not node:
            return "none", "没找到 node.exe，无法运行 .js"
        return "popen", ([node, path] + extra, workdir)
    if ext == ".ahk":
        ahk = find_exe(
            ["AutoHotkey.exe", "AutoHotkey64.exe"],
            [r"C:\Program Files\AutoHotkey\v2\AutoHotkey.exe",
             r"C:\Program Files\AutoHotkey\AutoHotkey.exe",
             r"C:\Program Files (x86)\AutoHotkey\AutoHotkey.exe"],
        )
        if not ahk:
            return "none", "没找到 AutoHotkey，无法运行 .ahk"
        return "popen", ([ahk, path] + extra, workdir)
    if ext == ".ps1":
        ps = find_exe(["powershell"])
        if not ps:
            ps = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path] + extra
        return "popen", (cmd, workdir)
    return "shell", (path, workdir, item.get("args", "").strip() or None)


def start_item(item):
    mode, payload = build_command(item)
    if mode == "none":
        return None, payload
    if mode == "shell":
        path, workdir, params = payload
        try:
            pid = shell_start(path, workdir, params)
            if pid:
                return pid, None
            return None, "系统拒绝打开该文件（可能没有关联程序）"
        except Exception as e:
            return None, str(e)
    cmd, workdir = payload
    try:
        p = subprocess.Popen(cmd, cwd=workdir)
        return p.pid, None
    except Exception as e:
        return None, str(e)


def kill_tree(pid):
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        pass


# ============ 托盘 ============
NIM_ADD = 0x00
NIM_MODIFY = 0x01
NIM_DELETE = 0x02
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10
NIIF_INFO = 0x01
NIIF_WARNING = 0x02
NIIF_ERROR = 0x03
WM_USER = 0x0400
WM_TRAY = WM_USER + 11
WM_WAKE = WM_USER + 12      # 其他实例发来：把主窗口叫出来
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040

_WNDPROC = ctypes.WINFUNCTYPE(
    _LPARAM_T, wintypes.HWND, wintypes.UINT, _WPARAM_T, _LPARAM_T
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HICON),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hWnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", _WPARAM_T),
        ("lParam", _LPARAM_T),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class TrayIcon:
    """原生系统托盘图标（后台线程跑独立消息循环）"""

    def __init__(self, on_show, on_menu, tip="一键启动", icon_path=None):
        self.on_show = on_show
        self.on_menu = on_menu
        self.tip = tip
        self.icon_path = icon_path
        self.hwnd = None
        self.ok = False
        self._cb = None
        self.thread = None
        self.ready = threading.Event()

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait(timeout=3.0)
        return bool(self.ok)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_WAKE:
            self.on_show()
            return 0
        if msg == WM_TRAY:
            if lparam == WM_LBUTTONDBLCLK:
                self.on_show()
            elif lparam == WM_RBUTTONDOWN:
                x = ctypes.c_short(lparam & 0xFFFF).value
                y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                pt = POINT()
                _user32.GetCursorPos(ctypes.byref(pt))
                self.on_menu(pt.x, pt.y)
            return 0
        if msg == WM_DESTROY:
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        cls_name = TRAY_CLASS
        try:
            self._cb = _WNDPROC(self._wndproc)
            hinst = _kernel32.GetModuleHandleW(None)

            wc = WNDCLASSW()
            wc.lpfnWndProc = self._cb
            wc.hInstance = ctypes.c_void_p(hinst)
            wc.lpszClassName = cls_name
            if not _user32.RegisterClassW(ctypes.byref(wc)):
                self.ok = False
                return

            hwnd = _user32.CreateWindowExW(
                0, cls_name, self.tip, 0, 0, 0, 0, 0, None, None,
                ctypes.c_void_p(hinst), None,
            )
            if not hwnd:
                self.ok = False
                return
            self.hwnd = hwnd

            icon = None
            if self.icon_path and os.path.isfile(self.icon_path):
                icon = _user32.LoadImageW(
                    None, self.icon_path, IMAGE_ICON, 0, 0,
                    LR_LOADFROMFILE | LR_DEFAULTSIZE,
                )
            if not icon:
                icon = _user32.LoadIconW(None, ctypes.cast(ctypes.c_void_p(IDI_APPLICATION), LPWSTR))
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAY
            nid.hIcon = icon
            nid.szTip = self.tip[:127]
            if not _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                self.ok = False
                return
            self.ok = True
            self.ready.set()

            msg = MSG()
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            self.ok = False
        finally:
            self.ready.set()

    def notify(self, title, msg, error=False):
        """在系统托盘弹出气泡提示"""
        if not self.hwnd:
            return False
        try:
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self.hwnd
            nid.uID = 1
            nid.uFlags = NIF_INFO
            nid.szInfoTitle = (title or "")[:63]
            nid.szInfo = (msg or "")[:255]
            nid.dwInfoFlags = NIIF_ERROR if error else NIIF_INFO
            return bool(_shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid)))
        except Exception:
            return False

    def stop(self):
        if self.hwnd:
            try:
                nid = NOTIFYICONDATAW()
                nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
                nid.hWnd = self.hwnd
                nid.uID = 1
                _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            except Exception:
                pass
            try:
                _user32.DestroyWindow(self.hwnd)
            except Exception:
                pass


def create_desktop_shortcut():
    """创建/更新桌面快捷方式，返回 (是否成功, 说明)"""
    bat = os.path.join(APP_DIR, "一键启动.bat")
    if not os.path.isfile(bat):
        return False, f"找不到启动文件：{bat}"
    icon = ICON_PATH if os.path.isfile(ICON_PATH) else ""
    ps = "\n".join([
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
        "$ws = New-Object -ComObject WScript.Shell",
        "$d = $ws.SpecialFolders('Desktop')",
        "$s = $ws.CreateShortcut((Join-Path $d '一键启动.lnk'))",
        f"$s.TargetPath = '{bat}'",
        f"$s.WorkingDirectory = '{APP_DIR}'",
        "$s.Description = '一键启动模拟器与脚本'",
        f"$s.IconLocation = '{icon},0'",
        "$s.Save()",
        "$c = $ws.CreateShortcut((Join-Path $d '一键启动.lnk'))",
        "Write-Output ('LNK|' + (Join-Path $d '一键启动.lnk') + '|' + $c.TargetPath + '|' + $c.IconLocation)",
    ])
    encoded = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", encoded],
            creationflags=subprocess.CREATE_NO_WINDOW,
            capture_output=True, timeout=40,
        )
    except Exception as e:
        return False, str(e)
    if r.returncode == 0:
        return True, r.stdout.decode("utf-8", "ignore").strip()
    return False, (r.stderr.decode("utf-8", "ignore") or "未知错误")


# ============ 编辑对话框 ============
class ItemDialog(tk.Toplevel):
    def __init__(self, master, item):
        super().__init__(master)
        self.result = False
        self.item = item
        self.title("项目设置")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        frm = ttk.Frame(self, padding=16)
        frm.grid(row=0, column=0, sticky="nsew")

        self.v_name = tk.StringVar(value=item.get("name", ""))
        self.v_path = tk.StringVar(value=item.get("path", ""))
        self.v_work = tk.StringVar(value=item.get("workdir", ""))
        self.v_args = tk.StringVar(value=item.get("args", ""))
        self.v_delay = tk.StringVar(value=str(item.get("delay", 5)))
        self.v_enabled = tk.BooleanVar(value=bool(item.get("enabled", True)))

        ttk.Label(frm, text="名称：").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frm, textvariable=self.v_name, width=52).grid(row=0, column=1, columnspan=2, sticky="w", pady=4)

        ttk.Label(frm, text="程序 / 脚本：").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frm, textvariable=self.v_path, width=52).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Button(frm, text="浏览…", width=8, command=self.pick_file).grid(row=1, column=2, sticky="w", padx=6)

        ttk.Label(frm, text="工作目录：").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(frm, textvariable=self.v_work, width=52).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Button(frm, text="浏览…", width=8, command=self.pick_dir).grid(row=2, column=2, sticky="w", padx=6)

        ttk.Label(frm, text="参数（可选）：").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(frm, textvariable=self.v_args, width=52).grid(row=3, column=1, columnspan=2, sticky="w", pady=4)

        ttk.Label(frm, text="启动后等待：").grid(row=4, column=0, sticky="w", pady=4)
        dfrm = ttk.Frame(frm)
        dfrm.grid(row=4, column=1, sticky="w", pady=4)
        ttk.Spinbox(dfrm, from_=0, to=3600, width=6, textvariable=self.v_delay).pack(side="left")
        ttk.Label(dfrm, text="秒后启动下一项").pack(side="left", padx=6)
        ttk.Checkbutton(frm, text="参与「一键全启」", variable=self.v_enabled).grid(row=4, column=2, sticky="w", padx=6)

        tip = ("说明：工作目录留空 = 程序所在的文件夹。\n"
               "模拟器的等待时间建议设 20-60 秒，等它完全起来再跑脚本。\n"
               "参数一般不用填。")
        ttk.Label(frm, text=tip, foreground="#777", justify="left").grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 4))

        bfrm = ttk.Frame(frm)
        bfrm.grid(row=6, column=0, columnspan=3, sticky="e", pady=(8, 0))
        ttk.Button(bfrm, text="确定", width=10, command=self.on_ok).pack(side="right", padx=6)
        ttk.Button(bfrm, text="取消", width=10, command=self.destroy).pack(side="right")

        self.bind("<Return>", lambda e: self.on_ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(200, lambda: self.focus_force())

    def pick_file(self):
        initial = self.v_path.get() or os.path.expanduser("~")
        p = filedialog.askopenfilename(
            parent=self,
            title="选择模拟器或脚本",
            initialdir=os.path.dirname(initial) if initial else None,
            filetypes=[("程序与脚本", "*.exe *.lnk *.bat *.cmd *.py *.pyw *.js *.ahk *.ps1"), ("所有文件", "*.*")],
        )
        if p:
            self.v_path.set(p)
            if not self.v_name.get().strip():
                self.v_name.set(os.path.splitext(os.path.basename(p))[0])

    def pick_dir(self):
        initial = self.v_work.get() or (os.path.dirname(self.v_path.get()) if self.v_path.get() else None)
        d = filedialog.askdirectory(parent=self, title="选择工作目录", initialdir=initial)
        if d:
            self.v_work.set(d)

    def on_ok(self):
        name = self.v_name.get().strip()
        path = self.v_path.get().strip()
        if not name:
            messagebox.showwarning("提示", "请填写名称。", parent=self)
            return
        if not path:
            messagebox.showwarning("提示", "请选择要启动的程序或脚本。", parent=self)
            return
        try:
            delay = max(0, int(float(self.v_delay.get())))
        except Exception:
            delay = 5
        self.item.update({
            "name": name,
            "path": path,
            "workdir": self.v_work.get().strip(),
            "args": self.v_args.get().strip(),
            "delay": delay,
            "enabled": bool(self.v_enabled.get()),
        })
        self.result = True
        self.destroy()


# ============ 主程序 ============
class App:
    def __init__(self, root):
        self.root = root
        self.items = load_config()
        self.settings = load_settings()
        self.running = {}          # id -> pid
        self.launching = False
        self.uiqueue = queue.Queue()
        self.tray = None
        self.tray_ok = False
        self.really_exit = False
        self.var_automini = tk.BooleanVar(value=bool(self.settings.get("auto_minimize", True)))

        root.title("一键启动")
        self._geo_job = None
        self.apply_saved_geometry(root)
        root.minsize(MIN_W, MIN_H)
        self.apply_window_icon(root)

        self._make_style()
        self._build_ui()
        self._build_tray()

        self.root.bind("<Configure>", self._on_configure)
        self.root.after(60, self._fit_log)

        self.root.after(150, self._drain)
        self.root.after(1000, self._tick)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- 界面 ----------
    def apply_saved_geometry(self, root):
        """恢复上次的窗口大小/位置；没记录过就用默认尺寸"""
        geo = str(self.settings.get("geometry") or "")
        m = re.fullmatch(r"(\d+)x(\d+)(?:([+-]\d+)([+-]\d+))?", geo)
        if not m:
            root.geometry(DEFAULT_GEOMETRY)
            return
        w = max(int(m.group(1)), MIN_W)
        h = max(int(m.group(2)), MIN_H)
        if m.group(3):
            # 位置也记过：做一次屏幕范围校验，免得窗口跑到屏幕外找不回来
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            x = min(max(int(m.group(3)), 60 - w), sw - 60)
            y = min(max(int(m.group(4)), 0), sh - 80)
            root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        else:
            root.geometry("%dx%d" % (w, h))

    def apply_window_icon(self, root):
        """窗口 / 任务栏图标：ico 管标题栏，png 补任务栏的大图标"""
        try:
            if os.path.isfile(ICON_PATH):
                root.iconbitmap(ICON_PATH)
        except Exception:
            pass
        try:
            if os.path.isfile(ICON_PNG):
                self._icon_img = tk.PhotoImage(file=ICON_PNG)   # 必须留引用，否则被回收
                root.iconphoto(True, self._icon_img)
        except Exception:
            pass

    def save_geometry(self):
        """把当前窗口大小/位置写进 settings.json"""
        self._geo_job = None
        try:
            if self.root.state() != "normal":
                return
            geo = self.root.geometry()
        except Exception:
            return
        m = re.fullmatch(r"(\d+)x(\d+)([+-]\d+[+-]\d+)?", geo or "")
        if not m or int(m.group(1)) < MIN_W or int(m.group(2)) < MIN_H:
            return          # 窗口还没成型，忽略
        if geo != self.settings.get("geometry"):
            self.settings["geometry"] = geo
            save_settings(self.settings)

    def _make_style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        self.root.option_add("*Font", ("Microsoft YaHei UI", 9))

    def _on_configure(self, event):
        if event.widget is not self.root:
            return
        self._fit_log()
        # 拖完窗口停手 0.7 秒后再记尺寸，避免拖动过程中反复写文件
        if self._geo_job:
            try:
                self.root.after_cancel(self._geo_job)
            except Exception:
                pass
        self._geo_job = self.root.after(700, self.save_geometry)

    def _fit_log(self):
        """窗口高度不够时，优先压缩运行日志，把空间让给列表。

        先尽量满足列表（按理想高度的 90% 保底），剩下的才给日志；
        日志行数在 3 ~ 8 之间浮动，最少也留 3 行，免得什么都看不到。
        """
        try:
            H = self.root.winfo_height()
        except Exception:
            return
        if H <= 1:
            return
        slack = 20          # 各处 pady / ipady 的安全余量
        avail = H - self.top.winfo_reqheight() - self.bottom_bar.winfo_reqheight() - slack
        lo = self._log_chrome + 3 * self._line_h
        hi = self._log_chrome + 8 * self._line_h
        want = min(max(avail - self._table_nat * 0.9, lo), hi)
        lines = int(round((want - self._log_chrome) / self._line_h))
        lines = max(3, min(8, lines))
        if lines != self._log_lines:
            self._log_lines = lines
            self.logbox.configure(height=lines)

    def _build_ui(self):
        self.top = ttk.Frame(self.root, padding=(10, 8))
        top = self.top
        top.pack(fill="x")

        ttk.Label(
            top,
            text="勾选「一键全启」列的条目会参与一键启动。双击某行可编辑。关闭窗口会缩到右下角托盘。",
            foreground="#777",
        ).pack(anchor="w")

        # ---- 按钮行：每行内部等宽，宽度随窗口自动缩放 ----
        def make_row(spec, tag, pady):
            row = ttk.Frame(top)
            row.pack(fill="x", pady=pady)
            for col, (txt, cmd) in enumerate(spec):
                ttk.Button(row, text=txt, command=cmd).grid(
                    row=0, column=col, sticky="nsew", padx=3)
                row.grid_columnconfigure(col, weight=1, uniform=tag)
            return row

        make_row([
            ("添加", self.add_item),
            ("编辑", self.edit_item),
            ("删除", self.del_item),
            ("上移", lambda: self.move(-1)),
            ("下移", lambda: self.move(1)),
            ("启用 / 禁用", self.toggle_enabled),
        ], "row1", (8, 4))

        make_row([
            ("一键全启", self.start_all),
            ("启动选中", self.start_selected),
            ("停止全部", self.stop_all),
            ("保存配置", self.save_only),
            ("使用说明", self.show_help),
            ("退出程序", self.quit_app),
        ], "row2", (4, 6))

        # 窗口最底部：一键全启后自动最小化开关
        # 先于列表 pack，这样窗口缩小时它不会被挤掉
        self.bottom_bar = ttk.Frame(self.root, padding=(10, 0, 14, 8))
        bottom = self.bottom_bar
        bottom.pack(fill="x", side="bottom")
        ttk.Checkbutton(
            bottom,
            text="一键全启后自动最小化到托盘",
            variable=self.var_automini,
            command=self.on_automini_toggle,
        ).pack(side="right")

        # 日志（贴在底部开关上方，同样先于列表 pack）
        self.log_frame = ttk.LabelFrame(self.root, text="运行日志", padding=6)
        lf = self.log_frame
        lf.pack(fill="x", side="bottom", padx=10, pady=(4, 4), ipady=2)
        self.logbox = tk.Text(lf, height=8, wrap="none", relief="flat", bg="#fafafa", fg="#333")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        self.logbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.logbox.configure(state="disabled")

        # 列表：最后 pack，占据中间的剩余空间
        self.listbox_frame = ttk.Frame(self.root)
        listbox_frame = self.listbox_frame
        listbox_frame.pack(fill="both", expand=True, padx=10, pady=(6, 2))

        cols = ("status", "enabled", "name", "path", "delay")
        self.tree = ttk.Treeview(listbox_frame, columns=cols, show="headings", selectmode="browse")
        heads = [("status", "状态", 90), ("enabled", "一键全启", 80), ("name", "名称", 150),
                 ("path", "程序 / 脚本路径", 430), ("delay", "等待(秒)", 80)]
        for k, t, w in heads:
            self.tree.heading(k, text=t)
            self.tree.column(k, width=w, anchor="w" if k in ("name", "path") else "center")
        vs = ttk.Scrollbar(listbox_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.tag_configure("run", foreground="#0a7a2f")
        self.tree.tag_configure("idle", foreground="#666666")
        self.tree.bind("<Double-1>", lambda e: self.edit_item())
        self.tree.bind("<space>", lambda e: self.toggle_enabled())

        # ---- 测一次行高，供「窗口变矮时优先压缩日志」使用 ----
        self._log_lines = 8
        self.logbox.configure(height=1)
        self.root.update_idletasks()
        h1 = lf.winfo_reqheight()
        self.logbox.configure(height=11)
        self.root.update_idletasks()
        self._line_h = max(1.0, (lf.winfo_reqheight() - h1) / 10.0)
        self._log_chrome = h1 - self._line_h          # 日志框自身（标签/边距）固定占高
        self._table_nat = self.tree.winfo_reqheight() + 8   # 列表的"理想高度"
        self.logbox.configure(height=self._log_lines)

        self.refresh_tree()
        self.log(f"配置文件：{CONFIG_PATH}")
        if not self.items:
            self.log("列表还是空的 —— 点【添加】把你的模拟器和脚本加进来。")
        else:
            self.log(f"已载入 {len(self.items)} 个项目。")

    # ---------- 托盘 ----------
    def _build_tray(self):
        self.tray_menu = tk.Menu(self.root, tearoff=0)
        self.tray_menu.add_command(label="显示窗口", command=self.show_window)
        self.tray_menu.add_separator()
        self.tray_menu.add_command(label="一键全启", command=self.start_all)
        self.tray_menu.add_command(label="停止全部", command=self.stop_all)
        self.tray_menu.add_separator()
        self.tray_menu.add_command(label="重建桌面快捷方式", command=self.make_shortcut)
        self.tray_menu.add_command(label="退出", command=self.quit_app)

        self.tray = TrayIcon(
            on_show=lambda: self.root.after(0, self.show_window),
            on_menu=lambda x, y: self.root.after(0, lambda: self._popup(x, y)),
            icon_path=ICON_PATH,
        )
        self.tray_ok = self.tray.start()

    def _popup(self, x, y):
        try:
            self.tray_menu.tk_popup(x, y)
        finally:
            self.tray_menu.grab_release()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self):
        if self.tray_ok:
            self.root.withdraw()
        else:
            self.root.iconify()

    def on_automini_toggle(self):
        self.settings["auto_minimize"] = bool(self.var_automini.get())
        save_settings(self.settings)
        tips = "开启：点【一键全启】后窗口会立刻缩到托盘。"
        tip = tips if self.var_automini.get() else "关闭：点【一键全启】后窗口保持不动。"
        self.log(tip)

    # ---------- 日志 ----------
    def log(self, text):
        ts = time.strftime("%H:%M:%S")
        try:
            self.logbox.configure(state="normal")
            self.logbox.insert("end", f"[{ts}] {text}\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        except Exception:
            pass

    # ---------- 列表 ----------
    def refresh_tree(self):
        sel = self.tree.selection()
        cur_iid = sel[0] if sel else None
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for it in self.items:
            pid = self.running.get(it["id"])
            if pid and _is_pid_alive(pid):
                status, tag = "● 运行中", "run"
            else:
                status, tag = "○ 未启动", "idle"
                if pid:
                    self.running.pop(it["id"], None)
            self.tree.insert(
                "", "end", iid=it["id"],
                values=(status, "✓" if it["enabled"] else "", it["name"], it["path"], it["delay"]),
                tags=(tag,),
            )
        if cur_iid and self.tree.exists(cur_iid):
            self.tree.selection_set(cur_iid)
            self.tree.focus(cur_iid)

    def selected_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        for i, it in enumerate(self.items):
            if it["id"] == sel[0]:
                return i
        return None

    def save_cfg(self):
        if save_config(self.items):
            return True
        messagebox.showerror("错误", "配置保存失败，请检查文件是否被占用。")
        return False

    # ---------- 增删改 ----------
    def add_item(self):
        it = new_item()
        dlg = ItemDialog(self.root, it)
        self.root.wait_window(dlg)
        if dlg.result:
            self.items.append(it)
            self.save_cfg()
            self.refresh_tree()
            self.log(f"已添加：{it['name']}")

    def edit_item(self):
        i = self.selected_index()
        if i is None:
            messagebox.showinfo("提示", "请先在列表中选中一行。")
            return
        it = self.items[i]
        backup = dict(it)
        dlg = ItemDialog(self.root, it)
        self.root.wait_window(dlg)
        if dlg.result:
            self.save_cfg()
            self.refresh_tree()
            self.log(f"已保存：{it['name']}")
        else:
            self.items[i] = backup

    def del_item(self):
        i = self.selected_index()
        if i is None:
            messagebox.showinfo("提示", "请先在列表中选中一行。")
            return
        name = self.items[i]["name"]
        if not messagebox.askyesno("确认", f"确定删除【{name}】吗？"):
            return
        pid = self.running.pop(self.items[i]["id"], None)
        if pid:
            kill_tree(pid)
        self.items.pop(i)
        self.save_cfg()
        self.refresh_tree()
        self.log(f"已删除：{name}")

    def move(self, delta):
        i = self.selected_index()
        if i is None:
            return
        j = i + delta
        if j < 0 or j >= len(self.items):
            return
        self.items[i], self.items[j] = self.items[j], self.items[i]
        self.save_cfg()
        self.refresh_tree()

    def toggle_enabled(self):
        i = self.selected_index()
        if i is None:
            messagebox.showinfo("提示", "请先在列表中选中一行。")
            return
        self.items[i]["enabled"] = not self.items[i]["enabled"]
        self.save_cfg()
        self.refresh_tree()

    # ---------- 启动 / 停止 ----------
    def start_all(self):
        todo = [it for it in self.items if it["enabled"]]
        if not todo:
            messagebox.showinfo("提示", "没有任何条目参与了「一键全启」。\n请先勾选列表里的「一键全启」列。")
            return
        self._start_list(todo, auto_mini=bool(self.var_automini.get()))

    def start_selected(self):
        i = self.selected_index()
        if i is None:
            messagebox.showinfo("提示", "请先在列表中选中一行。")
            return
        self._start_list([self.items[i]])

    def _start_list(self, todo, auto_mini=False):
        if self.launching:
            messagebox.showinfo("提示", "正在启动中，请稍候…")
            return
        self.launching = True
        if auto_mini:
            self.hide_window()
            self.log("窗口已缩到托盘，启动进度会在这儿继续记录。")
        threading.Thread(target=self._worker, args=(todo,), daemon=True).start()

    def _worker(self, todo):
        failed = 0
        try:
            for idx, it in enumerate(todo):
                self.uiqueue.put(("log", f"启动【{it['name']}】…"))
                pid, err = start_item(it)
                if pid:
                    self.uiqueue.put(("started", it["id"], pid))
                    self.uiqueue.put(("log", f"√ {it['name']} 已启动（进程号 {pid}）"))
                else:
                    failed += 1
                    self.uiqueue.put(("log", f"× {it['name']} 启动失败：{err}"))
                d = int(it.get("delay", 0))
                if idx < len(todo) - 1 and d > 0:
                    self.uiqueue.put(("log", f"等待 {d} 秒后启动下一项…"))
                    for _ in range(d * 2):
                        time.sleep(0.5)
            self.uiqueue.put(("log", "本次启动流程全部完成。"))
        finally:
            self.uiqueue.put(("done", failed, len(todo)))

    def stop_all(self):
        ids = list(self.running.keys())
        if not ids:
            self.log("当前没有由本程序启动、且仍在运行的项目。")
            return
        for i in ids:
            pid = self.running.pop(i, None)
            if pid:
                kill_tree(pid)
        self.log(f"已关闭 {len(ids)} 个项目（含其子进程）。")
        self.refresh_tree()

    # ---------- 其它 ----------
    def save_only(self):
        if self.save_cfg():
            self.log("配置已保存。")

    def show_help(self):
        messagebox.showinfo(
            "使用说明",
            "1) 点【添加】→【浏览…】选中你的模拟器，起个名字，确定。\n\n"
            "2) 模拟器那一项，「启动后等待」填 20-60 秒，\n"
            "    让它彻底起来之后再跑后面的脚本。\n\n"
            "3) 用【上移】【下移】排好顺序：模拟器在前，脚本在后。\n\n"
            "4) 勾选要参与的条目，点【一键全启】。\n\n"
            "5) 关掉窗口只是缩到右下角托盘，\n"
            "    要真正退出请点【退出程序】或右键托盘图标。\n\n"
            "支持：.exe / .lnk 快捷方式 / .bat / .cmd\n"
            "        .py / .js（需装 Node.js）/ .ahk（需装 AutoHotkey）/ .ps1",
        )

    def make_shortcut(self):
        ok, info = create_desktop_shortcut()
        if ok:
            messagebox.showinfo("完成", "桌面快捷方式已创建/更新。\n以后双击桌面上的「一键启动」即可。")
            self.log("已创建/更新桌面快捷方式。")
        else:
            messagebox.showerror("创建失败", info)

    def on_close(self):
        if self.tray_ok:
            self.hide_window()
        else:
            self.root.iconify()

    def quit_app(self):
        self.save_geometry()
        self.really_exit = True
        if self.tray:
            self.tray.stop()
        try:
            self.root.destroy()
        except Exception:
            pass

    # ---------- 定时 ----------
    def _drain(self):
        try:
            while True:
                ev = self.uiqueue.get_nowait()
                kind = ev[0]
                if kind == "log":
                    self.log(ev[1])
                elif kind == "started":
                    self.running[ev[1]] = ev[2]
                    self.refresh_tree()
                elif kind == "done":
                    self.launching = False
                    failed, total = ev[1], ev[2]
                    self.refresh_tree()
                    if failed and self.tray_ok:
                        self.tray.notify(
                            "有项目没起来",
                            f"{total} 个里有 {failed} 个启动失败，点托盘图标打开窗口看日志",
                            error=True,
                        )
                    elif self.tray_ok and self.root.state() == "withdrawn":
                        self.tray.notify("一键启动", f"{total} 个项目已全部启动完成。")
        except queue.Empty:
            pass
        self.root.after(200, self._drain)

    def _tick(self):
        changed = False
        for k in list(self.running.keys()):
            if not _is_pid_alive(self.running[k]):
                self.running.pop(k, None)
                changed = True
        if changed:
            self.refresh_tree()
        self.root.after(3000, self._tick)


def main():
    set_taskbar_app_id()
    if single_instance_guard():
        return                  # 已经在跑了：唤起原有窗口，本次直接退出
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = APP_DIR
    os.makedirs(base, exist_ok=True)
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
