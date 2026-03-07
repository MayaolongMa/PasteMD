# -*- coding: utf-8 -*-
"""Reverse paste router - dispatches the reverse paste hotkey."""

import re

from ....core.state import app_state
from ....utils.detector import detect_active_app, get_frontmost_window_title
from ....utils.logging import log
from ....service.notification.manager import NotificationManager
from ....i18n import t
from .reverse_workflow import ReversePasteWorkflow


class ReverseWorkflowRouter:
    """反向粘贴路由器（单例）

    检查 ``reverse_paste`` 配置后，将热键事件路由到 :class:`ReversePasteWorkflow`。
    当配置了 ``target_apps`` / ``window_patterns`` 时，只对匹配的应用生效；
    未配置时对所有前台应用生效。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._workflow = ReversePasteWorkflow()
        self.notification_manager = NotificationManager()
        self._initialized = True
        log("ReverseWorkflowRouter initialized")

    def route(self) -> None:
        """热键入口：检查配置 → 匹配目标应用 → 执行转换"""
        try:
            reverse_cfg = app_state.config.get("reverse_paste") or {}

            if not reverse_cfg.get("enabled", False):
                # 功能未启用，静默忽略
                return

            if not self._matches_target(reverse_cfg):
                log("Reverse paste: active app/window does not match target_apps/window_patterns")
                return

            self._workflow.execute()

        except Exception as e:
            log(f"ReverseWorkflowRouter failed: {e}")
            import traceback
            traceback.print_exc()
            self.notification_manager.notify(
                "PasteMD", t("workflow.generic.failure"), ok=False
            )

    def _matches_target(self, reverse_cfg: dict) -> bool:
        """检查当前应用/窗口是否为目标

        如果 ``target_apps`` 和 ``window_patterns`` 均为空，视为"对所有应用生效"
        并返回 ``True``。
        """
        target_apps = reverse_cfg.get("target_apps") or []
        window_patterns = reverse_cfg.get("window_patterns") or []

        if not target_apps and not window_patterns:
            return True  # 无限制，对所有应用生效

        active_app = detect_active_app() or ""
        window_title = get_frontmost_window_title() or ""

        # 检查应用 ID 匹配（大小写不敏感的子串匹配）
        for app in target_apps:
            app_id = app.get("id", "") if isinstance(app, dict) else str(app)
            if app_id and app_id.lower() in active_app.lower():
                log(f"Reverse paste: matched target_app '{app_id}'")
                return True

        # 检查窗口标题正则匹配
        for pattern in window_patterns:
            if not pattern:
                continue
            try:
                if re.search(pattern, window_title, re.IGNORECASE):
                    log(f"Reverse paste: matched window_pattern '{pattern}'")
                    return True
            except re.error as exc:
                log(f"Reverse paste: invalid window_pattern '{pattern}': {exc}")

        return False


# 全局单例
_router = ReverseWorkflowRouter()


def execute_reverse_paste_workflow() -> None:
    """反向粘贴热键入口函数"""
    _router.route()
