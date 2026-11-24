import ctypes
import importlib.util
import itertools
import json
import os
import queue
import random
import runpy
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import main
import window_guard
from window_guard import GUARD_DEFAULTS, WindowState
from typing_model import INTERVAL_DEFAULTS, MODEL_DEFAULTS, TypingRhythm, speed_profile


class AppTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows elevation')
    def test_frozen_elevation_resets_environment(self):
        for result in (42, 5, OSError('cancelled')):
            with self.subTest(result=result), patch.object(sys, 'frozen', True, create=True), patch.dict(
                os.environ, {'PYINSTALLER_RESET_ENVIRONMENT': 'original'}
            ):
                def elevate(*args):
                    self.assertEqual(os.environ['PYINSTALLER_RESET_ENVIRONMENT'], '1')
                    if isinstance(result, Exception):
                        raise result
                    return result

                with patch.object(ctypes.windll.shell32, 'ShellExecuteW', side_effect=elevate):
                    self.assertEqual(main.run_as_admin(), result == 42)
                self.assertEqual(os.environ['PYINSTALLER_RESET_ENVIRONMENT'], 'original')

    def test_layout_at_common_scales(self):
        main.enable_dpi_awareness()
        for scale, has_tray, advanced in itertools.product((1, 1.25, 1.5, 2), (False, True), (False, True)):
            with self.subTest(scale=scale, has_tray=has_tray, advanced=advanced):
                root = tk.Tk()
                root.withdraw()
                self.addCleanup(root.destroy)
                root.tk.call('tk', 'scaling', 96 * scale / 72)
                with patch.object(main.Copy2InputApp, 'initialize_background_features'), patch.object(
                    main.Copy2InputApp, 'load_config', return_value=main.DEFAULT_CONFIG.copy()
                ), patch.object(main, 'HAS_PYSTRAY', has_tray), patch.object(main.Copy2InputApp, 'save_config', return_value=True):
                    app = main.Copy2InputApp(root)
                    root.deiconify()
                    root.update()
                    if advanced:
                        app.advanced_mode_btn.invoke()
                        root.update()
                    self.assertEqual(root.title(), 'Copy2Input')
                    if scale == 1:
                        self.assertLessEqual(root.winfo_width(), 480)
                        preview_height = app.clipboard_preview.winfo_reqheight() + 5
                        self.assertLessEqual(root.winfo_height(), (670 if advanced else 440) + preview_height)
                    texts = []
                    pending = [root]
                    while pending:
                        parent = pending.pop()
                        for child in parent.winfo_children():
                            pending.append(child)
                            if child.winfo_ismapped():
                                self.assertLessEqual(child.winfo_x() + child.winfo_width(), parent.winfo_width() + 2)
                                self.assertLessEqual(child.winfo_y() + child.winfo_height(), parent.winfo_height() + 2)
                                if child.winfo_class() in ('Label', 'TLabel', 'TButton'):
                                    self.assertGreaterEqual(child.winfo_width(), child.winfo_reqwidth() - 2)
                                    texts.append(child.cget('text'))
                                    if child.cget('text') in ('开始/停止输入', '暂停/继续输入'):
                                        font = main.tkfont.Font(root=root, font=child.cget('font'))
                                        self.assertGreaterEqual(child.winfo_width(), font.measure(child.cget('text')) + 4)
                    self.assertIn('开始/停止输入', texts)
                    self.assertIn('暂停/继续输入', texts)
                    self.assertEqual(set(app.model_checks), set(MODEL_DEFAULTS))
                    for check in app.model_checks.values():
                        self.assertTrue(check.instate(['!disabled']))
                        self.assertEqual(bool(check.winfo_ismapped()), advanced)
                        if advanced:
                            self.assertGreaterEqual(check.winfo_width(), check.winfo_reqwidth() - 2)
                    self.assertEqual(bool(app.speed_scale.winfo_ismapped()), not advanced)
                    for key, check in app.guard_checks.items():
                        self.assertEqual(check.cget('text'), main.GUARD_LABELS[key])
                        self.assertEqual(bool(check.winfo_ismapped()), advanced)
                        self.assertTrue(check.instate(['!disabled']))
                        if advanced:
                            self.assertGreaterEqual(check.winfo_width(), check.winfo_reqwidth() - 2)
                    self.assertIn('简洁模式' if advanced else '高级模式', texts)
                    self.assertIn('输入间隔（毫秒）' if advanced else '输入速度', texts)
                    self.assertNotIn('输入速度' if advanced else '输入间隔（毫秒）', texts)
                    self.assertNotIn('Copy2Input', texts)
                    self.assertNotIn('保存设置', texts)
                    self.assertEqual([
                        app.start_btn.cget('text'), app.pause_btn.cget('text'),
                        app.test_btn.cget('text'), app.topmost_btn.cget('text'),
                    ], ['开始输入', '暂停输入', '复制测试文本', '窗口置顶'])
                    for text in texts:
                        self.assertNotIn('复制文本后', text)
                        self.assertNotIn('建议', text)
                        self.assertNotIn('更像人工', text)
                    self.assertTrue(app.separator_min_delay_entry.instate(['!disabled']))
                    self.assertTrue(app.separator_max_delay_entry.instate(['!disabled']))
                    self.assertTrue(app.min_speed_entry.instate(['!disabled']))
                    self.assertTrue(app.max_speed_entry.instate(['!disabled']))
                    self.assertFalse(hasattr(app, 'fixed_speed_var'))
                    self.assertFalse(hasattr(app, 'use_random_var'))
                    self.assertNotIn('固定间隔', texts)
                    app.flush_pending_settings()
                root.withdraw()

    def create_app(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(main, 'CONFIG_FILE', str(Path(directory) / 'config.json')))
        self.enterContext(patch.object(main, 'inspect_foreground_window', return_value=WindowState((101, 201))))
        self.enterContext(patch.object(main, 'foreground_window', return_value=(101, 201)))
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        with patch.object(main.Copy2InputApp, 'initialize_background_features'), patch.object(
            main.Copy2InputApp, 'load_config', return_value=main.DEFAULT_CONFIG.copy()
        ):
            app = main.Copy2InputApp(root)
            root.update_idletasks()
        self.addCleanup(app.flush_pending_settings)
        return root, app

    def test_clipboard_preview_uses_three_rows_and_adapts_to_window_width(self):
        root, app = self.create_app()
        root.deiconify()
        root.update()
        preview = app.clipboard_preview
        app.set_clipboard_text('少量文本')
        self.assertEqual(preview.get('1.0', 'end-1c'), '少量文本')
        app.set_clipboard_text('开头 ' + '中英文 mixed text ' * 80 + ' 结尾')
        narrow = preview.get('1.0', 'end-1c')
        root.geometry(f'{root.winfo_width() + 180}x{root.winfo_height()}')
        root.update()
        wide = preview.get('1.0', 'end-1c')
        self.assertEqual(int(preview.cget('height')), 3)
        self.assertEqual(preview.cget('state'), tk.DISABLED)
        for text in (narrow, wide):
            lines = text.splitlines()
            self.assertEqual(len(lines), 3)
            self.assertIn('...', lines[1])
            self.assertTrue(lines[0].startswith('开头 '))
            self.assertTrue(lines[-1].endswith(' 结尾'))
        self.assertGreater(len(wide), len(narrow))
        app.set_clipboard_text('')
        self.assertEqual(preview.get('1.0', 'end-1c'), '剪贴板为空')

    def test_clipboard_poll_retries_contention_and_skips_unchanged_text(self):
        if sys.platform != 'win32':
            self.skipTest('Windows clipboard sequence numbers')
        _, app = self.create_app()
        clipboard = Mock()
        clipboard.paste.side_effect = [RuntimeError('clipboard busy'), 'long clipboard text ' * 2]
        user32 = Mock()
        user32.GetClipboardSequenceNumber.return_value = 10
        user32.IsClipboardFormatAvailable.return_value = True
        with patch.object(app.root, 'after'), patch.object(main.ctypes, 'windll', SimpleNamespace(user32=user32)), patch.object(
            main, 'load_pyperclip', return_value=clipboard
        ), patch.object(main.threading, 'Thread', side_effect=lambda target, args, daemon:
                        SimpleNamespace(start=lambda: target(*args))):
            app.poll_clipboard()
            app.poll_clipboard()
            app.poll_clipboard()
            self.assertTrue(app.clipboard_ready)
            self.assertEqual(app.clipboard_text, 'long clipboard text long clipboard text')
            app.poll_clipboard()
            self.assertEqual(clipboard.paste.call_count, 2)
            user32.GetClipboardSequenceNumber.return_value = 11
            user32.IsClipboardFormatAvailable.return_value = False
            app.poll_clipboard()
            app.poll_clipboard()
            self.assertFalse(app.clipboard_ready)
            self.assertEqual(app.clipboard_text, '')
            self.assertEqual(clipboard.paste.call_count, 2)

    def test_auto_save_coalesces_edits(self):
        root, app = self.create_app()
        with patch.object(app, 'save_config', wraps=app.save_config) as save:
            app.min_speed_var.set('70')
            app.max_speed_var.set('170')
            app.separator_min_delay_var.set('250')
            app.separator_max_delay_var.set('450')
            app.separators_var.set(' ,._')
            root.after(550, root.quit)
            root.mainloop()
            save.assert_called_once()
        saved = json.loads(Path(main.CONFIG_FILE).read_text(encoding='utf-8'))
        self.assertEqual(saved['min_speed'], 70)
        self.assertEqual(saved['separator_min_delay'], 250)
        self.assertEqual(saved['separator_max_delay'], 450)
        self.assertEqual(saved['separators'], ' ,._')
        self.assertNotIn('use_random_speed', saved)
        self.assertNotIn('fixed_speed', saved)
        self.assertIsNone(app.settings_save_job)

    def test_speed_slider_updates_intervals_and_preserves_feature_selections(self):
        root, app = self.create_app()
        app.model_vars['model_bigrams'].set(False)
        app.separators_var.set(' ,;')
        for level in (0, 25, 50, 75, 100):
            with self.subTest(level=level):
                app.speed_scale.set(level)
                self.assertEqual(app.speed_label_var.get(), str(level))
                for key in INTERVAL_DEFAULTS:
                    self.assertEqual(int(getattr(app, key + '_var').get()), speed_profile(level)[key])
                self.assertTrue(app.flush_pending_settings())
                self.assertEqual(app.config['input_speed'], level)
                self.assertFalse(app.config['model_bigrams'])
                self.assertEqual(app.config['separators'], ' ,;')
                self.assertEqual(app.load_config(), app.config)

    def test_settings_modes_preserve_custom_values_and_shrink_on_return(self):
        root, app = self.create_app()
        root.deiconify()
        root.update()
        self.assertFalse(app.advanced_mode)
        simple_height = root.winfo_height()
        app.advanced_mode_btn.invoke()
        root.update()
        self.assertTrue(app.advanced_mode)
        self.assertGreater(root.winfo_height(), simple_height)
        app.min_speed_var.set('73')
        app.separator_max_delay_var.set('637')
        app.model_vars['model_shift_digits'].set(False)
        app.simple_mode_btn.invoke()
        root.update()
        self.assertFalse(app.advanced_mode)
        self.assertEqual(root.winfo_height(), simple_height)
        self.assertEqual(app.config['min_speed'], 73)
        self.assertEqual(app.config['separator_max_delay'], 637)
        self.assertFalse(app.config['model_shift_digits'])
        self.assertEqual(app.speed_label_var.get(), '自定义')
        saved = app.config.copy()
        app.advanced_mode_btn.invoke()
        app.simple_mode_btn.invoke()
        self.assertEqual(app.config, saved)
        # Opening the app again always starts in simple mode, including custom settings.
        with patch.object(main.Copy2InputApp, 'load_config', return_value=saved):
            second_root = tk.Tk()
            second_root.withdraw()
            self.addCleanup(second_root.destroy)
            with patch.object(main.Copy2InputApp, 'initialize_background_features'):
                second = main.Copy2InputApp(second_root)
                second_root.update_idletasks()
            self.assertFalse(second.advanced_mode)
            self.assertEqual(second.config, saved)
            self.assertEqual(second.speed_label_var.get(), '自定义')

    def test_invalid_advanced_edit_remains_visible_until_corrected(self):
        root, app = self.create_app()
        app.advanced_mode_btn.invoke()
        app.min_speed_var.set('')
        app.simple_mode_btn.invoke()
        self.assertTrue(app.advanced_mode)
        self.assertEqual(app.status_var.get(), '⚠ 间隔须为非负整数')
        app.simple_mode_btn.invoke()
        self.assertTrue(app.advanced_mode)
        app.min_speed_var.set('60')
        app.simple_mode_btn.invoke()
        self.assertFalse(app.advanced_mode)

    def test_typing_locks_settings_but_allows_mode_switches_and_pause(self):
        root, app = self.create_app()
        root.deiconify()
        root.update()
        settings = app.config.copy()
        clipboard = Mock()
        clipboard.paste.return_value = 'typing text'
        with patch.object(main, 'load_pyperclip'), patch.object(main, 'pyperclip', clipboard), patch.object(
            main.threading, 'Thread'
        ):
            app.start_typing()
        self.assertTrue(app.is_typing)

        def check_locked():
            self.assertTrue(all(control.instate(['disabled']) for control in app.input_setting_controls))
            self.assertTrue(app.advanced_mode_btn.instate(['!disabled']))
            self.assertTrue(app.simple_mode_btn.instate(['!disabled']))

        check_locked()
        app.speed_scale.set(90)
        self.assertEqual(app.input_speed_var.get(), settings['input_speed'])
        app.advanced_mode_btn.invoke()
        root.update()
        self.assertTrue(app.advanced_mode)
        check_locked()
        for key in (*INTERVAL_DEFAULTS, 'separators'):
            entry = getattr(app, key + '_entry')
            entry.delete(0, tk.END)
            entry.insert(0, '9999')
            self.assertEqual(getattr(app, key + '_var').get(), str(settings[key]))
        for key, check in (app.model_checks | app.guard_checks).items():
            check.invoke()
            self.assertEqual((app.model_vars | app.guard_vars)[key].get(), settings[key])
        app.toggle_pause()
        self.assertTrue(app.is_paused)
        check_locked()
        app.simple_mode_btn.invoke()
        root.update()
        self.assertFalse(app.advanced_mode)
        check_locked()
        app.toggle_pause()
        check_locked()
        self.assertEqual(app.config, settings)
        app.stop_typing()
        self.assertTrue(all(control.instate(['!disabled']) for control in app.input_setting_controls))
        app.speed_scale.set(75)
        self.assertEqual(app.input_speed_var.get(), 75)

    def test_completion_and_error_unlock_settings_but_stale_completion_does_not(self):
        root, app = self.create_app()
        for completed, error in ((True, None), (False, 'write failed')):
            with self.subTest(completed=completed):
                app.is_typing = True
                app.update_input_settings_state()
                app.finish_typing(threading.Event(), True, None)
                self.assertTrue(all(control.instate(['disabled']) for control in app.input_setting_controls))
                app.finish_typing(app.stop_event, completed, error)
                self.assertTrue(all(control.instate(['!disabled']) for control in app.input_setting_controls))

    def test_invalid_edit_keeps_last_saved_settings(self):
        root, app = self.create_app()
        app.min_speed_var.set('90')
        self.assertTrue(app.flush_pending_settings())
        saved = Path(main.CONFIG_FILE).read_bytes()
        with patch.object(main.messagebox, 'showerror') as popup:
            app.separator_min_delay_var.set('')
            root.after(550, root.quit)
            root.mainloop()
            self.assertEqual(Path(main.CONFIG_FILE).read_bytes(), saved)
            popup.assert_not_called()
        app.separator_min_delay_var.set('500')
        app.separator_max_delay_var.set('200')
        self.assertTrue(app.flush_pending_settings())
        self.assertEqual((app.config['separator_min_delay'], app.config['separator_max_delay']), (200, 500))
        self.assertEqual(app.separator_min_delay_var.get(), '200')
        self.assertIsNone(app.settings_save_job)

    def test_model_switches_auto_save_and_remain_available(self):
        root, app = self.create_app()
        for key, check in app.model_checks.items():
            self.assertTrue(app.model_vars[key].get())
            check.invoke()
            self.assertFalse(app.model_vars[key].get())
        root.after(550, root.quit)
        root.mainloop()
        saved = json.loads(Path(main.CONFIG_FILE).read_text(encoding='utf-8'))
        self.assertTrue(all(saved[key] is False for key in MODEL_DEFAULTS))
        self.assertTrue(all(not variable.get() for variable in app.model_vars.values()))
        self.assertTrue(all(check.instate(['!disabled']) for check in app.model_checks.values()))
        self.assertTrue(app.flush_pending_settings())
        self.assertEqual({key: app.load_config()[key] for key in MODEL_DEFAULTS},
                         {key: False for key in MODEL_DEFAULTS})

    def test_window_guard_switches_save_independently_of_speed(self):
        root, app = self.create_app()
        for key, check in app.guard_checks.items():
            self.assertTrue(app.guard_vars[key].get())
            check.invoke()
        app.speed_scale.set(75)
        self.assertTrue(app.flush_pending_settings())
        self.assertTrue(all(app.config[key] is False for key in GUARD_DEFAULTS))
        self.assertTrue(all(app.load_config()[key] is False for key in GUARD_DEFAULTS))

    def test_topmost_button_toggles_and_saves(self):
        root, app = self.create_app()
        app.topmost_btn.invoke()
        self.assertTrue(root.attributes('-topmost'))
        self.assertEqual(app.topmost_btn.cget('text'), '取消窗口置顶')
        self.assertTrue(app.load_config()['always_on_top'])
        app.topmost_btn.invoke()
        self.assertFalse(root.attributes('-topmost'))
        self.assertEqual(app.topmost_btn.cget('text'), '窗口置顶')
        self.assertFalse(app.load_config()['always_on_top'])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows window icons')
    def test_current_window_has_small_and_large_icons_after_restore(self):
        from ctypes import wintypes
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user.GetAncestor.restype = wintypes.HWND
        user.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user.SendMessageW.restype = ctypes.c_ssize_t
        root, app = self.create_app()

        def check_icons():
            root.update()
            hwnd = user.GetAncestor(root.winfo_id(), 2)
            for kind in (0, 1):  # ICON_SMALL / ICON_BIG: caption and taskbar.
                self.assertNotEqual(user.SendMessageW(hwnd, 0x007f, kind, 0), 0)

        root.deiconify()
        check_icons()
        app.topmost_btn.invoke()
        check_icons()
        root.withdraw()
        root.deiconify()
        check_icons()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows mutex')
    def test_single_instance_across_processes(self):
        name = 'Local\\Copy2Input.Test.' + uuid.uuid4().hex
        with patch.object(main, 'INSTANCE_MUTEX_NAME', name):
            handle = main.acquire_instance()
            self.assertIsNotNone(handle)
            try:
                code = (
                    'import main; '
                    f'main.INSTANCE_MUTEX_NAME = {name!r}; '
                    'assert main.acquire_instance() is None'
                )
                subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1], check=True, timeout=10)
            finally:
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
            handle = main.acquire_instance()
            self.assertIsNotNone(handle)
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


class InputTests(unittest.TestCase):
    def setUp(self):
        self.app = main.Copy2InputApp.__new__(main.Copy2InputApp)
        self.app.config = main.DEFAULT_CONFIG.copy()
        self.app.config.update(min_speed=80, max_speed=80)
        self.app.config.update({key: False for key in GUARD_DEFAULTS})
        self.app.is_typing = False
        self.app.is_paused = False
        self.app.is_setting_hotkey = False
        self.app.setting_hotkey = None
        self.app.settings_save_job = None
        self.app.is_saving_settings = False
        self.app.settings_valid = True
        self.app.is_topmost = False
        self.app.input_setting_controls = []
        self.app.speed_value_label = Mock()
        self.app.typing_condition = threading.Condition()
        self.app.stop_event = threading.Event()
        self.app.typing_thread = None
        self.app.guard_settings = {key: False for key in GUARD_DEFAULTS}
        self.app.target_window = None
        self.app.pause_reason = None
        self.app.focus_monitor_job = None
        self.app.tray_icon = None
        self.app.tray_images = {state: object() for state in main.TRAY_TITLES}
        self.app.clipboard_text = ''
        self.app.clipboard_ready = False
        self.app.toggle_hotkey_hook = None
        self.app.pause_hotkey_hook = None
        self.app.hook_handle = None
        self.app.pressed_keys = set()
        self.callbacks = queue.Queue()
        self.app.root = Mock()
        self.app.root.after.side_effect = lambda delay, callback: self.callbacks.put(callback) if delay == 0 else 'monitor'
        for attr in ('start_btn', 'pause_btn', 'topmost_btn', 'status_var', 'hotkey_var', 'pause_hotkey_var'):
            setattr(self.app, attr, Mock())
        self.keyboard = Mock(KEY_DOWN='down', KEY_UP='up')
        self.keyboard.is_pressed.return_value = False
        self.keyboard.add_hotkey.side_effect = lambda hotkey, callback, **options: hotkey
        self.clipboard = Mock()
        self.clipboard.paste.return_value = 'ab'
        self.enterContext(patch.object(main, 'keyboard', self.keyboard))
        self.enterContext(patch.object(main, 'pyperclip', self.clipboard))

    def tearDown(self):
        self.app.stop_typing()
        if self.app.typing_thread is not None:
            self.app.typing_thread.join(timeout=1)

    def flush_callbacks(self):
        while not self.callbacks.empty():
            self.callbacks.get_nowait()()

    def test_character_and_separator_delays(self):
        text = 'A@ ,._，b\n\u4e2d\u6587\U0001f642'
        for separators in (main.DEFAULT_CONFIG['separators'], '@', ''):
            with self.subTest(separators=separators):
                self.app.config.update(separators=separators)
                self.keyboard.write.reset_mock()
                with patch.object(self.app, 'wait_for_typing', return_value=True) as wait:
                    self.app.type_text(text, self.app.stop_event)
                self.assertEqual(wait.call_count, len(text) - 1)
                for args in wait.call_args_list:
                    self.assertGreaterEqual(args.args[0], 0)
                    self.assertLessEqual(args.args[0], self.app.config['separator_max_delay'] / 1000)
                    self.assertIs(args.args[1], self.app.stop_event)
                self.assertEqual(self.keyboard.write.call_args_list, [call(char, delay=0, exact=True) for char in text])
                self.keyboard.press.assert_not_called()
                self.flush_callbacks()
                self.app.status_var.set.assert_called_with('✓ 输入完成')

    def test_only_model_delay_is_waited_between_characters(self):
        with patch.object(main, 'TypingRhythm') as model, patch.object(
            self.app, 'wait_for_typing', return_value=True
        ) as wait:
            model.return_value.delay_after.side_effect = [0.023, 0.3, 0.017]
            self.app.type_text('abcd', self.app.stop_event)
        self.assertEqual(wait.call_args_list, [call(delay, self.app.stop_event)
                                              for delay in (0.023, 0.3, 0.017)])
        self.assertEqual(self.keyboard.write.call_args_list,
                         [call(char, delay=0, exact=True) for char in 'abcd'])

    def test_symbol_pairs_write_delimiters_then_move_caret_through_nested_content(self):
        text = 'a{[（“\'x\'”）]}z'
        self.app.config.update(min_speed=60, max_speed=140, separators='{[（“\'')
        output = Mock()
        output.attach_mock(self.keyboard, 'keyboard')
        with patch.object(self.app, 'wait_for_typing', return_value=True) as wait:
            output.attach_mock(wait, 'wait')
            self.app.type_text(text, self.app.stop_event)
        events = [event for event in self.keyboard.method_calls
                  if event[0] in ('write', 'press_and_release')]
        expected = [call.write('a', delay=0, exact=True)]
        for opening, closing in ('{}', '[]', '（）', '“”', "''"):
            expected.extend((call.write(opening, delay=0, exact=True),
                             call.write(closing, delay=0, exact=True),
                             call.press_and_release('left')))
        expected.append(call.write('x', delay=0, exact=True))
        expected.extend([call.press_and_release('right')] * 5)
        expected.append(call.write('z', delay=0, exact=True))
        self.assertEqual(events, expected)
        self.assertEqual(wait.call_count, len(text) - 1 + 3 * 5)
        for opening, closing in ('{}', '[]', '（）', '“”', "''"):
            index = output.mock_calls.index(call.keyboard.write(opening, delay=0, exact=True))
            name, args, _ = output.mock_calls[index + 1]
            self.assertEqual(name, 'wait')
            self.assertGreaterEqual(args[0], 0.06 + main.PAIR_SYMBOL_EXTRA_DELAY)
            self.assertLessEqual(args[0], 0.14 + main.PAIR_SYMBOL_EXTRA_DELAY)
            self.assertEqual(output.mock_calls[index + 2], call.keyboard.write(closing, delay=0, exact=True))

    def test_triple_single_quotes_wait_between_symbols_and_before_both_caret_moves(self):
        self.app.config.update(min_speed=70, max_speed=70, separators='')
        output = Mock()
        output.attach_mock(self.keyboard, 'keyboard')
        with patch.object(self.app, 'wait_for_typing', return_value=True) as wait:
            output.attach_mock(wait, 'wait')
            self.app.type_text("'''x'''", self.app.stop_event)

        events = [event for event in output.mock_calls
                  if event[0] in ('keyboard.write', 'keyboard.press_and_release', 'wait')]
        quote = call.keyboard.write("'", delay=0, exact=True)
        symbol_wait = call.wait(0.07 + main.PAIR_SYMBOL_EXTRA_DELAY, self.app.stop_event)
        caret_wait = call.wait(main.PAIR_CARET_DELAY, self.app.stop_event)
        content_wait = call.wait(0.07, self.app.stop_event)
        self.assertEqual(events, [
            quote, *[symbol_wait, quote] * 5,
            caret_wait, *[call.keyboard.press_and_release('left')] * 3,
            content_wait, call.keyboard.write('x', delay=0, exact=True), content_wait,
            caret_wait, *[call.keyboard.press_and_release('right')] * 3,
        ])

    def test_stop_between_paired_symbols_leaves_the_closing_symbol_unsent(self):
        def stop_during_wait(delay, stop_event):
            stop_event.set()
            return False

        with patch.object(self.app, 'wait_for_typing', side_effect=stop_during_wait):
            self.app.type_text('(x)', self.app.stop_event)
        self.keyboard.write.assert_called_once_with('(', delay=0, exact=True)
        self.keyboard.press_and_release.assert_not_called()

    def test_symbol_pair_detection_leaves_apostrophes_escapes_and_distant_symbols_literal(self):
        limit = main.MAX_PAIR_CONTENT_LENGTH
        for text, pairs in (
            ('""', {0: 1}),
            ('(' + 'x' * limit + ')', {0: limit + 1}),
            ('(' + 'x' * (limit + 1) + ')', {}),
            ("''''''", {0: 3}),
            ("('''a''')", {0: 8, 1: 5}),
            ("'''It's ok\nnext line'''", {0: 20}),
            ("'''" + 'x' * limit + "'''", {0: limit + 3}),
            ("'''" + 'x' * (limit + 1) + "'''", {}),
            ("'''open", {}),
            ('[open', {}),
            ("don't touch the dogs' toys", {}),
            ('甲‘乙’丙', {1: 3}),
            ('“don’t”', {0: 6}),
            ('(")")', {0: 4, 1: 3}),
            (r'"foo\"bar"', {0: 9}),
            (r'\(literal\)', {}),
            (r'\\(pair)', {2: 7}),
        ):
            with self.subTest(text=text):
                self.assertEqual(main.find_symbol_pairs(text), pairs)

    def test_tray_tracks_typing_pause_resume_stop_and_completion(self):
        self.app.tray_icon = Mock()
        self.app.config.update(min_speed=10000, max_speed=10000)

        def check(state, title):
            self.assertIs(self.app.tray_icon.icon, self.app.tray_images[state])
            self.assertEqual(self.app.tray_icon.title, title)

        self.app.start_typing()
        check('typing', 'Copy2Input · 正在输入')
        self.app.toggle_pause()
        check('paused', 'Copy2Input · 已暂停')
        self.app.toggle_pause()
        check('typing', 'Copy2Input · 正在输入')
        self.app.stop_typing()
        check('idle', 'Copy2Input')
        self.app.typing_thread.join(timeout=1)
        self.flush_callbacks()
        self.app.is_typing = True
        self.app.finish_typing(self.app.stop_event, True, None)
        check('idle', 'Copy2Input')
        self.app.is_typing = True
        self.app.is_paused = True
        self.app.finish_typing(self.app.stop_event, False, 'failed')
        check('idle', 'Copy2Input')

    def test_stale_completion_preserves_current_tray_status(self):
        self.app.tray_icon = Mock()
        self.app.is_typing = True
        self.app.is_paused = True
        self.app.update_tray_state()
        self.app.finish_typing(threading.Event(), True, None)
        self.assertIs(self.app.tray_icon.icon, self.app.tray_images['paused'])

    def test_tray_images_load_from_resources_and_keep_current_state(self):
        from PIL import Image
        tray = Mock()
        self.app.is_typing = True
        self.app.is_paused = True
        with patch.object(main, 'load_tray', return_value=(tray, Image)), patch.object(
            main.threading, 'Thread'
        ):
            self.app.setup_tray()
        for image in self.app.tray_images.values():
            self.assertEqual(image.size, (64, 64))
            self.assertEqual(image.mode, 'RGBA')
        colors = {'paused': (250, 204, 21, 255), 'typing': (239, 68, 68, 255), 'ready': (34, 197, 94, 255)}
        for state, color in colors.items():
            self.assertEqual(self.app.tray_images[state].getpixel((49, 15)), color)
            for point in ((59, 15), (49, 6)):
                actual = self.app.tray_images[state].getpixel(point)
                self.assertLessEqual(max(abs(channel - expected) for channel, expected in zip(actual, color)), 8)
        self.assertEqual(self.app.tray_images['idle'].getpixel((59, 15))[3], 0)
        self.assertEqual(self.app.tray_images['idle'].getpixel((49, 6))[3], 0)
        self.assertIs(self.app.tray_icon.icon, self.app.tray_images['paused'])
        self.assertEqual(self.app.tray_icon.title, 'Copy2Input · 已暂停')

    def test_tray_indicates_long_clipboard_only_when_idle(self):
        self.app.tray_icon = Mock()
        limit = main.CLIPBOARD_READY_LENGTH
        with patch.object(self.app, 'render_clipboard_preview'):
            self.app.update_tray_state()
            self.app.set_clipboard_text('x' * limit + ' ')
            self.assertIs(self.app.tray_icon.icon, self.app.tray_images['idle'])
            self.app.set_clipboard_text('x' * (limit + 1))
            self.assertIs(self.app.tray_icon.icon, self.app.tray_images['ready'])
            self.assertEqual(self.app.tray_icon.title, 'Copy2Input · 剪贴板就绪')
            self.app.is_typing = True
            self.app.update_tray_state()
            self.assertIs(self.app.tray_icon.icon, self.app.tray_images['typing'])
            self.app.toggle_pause()
            self.app.set_clipboard_text('longer ' * limit)
            self.assertIs(self.app.tray_icon.icon, self.app.tray_images['paused'])
            self.app.stop_typing()
            self.assertIs(self.app.tray_icon.icon, self.app.tray_images['ready'])
            self.app.set_clipboard_text('')
            self.assertIs(self.app.tray_icon.icon, self.app.tray_images['idle'])

    def test_tray_update_failure_does_not_interrupt_pause_or_stop(self):
        self.app.tray_icon = Mock()
        self.app.tray_icon.update_menu.side_effect = OSError('tray unavailable')
        self.app.is_typing = True
        self.app.toggle_pause()
        self.assertTrue(self.app.is_paused)
        self.app.stop_typing()
        self.assertTrue(self.app.stop_event.is_set())
        self.assertFalse(self.app.is_typing)

    def test_pause_resumes_original_text(self):
        self.app.config.update(min_speed=250, max_speed=250)
        first = threading.Event()
        second = threading.Event()
        self.keyboard.write.side_effect = lambda char, **options: (first if char == 'a' else second).set()
        self.app.toggle_typing()
        self.app.start_btn.config.assert_called_with(text='停止输入', style='Danger.TButton')
        self.assertTrue(first.wait(1))
        self.app.toggle_pause()
        self.assertTrue(self.app.is_paused)
        self.assertFalse(second.wait(0.15))
        self.clipboard.paste.return_value = 'changed clipboard'
        self.app.toggle_pause()
        self.assertFalse(self.app.is_paused)
        self.assertTrue(second.wait(1))
        self.app.typing_thread.join(timeout=1)
        self.assertFalse(self.app.typing_thread.is_alive())
        self.flush_callbacks()
        self.clipboard.paste.assert_called_once()
        self.assertEqual([args.args[0] for args in self.keyboard.write.call_args_list], ['a', 'b'])
        self.assertFalse(self.app.is_typing)
        self.app.start_btn.config.assert_called_with(text='开始输入', style='Primary.TButton')
        self.app.status_var.set.assert_called_with('✓ 输入完成')

    def test_focus_loss_before_next_character_pauses_and_resumes_original_progress(self):
        self.app.config.update(GUARD_DEFAULTS)
        self.app.tray_icon = Mock()
        original = (101, 201)
        other = (102, 202)
        with patch.object(main, 'inspect_foreground_window', return_value=WindowState(original)) as inspect, patch.object(
            main, 'foreground_window', return_value=original
        ) as foreground, patch.object(self.app, 'wait_for_typing', return_value=True):
            def write(char, **options):
                self.assertEqual(foreground.return_value, original)
                if char == 'a':
                    foreground.return_value = other
                    inspect.return_value = WindowState(other)

            self.keyboard.write.side_effect = write
            self.app.start_typing()
            with self.app.typing_condition:
                self.assertTrue(self.app.typing_condition.wait_for(lambda: self.app.is_paused, timeout=1))
            self.flush_callbacks()
            self.assertEqual(self.keyboard.write.call_args_list, [call('a', delay=0, exact=True)])
            self.app.status_var.set.assert_called_with('⏸ 已离开原输入窗口')
            self.assertIs(self.app.tray_icon.icon, self.app.tray_images['paused'])
            self.app.tray_icon.notify.assert_called_once()
            self.app.toggle_pause()
            self.assertTrue(self.app.is_paused)
            self.app.status_var.set.assert_called_with('⏸ 请返回原输入窗口')
            self.assertEqual(self.app.tray_icon.notify.call_count, 2)
            self.app.toggle_pause()
            self.assertEqual(self.app.tray_icon.notify.call_count, 2)
            self.clipboard.paste.return_value = 'changed clipboard'
            foreground.return_value = original
            inspect.return_value = WindowState(original)
            self.app.toggle_pause()
            self.app.typing_thread.join(timeout=1)
            self.assertFalse(self.app.typing_thread.is_alive())
        self.flush_callbacks()
        self.assertEqual(self.keyboard.write.call_args_list, [call(char, delay=0, exact=True) for char in 'ab'])
        self.clipboard.paste.assert_called_once()
        self.assertFalse(self.app.is_typing)
        self.app.status_var.set.assert_called_with('✓ 输入完成')

    def test_focus_loss_after_pair_insertion_pauses_before_moving_caret(self):
        self.app.config.update(GUARD_DEFAULTS)
        self.clipboard.paste.return_value = '(x)'
        original, other = (101, 201), (102, 202)
        with patch.object(main, 'inspect_foreground_window', return_value=WindowState(original)), patch.object(
            main, 'foreground_window', return_value=original
        ) as foreground, patch.object(self.app, 'wait_for_typing', return_value=True):
            def write(char, **options):
                if char == ')':
                    foreground.return_value = other

            self.keyboard.write.side_effect = write
            self.app.start_typing()
            with self.app.typing_condition:
                self.assertTrue(self.app.typing_condition.wait_for(lambda: self.app.is_paused, timeout=1))
            self.assertEqual(self.keyboard.write.call_args_list,
                             [call(char, delay=0, exact=True) for char in '()'])
            self.keyboard.press_and_release.assert_not_called()
            foreground.return_value = original
            self.app.toggle_pause()
            self.app.typing_thread.join(timeout=1)
            self.assertFalse(self.app.typing_thread.is_alive())
        self.flush_callbacks()
        self.assertEqual(self.keyboard.write.call_args_list,
                         [call(char, delay=0, exact=True) for char in '()x'])
        self.assertEqual(self.keyboard.press_and_release.call_args_list, [call('left'), call('right')])
        self.app.status_var.set.assert_called_with('✓ 输入完成')

    def test_monitor_pauses_during_long_delay_without_automatic_resume(self):
        self.app.config.update(GUARD_DEFAULTS)
        self.app.config.update(min_speed=10000, max_speed=10000)
        self.app.tray_icon = Mock()
        first = threading.Event()
        self.keyboard.write.side_effect = lambda *args, **kwargs: first.set()
        with patch.object(main, 'inspect_foreground_window', return_value=WindowState((101, 201))), patch.object(
            main, 'foreground_window', return_value=(102, 201)
        ) as foreground:
            foreground.return_value = (101, 201)
            self.app.start_typing()
            self.assertTrue(first.wait(1))
            foreground.return_value = (102, 201)
            self.app.monitor_focus(self.app.stop_event)
            self.assertTrue(self.app.is_paused)
            self.flush_callbacks()
            foreground.return_value = (101, 201)
            for _ in range(3):
                self.app.monitor_focus(self.app.stop_event)
            self.assertTrue(self.app.is_paused)
            self.app.tray_icon.notify.assert_called_once()
            self.assertEqual(self.keyboard.write.call_args_list, [call('a', delay=0, exact=True)])
        self.app.stop_typing()
        self.app.typing_thread.join(timeout=1)
        self.assertFalse(self.app.typing_thread.is_alive())

    def test_blocked_start_sends_no_keyboard_events_and_binds_target_on_resume(self):
        self.app.config.update(GUARD_DEFAULTS)
        self.app.config.update(min_speed=0, max_speed=0)
        self.app.tray_icon = Mock()
        with patch.object(main, 'inspect_foreground_window', return_value=WindowState((101, 201), '当前文本框为只读')) as inspect, patch.object(
            main, 'foreground_window', return_value=(102, 202)
        ):
            self.app.start_typing()
            self.app.typing_thread.join(timeout=0.05)
            self.assertTrue(self.app.is_typing)
            self.assertTrue(self.app.is_paused)
            self.assertIsNone(self.app.target_window)
            self.assertTrue(self.app.typing_thread.is_alive())
            self.keyboard.is_pressed.assert_not_called()
            self.keyboard.release.assert_not_called()
            self.keyboard.write.assert_not_called()
            self.app.status_var.set.assert_called_with('⏸ 当前文本框为只读')
            self.app.toggle_pause()
            self.assertTrue(self.app.is_paused)
            self.app.tray_icon.notify.assert_called_once()
            inspect.return_value = WindowState((102, 202))
            self.app.toggle_pause()
            self.assertEqual(self.app.target_window, (102, 202))
            self.app.typing_thread.join(timeout=1)
            self.assertFalse(self.app.typing_thread.is_alive())
        self.flush_callbacks()
        self.assertEqual(self.keyboard.write.call_args_list, [call(char, delay=0, exact=True) for char in 'ab'])
        self.assertFalse(self.app.is_typing)

    def test_guard_switches_are_independent_and_disabled_checks_are_skipped(self):
        for focus, block in itertools.product((False, True), repeat=2):
            with self.subTest(focus=focus, block=block), patch.object(main.threading, 'Thread'), patch.object(
                main, 'inspect_foreground_window', return_value=WindowState((101, 201), '当前文本框为只读')
            ) as inspect, patch.object(main, 'foreground_window', return_value=(102, 202)) as foreground:
                self.app.config.update(pause_on_focus_loss=focus, block_untypable_windows=block)
                self.app.start_typing()
                self.assertEqual(self.app.is_paused, block)
                self.assertEqual(inspect.call_count, int(focus or block))
                inspect.return_value = WindowState((101, 201))
                if block:
                    self.app.toggle_pause()
                    self.assertFalse(self.app.is_paused)
                self.assertEqual(bool(self.app.focus_loss_reason()), focus)
                self.assertEqual(foreground.call_count, int(focus))
                self.app.stop_typing()

    def test_unknown_target_is_allowed(self):
        self.app.config.update(GUARD_DEFAULTS)
        self.clipboard.paste.return_value = 'x'
        with patch.object(main, 'inspect_foreground_window', return_value=WindowState()), patch.object(
            main, 'foreground_window'
        ) as foreground:
            self.app.start_typing()
            self.app.typing_thread.join(timeout=1)
            self.assertFalse(self.app.typing_thread.is_alive())
            self.assertIsNone(self.app.target_window)
            foreground.assert_not_called()
        self.flush_callbacks()
        self.keyboard.write.assert_called_once_with('x', delay=0, exact=True)
        self.app.status_var.set.assert_called_with('✓ 输入完成')

    def test_focus_identity_includes_process_and_detects_missing_foreground(self):
        self.app.guard_settings.update(pause_on_focus_loss=True)
        self.app.target_window = (101, 201)
        for current in ((101, 201), (101, 202), (102, 201), None):
            with self.subTest(current=current), patch.object(main, 'foreground_window', return_value=current):
                self.assertEqual(bool(self.app.focus_loss_reason()), current != self.app.target_window)

    def test_stale_focus_callbacks_and_failed_notifications_do_not_affect_new_session(self):
        old_event = threading.Event()
        self.app.is_typing = True
        self.app.focus_monitor_job = 'new monitor'
        self.app.tray_icon = Mock()
        self.app.monitor_focus(old_event)
        self.app.pause_for_window(old_event, 'stale')
        self.app.show_window_pause(old_event, 'stale')
        self.app.finish_typing(old_event, True, None)
        self.assertFalse(self.app.is_paused)
        self.assertEqual(self.app.focus_monitor_job, 'new monitor')
        self.app.root.after_cancel.assert_not_called()
        self.app.tray_icon.notify.assert_not_called()
        self.app.tray_icon.notify.side_effect = OSError('notifications unavailable')
        self.app.pause_for_window(self.app.stop_event, '已离开原输入窗口')
        self.flush_callbacks()
        self.assertTrue(self.app.is_paused)
        self.app.status_var.set.assert_called_with('⏸ 已离开原输入窗口')
        self.app.toggle_pause()
        self.app.show_window_pause(self.app.stop_event, '已离开原输入窗口')
        self.assertFalse(self.app.is_paused)
        self.app.tray_icon.notify.assert_called_once()

    def test_stop_and_completion_cancel_focus_monitor(self):
        self.app.config.update(GUARD_DEFAULTS)
        with patch.object(main.threading, 'Thread'), patch.object(
            main, 'inspect_foreground_window', return_value=WindowState((101, 201))
        ):
            self.app.start_typing()
            self.app.stop_typing()
            self.assertIsNone(self.app.focus_monitor_job)
            self.assertIsNone(self.app.target_window)
            self.app.root.after_cancel.assert_called_once_with('monitor')
            self.app.start_typing()
            self.app.finish_typing(self.app.stop_event, True, None)
            self.assertIsNone(self.app.focus_monitor_job)
            self.assertIsNone(self.app.target_window)
            self.assertEqual(self.app.root.after_cancel.call_args_list, [call('monitor'), call('monitor')])

    def test_stop_interrupts_long_delay_and_pause(self):
        for paused in (False, True):
            with self.subTest(paused=paused):
                written = threading.Event()
                self.keyboard.write.reset_mock()
                self.keyboard.write.side_effect = lambda *args, **kwargs: written.set()
                self.clipboard.paste.return_value = '.b'
                self.app.config.update(separator_min_delay=10000, separator_max_delay=10000)
                self.app.toggle_typing()
                self.assertTrue(written.wait(1))
                if paused:
                    self.app.toggle_pause()
                self.app.toggle_typing()
                self.app.typing_thread.join(timeout=1)
                self.assertFalse(self.app.typing_thread.is_alive())
                self.flush_callbacks()
                self.assertEqual(self.keyboard.write.call_args_list, [call('.', delay=0, exact=True)])
                self.assertFalse(self.app.is_typing)
                self.assertFalse(self.app.is_paused)
                self.app.status_var.set.assert_called_with('⏹ 已停止')

    def test_restart_ignores_previous_worker_completion(self):
        written = threading.Event()
        self.keyboard.write.side_effect = lambda *args, **kwargs: written.set()
        self.app.config.update(min_speed=10000, max_speed=10000)
        self.app.toggle_typing()
        previous_thread = self.app.typing_thread
        self.assertTrue(written.wait(1))
        self.app.toggle_typing()
        self.app.toggle_typing()
        current_event = self.app.stop_event
        previous_thread.join(timeout=1)
        self.assertFalse(previous_thread.is_alive())
        self.flush_callbacks()
        self.assertTrue(self.app.is_typing)
        self.assertIs(self.app.stop_event, current_event)
        self.assertFalse(current_event.is_set())

    def test_idle_pause_and_empty_clipboard(self):
        self.app.toggle_pause()
        self.assertFalse(self.app.is_paused)
        self.clipboard.paste.return_value = ''
        self.app.toggle_typing()
        self.assertFalse(self.app.is_typing)
        self.assertIsNone(self.app.typing_thread)
        self.keyboard.write.assert_not_called()

    def test_hotkeys_dispatch_both_toggles(self):
        with patch.object(self.app, 'toggle_typing') as toggle, patch.object(self.app, 'toggle_pause') as pause:
            self.app.register_hotkeys()
            bindings = self.keyboard.add_hotkey.call_args_list
            hotkeys = [self.app.config['hotkey'], self.app.config['pause_hotkey']]
            self.assertEqual([args.args[0] for args in bindings], hotkeys)
            for binding in bindings:
                self.assertTrue(binding.kwargs['trigger_on_release'])
                self.assertTrue(binding.kwargs['suppress'])
                binding.args[1]()
            self.flush_callbacks()
            toggle.assert_called_once()
            pause.assert_called_once()
            self.app.register_hotkeys()
            self.assertEqual(self.keyboard.remove_hotkey.call_args_list, [call(hotkey) for hotkey in hotkeys])

    def test_hotkey_recording_and_conflict(self):
        self.app.config['hotkey'] = 'ctrl+alt+v'
        with patch.object(self.app, 'save_config') as save:
            for key, expected in (('q', 'ctrl+alt+q'), ('v', 'ctrl+alt+q')):
                self.app.start_set_hotkey('pause_hotkey')
                for name in ('left ctrl', 'alt', key):
                    self.app.on_key_event(SimpleNamespace(name=name, event_type='down'))
                self.app.on_key_event(SimpleNamespace(name=key, event_type='up'))
                self.flush_callbacks()
                self.assertEqual(self.app.config['pause_hotkey'], expected)
                self.assertFalse(self.app.is_setting_hotkey)
            save.assert_called_once()
            self.app.status_var.set.assert_called_with('⚠ 快捷键重复')

    def test_function_key_recording(self):
        combinations = [('f1',), ('f5',), ('f12',), ('f24',), ('ctrl', 'f4'), ('alt', 'shift', 'f10')]
        with patch.object(self.app, 'save_config'):
            for combination in combinations:
                with self.subTest(combination=combination):
                    self.app.start_set_hotkey('hotkey')
                    for key in combination:
                        self.app.on_key_event(SimpleNamespace(name=key, event_type='down'))
                    self.app.on_key_event(SimpleNamespace(name=combination[-1], event_type='up'))
                    self.flush_callbacks()
                    self.assertFalse(self.app.is_setting_hotkey)
                    self.assertEqual(self.app.config['hotkey'], '+'.join(combination))

    def test_unmodified_letter_and_invalid_function_key_are_not_recorded(self):
        for key in ('a', 'f0', 'f25'):
            with self.subTest(key=key), patch.object(self.app, 'save_config') as save:
                self.app.start_set_hotkey('hotkey')
                self.app.on_key_event(SimpleNamespace(name=key, event_type='down'))
                self.app.on_key_event(SimpleNamespace(name=key, event_type='up'))
                self.assertTrue(self.app.is_setting_hotkey)
                self.app.on_key_event(SimpleNamespace(name='esc', event_type='down'))
                self.flush_callbacks()
                self.assertFalse(self.app.is_setting_hotkey)
                save.assert_not_called()

    def test_copy_test_text_only_copies(self):
        self.app.copy_test_text()
        self.clipboard.copy.assert_called_once_with(main.TEST_TEXT)
        self.assertGreater(len(main.TEST_TEXT), 1000)
        for sample in ('The other', 'WORLD', '0123456789', 'Dr. Smith', 'J. Adams', '3.14',
                       '1,234.56', 'v1.2', 'user_name', 'https://example.com/',
                       'user.name+tag@example.com', '?!"  ', '\n\n', '中文', '🙂'):
            self.assertIn(sample, main.TEST_TEXT)
        self.keyboard.write.assert_not_called()

    def test_keyboard_import_failure_reports_status(self):
        with patch.object(main, 'load_keyboard', side_effect=ModuleNotFoundError('keyboard')):
            self.assertFalse(self.app.register_hotkeys())
            self.app.status_var.set.assert_called_with('⚠ 快捷键不可用')
            self.app.start_set_hotkey('hotkey')
            self.assertFalse(self.app.is_setting_hotkey)
            self.assertIsNone(self.app.hook_handle)
            self.app.status_var.set.assert_called_with('⚠ 快捷键录制失败')

    def test_keyboard_hook_failure_restores_hotkeys(self):
        self.keyboard.hook.side_effect = OSError('hook failed')
        self.app.start_set_hotkey('pause_hotkey')
        self.assertFalse(self.app.is_setting_hotkey)
        self.assertIsNone(self.app.hook_handle)
        self.app.hotkey_var.set.assert_called_with(self.app.config['hotkey'])
        self.app.pause_hotkey_var.set.assert_called_with(self.app.config['pause_hotkey'])
        self.assertEqual(self.keyboard.add_hotkey.call_count, 2)

    def test_keyboard_failure_does_not_block_tray(self):
        with patch.object(main, 'load_keyboard', side_effect=ModuleNotFoundError('keyboard')), patch.object(
            main, 'HAS_PYSTRAY', True
        ), patch.object(self.app, 'poll_clipboard'), patch.object(self.app, 'setup_tray') as tray:
            self.app.initialize_background_features()
            tray.assert_called_once()

    def test_save_separator_settings_and_reject_invalid_delays(self):
        for key in ('min_speed', 'max_speed', 'separator_min_delay', 'separator_max_delay', 'separators'):
            variable = Mock()
            variable.get.return_value = str(self.app.config[key])
            setattr(self.app, key + '_var', variable)
        self.app.model_vars = {key: Mock() for key in MODEL_DEFAULTS}
        for variable in self.app.model_vars.values():
            variable.get.return_value = True
        self.app.guard_vars = {key: Mock() for key in GUARD_DEFAULTS}
        for variable in self.app.guard_vars.values():
            variable.get.return_value = False
        self.app.hide_to_tray_var = Mock()
        self.app.hide_to_tray_var.get.return_value = True
        self.app.separator_min_delay_var.get.return_value = '250'
        self.app.separator_max_delay_var.get.return_value = '450'
        self.app.separators_var.get.return_value = ' ,._'
        self.app.input_speed_var = Mock()
        self.app.input_speed_var.get.return_value = 50
        self.app.speed_label_var = Mock()
        with tempfile.TemporaryDirectory() as directory, patch.object(main, 'CONFIG_FILE', str(Path(directory) / 'config.json')):
            self.app.save_settings()
            with open(main.CONFIG_FILE, encoding='utf-8') as config_file:
                saved = json.load(config_file)
            self.assertEqual(saved['separators'], ' ,._')
            self.assertEqual(saved['separator_min_delay'], 250)
            self.assertEqual(saved['separator_max_delay'], 450)
            self.assertEqual(self.app.load_config(), saved)
            for invalid in ('-1', 'abc', '1.5'):
                with self.subTest(invalid=invalid):
                    self.app.separator_min_delay_var.get.return_value = invalid
                    self.assertFalse(self.app.save_settings())
                    self.app.status_var.set.assert_called_with('⚠ 间隔须为非负整数')
                    self.assertEqual(self.app.config, saved)

    def test_old_config_migration(self):
        for hotkey in ('ctrl+shift+v', 'ctrl+alt+p'):
            with self.subTest(hotkey=hotkey), tempfile.TemporaryDirectory() as directory, patch.object(
                main, 'CONFIG_FILE', str(Path(directory) / 'config.json')
            ):
                Path(main.CONFIG_FILE).write_text(json.dumps({'hotkey': hotkey, 'stop_hotkey': 'ctrl+a',
                    'separator_delay': 325, 'use_random_speed': False, 'fixed_speed': 123,
                    'min_speed': 60, 'max_speed': 160, 'model_bigrams': False}), encoding='utf-8')
                config = self.app.load_config()
                self.assertEqual(config['hotkey'], hotkey)
                self.assertNotEqual(config['pause_hotkey'], hotkey)
                self.assertNotIn('stop_hotkey', config)
                self.assertNotIn('separator_delay', config)
                self.assertEqual(config['separator_min_delay'], 325)
                self.assertEqual(config['separator_max_delay'], 325)
                self.assertIn(' ', config['separators'])
                self.assertNotIn('use_random_speed', config)
                self.assertNotIn('fixed_speed', config)
                self.assertEqual((config['min_speed'], config['max_speed']), (60, 160))
                self.assertEqual(config['input_speed'], 50)
                self.assertTrue(all(config[key] is True for key in GUARD_DEFAULTS))
                self.assertFalse(config['model_bigrams'])
                self.assertTrue(all(config[key] is True for key in MODEL_DEFAULTS if key != 'model_bigrams'))
                self.app.config = config
                self.assertTrue(self.app.save_config())
                saved = json.loads(Path(main.CONFIG_FILE).read_text(encoding='utf-8'))
                self.assertNotIn('use_random_speed', saved)
                self.assertNotIn('fixed_speed', saved)


class WindowGuardTests(unittest.TestCase):
    def setUp(self):
        self.api = window_guard._WindowsAPI.__new__(window_guard._WindowsAPI)
        self.user = self.api.user = Mock()
        self.user.GetForegroundWindow.return_value = 101
        self.user.IsWindow.return_value = True
        self.user.IsWindowEnabled.return_value = True
        self.user.IsWindowVisible.return_value = True
        self.user.IsIconic.return_value = False
        self.user.GetWindowLongW.return_value = 0
        self.classes = {101: 'OtherWindow', 102: 'Edit'}
        self.focus = 102
        self.flags = 0
        self.pid = 987654

        def thread_process(hwnd, pid):
            if pid is not None:
                pid._obj.value = self.pid
            return 301

        def gui_info(thread, info):
            info._obj.flags = self.flags
            info._obj.hwndFocus = self.focus
            return True

        def class_name(hwnd, buffer, size):
            buffer.value = self.classes.get(hwnd, '')
            return len(buffer.value)

        self.user.GetWindowThreadProcessId.side_effect = thread_process
        self.user.GetGUIThreadInfo.side_effect = gui_info
        self.user.GetClassNameW.side_effect = class_name

    def test_explicit_window_blacklist(self):
        self.assertEqual(self.api.inspect(), WindowState((101, self.pid)))
        for name in ('Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'):
            with self.subTest(window_class=name):
                self.classes[101] = name
                self.assertEqual(self.api.inspect().blocked_reason, '桌面或任务栏不能输入文本')
        self.classes[101] = 'OtherWindow'
        for name, value in (('IsWindow', False), ('IsWindowEnabled', False), ('IsWindowVisible', False), ('IsIconic', True)):
            with self.subTest(api=name), patch.object(self.user, name, return_value=value):
                self.assertIsNotNone(self.api.inspect().blocked_reason)
        self.pid = os.getpid()
        self.assertEqual(self.api.inspect().blocked_reason, '当前为 Copy2Input 窗口')
        self.user.GetForegroundWindow.return_value = 0
        self.assertIsNone(self.api.foreground())
        self.assertEqual(self.api.inspect(), WindowState(blocked_reason='未检测到前台窗口'))

    def test_explicit_control_blacklist(self):
        for name in ('Button', 'Static', 'ScrollBar', 'msctls_trackbar32', 'msctls_progress32'):
            with self.subTest(control_class=name):
                self.classes[102] = name
                self.assertEqual(self.api.inspect().blocked_reason, '当前控件不能输入文本')
        for name in ('Edit', 'RichEdit20W', 'RICHEDIT50W'):
            with self.subTest(control_class=name):
                self.classes[102] = name
                self.user.GetWindowLongW.return_value = 0x800
                self.assertEqual(self.api.inspect().blocked_reason, '当前文本框为只读')
                self.user.GetWindowLongW.return_value = 0
                self.assertIsNone(self.api.inspect().blocked_reason)
        self.user.IsWindowEnabled.side_effect = lambda hwnd: hwnd != 102
        self.assertEqual(self.api.inspect().blocked_reason, '当前控件已禁用')
        self.user.IsWindowEnabled.side_effect = None
        self.focus = None
        self.assertEqual(self.api.inspect().blocked_reason, '未检测到输入焦点')
        self.focus = 102
        for flag in (2, 4, 8, 16):
            with self.subTest(flag=flag):
                self.flags = flag
                self.assertEqual(self.api.inspect().blocked_reason, '当前菜单或窗口操作不能输入文本')

    def test_unknown_controls_and_failed_inspection_are_allowed(self):
        for name in ('Chrome_RenderWidgetHostHWND', 'Windows.UI.Core.CoreWindow', 'CustomCanvas', ''):
            with self.subTest(control_class=name):
                self.classes[102] = name
                self.user.GetWindowLongW.return_value = 0x800
                self.assertIsNone(self.api.inspect().blocked_reason)
        self.flags = 1  # A blinking caret is not a menu or move/resize operation.
        self.assertIsNone(self.api.inspect().blocked_reason)
        self.user.GetGUIThreadInfo.side_effect = None
        self.user.GetGUIThreadInfo.return_value = False
        self.assertIsNone(self.api.inspect().blocked_reason)
        with patch.object(window_guard.sys, 'platform', 'win32'), patch.object(
            window_guard, '_windows_api', return_value=self.api
        ):
            self.user.GetForegroundWindow.side_effect = OSError('API unavailable')
            self.assertEqual(window_guard.inspect_foreground_window(), WindowState())


class TypingRhythmTests(unittest.TestCase):
    def rhythm(self, text, seed=17, **settings):
        return TypingRhythm(text, main.DEFAULT_CONFIG | settings, random.Random(seed))

    def test_speed_profiles_keep_bounds_and_decrease_total_typing_time(self):
        # Compare every adjacent slider step with the same random stream.
        for seed in (7, 17, 93):
            totals = []
            for level in range(101):
                settings = speed_profile(level)
                self.assertGreater(settings['min_speed'], 0)
                self.assertLess(settings['min_speed'], settings['max_speed'])
                self.assertLess(settings['max_speed'], settings['separator_min_delay'])
                self.assertLess(settings['separator_min_delay'], settings['separator_max_delay'])
                rhythm = self.rhythm(main.TEST_TEXT, seed=seed, **settings)
                totals.append(sum(rhythm.delay_after(index) for index in range(len(main.TEST_TEXT))))
            self.assertTrue(all(slow > fast for slow, fast in zip(totals, totals[1:])))
            self.assertGreater(totals[0] / totals[-1], 8)
        self.assertEqual(speed_profile(50), {'input_speed': 50, **INTERVAL_DEFAULTS})

    def test_speed_adjusts_model_parameters_without_scaling_custom_bounds_again(self):
        text = main.TEST_TEXT
        slow, fast = (self.rhythm(text, input_speed=level) for level in (0, 100))
        self.assertGreater(slow.context_cost, fast.context_cost)
        slow_delays, fast_delays = [], []
        for index in range(len(text) - 1):
            for rhythm, delays in ((slow, slow_delays), (fast, fast_delays)):
                delay = rhythm.delay_after(index)
                low_key, high_key = (('separator_min_delay', 'separator_max_delay')
                                     if index in rhythm.boundaries else ('min_speed', 'max_speed'))
                lower, upper = (INTERVAL_DEFAULTS[key] / 1000 for key in (low_key, high_key))
                self.assertGreaterEqual(delay, lower)
                self.assertLessEqual(delay, upper)
                delays.append(delay)
        self.assertGreater(sum(slow_delays), sum(fast_delays))
        for value in (None, 'invalid', float('nan'), float('inf'), -200, 400):
            profile = speed_profile(value)
            self.assertGreaterEqual(profile['input_speed'], 0)
            self.assertLessEqual(profile['input_speed'], 100)

    def test_legacy_fixed_settings_cannot_disable_model(self):
        text = 'The quick reader, v1.2. Next sentence.\nAnother line.'
        current = self.rhythm(text)
        legacy = self.rhythm(text, use_random_speed=False, fixed_speed=9999)
        self.assertEqual([current.delay_after(i) for i in range(len(text))],
                         [legacy.delay_after(i) for i in range(len(text))])

    def test_sentence_quotes_spaces_and_crlf_share_one_pause(self):
        for suffix in ('. ', '?! ', '... ', '."  ', '.\r\n', '.\r\n\r\n'):
            with self.subTest(suffix=suffix):
                text = 'Hello' + suffix + 'World'
                rhythm = self.rhythm(text)
                delays = [rhythm.delay_after(i) for i in range(len(text) - 1)]
                pauses = [i for i, delay in enumerate(delays)
                          if delay >= INTERVAL_DEFAULTS['separator_min_delay'] / 1000]
                self.assertEqual(pauses, [len('Hello' + suffix) - 1])

    def test_english_tokens_do_not_trigger_internal_separator_pauses(self):
        for token in ('3.14', '1,234.56', 'v1.2', 'user_name', 'example.com',
                      'user.name+tag@example.com', 'https://example.com/a_b?q=1,2',
                      'Dr.', 'e.g.', "don't"):
            with self.subTest(token=token):
                rhythm = self.rhythm(token)
                self.assertTrue(all(rhythm.delay_after(i) <= INTERVAL_DEFAULTS['max_speed'] / 1000
                                    for i in range(len(token) - 1)))
        rhythm = self.rhythm('https://example.com. Next')
        self.assertGreaterEqual(rhythm.delay_after(len('https://example.com. ') - 1),
                                INTERVAL_DEFAULTS['separator_min_delay'] / 1000)

    def test_boundary_strength_increases_with_sentence_structure(self):
        samples = ('a b', 'a, b', 'a. b', 'a\nb', 'a\n\nb')
        pauses = [self.rhythm(text).delay_after(len(text) - 2) for text in samples]
        self.assertEqual(pauses, sorted(pauses))
        self.assertEqual(len(set(pauses)), len(pauses))

    def test_bigrams_key_distance_and_shift_affect_character_timing(self):
        # Identical seeds isolate contextual factors rather than random samples.
        delay = lambda text: self.rhythm(text).delay_after(0)
        self.assertLess(delay('th'), delay('tg'))
        self.assertLess(delay('as'), delay('ap'))
        self.assertLess(delay('ab'), delay('aB'))
        self.assertLess(delay('a1'), delay('a!'))

    def test_each_character_feature_can_be_disabled(self):
        plain = {key: False for key in MODEL_DEFAULTS}
        for text, feature, faster in (('th', 'model_bigrams', True),
                                      ('ap', 'model_key_distance', False),
                                      ('aa', 'model_key_distance', False),
                                      ('aB', 'model_shift_digits', False),
                                      ('a1', 'model_shift_digits', False)):
            with self.subTest(feature=feature, text=text):
                baseline = self.rhythm(text, **plain).delay_after(0)
                enabled = self.rhythm(text, **(plain | {feature: True})).delay_after(0)
                if faster:
                    self.assertLess(enabled, baseline)
                else:
                    self.assertGreater(enabled, baseline)
        text = 'a quick brown fox jumps over a quiet dog' * 3
        plain_rhythm = self.rhythm(text, **plain)
        tempo_rhythm = self.rhythm(text, **(plain | {'model_tempo': True}))
        self.assertNotEqual([plain_rhythm.delay_after(i) for i in range(len(text) - 1)],
                            [tempo_rhythm.delay_after(i) for i in range(len(text) - 1)])

    def test_smart_pauses_and_format_recognition_work_independently(self):
        text = 'Hello. World'
        smart = self.rhythm(text)
        literal = self.rhythm(text, model_smart_pauses=False)
        normal_max = INTERVAL_DEFAULTS['max_speed'] / 1000
        separator_min = INTERVAL_DEFAULTS['separator_min_delay'] / 1000
        self.assertLessEqual(smart.delay_after(text.index('.')), normal_max)
        self.assertGreaterEqual(literal.delay_after(text.index('.')), separator_min)
        self.assertGreaterEqual(smart.delay_after(text.index(' ')), separator_min)
        self.assertGreaterEqual(literal.delay_after(text.index(' ')), separator_min)
        for smart_pauses in (False, True):
            for token in ('3.14', 'Dr. Smith', 'user_name', 'user.name@example.com'):
                with self.subTest(smart=smart_pauses, token=token):
                    index = next(i for i, char in enumerate(token) if char in '._')
                    protected = self.rhythm(token, model_smart_pauses=smart_pauses)
                    unprotected = self.rhythm(token, model_smart_pauses=smart_pauses,
                                             model_english_tokens=False)
                    self.assertLessEqual(protected.delay_after(index), normal_max)
                    # Smart pauses may move punctuation delay onto its following space.
                    end = index + (1 if token[index + 1:index + 2] == ' ' and smart_pauses else 0)
                    self.assertGreaterEqual(unprotected.delay_after(end), separator_min)

    def test_long_sample_outputs_intact_with_all_features_on_and_off(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                app = main.Copy2InputApp.__new__(main.Copy2InputApp)
                app.config = main.DEFAULT_CONFIG | {key: enabled for key in MODEL_DEFAULTS}
                app.typing_condition = threading.Condition()
                app.is_paused = False
                app.guard_settings = {key: False for key in GUARD_DEFAULTS}
                app.target_window = None
                app.root = Mock()
                keyboard = Mock()
                keyboard.is_pressed.return_value = False
                with patch.object(main, 'keyboard', keyboard), patch.object(app, 'wait_for_typing', return_value=True):
                    app.type_text(main.TEST_TEXT, threading.Event())
                output = []
                caret = 0
                for name, args, _ in keyboard.method_calls:
                    if name == 'write':
                        output.insert(caret, args[0])
                        caret += 1
                    elif name == 'press_and_release':
                        caret += -1 if args[0] == 'left' else 1
                    self.assertLessEqual(0, caret)
                    self.assertLessEqual(caret, len(output))
                self.assertEqual(''.join(output), main.TEST_TEXT)
                self.assertEqual(caret, len(output))

    def test_delay_limits_zero_custom_separators_and_reproducibility(self):
        text = 'The QUICK fox, 3.14!\r\n\u4e2d\u6587\U0001f642 ' * 30
        for lower, upper in ((0, 0), (0, 150), (50, 150), (150, 50), (100, 100)):
            with self.subTest(limits=(lower, upper)):
                rhythm = self.rhythm(text, min_speed=lower, max_speed=upper,
                                     separators='', separator_min_delay=0, separator_max_delay=0)
                delays = [rhythm.delay_after(i) * 1000 for i in range(len(text) - 1)]
                self.assertTrue(all(min(lower, upper) <= delay <= max(lower, upper) for delay in delays))
        rhythm = self.rhythm('a@ b', separators='@', separator_min_delay=300, separator_max_delay=300)
        self.assertEqual([rhythm.delay_after(i) >= 0.3 for i in range(3)], [False, False, True])
        left, right = self.rhythm(text), self.rhythm(text)
        self.assertEqual([left.delay_after(i) for i in range(len(text) - 1)],
                         [right.delay_after(i) for i in range(len(text) - 1)])
        self.assertEqual(self.rhythm('').delay_after(0), 0)
        self.assertEqual(self.rhythm('a').delay_after(0), 0)


class PackagingTests(unittest.TestCase):
    def built_executable(self):
        return Path(os.environ.get('COPY2INPUT_TEST_EXE',
                    Path(__file__).resolve().parents[1] / 'release' / 'Copy2Input.exe'))

    def test_spec_rejects_missing_runtime_dependencies(self):
        spec = Path(__file__).resolve().parents[1] / 'Copy2Input.spec'
        for missing in ('keyboard', 'pyperclip', 'pystray', 'PIL', '_tkinter'):
            with self.subTest(missing=missing), patch.object(
                importlib.util, 'find_spec', side_effect=lambda name: None if name == missing else object()
            ):
                analysis = Mock()
                with self.assertRaisesRegex(SystemExit, missing):
                    runpy.run_path(str(spec), init_globals={'Analysis': analysis})
                analysis.assert_not_called()

    def test_built_executable_contains_runtime_dependencies(self):
        executable = self.built_executable()
        if not executable.exists() or importlib.util.find_spec('PyInstaller') is None:
            self.skipTest('No built executable or PyInstaller')
        from PyInstaller.archive.readers import CArchiveReader
        archive = CArchiveReader(str(executable))
        pyz_name = next(name for name in archive.toc if name.endswith('.pyz'))
        bundled = archive.open_embedded_archive(pyz_name).toc
        for module in ('keyboard', 'keyboard._winkeyboard', 'pyperclip', 'pystray', 'pystray._win32', 'PIL.Image', 'PIL.IcoImagePlugin', 'PIL.PngImagePlugin', 'PIL.BmpImagePlugin'):
            with self.subTest(module=module):
                self.assertTrue(module in bundled, f'EXE missing {module}')

    def test_built_executable_contains_typing_model_and_icons(self):
        executable = self.built_executable()
        if not executable.exists() or importlib.util.find_spec('PyInstaller') is None:
            self.skipTest('No built executable or PyInstaller')
        from PyInstaller.archive.readers import CArchiveReader
        archive = CArchiveReader(str(executable))
        bundled = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith('.pyz'))).toc
        self.assertIn('typing_model', bundled)
        self.assertIn('window_guard', bundled)
        paths = {name.replace('\\', '/') for name in archive.toc}
        for name in ('assets/Copy2Input.ico', 'assets/Copy2Input.png', 'LICENSE',
                     *(f'assets/tray-{state}.png' for state in main.TRAY_TITLES)):
            self.assertIn(name, paths)
            archived_name = next(path for path in archive.toc if path.replace('\\', '/') == name)
            self.assertEqual(archive.extract(archived_name),
                             (Path(__file__).resolve().parents[1] / name).read_bytes(),
                             f'EXE contains an outdated resource: {name}')
        import pefile
        with pefile.PE(str(executable), fast_load=True) as pe:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
            self.assertIn(pefile.RESOURCE_TYPE['RT_GROUP_ICON'],
                          [entry.id for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries])

    def test_built_executable_excludes_unused_backends_and_imaging_modules(self):
        executable = self.built_executable()
        if not executable.exists() or importlib.util.find_spec('PyInstaller') is None:
            self.skipTest('No built executable or PyInstaller')
        from PyInstaller.archive.readers import CArchiveReader
        archive = CArchiveReader(str(executable))
        bundled = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith('.pyz'))).toc
        for module in ('PIL.ImageDraw', 'PIL.ImageFont', 'PIL.ImageShow', 'PIL.TiffImagePlugin', 'PIL.AvifImagePlugin', 'PIL.JpegImagePlugin', 'PIL.WebPImagePlugin', 'keyboard._darwinkeyboard', 'keyboard._nixkeyboard', 'pystray._gtk', 'pystray._util.gtk', 'pystray._util.notify_dbus'):
            self.assertFalse(module in bundled, f'Unused module bundled: {module}')
        for name in archive.toc:
            self.assertFalse(any(unused in name for unused in ('_avif.', '_webp.', '_imagingft.', '_imagingcms.')), name)


if __name__ == '__main__':
    unittest.main()
