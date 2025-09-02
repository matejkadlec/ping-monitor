#!/usr/bin/env python3
"""
Main entry point for the Ping Monitor application.
"""

from src.utils.instance_lock import is_already_running
from src.core.ping_monitor import PingMonitor


def main():
    """Main entry point"""
    try:
        # Check if an instance is already running
        if is_already_running():
            print("Another instance of Ping Monitor is already running.")
            return

        app = PingMonitor()
        app.run()
    except Exception as e:
        print(f"Failed to start Ping Monitor: {e}")
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
