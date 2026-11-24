import ctypes
import sys
import os
import importlib.util
import subprocess

def enable_dpi_awareness():
    if sys.platform != 'win32':
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    if sys.platform == 'win32':
        script = os.path.abspath(sys.argv[0])
        params = subprocess.list2cmdline(sys.argv[1:] if getattr(sys, 'frozen', False) else [script] + sys.argv[1:])
        reset_environment = os.environ.get('PYINSTALLER_RESET_ENVIRONMENT')
        try:
            if getattr(sys, 'frozen', False):
                # 提权后的独立进程需要自己的解包目录，避免原进程退出后依赖被清理。
                os.environ['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
            return ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1) > 32
        except:
            return False
        finally:
            if reset_environment is None:
                os.environ.pop('PYINSTALLER_RESET_ENVIRONMENT', None)
            else:
                os.environ['PYINSTALLER_RESET_ENVIRONMENT'] = reset_environment
    return False

import tkinter as tk
from tkinter import messagebox, ttk, font as tkfont
import threading
import json
import time
from collections import deque
from functools import partial
from queue import Empty, SimpleQueue
from unicodedata import east_asian_width

from typing_model import (DEFAULT_INPUT_SPEED, INTERVAL_DEFAULTS, MODEL_DEFAULTS,
                          TypingRhythm, normalize_input_speed, speed_profile)
from window_guard import GUARD_DEFAULTS, foreground_window, inspect_foreground_window

keyboard = None
pyperclip = None
pystray = None
HAS_PYSTRAY = importlib.util.find_spec("pystray") is not None

def load_keyboard():
    global keyboard
    if keyboard is None:
        import keyboard as keyboard_module
        keyboard = keyboard_module
    return keyboard

def load_pyperclip():
    global pyperclip
    if pyperclip is None:
        import pyperclip as pyperclip_module
        pyperclip = pyperclip_module
    return pyperclip

def load_tray():
    global pystray
    if pystray is None:
        import pystray as pystray_module
        pystray = pystray_module
    from PIL import Image
    return pystray, Image

def get_config_path():
    if getattr(sys, 'frozen', False):
        # 程序被打包成 exe
        base_dir = os.path.dirname(sys.executable)
    else:
        # 普通 Python 脚本
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "config.json")

def resource_path(name):
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, name)

CONFIG_FILE = get_config_path()
APP_NAME = "Copy2Input"
CLIPBOARD_READY_LENGTH = 20
CLIPBOARD_POLL_MS = 400
TRAY_TITLES = {
    'idle': APP_NAME,
    'ready': f'{APP_NAME} · 剪贴板就绪',
    'typing': f'{APP_NAME} · 正在输入',
    'paused': f'{APP_NAME} · 已暂停',
}
DEFAULT_CONFIG = {
    **INTERVAL_DEFAULTS,
    "input_speed": DEFAULT_INPUT_SPEED,
    "hotkey": "f4",
    "pause_hotkey": "f6",
    "separators": " ,._，。;；:：!?！？、",
    **MODEL_DEFAULTS,
    **GUARD_DEFAULTS,
    "hide_to_tray": True,
    "always_on_top": False
}

MODEL_LABELS = {
    'model_tempo': '节奏变化',
    'model_bigrams': '英文连击',
    'model_key_distance': '键位距离',
    'model_shift_digits': 'Shift/数字',
    'model_smart_pauses': '智能停顿',
    'model_english_tokens': '格式识别',
}
GUARD_LABELS = {
    'pause_on_focus_loss': '输入时离开窗口自动暂停',
    'block_untypable_windows': '启动时拦截不可输入的窗口（实验性）',
}
TEST_TEXT = (
    'Copy2Input: The quick brown fox jumps over the lazy dog.\n'
    'The other reader is thinking, then writing another sentence; there is time to breathe.\n'
    'Near keys: asdf jkl; far keys: ap qz zm. Repeated letters: bookkeeper, coffee, balloon.\n'
    'Hello WORLD! Copy2Input uses Aa Bb Zz, 0123456789, and symbols: @ # $ % ^ & * _ + =.\n'
    '\n'
    'Dr. Smith met Mrs. Brown and J. Adams at St. James, e.g. near the station.\n'
    'Version v1.2 costs 1,234.56; pi is 3.14. The user_name is ready.\n'
    'Visit https://example.com/a_b?q=1,2 or www.example.com. Email user.name+tag@example.com.\n'
    '"Really?!"  Yes... (That is right.)  Don\'t stop; it\'s a new sentence: keep going!\n'
    '\n'
    'One line ends here.\n'
    'Another line follows, with a comma, a colon: and a semicolon; then a full stop.\n'
    '\n'
    'A new paragraph begins. The rhythm carries on through this longer passage, '
    'moving between familiar words and less common combinations. '
    'The final sentence stays intact from its first letter to its last.\n'
    '中文兼容：你好，世界！Mixed English 与中文。Unicode: café, naïve, “quotes”, 🙂.\n'
    'Copy2Input complete.'
)

INSTANCE_MUTEX_NAME = rf'Local\{APP_NAME}.SingleInstance'
MAX_PAIR_CONTENT_LENGTH = 80
PAIR_SYMBOL_EXTRA_DELAY = 0.1
PAIR_CARET_DELAY = 0.3
TRIPLE_SINGLE_QUOTE = "'''"
QUOTE_ENDS = {
    '"': '"', "'": "'", '“': '”', '‘': '’', '＂': '＂', '＇': '＇',
    '「': '」', '『': '』', TRIPLE_SINGLE_QUOTE: TRIPLE_SINGLE_QUOTE,
}
PAIR_ENDS = {
    **QUOTE_ENDS, '(': ')', '[': ']', '{': '}',
    '（': '）', '［': '］', '｛': '｝', '【': '】',
}
QUOTE_CLOSERS = frozenset(QUOTE_ENDS.values())
PAIR_CLOSERS = frozenset(PAIR_ENDS.values())


def pair_symbol_at(text, index):
    return TRIPLE_SINGLE_QUOTE if text.startswith(TRIPLE_SINGLE_QUOTE, index) else text[index]


def find_symbol_pairs(text):
    pairs = {}
    openings = deque()
    escaped = False
    symbol_end = 0
    for index, char in enumerate(text):
        if index < symbol_end:
            continue
        if char == '\\':
            escaped = not escaped
            continue
        if escaped:
            escaped = False
            continue
        if char == "'":
            char = pair_symbol_at(text, index)
            symbol_end = index + len(char)
        can_open = char in PAIR_ENDS
        can_close = char in PAIR_CLOSERS
        if not (can_open or can_close):
            continue
        while openings and index - openings[0][0] - len(openings[0][1]) > MAX_PAIR_CONTENT_LENGTH:
            openings.popleft()
        if char in ("'", '’', '＇'):
            previous = text[index - 1] if index else ''
            following = text[index + 1:index + 2]
            # Ignore apostrophes inside words while allowing quotes next to CJK text.
            can_open = can_open and not (previous.isalnum() and east_asian_width(previous) not in 'WF')
            can_close = can_close and not (following.isalnum() and east_asian_width(following) not in 'WF')
        if can_close:
            for count, (start, expected) in enumerate(reversed(openings), 1):
                if expected == char:
                    pairs[start] = index
                    # Discard unmatched openings within this pair to prevent crossing pairs.
                    for _ in range(count):
                        openings.pop()
                    can_open = False
                    break
                # A bracket inside a quote can only close a bracket within that quote.
                if expected in QUOTE_CLOSERS and char not in QUOTE_CLOSERS:
                    break
        if can_open:
            openings.append((index, PAIR_ENDS[char]))
    return pairs


def fit_clipboard_slice(text, start, end, width, measure, *, from_end=False):
    """Find how many characters fit without measuring the entire clipboard."""
    def fits(length):
        fragment = text[end - length:end] if from_end else text[start:start + length]
        return measure(fragment) <= width

    lower, upper = 0, min(1, end - start)
    while upper < end - start and fits(upper):
        lower, upper = upper, min(upper * 2, end - start)
    while lower < upper:
        middle = (lower + upper + 1) // 2
        if fits(middle):
            lower = middle
        else:
            upper = middle - 1
    return lower


def format_clipboard_preview(text, width, measure):
    ellipsis = '...'
    ellipsis_width = measure(ellipsis)
    if width < ellipsis_width:
        return ''

    fit = partial(fit_clipboard_slice, text, measure=measure)
    end = len(text)
    lines = []
    start = 0
    for _ in range(3):
        boundary = start + fit(start, end, width)
        lines.append(text[start:boundary])
        if boundary == end:
            return '\n'.join(lines)
        start = boundary

    head_end = len(lines[0])
    tail_start = end - fit(head_end, end, width, from_end=True)
    middle_width = width - ellipsis_width
    head_middle = head_end + fit(head_end, tail_start, middle_width // 2)
    tail_middle = tail_start - fit(head_middle, tail_start, middle_width - middle_width // 2, from_end=True)
    middle = text[head_end:head_middle] + ellipsis + text[tail_middle:tail_start]
    return '\n'.join((lines[0], middle, text[tail_start:]))


def acquire_instance():
    if sys.platform != 'win32':
        return None
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexExW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
    kernel.CreateMutexExW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateMutexExW(None, INSTANCE_MUTEX_NAME, 0, 0x00100000)
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    if error == 183:
        kernel.CloseHandle(handle)
        user = ctypes.windll.user32
        user.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
        user.FindWindowW.restype = wintypes.HWND
        user.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        user.SetForegroundWindow.argtypes = (wintypes.HWND,)
        window = user.FindWindowW('TkTopLevel', APP_NAME)
        if window:
            user.ShowWindow(window, 9)
            user.SetForegroundWindow(window)
        return None
    return handle

class Copy2InputApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.resizable(True, True)
        self.root.configure(bg='#f7f8fa')
        
        self.config = self.load_config()
        self.is_topmost = self.config.get("always_on_top", False)
        self.root.attributes('-topmost', self.is_topmost)
        if sys.platform == 'win32':
            icon_path = resource_path('assets/Copy2Input.ico')
            self.root.iconbitmap(default=icon_path)
            # 同时显式设置当前窗口，保证标题栏和任务栏使用该 ICO。
            self.root.iconbitmap(icon_path)
        else:
            self.window_icon = tk.PhotoImage(master=root, file=resource_path('assets/Copy2Input.png'))
            self.root.iconphoto(True, self.window_icon)
        self.settings_save_job = None
        self.is_saving_settings = False
        self.settings_valid = True
        self.is_typing = False
        self.is_paused = False
        self.typing_condition = threading.Condition()
        self.stop_event = threading.Event()
        self.typing_thread = None
        self.guard_settings = GUARD_DEFAULTS.copy()
        self.target_window = None
        self.pause_reason = None
        self.focus_monitor_job = None
        self.is_setting_hotkey = False
        self.setting_hotkey = None
        self.pressed_keys = set()
        self.tray_icon = None
        self.tray_images = {}
        self.clipboard_text = ''
        self.clipboard_ready = False
        self.clipboard_sequence = None
        self.clipboard_poll_job = None
        self.clipboard_reading = False
        self.clipboard_results = SimpleQueue()
        self.is_hidden = False
        self.hook_handle = None
        self.toggle_hotkey_hook = None
        self.pause_hotkey_hook = None
        
        self.setup_ui()
        self.setup_auto_save()
        self.fit_window()
        
        self.root.after_idle(self.initialize_background_features)
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    def initialize_background_features(self):
        self.init_keyboard()
        self.poll_clipboard()
        if HAS_PYSTRAY:
            try:
                self.setup_tray()
            except Exception as e:
                print(f"初始化托盘失败: {e}")
                self.status_var.set("⚠ 托盘不可用")
    
    def init_keyboard(self):
        self.register_hotkeys()
    
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    loaded.pop("stop_hotkey", None)
                    loaded.pop("use_random_speed", None)
                    loaded.pop("fixed_speed", None)
                    old_separator_delay = loaded.pop("separator_delay", None)
                    if old_separator_delay is not None:
                        loaded.setdefault("separator_min_delay", old_separator_delay)
                        loaded.setdefault("separator_max_delay", old_separator_delay)
                    for key in DEFAULT_CONFIG:
                        if key not in loaded:
                            loaded[key] = DEFAULT_CONFIG[key]
                    loaded['input_speed'] = normalize_input_speed(loaded['input_speed'])
                    if loaded["pause_hotkey"] == loaded["hotkey"]:
                        loaded["pause_hotkey"] = (
                            "ctrl+alt+shift+p" if loaded["hotkey"] == DEFAULT_CONFIG["pause_hotkey"]
                            else DEFAULT_CONFIG["pause_hotkey"]
                        )
                    return loaded
            except:
                return DEFAULT_CONFIG.copy()
        else:
            default = DEFAULT_CONFIG.copy()
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(default, f, ensure_ascii=False, indent=2)
            return default
    
    def save_config(self):
        try:
            with open(CONFIG_FILE + '.tmp', 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            os.replace(CONFIG_FILE + '.tmp', CONFIG_FILE)
            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            self.status_var.set("⚠ 保存失败")
            return False

    def button_style(self, kind="primary"):
        styles = {
            "primary": ("#2563eb", "#ffffff", "#1d4ed8"),
            "success": ("#0f766e", "#ffffff", "#115e59"),
            "danger": ("#dc2626", "#ffffff", "#b91c1c"),
            "muted": ("#334155", "#ffffff", "#1e293b"),
            "light": ("#e8eef7", "#1e293b", "#dbe5f2"),
        }
        bg, fg, active_bg = styles.get(kind, styles["primary"])
        return {
            "font": ('Microsoft YaHei UI', 10, 'bold'),
            "bg": bg,
            "fg": fg,
            "activebackground": active_bg,
            "activeforeground": fg,
            "relief": "flat",
            "bd": 0,
            "padx": 15,
            "pady": 8,
            "cursor": "hand2",
        }

    def create_card(self, parent, pady=(0, 14)):
        frame = tk.Frame(
            parent,
            bg='#ffffff',
            highlightbackground='#dbe4f0',
            highlightthickness=1,
            padx=18,
            pady=14
        )
        frame.pack(fill=tk.X, pady=pady)
        return frame

    def create_section_title(self, parent, title):
        tk.Label(
            parent,
            text=title,
            font=('Microsoft YaHei', 12, 'bold'),
            bg='#ffffff',
            fg='#111827'
        ).pack(anchor=tk.W, pady=(0, 6))

    def create_entry(self, parent, variable, width=10):
        return tk.Entry(
            parent,
            textvariable=variable,
            width=width,
            font=('Microsoft YaHei', 11),
            bg='#f8fafc',
            fg='#111827',
            relief='flat',
            bd=0,
            highlightthickness=1,
            highlightbackground='#cbd5e1',
            highlightcolor='#0f766e',
            insertbackground='#0f766e'
        )

    def update_scroll_region(self, event=None):
        self.content_canvas.configure(scrollregion=self.content_canvas.bbox("all"))

    def sync_scroll_width(self, event):
        self.content_canvas.itemconfigure(self.scroll_window, width=event.width)

    def on_mousewheel(self, event):
        self.content_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    
    def setup_ui(self):
        self.font = ('Microsoft YaHei UI', 10)
        self.font_small = ('Microsoft YaHei UI', 9)
        self.mono_font = ('Cascadia Mono', 10)
        tkfont.nametofont('TkDefaultFont').configure(family=self.font[0], size=10)
        tkfont.nametofont('TkTextFont').configure(family=self.font[0], size=10)

        style = ttk.Style(self.root)
        style.theme_use('clam')
        if sys.platform == 'win32':
            style.element_create('App.Checkbutton.indicator', 'from', 'vista', 'Checkbutton.indicator')
            style.layout('App.TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
                ('App.Checkbutton.indicator', {'side': 'left', 'sticky': ''}),
                ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [
                    ('Checkbutton.label', {'sticky': 'nswe'})
                ]})
            ]})])
        style.configure('App.TFrame', background='#f7f8fa')
        style.configure('App.TCheckbutton', background='#ffffff', foreground='#334155', font=self.font)
        style.map('App.TCheckbutton', background=[('active', '#ffffff')])
        style.configure('App.TEntry', fieldbackground='#ffffff', foreground='#17202a', padding=(7, 4))
        style.configure('Secondary.TButton', background='#eef2f6', foreground='#334155', padding=(10, 5), borderwidth=0, font=self.font)
        style.map('Secondary.TButton', background=[('active', '#e2e8f0')])
        style.configure('Primary.TButton', background='#0f6cbd', foreground='#ffffff', padding=(10, 5), borderwidth=0, font=('Microsoft YaHei UI', 10, 'bold'))
        style.map('Primary.TButton', background=[('active', '#0b5da5')])
        style.configure('Danger.TButton', background='#fff1f2', foreground='#be123c', padding=(10, 5), borderwidth=0, font=self.font)
        style.map('Danger.TButton', background=[('active', '#ffe4e6')])
        style.configure('Speed.Horizontal.TScale', background='#ffffff', troughcolor='#e2e8f0')
        style.map('Speed.Horizontal.TScale', troughcolor=[('disabled', '#f1f5f9')])

        root_frame = ttk.Frame(self.root, style='App.TFrame', padding=(14, 10))
        root_frame.pack(fill=tk.BOTH, expand=True)
        root_frame.columnconfigure(0, weight=1)

        self.create_input_settings(root_frame, 0)
        self.create_hotkey_section(root_frame, 1)
        self.create_tray_section(root_frame, 2)
        self.create_status_section(root_frame, 3)
        self.create_button_section(root_frame, 4)

    def create_input_settings(self, parent, row):
        container = ttk.Frame(parent, style='App.TFrame')
        container.grid(row=row, column=0, sticky='ew')
        container.columnconfigure(0, weight=1)
        self.advanced_mode = False
        self.simple_settings = tk.Frame(container, bg='#ffffff', highlightbackground='#e5e7eb',
                                        highlightthickness=1, padx=10, pady=8)
        self.simple_settings.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        self.simple_settings.columnconfigure(1, weight=1)
        tk.Label(self.simple_settings, text='输入速度', bg='#ffffff', fg='#17202a',
                 font=('Microsoft YaHei UI', 11, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w')
        self.input_speed_var = tk.DoubleVar(value=normalize_input_speed(self.config['input_speed']))
        profile = speed_profile(self.input_speed_var.get())
        custom = any(self.config[key] != profile[key] for key in INTERVAL_DEFAULTS)
        self.speed_label_var = tk.StringVar(value='自定义' if custom else str(profile['input_speed']))
        self.speed_value_label = tk.Label(self.simple_settings, textvariable=self.speed_label_var,
                                          font=self.font_small, bg='#ffffff', fg='#475569')
        self.speed_value_label.grid(row=0, column=2, sticky='e')
        tk.Label(self.simple_settings, text='慢', font=self.font_small,
                 bg='#ffffff', fg='#475569').grid(row=1, column=0)
        self.speed_scale = ttk.Scale(self.simple_settings, from_=0, to=100, orient=tk.HORIZONTAL,
                                     variable=self.input_speed_var, command=self.on_input_speed_change,
                                     style='Speed.Horizontal.TScale', takefocus=True)
        self.speed_scale.grid(row=1, column=1, sticky='ew', padx=8, pady=(7, 9))
        tk.Label(self.simple_settings, text='快', font=self.font_small,
                 bg='#ffffff', fg='#475569').grid(row=1, column=2)
        self.advanced_mode_btn = ttk.Button(self.simple_settings, text='高级模式',
                                            command=self.toggle_settings_mode, style='Secondary.TButton')
        self.advanced_mode_btn.grid(row=2, column=0, columnspan=3, sticky='ew')

        self.advanced_settings = ttk.Frame(container, style='App.TFrame')
        self.advanced_settings.grid(row=0, column=0, sticky='ew')
        self.advanced_settings.columnconfigure(0, weight=1)
        self.create_speed_section(self.advanced_settings, 0)
        self.create_model_section(self.advanced_settings, 1)
        self.simple_mode_btn = ttk.Button(self.advanced_settings, text='简洁模式',
                                          command=self.toggle_settings_mode, style='Secondary.TButton')
        self.simple_mode_btn.grid(row=2, column=0, sticky='ew', pady=(0, 6))
        self.advanced_settings.grid_remove()
        self.input_setting_controls = (
            self.speed_scale, self.min_speed_entry, self.max_speed_entry,
            self.separator_min_delay_entry, self.separator_max_delay_entry,
            self.separators_entry, *self.model_checks.values(),
            *self.guard_checks.values(),
        )

    def update_input_settings_state(self):
        state = tk.DISABLED if self.is_typing else tk.NORMAL
        for control in self.input_setting_controls:
            control.configure(state=state)
        self.speed_value_label.configure(fg='#9ca3af' if self.is_typing else '#475569')

    def fit_window(self):
        self.root.update_idletasks()
        width, height = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        self.root.minsize(width, height)
        self.root.geometry(f'{width}x{height}')

    def toggle_settings_mode(self):
        if not self.flush_pending_settings():
            return
        self.advanced_mode = not self.advanced_mode
        if self.advanced_mode:
            self.simple_settings.grid_remove()
            self.advanced_settings.grid()
            self.simple_mode_btn.focus_set()
        else:
            self.advanced_settings.grid_remove()
            self.simple_settings.grid()
            self.advanced_mode_btn.focus_set()
        self.fit_window()

    def on_input_speed_change(self, value):
        if self.is_typing:
            self.input_speed_var.set(self.config['input_speed'])
            return
        profile = speed_profile(value)
        self.is_saving_settings = True
        try:
            self.input_speed_var.set(profile['input_speed'])
            for key in INTERVAL_DEFAULTS:
                getattr(self, key + '_var').set(str(profile[key]))
            self.speed_label_var.set(str(profile['input_speed']))
        finally:
            self.is_saving_settings = False
        self.schedule_settings_save()
    
    def create_speed_section(self, parent, row):
        frame = tk.Frame(parent, bg='#ffffff', highlightbackground='#e5e7eb', highlightthickness=1, padx=10, pady=6)
        frame.grid(row=row, column=0, sticky='ew', pady=(0, 6))
        tk.Label(frame, text='输入间隔（毫秒）', bg='#ffffff', fg='#17202a', font=('Microsoft YaHei UI', 11, 'bold')).grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 5))
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        tk.Label(frame, text='最小间隔', font=self.font_small, bg='#ffffff', fg='#475569').grid(row=1, column=0, sticky='w', pady=3)
        self.min_speed_var = tk.StringVar(value=str(self.config["min_speed"]))
        self.min_speed_entry = ttk.Entry(frame, textvariable=self.min_speed_var, style='App.TEntry', width=8)
        self.min_speed_entry.grid(row=1, column=1, sticky='ew', padx=(8, 12), pady=3)
        tk.Label(frame, text='最大间隔', font=self.font_small, bg='#ffffff', fg='#475569').grid(row=1, column=2, sticky='w', pady=3)
        self.max_speed_var = tk.StringVar(value=str(self.config["max_speed"]))
        self.max_speed_entry = ttk.Entry(frame, textvariable=self.max_speed_var, style='App.TEntry', width=8)
        self.max_speed_entry.grid(row=1, column=3, sticky='ew', padx=(8, 0), pady=3)
        tk.Label(frame, text='分词符最小间隔', font=self.font_small, bg='#ffffff', fg='#475569').grid(row=2, column=0, sticky='w', pady=3)
        self.separator_min_delay_var = tk.StringVar(value=str(self.config["separator_min_delay"]))
        self.separator_min_delay_entry = ttk.Entry(frame, textvariable=self.separator_min_delay_var, style='App.TEntry', width=8)
        self.separator_min_delay_entry.grid(row=2, column=1, sticky='ew', padx=(8, 12), pady=3)
        tk.Label(frame, text='分词符最大间隔', font=self.font_small, bg='#ffffff', fg='#475569').grid(row=2, column=2, sticky='w', pady=3)
        self.separator_max_delay_var = tk.StringVar(value=str(self.config["separator_max_delay"]))
        self.separator_max_delay_entry = ttk.Entry(frame, textvariable=self.separator_max_delay_var, style='App.TEntry', width=8)
        self.separator_max_delay_entry.grid(row=2, column=3, sticky='ew', padx=(8, 0), pady=3)
        tk.Label(frame, text='分词符', font=self.font_small, bg='#ffffff', fg='#475569').grid(row=3, column=0, sticky='w', pady=3)
        self.separators_var = tk.StringVar(value=self.config["separators"])
        self.separators_entry = ttk.Entry(frame, textvariable=self.separators_var, style='App.TEntry')
        self.separators_entry.grid(row=3, column=1, columnspan=3, sticky='ew', padx=(8, 0), pady=3)
    
    def create_model_section(self, parent, row):
        frame = tk.Frame(parent, bg='#ffffff', highlightbackground='#e5e7eb', highlightthickness=1, padx=10, pady=4)
        frame.grid(row=row, column=0, sticky='ew', pady=(0, 6))
        frame.columnconfigure((0, 1, 2), weight=1, uniform='model')
        tk.Label(frame, text='输入模型', bg='#ffffff', fg='#17202a', font=('Microsoft YaHei UI', 10, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 2))
        self.model_vars = {}
        self.model_checks = {}
        for index, (key, label) in enumerate(MODEL_LABELS.items()):
            variable = tk.BooleanVar(value=self.config.get(key, MODEL_DEFAULTS[key]))
            check = ttk.Checkbutton(frame, text=label, variable=variable, style='App.TCheckbutton')
            check.grid(row=1 + index // 3, column=index % 3, sticky='w', pady=1)
            self.model_vars[key] = variable
            self.model_checks[key] = check
        self.guard_vars = {}
        self.guard_checks = {}
        for index, (key, label) in enumerate(GUARD_LABELS.items()):
            variable = tk.BooleanVar(value=self.config[key])
            check = ttk.Checkbutton(frame, text=label, variable=variable, style='App.TCheckbutton')
            check.grid(row=3 + index, column=0, columnspan=3, sticky='w', pady=(5 if index == 0 else 1, 1))
            self.guard_vars[key] = variable
            self.guard_checks[key] = check

    def create_hotkey_section(self, parent, row):
        frame = tk.Frame(parent, bg='#ffffff', highlightbackground='#e5e7eb', highlightthickness=1, padx=10, pady=6)
        frame.grid(row=row, column=0, sticky='ew', pady=(0, 6))
        tk.Label(frame, text='快捷键', bg='#ffffff', fg='#17202a', font=('Microsoft YaHei UI', 11, 'bold')).pack(anchor='w')

        self.hotkey_var = self.create_hotkey_row(frame, "开始/停止输入", "hotkey")
        self.pause_hotkey_var = self.create_hotkey_row(frame, "暂停/继续输入", "pause_hotkey")
    
    def create_hotkey_row(self, parent, label, config_key):
        row_frame = tk.Frame(parent, bg='#ffffff')
        row_frame.pack(fill=tk.X, pady=4)
        
        tk.Label(row_frame, text=label, font=self.font_small, anchor=tk.W,
                bg='#ffffff', fg='#475569').pack(side=tk.LEFT)
        
        var = tk.StringVar(value=self.config[config_key])
        
        entry_frame = tk.Frame(row_frame, bg='#f8fafc', highlightbackground='#dbe3ec', highlightthickness=1, padx=8, pady=3)
        entry_frame.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)
        
        tk.Label(entry_frame, textvariable=var, font=self.mono_font,
                bg='#f8fafc', fg='#111827').pack(anchor=tk.W)
        ttk.Button(row_frame, text='修改', command=lambda: self.start_set_hotkey(config_key), style='Secondary.TButton').pack(side=tk.LEFT)
        return var
    
    def create_tray_section(self, parent, row):
        frame = tk.Frame(parent, bg='#ffffff', highlightbackground='#e5e7eb', highlightthickness=1, padx=10, pady=6)
        frame.grid(row=row, column=0, sticky='ew', pady=(0, 6))
        frame.columnconfigure(0, weight=1)
        
        if HAS_PYSTRAY:
            self.hide_to_tray_var = tk.BooleanVar(value=self.config.get("hide_to_tray", True))
            ttk.Checkbutton(frame, text='关闭时隐藏到托盘', variable=self.hide_to_tray_var, command=self.on_tray_setting_change, style='App.TCheckbutton').grid(row=0, column=0, sticky='w')
        else:
            tk.Label(frame, text="托盘不可用", font=self.font_small, bg='#ffffff', fg='#94a3b8').grid(row=0, column=0, sticky='w')

        self.preview_font = tkfont.Font(root=self.root, font=self.font_small)
        self.clipboard_preview = tk.Text(
            frame, height=3, width=1, wrap='none', state=tk.DISABLED, takefocus=False,
            font=self.preview_font, bg='#f8fafc', fg='#475569', padx=8, pady=5,
            relief='flat', bd=0, highlightthickness=1, highlightbackground='#dbe3ec',
        )
        self.clipboard_preview.grid(row=1, column=0, sticky='ew', pady=(5, 0))
        self.clipboard_preview.bind('<Configure>', self.render_clipboard_preview)

    def render_clipboard_preview(self, event=None):
        preview = self.clipboard_preview
        inset = 2 * (int(preview.cget('padx')) + int(preview.cget('highlightthickness')))
        width = preview.winfo_width() - inset
        text = format_clipboard_preview(self.clipboard_text or '剪贴板为空', width, self.preview_font.measure)
        preview.configure(state=tk.NORMAL)
        preview.delete('1.0', tk.END)
        preview.insert('1.0', text)
        preview.configure(state=tk.DISABLED)

    def set_clipboard_text(self, text):
        ready = len(text.strip()) > CLIPBOARD_READY_LENGTH
        if ready != self.clipboard_ready:
            self.clipboard_ready = ready
            if not self.is_typing:
                self.update_tray_state()
        preview_text = ' '.join(text.split())
        if preview_text != self.clipboard_text:
            self.clipboard_text = preview_text
            self.render_clipboard_preview()

    def read_clipboard_for_preview(self, sequence):
        try:
            # CF_UNICODETEXT is also available when Windows can convert plain text to Unicode.
            if sys.platform == 'win32' and not ctypes.windll.user32.IsClipboardFormatAvailable(13):
                text = ''
            else:
                text = load_pyperclip().paste()
        except (ImportError, OSError, RuntimeError):
            text = None
        self.clipboard_results.put((sequence, text))

    def poll_clipboard(self):
        self.clipboard_poll_job = self.root.after(CLIPBOARD_POLL_MS, self.poll_clipboard)
        if self.clipboard_reading:
            try:
                sequence, text = self.clipboard_results.get_nowait()
            except Empty:
                return
            self.clipboard_reading = False
            if text is not None:
                self.clipboard_sequence = sequence
                self.set_clipboard_text(text)

        sequence = ctypes.windll.user32.GetClipboardSequenceNumber() if sys.platform == 'win32' else 0
        if not sequence or sequence != self.clipboard_sequence:
            self.clipboard_reading = True
            threading.Thread(target=self.read_clipboard_for_preview, args=(sequence,), daemon=True).start()
    
    def create_status_section(self, parent, row):
        frame = tk.Frame(parent, bg='#17202a', highlightbackground='#17202a', highlightthickness=1, padx=10, pady=6)
        frame.grid(row=row, column=0, sticky='ew', pady=(0, 6))
        self.status_var = tk.StringVar(value="✓ 就绪")
        self.status_label = tk.Label(frame, textvariable=self.status_var, 
                                     font=self.font_small, bg='#17202a', fg='#d7e2ef',
                                     wraplength=460, justify=tk.LEFT)
        self.status_label.pack(anchor=tk.W)
    
    def create_button_section(self, parent, row):
        frame = tk.Frame(parent, bg='#f7f8fa')
        frame.grid(row=row, column=0, sticky='ew')
        frame.columnconfigure((0, 1), weight=1, uniform='actions')
        self.start_btn = ttk.Button(frame, text='开始输入', command=self.toggle_typing, style='Primary.TButton')
        self.start_btn.grid(row=0, column=0, sticky='ew', padx=(0, 4))
        self.pause_btn = ttk.Button(frame, text='暂停输入', command=self.toggle_pause, state=tk.DISABLED, style='Secondary.TButton')
        self.pause_btn.grid(row=0, column=1, sticky='ew', padx=(4, 0))
        self.test_btn = ttk.Button(frame, text='复制测试文本', command=self.copy_test_text, style='Secondary.TButton')
        self.test_btn.grid(row=1, column=0, sticky='ew', padx=(0, 4), pady=(4, 0))
        self.topmost_btn = ttk.Button(frame, text='取消窗口置顶' if self.is_topmost else '窗口置顶', command=self.toggle_topmost, style='Secondary.TButton')
        self.topmost_btn.grid(row=1, column=1, sticky='ew', padx=(4, 0), pady=(4, 0))

    def setup_auto_save(self):
        for variable in (
            self.min_speed_var, self.max_speed_var,
            self.separator_min_delay_var, self.separator_max_delay_var,
            self.separators_var, *self.model_vars.values(), *self.guard_vars.values(),
        ):
            variable.trace_add('write', self.schedule_settings_save)

    def schedule_settings_save(self, *args):
        if self.is_saving_settings:
            return
        if self.settings_save_job is not None:
            self.root.after_cancel(self.settings_save_job)
        self.settings_save_job = self.root.after(400, self.save_settings)

    def flush_pending_settings(self):
        if self.settings_save_job is None:
            return self.settings_valid
        self.root.after_cancel(self.settings_save_job)
        self.settings_save_job = None
        return self.save_settings()

    def toggle_topmost(self):
        self.is_topmost = not self.is_topmost
        self.root.attributes('-topmost', self.is_topmost)
        self.topmost_btn.config(text='取消窗口置顶' if self.is_topmost else '窗口置顶')
        self.config['always_on_top'] = self.is_topmost
        self.save_config()
    
    def on_tray_setting_change(self):
        self.config["hide_to_tray"] = self.hide_to_tray_var.get()
        self.save_config()
        self.status_var.set("✓ 设置已保存")
    
    def start_set_hotkey(self, config_key):
        try:
            load_keyboard()
            if self.is_typing:
                self.stop_typing()
            if self.hook_handle is not None:
                keyboard.unhook(self.hook_handle)
            self.hotkey_var.set(self.config["hotkey"])
            self.pause_hotkey_var.set(self.config["pause_hotkey"])
            self.unregister_hotkeys()
            self.is_setting_hotkey = True
            self.setting_hotkey = config_key
            self.pressed_keys.clear()
            variable = self.hotkey_var if config_key == "hotkey" else self.pause_hotkey_var
            variable.set("录制中")
            self.status_var.set("⌨ 录制中")
            self.hook_handle = keyboard.hook(self.on_key_event)
        except Exception as e:
            print(f"录制快捷键失败: {e}")
            self.is_setting_hotkey = False
            self.setting_hotkey = None
            self.hook_handle = None
            self.hotkey_var.set(self.config["hotkey"])
            self.pause_hotkey_var.set(self.config["pause_hotkey"])
            self.register_hotkeys()
            self.status_var.set("⚠ 快捷键录制失败")
    
    def on_key_event(self, event):
        if not self.is_setting_hotkey or self.hook_handle is None:
            return
            
        name = (event.name or "").lower()
        aliases = {
            'left ctrl': 'ctrl', 'right ctrl': 'ctrl',
            'left alt': 'alt', 'right alt': 'alt',
            'left shift': 'shift', 'right shift': 'shift',
            'left windows': 'windows', 'right windows': 'windows', 'win': 'windows',
        }
        name = aliases.get(name, name)
        new_hotkey = None
        if event.event_type == keyboard.KEY_DOWN and name != 'esc':
            self.pressed_keys.add(name)
            return
        elif event.event_type == keyboard.KEY_UP:
            modifiers = ['ctrl', 'alt', 'shift', 'windows']
            normal_keys = sorted(self.pressed_keys.difference(modifiers))
            function_key = (
                len(normal_keys) == 1 and normal_keys[0].startswith('f')
                and normal_keys[0][1:].isdigit() and 1 <= int(normal_keys[0][1:]) <= 24
            )
            if not normal_keys or not (function_key or any(key in self.pressed_keys for key in modifiers)):
                self.pressed_keys.discard(name)
                return
            new_hotkey = '+'.join([key for key in modifiers if key in self.pressed_keys] + normal_keys[:1])
        elif name != 'esc':
            return

        keyboard.unhook(self.hook_handle)
        self.hook_handle = None
        config_key = self.setting_hotkey
        self.root.after(0, lambda: self.finish_set_hotkey(config_key, new_hotkey))

    def finish_set_hotkey(self, config_key, new_hotkey):
        other_key = "pause_hotkey" if config_key == "hotkey" else "hotkey"
        if new_hotkey == self.config[other_key]:
            self.status_var.set("⚠ 快捷键重复")
        elif new_hotkey is not None:
            self.config[config_key] = new_hotkey
            self.save_config()
            self.status_var.set("✓ 快捷键已保存")
        else:
            self.status_var.set("✓ 就绪")
        self.hotkey_var.set(self.config["hotkey"])
        self.pause_hotkey_var.set(self.config["pause_hotkey"])
        self.is_setting_hotkey = False
        self.setting_hotkey = None
        self.register_hotkeys()

    def unregister_hotkeys(self):
        for attr in ("toggle_hotkey_hook", "pause_hotkey_hook"):
            hook = getattr(self, attr)
            if hook is not None:
                keyboard.remove_hotkey(hook)
                setattr(self, attr, None)
    
    def register_hotkeys(self):
        try:
            load_keyboard()
            self.unregister_hotkeys()
            self.toggle_hotkey_hook = keyboard.add_hotkey(
                self.config["hotkey"],
                lambda: self.root.after(0, self.toggle_typing),
                suppress=True, trigger_on_release=True,
            )
            self.pause_hotkey_hook = keyboard.add_hotkey(
                self.config["pause_hotkey"],
                lambda: self.root.after(0, self.toggle_pause),
                suppress=True, trigger_on_release=True,
            )
            return True
        except Exception as e:
            error_msg = str(e)
            print(f"注册快捷键失败: {error_msg}")
            self.status_var.set("⚠ 快捷键不可用")
            return False

    def toggle_typing(self):
        if self.is_setting_hotkey:
            return
        if self.is_typing:
            self.stop_typing()
        else:
            self.start_typing()

    def toggle_pause(self):
        with self.typing_condition:
            if not self.is_typing or self.is_setting_hotkey:
                return
            was_paused = self.is_paused
            stop_event = self.stop_event
        target = self.target_window
        if was_paused:
            reason, target = self.validate_resume_window()
            if reason:
                previous_reason = self.pause_reason
                self.pause_reason = reason
                self.show_window_pause(self.stop_event, reason, notify=reason != previous_reason)
                return
        with self.typing_condition:
            if stop_event is not self.stop_event or self.is_paused != was_paused:
                return
            if self.target_window is None:
                self.target_window = target
            self.is_paused = not was_paused
            self.pause_reason = None
            self.typing_condition.notify_all()
        self.pause_btn.config(text="继续输入" if self.is_paused else "暂停输入")
        self.status_var.set("⏸ 已暂停" if self.is_paused else "▶ 正在输入")
        self.update_tray_state()

    def validate_resume_window(self):
        if not any(self.guard_settings.values()):
            return None, None
        state = inspect_foreground_window()
        if self.guard_settings['block_untypable_windows'] and state.blocked_reason:
            return state.blocked_reason, None
        if (self.guard_settings['pause_on_focus_loss'] and self.target_window is not None
                and state.window != self.target_window):
            return '请返回原输入窗口', None
        return None, state.window

    def focus_loss_reason(self):
        if (self.guard_settings['pause_on_focus_loss'] and self.target_window is not None
                and foreground_window() != self.target_window):
            return '已离开原输入窗口'
        return None

    def pause_for_window(self, stop_event, reason):
        with self.typing_condition:
            if stop_event is not self.stop_event or stop_event.is_set() or not self.is_typing or self.is_paused:
                return
            self.is_paused = True
            self.pause_reason = reason
            self.typing_condition.notify_all()
        self.root.after(0, lambda: self.show_window_pause(stop_event, reason))

    def show_window_pause(self, stop_event, reason, notify=True):
        if (stop_event is not self.stop_event or not self.is_typing or not self.is_paused
                or self.pause_reason != reason):
            return
        self.pause_btn.config(text='继续输入')
        self.status_var.set(f'⏸ {reason}')
        self.update_tray_state()
        if notify and self.tray_icon is not None:
            try:
                self.tray_icon.notify(reason, f'{APP_NAME} · 已暂停')
            except Exception as e:
                print(f'托盘通知失败: {e}')

    def monitor_focus(self, stop_event):
        if stop_event is not self.stop_event:
            return
        self.focus_monitor_job = None
        if not self.is_typing or stop_event.is_set():
            return
        if not self.is_paused:
            reason = self.focus_loss_reason()
            if reason:
                self.pause_for_window(stop_event, reason)
        self.focus_monitor_job = self.root.after(50, lambda: self.monitor_focus(stop_event))

    def cancel_focus_monitor(self):
        if self.focus_monitor_job is not None:
            self.root.after_cancel(self.focus_monitor_job)
            self.focus_monitor_job = None
    
    def start_typing(self):
        if self.is_typing or self.is_setting_hotkey:
            return
        if not self.flush_pending_settings():
            return
        load_pyperclip()
            
        try:
            text = pyperclip.paste()
        except:
            text = ""
            
        if not text:
            self.status_var.set("⚠ 剪贴板为空")
            return

        self.guard_settings = {key: bool(self.config.get(key, default)) for key, default in GUARD_DEFAULTS.items()}
        state = inspect_foreground_window() if any(self.guard_settings.values()) else None
        self.pause_reason = state.blocked_reason if state and self.guard_settings['block_untypable_windows'] else None
        self.target_window = state.window if state and self.pause_reason is None else None
        
        with self.typing_condition:
            self.stop_event = threading.Event()
            self.is_typing = True
            self.is_paused = self.pause_reason is not None
        self.start_btn.config(text="停止输入", style='Danger.TButton')
        self.pause_btn.config(state=tk.NORMAL, text="暂停输入")
        self.status_var.set("▶ 正在输入")
        self.update_input_settings_state()
        self.update_tray_state()
        if self.pause_reason:
            self.show_window_pause(self.stop_event, self.pause_reason)
        self.cancel_focus_monitor()
        if self.guard_settings['pause_on_focus_loss']:
            self.focus_monitor_job = self.root.after(50, lambda event=self.stop_event: self.monitor_focus(event))
        
        self.typing_thread = threading.Thread(target=self.type_text, args=(text, self.stop_event), daemon=True)
        self.typing_thread.start()
    
    def wait_for_typing(self, delay, stop_event):
        remaining = delay
        with self.typing_condition:
            while not stop_event.is_set():
                if self.is_paused:
                    self.typing_condition.wait()
                elif remaining <= 0:
                    return True
                else:
                    started = time.monotonic()
                    self.typing_condition.wait(remaining)
                    remaining -= time.monotonic() - started
        return False

    def send_typing_input(self, send, value, stop_event):
        while not stop_event.is_set():
            with self.typing_condition:
                self.typing_condition.wait_for(lambda: not self.is_paused or stop_event.is_set())
                if stop_event.is_set():
                    break
                reason = self.focus_loss_reason()
                if not reason:
                    send(value)
                    return True
            self.pause_for_window(stop_event, reason)
        return False

    def type_text(self, text, stop_event):
        completed = False
        error_message = None
        try:
            with self.typing_condition:
                self.typing_condition.wait_for(lambda: not self.is_paused or stop_event.is_set())
                if stop_event.is_set():
                    return
            load_keyboard()
            settings = self.config.copy()
            rhythm = TypingRhythm(text, settings)
            pairs = find_symbol_pairs(text)
            closing_indexes = set(pairs.values())
            # 逐字符按文本写入，避免 @、大写字母等字符被当作按键名解析
            write = partial(keyboard.write, delay=0, exact=True)

            def move_caret(direction):
                state = keyboard.stash_state()
                try:
                    keyboard.press_and_release(direction)
                finally:
                    keyboard.restore_modifiers(state)
            
            # 释放所有修饰键，避免影响输入
            for key in ['alt', 'ctrl', 'shift', 'win']:
                if stop_event.is_set():
                    return
                if keyboard.is_pressed(key):
                    keyboard.release(key)
                    if not self.wait_for_typing(0.1, stop_event):
                        return
            
            index = 0
            while index < len(text):
                symbol = text[index]
                direction = None
                if index in pairs or index in closing_indexes:
                    symbol = pair_symbol_at(text, index)
                if index in pairs:
                    delimiters = symbol + PAIR_ENDS[symbol]
                    for offset, char in enumerate(delimiters):
                        if offset:
                            delay = rhythm.character_delay(delimiters[offset - 1], char)
                            if not self.wait_for_typing(delay + PAIR_SYMBOL_EXTRA_DELAY, stop_event):
                                return
                        if not self.send_typing_input(write, char, stop_event):
                            return
                    direction = 'left'
                elif index in closing_indexes:
                    direction = 'right'
                elif not self.send_typing_input(write, symbol, stop_event):
                    return

                if direction:
                    if not self.wait_for_typing(PAIR_CARET_DELAY, stop_event):
                        return
                    for _ in symbol:
                        if not self.send_typing_input(move_caret, direction, stop_event):
                            return

                index += len(symbol)
                if index < len(text) and not self.wait_for_typing(rhythm.delay_after(index - 1), stop_event):
                    return
            completed = not stop_event.is_set()
        except Exception as e:
            error_message = str(e)
        finally:
            self.root.after(0, lambda: self.finish_typing(stop_event, completed, error_message))

    def finish_typing(self, stop_event, completed, error_message):
        if stop_event is not self.stop_event:
            return
        self.is_typing = False
        self.is_paused = False
        self.pause_reason = None
        self.target_window = None
        self.cancel_focus_monitor()
        self.start_btn.config(text="开始输入", style='Primary.TButton')
        self.pause_btn.config(state=tk.DISABLED, text="暂停输入")
        self.update_input_settings_state()
        self.update_tray_state()
        if error_message is not None:
            self.status_var.set(f"⚠ 输入错误: {error_message}")
        elif completed:
            self.status_var.set("✓ 输入完成")
    
    def stop_typing(self):
        with self.typing_condition:
            self.stop_event.set()
            self.is_typing = False
            self.is_paused = False
            self.typing_condition.notify_all()
        self.status_var.set("⏹ 已停止")
        self.pause_reason = None
        self.target_window = None
        self.cancel_focus_monitor()
        self.start_btn.config(text="开始输入", style='Primary.TButton')
        self.pause_btn.config(state=tk.DISABLED, text="暂停输入")
        self.update_input_settings_state()
        self.update_tray_state()
    
    def copy_test_text(self):
        load_pyperclip()
        pyperclip.copy(TEST_TEXT)
        self.status_var.set("✓ 测试文本已复制")
    
    def save_settings(self):
        self.settings_save_job = None
        try:
            settings = {
                "min_speed": int(self.min_speed_var.get()),
                "max_speed": int(self.max_speed_var.get()),
                "separator_min_delay": int(self.separator_min_delay_var.get()),
                "separator_max_delay": int(self.separator_max_delay_var.get()),
            }
            if any(value < 0 for value in settings.values()):
                raise ValueError
            settings['input_speed'] = normalize_input_speed(self.input_speed_var.get())
            settings.update({key: variable.get() for key, variable in self.model_vars.items()})
            settings.update({key: variable.get() for key, variable in self.guard_vars.items()})
            settings["separators"] = self.separators_var.get()
            if HAS_PYSTRAY:
                settings["hide_to_tray"] = self.hide_to_tray_var.get()
            
            self.is_saving_settings = True
            for lower, upper in (("min_speed", "max_speed"), ("separator_min_delay", "separator_max_delay")):
                if settings[lower] > settings[upper]:
                    settings[lower], settings[upper] = settings[upper], settings[lower]
                    getattr(self, lower + '_var').set(str(settings[lower]))
                    getattr(self, upper + '_var').set(str(settings[upper]))
            
            self.config.update(settings)
            profile = speed_profile(settings['input_speed'])
            custom = any(settings[key] != profile[key] for key in INTERVAL_DEFAULTS)
            self.speed_label_var.set('自定义' if custom else str(profile['input_speed']))
            if not self.save_config():
                self.settings_valid = False
                return False
            self.settings_valid = True
            if not self.is_typing and not self.is_setting_hotkey:
                self.status_var.set("✓ 设置已保存")
            return True
        except ValueError:
            self.settings_valid = False
            self.status_var.set("⚠ 间隔须为非负整数")
            return False
        finally:
            self.is_saving_settings = False
    
    def create_tray_icon(self):
        pystray_module, Image = load_tray()
        for state in TRAY_TITLES:
            with Image.open(resource_path(f'assets/tray-{state}.png')) as image:
                self.tray_images[state] = image.copy()
        
        return pystray_module.Icon(
            APP_NAME,
            self.tray_images['idle'],
            APP_NAME,
            menu=pystray_module.Menu(
                pystray_module.MenuItem("显示主窗口", self.show_window, default=True),
                pystray_module.MenuItem("开始/停止输入", lambda icon, item: self.root.after(0, self.toggle_typing)),
                pystray_module.MenuItem("暂停/继续输入", lambda icon, item: self.root.after(0, self.toggle_pause), enabled=lambda item: self.is_typing),
                pystray_module.Menu.SEPARATOR,
                pystray_module.MenuItem("退出", lambda icon, item: self.root.after(0, self.quit_app))
            )
        )

    def update_tray_state(self):
        if self.tray_icon is None:
            return
        if self.is_typing:
            state = 'paused' if self.is_paused else 'typing'
        else:
            state = 'ready' if self.clipboard_ready else 'idle'
        try:
            self.tray_icon.icon = self.tray_images[state]
            self.tray_icon.title = TRAY_TITLES[state]
            self.tray_icon.update_menu()
        except Exception as e:
            print(f"更新托盘状态失败: {e}")
    
    def setup_tray(self):
        self.tray_icon = self.create_tray_icon()
        self.update_tray_state()
        tray_thread = threading.Thread(target=self.run_tray, daemon=True)
        tray_thread.start()
    
    def run_tray(self):
        if self.tray_icon:
            self.tray_icon.run()
    
    def hide_to_tray(self):
        if HAS_PYSTRAY:
            self.is_hidden = True
            self.root.withdraw()
    
    def show_window(self, icon=None, item=None):
        self.is_hidden = False
        self.root.after(0, self.root.deiconify)
    
    def quit_app(self, icon=None, item=None):
        if self.clipboard_poll_job is not None:
            self.root.after_cancel(self.clipboard_poll_job)
        self.flush_pending_settings()
        self.stop_typing()
        try:
            keyboard.unhook_all()
        except:
            pass
        self.save_config()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)
    
    def on_closing(self):
        if HAS_PYSTRAY and self.tray_icon:
            if self.config.get("hide_to_tray", True):
                self.hide_to_tray()
            else:
                self.quit_app()
        else:
            self.quit_app()

def main():
    handle = acquire_instance()
    if sys.platform == 'win32' and handle is None:
        return
    try:
        if sys.platform == 'win32' and not is_admin():
            # 提权后的新进程接管互斥锁。
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
            handle = None
            if not run_as_admin():
                enable_dpi_awareness()
                root = tk.Tk()
                root.withdraw()
                messagebox.showwarning('权限不足', '需要管理员权限', parent=root)
                root.destroy()
            return
        run_app()
    finally:
        if handle is not None:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))

def run_app():
    enable_dpi_awareness()
    if sys.platform == 'win32':
        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = (ctypes.c_wchar_p,)
        set_app_id.restype = ctypes.c_long
        set_app_id('Copy2Input')
    root = tk.Tk()
    app = Copy2InputApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
