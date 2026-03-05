"""
EMP Monitor Agent — Windows Service Wrapper

Allows the agent to run as a Windows Service that starts automatically on boot.

Usage:
    Install:  python service.py install
    Start:    python service.py start
    Stop:     python service.py stop
    Remove:   python service.py remove
    Debug:    python service.py debug
"""

import os
import sys
import logging

# Add this directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
except ImportError:
    print("ERROR: pywin32 is required. Install it with: pip install pywin32")
    sys.exit(1)

from main import EmpMonitorAgent, load_config, setup_logging


class EmpMonitorService(win32serviceutil.ServiceFramework):
    """Windows Service wrapper for the EMP Monitor Agent."""

    _svc_name_ = 'EmpMonitorAgent'
    _svc_display_name_ = 'EMP Monitor Agent'
    _svc_description_ = (
        'Employee monitoring agent - captures screenshots and tracks activity. '
        'Part of the EMP Monitor system.'
    )

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.agent = None

    def SvcStop(self):
        """Called when the service is asked to stop."""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self.agent:
            self.agent.stop()

    def SvcDoRun(self):
        """Called when the service starts."""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )

        try:
            config = load_config()
            setup_logging(config.get('log_level', 'INFO'))

            logger = logging.getLogger('emp_agent.service')
            logger.info("EMP Monitor Windows Service starting")

            self.agent = EmpMonitorAgent(config)
            self.agent.start()

        except Exception as e:
            logging.getLogger('emp_agent.service').error(
                f"Service failed: {e}", exc_info=True
            )
            servicemanager.LogErrorMsg(f"EMP Monitor Agent failed: {e}")


if __name__ == '__main__':
    if len(sys.argv) == 1:
        # Running as a service — let the service manager handle it
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(EmpMonitorService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # Running from command line (install/start/stop/remove/debug)
        win32serviceutil.HandleCommandLine(EmpMonitorService)
