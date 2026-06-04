"""
告警通知 — 钉钉/邮件/Webhook 多通道
"""

import json
import logging
import urllib.request
from typing import List

logger = logging.getLogger(__name__)


class Alerter:
    def __init__(self, config):
        """config: AppConfig.monitoring.alerting"""
        self._cfg = config

    def send_alert(self, title: str, message: str,
                   level: str = "warning") -> None:
        if not self._cfg.enabled:
            return
        for ch in self._cfg.channels:
            try:
                if ch.type == "dingtalk":
                    self._send_dingtalk(ch, title, message)
                elif ch.type == "webhook":
                    self._send_webhook(ch, title, message, level)
            except Exception as e:
                logger.error("Alert send failed [%s]: %s", ch.type, e)

    def check_quality_alert(self, task_id: str,
                             score: float) -> None:
        min_score = self._cfg.rules.quality_score_min
        if score < min_score:
            self.send_alert(
                f"Low Quality: {task_id}",
                f"Quality score {score:.1f} < threshold {min_score}",
                level="warning",
            )

    def check_failed_files_alert(self, task_id: str,
                                  count: int) -> None:
        threshold = self._cfg.rules.failed_files_threshold
        if count >= threshold:
            self.send_alert(
                f"High Failure Rate: {task_id}",
                f"Failed files {count} >= threshold {threshold}",
                level="error",
            )

    def _send_dingtalk(self, ch, title: str, msg: str) -> None:
        payload = json.dumps({
            "msgtype": "text",
            "text": {"content": f"[ETL Alert] {title}\n{msg}"},
        }).encode()
        req = urllib.request.Request(
            ch.webhook,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)

    def _send_webhook(self, ch, title: str, msg: str,
                       level: str) -> None:
        payload = json.dumps({
            "title": title, "message": msg, "level": level,
        }).encode()
        req = urllib.request.Request(
            ch.webhook,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
