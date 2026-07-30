"""
告警通知 — 可扩展多通道架构

当前支持: webhook（通用）
预留接口: 企业微信（WeCom）、钉钉（DingTalk）、邮件（Email）

接入新渠道:
    1. 继承 AlertChannel，实现 send(title, message, level)
    2. 在 Alerter.__init__ 的 _CHANNEL_TYPES 注册
"""

import hashlib
import hmac
import json
import logging
import os
import re
import urllib.request
from abc import ABC, abstractmethod
from typing import List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 允许的 webhook 域名白名单（仅允许 HTTPS 的外部域名，阻断内网/云元数据地址）
_ALLOWED_WEBHOOK_DOMAINS = re.compile(
    r'^(qyapi\.weixin\.qq\.com|oapi\.dingtalk\.com|'
    r'hooks\.slack\.com|discord\.com/api/webhooks)$'
)
# 内网 / 云元数据服务地址黑名单
_BLOCKED_HOSTS = frozenset({
    '127.0.0.1', 'localhost', '0.0.0.0', '::1',
    '169.254.169.254',  # AWS / GCP / Azure 元数据
    'metadata.google.internal',
})
_BLOCKED_NETS = (
    (b'\x0a\x00\x00\x00', b'\x0a\xff\xff\xff'),       # 10.0.0.0/8
    (b'\xac\x10\x00\x00', b'\xac\x1f\xff\xff'),       # 172.16.0.0/12
    (b'\xc0\xa8\x00\x00', b'\xc0\xa8\xff\xff'),       # 192.168.0.0/16
)


def _validate_webhook_url(url: str) -> None:
    """校验 webhook URL：仅允许 HTTPS 已知域名，拒绝内网/元数据地址."""
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        raise ValueError(f"Webhook URL must use HTTPS: {url}")
    hostname = parsed.hostname or ''
    if hostname in _BLOCKED_HOSTS:
        raise ValueError(f"Webhook URL blocked (internal): {url}")
    # 检查 IP 是否属于内网段
    import ipaddress
    try:
        ip = ipaddress.ip_address(hostname)
        ip_bytes = ip.packed
        for lo, hi in _BLOCKED_NETS:
            if lo <= ip_bytes <= hi:
                raise ValueError(f"Webhook URL blocked (private IP): {url}")
    except ValueError:
        pass  # 不是 IP 地址，继续域名白名单检查
    if not _ALLOWED_WEBHOOK_DOMAINS.search(hostname):
        raise ValueError(f"Webhook domain not in allowlist: {hostname}")


def _sign_payload(payload: bytes, secret: str) -> str:
    """HMAC-SHA256 签名，通用 hex 格式（用于 X-Signature 头）."""
    return hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()


def _dingtalk_sign(secret: str) -> tuple:
    """钉钉加签：timestamp + '\n' + secret → HMAC-SHA256 → Base64.
    返回 (timestamp, sign) 用于 URL 查询参数。"""
    import time as _time
    timestamp = str(round(_time.time() * 1000))
    sign = hmac.new(
        secret.encode(),
        f"{timestamp}\n{secret}".encode(),
        hashlib.sha256,
    ).digest()
    import base64
    return timestamp, base64.b64encode(sign).decode()


def _sanitize_path(file_path: str) -> str:
    """脱敏绝对路径：仅保留文件名，避免泄露服务器目录结构."""
    return os.path.basename(file_path)


# ─────────────────────────────────────────────────────────────────────────────
# 通道基类
# ─────────────────────────────────────────────────────────────────────────────

class AlertChannel(ABC):
    """所有告警通道的抽象基类."""

    @abstractmethod
    def send(self, title: str, message: str, level: str = "warning") -> None:
        """发送告警。实现中应自行处理异常，不向上抛出。"""


class WebhookChannel(AlertChannel):
    """Webhook 通道，支持通用 JSON 和企业微信两种 payload 格式."""

    def __init__(self, cfg):
        _validate_webhook_url(cfg.webhook)
        self._url = cfg.webhook
        self._secret: str = getattr(cfg, 'secret', '')
        self._is_wecom: bool = getattr(cfg, 'type', '') == 'wecom'

    def send(self, title: str, message: str, level: str = "warning") -> None:
        content = f"[ETL {level.upper()}] {title}\n{message}"
        payload = json.dumps(
            {"msgtype": "text", "text": {"content": content}}
            if self._is_wecom else
            {"title": title, "message": message, "level": level}
        ).encode()
        headers = {"Content-Type": "application/json"}
        if self._secret and not self._is_wecom:
            headers["X-Signature"] = _sign_payload(payload, self._secret)
        req = urllib.request.Request(
            self._url,
            data=payload,
            headers=headers,
        )
        urllib.request.urlopen(req, timeout=10)


class DingTalkChannel(AlertChannel):
    """钉钉自定义机器人通道，支持加签和 markdown 消息."""

    def __init__(self, cfg):
        _validate_webhook_url(cfg.webhook)
        self._url = cfg.webhook
        self._secret: str = getattr(cfg, 'secret', '')

    def send(self, title: str, message: str, level: str = "warning") -> None:
        url = self._url
        if self._secret:
            timestamp, sign = _dingtalk_sign(self._secret)
            sep = '&' if '?' in url else '?'
            url = f"{url}{sep}timestamp={timestamp}&sign={sign}"
        level_emoji = {"error": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(level, "📢")
        payload = json.dumps({
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"## {level_emoji} {title}\n\n{message}\n\n> ETL Service Alert"
            }
        }).encode()
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=payload, headers=headers)
        urllib.request.urlopen(req, timeout=10)


# ─────────────────────────────────────────────────────────────────────────────
# 告警管理器
# ─────────────────────────────────────────────────────────────────────────────

_CHANNEL_TYPES = {
    "webhook": WebhookChannel,
    "wecom":   WebhookChannel,  # 企业微信，通过 type 字段自动切换 payload 格式
    "dingtalk": DingTalkChannel,  # 钉钉自定义机器人，支持加签 + markdown
}


class Alerter:
    """告警管理器，支持多通道并行发送."""

    def __init__(self, config):
        """config: AppConfig.monitoring.alerting"""
        self._cfg = config
        self._channels: List[AlertChannel] = []
        for ch in self._cfg.channels:
            cls = _CHANNEL_TYPES.get(ch.type)
            if cls:
                try:
                    self._channels.append(cls(ch))
                except ValueError as e:
                    logger.error("Skip invalid alert channel [%s]: %s",
                                 ch.type, e)
            else:
                logger.warning("Unknown alert channel type: %s", ch.type)

    def send_alert(self, title: str, message: str,
                   level: str = "warning") -> None:
        """向所有已配置通道发送告警。告警未启用时静默跳过。"""
        if not self._cfg.enabled:
            return
        for ch in self._channels:
            try:
                ch.send(title, message, level)
            except Exception as e:
                logger.error("Alert send failed [%s]: %s",
                             type(ch).__name__, e)

    def check_quality_alert(self, task_id: str, score: float) -> None:
        """质量评分低于阈值时触发告警。"""
        min_score = self._cfg.rules.quality_score_min
        if score < min_score:
            self.send_alert(
                f"数据质量低: {task_id}",
                f"质量评分 {score:.1f} < 阈值 {min_score}",
                level="warning",
            )

    def notify_pipeline_failure(self, task_id: str,
                                 file_path: str, error: str) -> None:
        """Pipeline 致命错误时通知（由 FileProcessor 调用）."""
        self.send_alert(
            f"文件处理失败: {task_id}",
            f"文件: {_sanitize_path(file_path)}\n错误: {error}",
            level="error",
        )

    def notify_dead_letter(self, task_id: str, file_path: str) -> None:
        """文件进入死信目录时通知。"""
        self.send_alert(
            f"文件进入死信: {task_id}",
            f"已超过最大重试次数，文件移入死信目录\n{_sanitize_path(file_path)}",
            level="error",
        )
