"""CAS 适配器：用账号密码换 TGT，再用 TGT 换 ST 并校验。

依赖 CAS 服务端开启 **REST API**（``/cas/v1/tickets``）。

流程：
1. ``POST {server}/cas/v1/tickets``  form: username/password → 201，Location 头给出 TGT
2. ``POST {TGT}``                     form: service=xxx    → 200，响应体是 ST
3. ``GET {server}/cas/serviceValidate?ticket=ST&service=xxx`` → 200 XML，解析出用户名

第 2、3 步可用 ``cas_require_service_ticket=False`` 跳过（CAS 未开放 service 校验时），
此时只要换到 TGT 即认为凭据有效，安全性略低但部署更省事。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.core.logging import get_logger
from app.models.enums import AuthSource

from .base import (
    IdentityResult,
    SSOProvider,
    SSOUnavailableError,
    SSOMisconfiguredError,
    _missing,
)

logger = get_logger(__name__)

CAS_NS = "{http://www.yale.edu/tp/cas}"


class CASProvider(SSOProvider):
    source = AuthSource.CAS
    provider_id = "cas"

    def __init__(self, settings: Any) -> None:
        super().__init__(settings)
        self.server_url = (settings.cas_server_url or "").rstrip("/")
        self.rest_path = settings.cas_rest_path or "/cas/v1/tickets"
        self.service_url = (settings.cas_service_url or "").rstrip("/")
        self.require_st = bool(settings.cas_require_service_ticket)

    def _validate_config(self) -> None:
        gaps = _missing({"cas_server_url": self.server_url})
        if gaps:
            raise SSOMisconfiguredError(f"CAS 配置缺失：{', '.join(gaps)}")
        if self.require_st and not self.service_url:
            raise SSOMisconfiguredError(
                "cas_require_service_ticket=True 时必须配置 cas_service_url"
            )

    def verify(self, username: str, password: str) -> IdentityResult | None:
        self._validate_config()
        tgt = self._grant_ticket(username, password)
        if tgt is None:
            return None
        if not self.require_st:
            return IdentityResult(
                external_id=username, username=username, raw={"tgt": tgt}
            )

        service_ticket = self._service_ticket(tgt)
        if service_ticket is None:
            # TGT 有效却换不出 ST，属于服务端异常，不能当成密码错误
            raise SSOUnavailableError("CAS 已通过认证，但未能换取服务票据（ST）")
        return self._validate_service_ticket(service_ticket, username)

    def _grant_ticket(self, username: str, password: str) -> str | None:
        """换取 TGT。凭据错误返回 None，其余故障抛异常。"""
        url = f"{self.server_url}{self.rest_path}"
        try:
            resp = httpx.post(
                url,
                data={"username": username, "password": password},
                timeout=self.timeout,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise SSOUnavailableError(f"CAS 服务不可达：{exc}") from exc

        if resp.status_code == 201:
            location = resp.headers.get("location") or resp.headers.get("Location")
            if not location:
                raise SSOUnavailableError("CAS 返回 201 但未给出 TGT 地址")
            return location
        if resp.status_code in (400, 401):
            # CAS REST 对错误口令返回 400
            logger.info("CAS 认证失败 username=%s status=%s", username, resp.status_code)
            return None
        raise SSOUnavailableError(f"CAS 换票接口异常：HTTP {resp.status_code}")

    def _service_ticket(self, tgt: str) -> str | None:
        try:
            resp = httpx.post(
                tgt, data={"service": self.service_url}, timeout=self.timeout
            )
        except httpx.HTTPError as exc:
            raise SSOUnavailableError(f"CAS 换取 ST 失败：{exc}") from exc
        if resp.status_code != 200:
            raise SSOUnavailableError(f"CAS 换取 ST 返回 HTTP {resp.status_code}")
        ticket = (resp.text or "").strip()
        return ticket or None

    def _validate_service_ticket(self, ticket: str, fallback_username: str) -> IdentityResult | None:
        url = f"{self.server_url}/cas/serviceValidate"
        try:
            resp = httpx.get(
                url,
                params={"ticket": ticket, "service": self.service_url},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise SSOUnavailableError(f"CAS 票据校验失败：{exc}") from exc
        if resp.status_code != 200:
            raise SSOUnavailableError(f"CAS 票据校验返回 HTTP {resp.status_code}")
        return parse_service_response(resp.text, fallback_username)

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "server_url": self.server_url,
            "rest_path": self.rest_path,
            "service_url": self.service_url or None,
            "require_service_ticket": self.require_st,
        }


def parse_service_response(xml_text: str, fallback_username: str) -> IdentityResult | None:
    """解析 CAS ``serviceValidate`` 响应。

    只认 ``authenticationSuccess`` ；``authenticationFailure`` 一律视为凭据无效。
    命名空间用 localname 匹配，避免不同 CAS 版本命名空间前缀不一致导致解析失败。
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SSOUnavailableError(f"CAS 响应不是合法 XML：{exc}") from exc

    def localname(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    for child in root:
        name = localname(child.tag)
        if name == "authenticationFailure":
            logger.info("CAS 票据校验未通过：%s", child.attrib.get("code"))
            return None
        if name != "authenticationSuccess":
            continue

        username = fallback_username
        attrs: dict[str, Any] = {}
        for node in child.iter():
            node_name = localname(node.tag)
            if node_name == "user" and node.text:
                username = node.text.strip()
            elif node_name == "attributes":
                for attr in node:
                    key = localname(attr.tag)
                    attrs[key] = attr.text.strip() if attr.text else None

        email = attrs.get("mail") or attrs.get("email")
        full_name = attrs.get("cn") or attrs.get("displayName") or attrs.get("name")
        return IdentityResult(
            external_id=username,
            username=username,
            full_name=full_name or None,
            email=email or None,
            raw=attrs,
        )
    return None
