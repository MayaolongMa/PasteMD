"""Tests for the reverse paste workflow."""

import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal stubs so the module can be imported without platform-specific deps
# ---------------------------------------------------------------------------

def _make_stub_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# Stub out heavyweight platform modules before any pastemd import
for _mod in [
    "win32clipboard",
    "pynput",
    "pynput.keyboard",
    "pystray",
    "plyer",
    "pync",
    "AppKit",
    "Foundation",
    "Quartz",
    "mathml2omml",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = _make_stub_module(_mod)

# tkinter needs special handling - use MagicMock as a more capable stub
if "tkinter" not in sys.modules:
    sys.modules["tkinter"] = MagicMock()
    sys.modules["tkinter.ttk"] = MagicMock()
    sys.modules["tkinter.messagebox"] = MagicMock()
    sys.modules["tkinter.simpledialog"] = MagicMock()

# pynput.keyboard needs specific attrs
_kb = sys.modules["pynput.keyboard"]
_kb.GlobalHotKeys = MagicMock()
_kb.Listener = MagicMock()
_kb.HotKey = MagicMock()
_kb.Key = MagicMock()

# AppKit stubs
_appkit = sys.modules["AppKit"]
_appkit.NSPasteboard = MagicMock()
_appkit.NSPasteboardTypeHTML = "public.html"
_appkit.NSPasteboardTypeRTF = "public.rtf"
_appkit.NSPasteboardItem = MagicMock()
_appkit.NSPasteboardTypeString = "public.utf8-plain-text"
_appkit.NSFilenamesPboardType = "NSFilenamesPboardType"
_appkit.NSURL = MagicMock()

sys.modules["Foundation"].NSData = MagicMock()

# Patch pastemd.utils.clipboard to add missing functions on non-Win/Mac platforms
import pastemd.utils.clipboard as _clipboard_mod  # noqa: E402

if not hasattr(_clipboard_mod, "preserve_clipboard"):
    @contextmanager
    def _preserve_clipboard_stub():
        yield
    _clipboard_mod.preserve_clipboard = _preserve_clipboard_stub

for _missing_fn in [
    "set_clipboard_text",
    "set_clipboard_rich_text",
    "simulate_paste",
    "copy_files_to_clipboard",
    "is_clipboard_files",
    "get_clipboard_files",
    "get_markdown_files_from_clipboard",
    "read_markdown_files_from_clipboard",
    "read_file_with_encoding",
]:
    if not hasattr(_clipboard_mod, _missing_fn):
        setattr(_clipboard_mod, _missing_fn, MagicMock())

# ---------------------------------------------------------------------------
# Now we can safely import the modules under test
# ---------------------------------------------------------------------------

from pastemd.app.workflows.reverse.reverse_workflow import ReversePasteWorkflow  # noqa: E402


class TestReversePasteWorkflowCleanOfficeHtml(unittest.TestCase):
    """Tests for _clean_office_html static method."""

    def _clean(self, html: str) -> str:
        return ReversePasteWorkflow._clean_office_html(html)

    def test_removes_conditional_comments(self):
        html = "before<!--[if gte mso 9]><xml>junk</xml><![endif]-->after"
        result = self._clean(html)
        self.assertNotIn("[if", result)
        self.assertNotIn("junk", result)
        self.assertIn("before", result)
        self.assertIn("after", result)

    def test_removes_office_namespace_tags(self):
        html = "<p>Hello <o:p></o:p> World</p>"
        result = self._clean(html)
        self.assertNotIn("<o:p>", result)
        self.assertIn("Hello", result)
        self.assertIn("World", result)

    def test_removes_style_blocks(self):
        html = "<style>p.MsoNormal{mso-style-name:'Normal';}</style><p>text</p>"
        result = self._clean(html)
        self.assertNotIn("<style>", result)
        self.assertIn("<p>", result)

    def test_strips_mso_inline_styles(self):
        html = '<p style="mso-margin-top-alt:0cm;color:red;">text</p>'
        result = self._clean(html)
        self.assertNotIn("mso-margin-top-alt", result)
        self.assertIn("color", result)

    def test_strips_class_attributes(self):
        html = '<p class="MsoNormal">text</p>'
        result = self._clean(html)
        self.assertNotIn('class="MsoNormal"', result)
        self.assertIn("text", result)

    def test_passthrough_clean_html(self):
        html = "<p>Hello <strong>World</strong></p>"
        result = self._clean(html)
        self.assertIn("Hello", result)
        self.assertIn("<strong>", result)


class TestReversePasteWorkflowPostprocess(unittest.TestCase):
    """Tests for _postprocess_for_ai static method."""

    def _post(self, md: str, config: dict | None = None) -> str:
        return ReversePasteWorkflow._postprocess_for_ai(md, config or {})

    def test_collapses_excess_blank_lines(self):
        md = "line1\n\n\n\nline2"
        result = self._post(md)
        self.assertNotIn("\n\n\n", result)
        self.assertIn("line1", result)
        self.assertIn("line2", result)

    def test_strips_trailing_whitespace_per_line(self):
        md = "line1   \nline2  "
        result = self._post(md)
        for line in result.split("\n"):
            self.assertEqual(line, line.rstrip())

    def test_strips_leading_and_trailing_empty_lines(self):
        md = "\n\nfoo\n\n"
        result = self._post(md)
        self.assertEqual(result, "foo")

    def test_preserves_code_blocks(self):
        md = "```python\nprint('hello')\n```"
        result = self._post(md)
        self.assertIn("```python", result)
        self.assertIn("print('hello')", result)


class TestReverseWorkflowRouter(unittest.TestCase):
    """Tests for ReverseWorkflowRouter._matches_target."""

    def _make_router(self):
        from pastemd.app.workflows.reverse.reverse_router import ReverseWorkflowRouter
        router = object.__new__(ReverseWorkflowRouter)
        router._workflow = MagicMock()
        router.notification_manager = MagicMock()
        router._initialized = True
        return router

    def test_matches_all_apps_when_no_target_configured(self):
        router = self._make_router()
        cfg = {"enabled": True, "target_apps": [], "window_patterns": []}
        self.assertTrue(router._matches_target(cfg))

    def test_matches_app_by_id_substring(self):
        router = self._make_router()
        cfg = {
            "target_apps": [{"name": "Chrome", "id": "chrome"}],
            "window_patterns": [],
        }
        with patch(
            "pastemd.app.workflows.reverse.reverse_router.detect_active_app",
            return_value="chrome.exe",
        ), patch(
            "pastemd.app.workflows.reverse.reverse_router.get_frontmost_window_title",
            return_value="ChatGPT",
        ):
            self.assertTrue(router._matches_target(cfg))

    def test_does_not_match_wrong_app(self):
        router = self._make_router()
        cfg = {
            "target_apps": [{"name": "Chrome", "id": "chrome"}],
            "window_patterns": [],
        }
        with patch(
            "pastemd.app.workflows.reverse.reverse_router.detect_active_app",
            return_value="notepad.exe",
        ), patch(
            "pastemd.app.workflows.reverse.reverse_router.get_frontmost_window_title",
            return_value="Untitled - Notepad",
        ):
            self.assertFalse(router._matches_target(cfg))

    def test_matches_window_pattern(self):
        router = self._make_router()
        cfg = {
            "target_apps": [],
            "window_patterns": [r"ChatGPT|DeepSeek|Claude"],
        }
        with patch(
            "pastemd.app.workflows.reverse.reverse_router.detect_active_app",
            return_value="",
        ), patch(
            "pastemd.app.workflows.reverse.reverse_router.get_frontmost_window_title",
            return_value="ChatGPT - Google Chrome",
        ):
            self.assertTrue(router._matches_target(cfg))

    def test_does_not_match_wrong_window(self):
        router = self._make_router()
        cfg = {
            "target_apps": [],
            "window_patterns": [r"ChatGPT"],
        }
        with patch(
            "pastemd.app.workflows.reverse.reverse_router.detect_active_app",
            return_value="",
        ), patch(
            "pastemd.app.workflows.reverse.reverse_router.get_frontmost_window_title",
            return_value="Google - Google Chrome",
        ):
            self.assertFalse(router._matches_target(cfg))

    def test_invalid_regex_pattern_does_not_crash(self):
        router = self._make_router()
        cfg = {
            "target_apps": [],
            "window_patterns": ["[invalid"],
        }
        with patch(
            "pastemd.app.workflows.reverse.reverse_router.detect_active_app",
            return_value="",
        ), patch(
            "pastemd.app.workflows.reverse.reverse_router.get_frontmost_window_title",
            return_value="Some Window",
        ):
            self.assertFalse(router._matches_target(cfg))


class TestHotkeyRunnerReverse(unittest.TestCase):
    """Tests for HotkeyRunner secondary (reverse paste) hotkey support."""

    def _make_runner(self, reverse_cb=None):
        from pastemd.presentation.hotkey.run import HotkeyRunner
        runner = HotkeyRunner.__new__(HotkeyRunner)
        runner.hotkey_manager = MagicMock()
        runner.debounce_manager = MagicMock()
        runner.controller_callback = MagicMock()
        runner.notification_manager = MagicMock()
        runner.config_loader = None
        runner.reverse_controller_callback = reverse_cb
        if reverse_cb is not None:
            runner._reverse_hotkey_manager = MagicMock()
            runner._reverse_debounce_manager = MagicMock()
        else:
            runner._reverse_hotkey_manager = None
            runner._reverse_debounce_manager = None
        return runner

    def test_reverse_hotkey_bound_when_enabled(self):
        from pastemd.core.state import app_state

        reverse_cb = MagicMock()
        runner = self._make_runner(reverse_cb)
        app_state.config = {
            "reverse_paste": {
                "enabled": True,
                "hotkey": "<ctrl>+<shift>+v",
            }
        }
        app_state.hotkey_str = "<ctrl>+<shift>+b"

        with patch.object(runner.hotkey_manager, "bind"), \
             patch.object(runner._reverse_hotkey_manager, "bind") as mock_bind:
            runner._start_reverse()
            mock_bind.assert_called_once()
            bound_hotkey = mock_bind.call_args[0][0]
            self.assertEqual(bound_hotkey, "<ctrl>+<shift>+v")

    def test_reverse_hotkey_not_bound_when_disabled(self):
        from pastemd.core.state import app_state

        reverse_cb = MagicMock()
        runner = self._make_runner(reverse_cb)
        app_state.config = {
            "reverse_paste": {
                "enabled": False,
                "hotkey": "<ctrl>+<shift>+v",
            }
        }

        with patch.object(runner._reverse_hotkey_manager, "bind") as mock_bind:
            runner._start_reverse()
            mock_bind.assert_not_called()

    def test_stop_unbinds_both_hotkeys(self):
        reverse_cb = MagicMock()
        runner = self._make_runner(reverse_cb)
        runner.stop()
        runner.hotkey_manager.unbind.assert_called_once()
        runner._reverse_hotkey_manager.unbind.assert_called_once()

    def test_no_reverse_manager_when_callback_is_none(self):
        runner = self._make_runner(reverse_cb=None)
        self.assertIsNone(runner._reverse_hotkey_manager)


if __name__ == "__main__":
    unittest.main()
