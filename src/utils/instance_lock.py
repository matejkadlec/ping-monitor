"""
Instance lock utilities for preventing multiple application instances.
"""

import os
import atexit
import psutil


# Define lock file path globally for use in cleanup functions
LOCK_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "ping_monitor.lock",
)

# Flag to determine if this is the main running instance (to prevent lock file deletion on aborted starts)
IS_MAIN_INSTANCE = False


def cleanup_lock_file():
    """Delete the lock file if it exists, but only if this is the main running instance"""
    try:
        if IS_MAIN_INSTANCE and os.path.exists(LOCK_FILE_PATH):
            os.remove(LOCK_FILE_PATH)
            print("Lock file removed during cleanup")
    except Exception as e:
        print(f"Error removing lock file: {e}")


# Register the cleanup function to run at exit
atexit.register(cleanup_lock_file)


def is_already_running():
    """Check if another instance of this application is already running using a lock file"""
    try:
        # Try to create or check the lock file
        if os.path.exists(LOCK_FILE_PATH):
            # Check if the process with the stored PID is still running
            with open(LOCK_FILE_PATH, "r") as f:
                try:
                    pid = int(f.read().strip())
                    # Try to check if process exists without actually sending a signal
                    if psutil.pid_exists(pid):
                        # Process exists, check if it's a Python process (more reliable)
                        try:
                            process = psutil.Process(pid)
                            if "python" in process.name().lower():
                                return True
                        except psutil.NoSuchProcess:
                            pass  # Process doesn't exist anymore
                except (ValueError, psutil.Error):
                    # Invalid PID or process not found, we can reuse the lock file
                    pass

        # If we get here, either the lock file doesn't exist or the process is no longer running
        # Create/update the lock file with our PID
        with open(LOCK_FILE_PATH, "w") as f:
            f.write(str(os.getpid()))

        # Flag this as the main instance
        global IS_MAIN_INSTANCE
        IS_MAIN_INSTANCE = True

        return False
    except Exception as e:
        print(f"Warning: Lock file check failed: {e}")
        # If the lock check fails, assume we can run (better than preventing startup)
        return False
