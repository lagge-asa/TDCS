"""
告警通知 — 可扩展多通道架构

当前支持: webhook（通用）
预留接口: 企业微信（WeCom）、钉钉（DingTalk）、邮件（Email）

接入新渠道:
    1. 继承 AlertChannel，实现 send(title, message, level)
    2. 在 Alerter.__init__ 的 _CHANNEL_TYPES 注册
"""

import json
import logging
import urllib.request
from abc import ABC, abstractmethod
from typing import List

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 通道基类
# ─────────────────────────────────────────────────────────────────────────────

class AlertChannel(ABC):
    """所有告警通道的抽象基类."""

    @abstractmethod
    def send(self, title: str, message: str, level: str = "warning") -> None:
        """发送告警。实现中应自行处理异常，不向上抛出。"""


class WebhookChannel(AlertChannel):
    """通用 Webhook 通道（POST JSON）."""

    def __init__(self, cfg):
        self._url = cfg.webhook

    def send(self, title: str, message: str, level: str = "warning") -> None:
        payload = json.dumps({
            "title": title,
            "message": message,
            "level": level,
        }).encode()
        req = urllib.request.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)


class WeCom(AlertChannel):
    """企业微信群机器人通道（预留，待实现）.

    配置示例:
        channels:
          - type: wecom
            webhook: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"

    企微文档: https://developer.work.weixin.qq.com/document/path/91770
    """

    def __init__(self, cfg):
        self._url = cfg.webhook

    def send(self, title: str, message: str, level: str = "warning") -> None:
        # TODO: 实现企业微信消息卡片格式
        # 当前降级为纯文本
        payload = json.dumps({
            "msgtype": "text",
            "text": {"content": f"[ETL {level.upper()}] {title}\n{message}"},
        }).encode()
        req = urllib.request.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)


# ─────────────────────────────────────────────────────────────────────────────
# 告警管理器
# ─────────────────────────────────────────────────────────────────────────────

_CHANNEL_TYPES = {
    "webhook": WebhookChannel,
    "wecom":   WeCom,
    # "dingtalk": DingTalkChannel,  # 如需接入钉钉，在此注册
    # "email":    EmailChannel,
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
                self._channels.append(cls(ch))
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

    def check_failed_files_alert(self, task_id: str, count: int) -> None:
        """失败文件数超过阈值时触发告警。"""
        threshold = self._cfg.rules.failed_files_threshold
        if count >= threshold:
            self.send_alert(
                f"文件失败率高: {task_id}",
                f"失败文件数 {count} >= 阈值 {threshold}",
                level="error",
            )

    def notify_pipeline_failure(self, task_id: str,
                                 file_path: str, error: str) -> None:
        """Pipeline 致命错误时通知（由 FileProcessor 调用）。"""
        self.send_alert(
            f"文件处理失败: {task_id}",
            f"文件: {file_path}\n错误: {error}",
            level="error",
        )

    def notify_dead_letter(self, task_id: str, file_path: str) -> None:
        """文件进入死信目录时通知。"""
        self.send_alert(
            f"文件进入死信: {task_id}",
            f"已超过最大重试次数，文件移入死信目录\n{file_path}",
            level="error",
        )
