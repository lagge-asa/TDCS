"""
Windows 服务封装 — pywin32

sc start ETLService  -> SvcStart -> main()
sc stop  ETLService  -> SvcStop  -> 优雅退出
"""

import logging
import os
import sys

logger = logging.getLogger(__name__)

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager

    class ETLService(win32serviceutil.ServiceFramework):
        _svc_name_ = "ETLService"
        _svc_display_name_ = "ETL Folder Monitor Service"
        _svc_description_ = "Monitors folders and processes ETL pipelines"

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._app = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self._stop_event)
            logger.info("ETLService stopping...")

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            self._run()

        def _run(self):
            from .main import bootstrap
            bootstrap(stop_event=self._stop_event)

    def main():
        win32serviceutil.HandleCommandLine(ETLService)

except ImportError:
    # 非 Windows 环境 (CI/测试)
    def main():
        from .main import bootstrap
        bootstrap()
