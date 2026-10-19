"""通知服务：站内消息 + 邮件。

设计要点：
1. ``Notifier`` 为抽象基类，后续接入企业微信 / 钉钉只需实现同名子类并注册进 ``CompositeNotifier``；
2. 邮件未配置 SMTP 时自动降级为纯站内，不让调用方感知失败；
3. 邮件发送失败记录日志但不抛异常，避免阻塞主流程（统计/定时任务）。
"""

from __future__ import annotations

import smtplib
import ssl
from abc import ABC, abstractmethod
from email.message import EmailMessage
from typing import Iterable, Sequence

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import NotifyChannel
from app.models.organization import User
from app.models.system import Notification
from app.utils.week import utcnow

logger = get_logger(__name__)


class Notifier(ABC):
    """通知渠道抽象基类。"""

    channel: NotifyChannel

    @abstractmethod
    def send(self, user: User, title: str, content: str, link: str | None = None) -> bool:
        """发送单条通知，返回是否成功。"""


class InboxNotifier(Notifier):
    """站内消息。"""

    channel = NotifyChannel.inbox

    def __init__(self, db: Session) -> None:
        self.db = db

    def send(self, user: User, title: str, content: str, link: str | None = None) -> bool:
        self.db.add(
            Notification(
                user_id=user.id,
                title=title,
                content=content,
                channel=NotifyChannel.inbox,
                link=link,
                created_at=utcnow(),
            )
        )
        return True


class EmailNotifier(Notifier):
    """邮件通知（SMTP SSL/TLS）。

    账号走环境变量；未配置时 ``available`` 为 False，``send`` 直接返回 False。
    """

    channel = NotifyChannel.email

    @property
    def available(self) -> bool:
        return bool(settings.email_enabled and settings.smtp_host and settings.smtp_username)

    def send(self, user: User, title: str, content: str, link: str | None = None) -> bool:
        if not self.available:
            logger.debug("邮件通知未启用，跳过：user=%s", user.username)
            return False
        if not user.email:
            logger.warning("用户 %s 未配置邮箱，跳过邮件通知", user.username)
            return False

        body = content
        if link:
            body = f"{content}\n\n详情链接：{link}"

        msg = EmailMessage()
        msg["Subject"] = f"[{settings.smtp_from_name}] {title}"
        msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_username}>"
        msg["To"] = user.email
        msg.set_content(body)

        try:
            if settings.smtp_use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(
                    settings.smtp_host, settings.smtp_port, context=context, timeout=10
                ) as server:
                    server.login(settings.smtp_username, settings.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                    server.starttls(context=ssl.create_default_context())
                    server.login(settings.smtp_username, settings.smtp_password)
                    server.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("邮件发送失败 user=%s: %s", user.username, exc)
            return False
        return True


def notify(
    db: Session,
    users: Iterable[User] | Sequence[User],
    title: str,
    content: str,
    *,
    link: str | None = None,
    include_email: bool = True,
) -> int:
    """向一批用户发送通知（站内必发，邮件按配置）。

    :return: 实际成功写入站内消息的人数
    """
    inbox = InboxNotifier(db)
    emailer = EmailNotifier()
    count = 0
    for user in users:
        if inbox.send(user, title, content, link):
            count += 1
        if include_email:
            emailer.send(user, title, content, link)
    db.flush()
    return count


def send_email(to_email: str, subject: str, body: str) -> None:
    """发送单封邮件（用于连通性测试）。"""
    if not (settings.email_enabled and settings.smtp_host and settings.smtp_username):
        raise RuntimeError("邮件服务未启用或未配置 SMTP")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_username}>"
    msg["To"] = to_email
    msg.set_content(body)

    if settings.smtp_use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, context=context, timeout=10
        ) as server:
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
