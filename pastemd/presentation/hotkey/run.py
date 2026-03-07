"""Hotkey UI entry point."""

from typing import Optional, Callable

from ...service.hotkey.manager import HotkeyManager
from ...service.hotkey.debounce import DebounceManager
from ...config.defaults import DEFAULT_CONFIG
from ...core.state import app_state
from ...utils.logging import log
from ...utils.hotkey_checker import HotkeyChecker
from ...i18n import t


class HotkeyRunner:
    """热键运行器

    管理主热键（正向粘贴）以及可选的反向粘贴热键。
    两个热键各使用独立的 :class:`HotkeyManager` 实例，互不干扰。
    """

    def __init__(
        self,
        controller_callback: Callable,
        notification_manager=None,
        config_loader=None,
        reverse_controller_callback: Optional[Callable] = None,
    ):
        self.hotkey_manager = HotkeyManager()
        self.debounce_manager = DebounceManager()
        self.controller_callback = controller_callback
        self.notification_manager = notification_manager
        self.config_loader = config_loader

        # 反向粘贴热键（可选）
        self.reverse_controller_callback = reverse_controller_callback
        self._reverse_hotkey_manager: Optional[HotkeyManager] = (
            HotkeyManager() if reverse_controller_callback is not None else None
        )
        self._reverse_debounce_manager: Optional[DebounceManager] = (
            DebounceManager() if reverse_controller_callback is not None else None
        )

    def get_hotkey_manager(self) -> HotkeyManager:
        """获取主热键管理器（用于暂停/恢复）"""
        return self.hotkey_manager

    def start(self) -> None:
        """启动热键监听（主热键 + 反向粘贴热键）"""
        self._start_primary()
        self._start_reverse()

    def _start_primary(self) -> None:
        """绑定主热键"""
        hotkey = app_state.hotkey_str

        error = HotkeyChecker.validate_hotkey_string(hotkey)
        if error:
            log(f"Invalid hotkey '{hotkey}': {error}. Resetting to default.")

            default_hotkey = DEFAULT_CONFIG["hotkey"]
            app_state.hotkey_str = default_hotkey
            app_state.config["hotkey"] = default_hotkey
            hotkey = default_hotkey

            if self.config_loader:
                try:
                    self.config_loader.save(app_state.config)
                except Exception as e:
                    log(f"Failed to save corrected config: {e}")

            if self.notification_manager:
                self.notification_manager.notify(
                    f"PasteMD - {t('hotkey.runner.title_invalid_config')}",
                    t("hotkey.runner.invalid_config", error=error),
                    ok=False,
                )

        def on_hotkey():
            if app_state.enabled and not getattr(app_state, "ui_block_hotkeys", False):
                self.debounce_manager.trigger_async(self.controller_callback)

        try:
            self.hotkey_manager.bind(hotkey, on_hotkey)
        except Exception as e:
            log(f"Failed to bind hotkey '{hotkey}': {e}")

            if hotkey != DEFAULT_CONFIG["hotkey"]:
                try:
                    default_hotkey = DEFAULT_CONFIG["hotkey"]
                    app_state.hotkey_str = default_hotkey
                    app_state.config["hotkey"] = default_hotkey
                    self.hotkey_manager.bind(default_hotkey, on_hotkey)

                    if self.config_loader:
                        self.config_loader.save(app_state.config)

                    if self.notification_manager:
                        self.notification_manager.notify(
                            f"PasteMD - {t('hotkey.runner.title_binding_failed')}",
                            t("hotkey.runner.binding_failed"),
                            ok=False,
                        )
                except Exception as fallback_error:
                    log(f"Failed to bind default hotkey: {fallback_error}")
                    if self.notification_manager:
                        self.notification_manager.notify(
                            f"PasteMD - {t('hotkey.runner.title_serious_error')}",
                            t("hotkey.runner.serious_error"),
                            ok=False,
                        )

    def _start_reverse(self) -> None:
        """绑定反向粘贴热键（如已配置且启用）"""
        if (
            self._reverse_hotkey_manager is None
            or self.reverse_controller_callback is None
            or self._reverse_debounce_manager is None
        ):
            return

        reverse_cfg = app_state.config.get("reverse_paste") or {}
        if not reverse_cfg.get("enabled", False):
            log("Reverse paste hotkey: disabled in config, skipping")
            return

        reverse_hotkey = reverse_cfg.get("hotkey") or DEFAULT_CONFIG["reverse_paste"]["hotkey"]

        error = HotkeyChecker.validate_hotkey_string(reverse_hotkey)
        if error:
            log(f"Invalid reverse paste hotkey '{reverse_hotkey}': {error}. Skipping.")
            if self.notification_manager:
                self.notification_manager.notify(
                    f"PasteMD - {t('hotkey.runner.title_invalid_config')}",
                    t("hotkey.runner.reverse_invalid_config", error=error),
                    ok=False,
                )
            return

        reverse_callback = self.reverse_controller_callback
        reverse_debounce = self._reverse_debounce_manager

        def on_reverse_hotkey():
            if app_state.enabled and not getattr(app_state, "ui_block_hotkeys", False):
                reverse_debounce.trigger_async(reverse_callback)

        try:
            self._reverse_hotkey_manager.bind(reverse_hotkey, on_reverse_hotkey)
            log(f"Reverse paste hotkey bound: {reverse_hotkey}")
        except Exception as e:
            log(f"Failed to bind reverse paste hotkey '{reverse_hotkey}': {e}")

    def stop(self) -> None:
        """停止所有热键监听"""
        self.hotkey_manager.unbind()
        if self._reverse_hotkey_manager is not None:
            self._reverse_hotkey_manager.unbind()

    def restart(self) -> None:
        """重启所有热键监听"""
        self.stop()
        self.start()
