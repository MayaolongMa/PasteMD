# -*- coding: utf-8 -*-
"""Reverse paste workflow: clipboard rich text (Word/WPS) → Markdown → paste."""

import re
import time

from bs4 import BeautifulSoup

from ..base import BaseWorkflow
from ....core.errors import ClipboardError, PandocError
from ....utils.clipboard import (
    get_clipboard_html,
    get_clipboard_text,
    is_clipboard_empty,
    set_clipboard_text,
    simulate_paste,
    preserve_clipboard,
)
from ....utils.logging import log
from ....i18n import t


class ReversePasteWorkflow(BaseWorkflow):
    """反向粘贴工作流

    将剪贴板中 Word/WPS 的富文本（HTML）转换为 Markdown，
    然后写回剪贴板并模拟粘贴到 AI 网页或应用中。

    转换链：Word/WPS 富文本 → Office HTML 清理 → HTML→Markdown → AI 后处理 → 粘贴
    """

    def execute(self) -> None:
        """执行反向粘贴工作流"""
        try:
            config = self._build_reverse_config()

            # 1. 读取剪贴板内容（优先 HTML，回退纯文本）
            content_type, content = self._read_clipboard()
            self._log(f"Reverse workflow: content_type={content_type}")

            # 2. 转换为 Markdown
            if content_type == "html":
                cleaned_html = self._clean_office_html(content)
                cleaned_html = self.html_preprocessor.process(cleaned_html, config)
                md_text = self.doc_generator.convert_html_to_markdown_text(
                    cleaned_html, config
                )
            else:
                # 纯文本直接使用（已经是 Markdown 或普通文本）
                md_text = content

            # 3. Markdown 后处理（通用标准化 + AI 优化）
            md_text = self.markdown_preprocessor.process(md_text, config)
            md_text = self._postprocess_for_ai(md_text, config)

            # 4. 写回剪贴板并模拟粘贴
            paste_delay_s = config.get("paste_delay_s", 0.3)
            with preserve_clipboard():
                set_clipboard_text(md_text)
                time.sleep(paste_delay_s)
                simulate_paste()

            self._notify_success(t("workflow.reverse.paste_success"))

        except ClipboardError as e:
            self._log(f"Clipboard error: {e}")
            self._notify_error(t("workflow.clipboard.read_failed"))
        except PandocError as e:
            self._log(f"Pandoc error: {e}")
            self._notify_error(t("workflow.reverse.convert_failed"))
        except Exception as e:
            self._log(f"Reverse workflow failed: {e}")
            import traceback
            traceback.print_exc()
            self._notify_error(t("workflow.generic.failure"))

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _build_reverse_config(self) -> dict:
        """根据 reverse_paste 配置项构建本次转换所用的配置字典"""
        config = dict(self.config)
        reverse_cfg = (config.get("reverse_paste") or {})

        # 公式处理：保留 $...$ 原始 LaTeX（默认 True）
        keep_formula = reverse_cfg.get("keep_formula", True)
        config["Keep_original_formula"] = keep_formula

        # 合并 reverse_paste 层级的 pandoc_filters_by_conversion 覆盖
        extra_filters = reverse_cfg.get("pandoc_filters_by_conversion")
        if isinstance(extra_filters, dict):
            base = dict(config.get("pandoc_filters_by_conversion") or {})
            base.update(extra_filters)
            config["pandoc_filters_by_conversion"] = base

        return config

    def _read_clipboard(self) -> tuple[str, str]:
        """读取剪贴板，优先 HTML，回退纯文本

        Returns:
            ("html", html_str) 或 ("text", plain_text)

        Raises:
            ClipboardError: 剪贴板为空
        """
        try:
            html = get_clipboard_html(self.config)
            if html and html.strip():
                return ("html", html)
        except ClipboardError:
            pass

        if not is_clipboard_empty():
            return ("text", get_clipboard_text())

        raise ClipboardError("剪贴板为空或无有效内容")

    @staticmethod
    def _clean_office_html(html: str) -> str:
        """清理 Office（Word/WPS）特有的 HTML 噪声标记

        处理内容：
        - Word 条件注释（``<!--[if ...]>...</[endif]-->``）
        - Office 命名空间标签（``<o:p>``, ``<w:...>``, ``<m:...>``）
        - mso-* 内联样式属性
        - Office 专有 class / lang / xml:lang 属性

        Args:
            html: 原始 HTML（可能来自 Word/WPS 剪贴板）

        Returns:
            清理后的 HTML 字符串
        """
        # 1. 移除 Word 条件注释（两种风格）
        html = re.sub(
            r'<!--\[if[^\]]*\]>.*?<!\[endif\]-->',
            '',
            html,
            flags=re.DOTALL,
        )
        html = re.sub(
            r'<!\[if[^\]]*\]>.*?<!\[endif\]>',
            '',
            html,
            flags=re.DOTALL,
        )

        # 2. 用 BeautifulSoup 做结构性清理
        try:
            soup = BeautifulSoup(html, "html.parser")

            # 移除 Office 命名空间标签（o:p, w:*, m:* 等）
            for tag in soup.find_all(re.compile(r'^[owm]:')):
                tag.decompose()

            # 移除嵌入的 <style> 块（Office 生成的 class 无意义）
            for style_tag in soup.find_all("style"):
                style_tag.decompose()

            # 清理各标签上的 mso-* 属性和 Office 专有属性
            _OFFICE_ATTRS = {"class", "lang", "xml:lang", "mso-element", "mso-style-name"}
            for tag in soup.find_all(True):
                # 清理内联 style：只保留非 mso- 属性
                style = tag.get("style", "")
                if style:
                    cleaned = re.sub(r'\bmso-[^:]+:[^;]+;?', '', style)
                    cleaned = re.sub(r'\s+', ' ', cleaned).strip().strip(';')
                    if cleaned:
                        tag["style"] = cleaned
                    else:
                        del tag["style"]

                # 删除 Office 专有属性
                for attr in list(tag.attrs.keys()):
                    if attr in _OFFICE_ATTRS or attr.startswith("mso-"):
                        del tag[attr]

            html = str(soup)
        except Exception as exc:
            log(f"Office HTML cleanup error (non-fatal): {exc}")

        return html

    @staticmethod
    def _postprocess_for_ai(md_text: str, config: dict) -> str:
        """后处理 Markdown，优化 AI 输入格式

        - 规范化连续空行（最多保留 2 个）
        - 清理行尾空白
        - 确保末尾只有一个换行
        """
        # 规范化连续空行
        md_text = re.sub(r'\n{3,}', '\n\n', md_text)

        # 清理行尾空白
        lines = [line.rstrip() for line in md_text.split('\n')]
        md_text = '\n'.join(lines)

        return md_text.strip()
