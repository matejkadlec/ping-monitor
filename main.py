#!/usr/bin/env python3
"""
Main entry point for the Ping Monitor application.
"""

import logging
from src.utils.instance_lock import is_already_running
from src.utils.app_logger import configure_app_logging
from src.core.ping_monitor import PingMonitor


def main():
    """Main entry point"""
    try:
        configure_app_logging()
        logger = logging.getLogger(__name__)

        # Check if an instance is already running
        if is_already_running():
            logger.warning("Another instance of Ping Monitor is already running.")
            return

        app = PingMonitor()
        app.run()
    except Exception as e:
        logging.getLogger(__name__).exception("Failed to start Ping Monitor: %s", e)
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
