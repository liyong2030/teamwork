"""HTTP 附件响应头辅助。

``Content-Disposition`` 头只能承载 latin-1 字符，中文文件名会被 Starlette
拒绝（``UnicodeEncodeError: 'latin-1' codec``）。这里统一使用 RFC 5987 的
``filename*=UTF-8''<percent-encoded>`` 形式，并保留 ASCII 兜底名，
兼容老浏览器（IE/部分 Office 插件只认 ``filename=``）。
"""

from __future__ import annotations

from urllib.parse import quote


def ascii_fallback(filename: str) -> str:
    """把非 ASCII 字符替换为 ``_``，生成安全的兜底文件名。"""
    return "".join(ch if ord(ch) < 128 and ch not in '"\\' else "_" for ch in filename)


def content_disposition(filename: str) -> str:
    """构造同时包含 ``filename`` 与 ``filename*`` 的下载头。"""
    fallback = ascii_fallback(filename)
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
