#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jackify CLI Frontend Entry Point

New entry point for the CLI frontend that uses the refactored structure.
"""

import sys
import signal
import logging

from .main import JackifyCLI
from jackify.shared.logging import LoggingHandler
from jackify import __version__ as jackify_version

def _setup_cli_logging() -> logging.Logger:
    debug_mode = '--debug' in sys.argv or '-d' in sys.argv
    if not debug_mode:
        try:
            from jackify.backend.handlers.config_handler import ConfigHandler
            debug_mode = ConfigHandler().get('debug_mode', False)
        except Exception:
            pass
    return LoggingHandler().setup_application_logging(debug_mode)

root_logger = _setup_cli_logging()
root_logger.info("Jackify %s starting (CLI)", jackify_version)

def terminate_children(signum, frame):
    """Signal handler to terminate child processes on exit"""
    print("Received signal, shutting down...")
    try:
        from jackify.backend.handlers.subprocess_utils import kill_all_registered_process_groups
        kill_all_registered_process_groups()
    except Exception:
        pass
    sys.exit(0)

def main():
    """Main entry point for the CLI frontend"""
    # Set up signal handlers
    signal.signal(signal.SIGTERM, terminate_children)
    signal.signal(signal.SIGINT, terminate_children)

    try:
        cli = JackifyCLI()
        exit_code = cli.run()
        sys.exit(exit_code or 0)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        print(f"Fatal error: {e}")
        logging.exception("Fatal error in CLI frontend")
        sys.exit(1)

if __name__ == "__main__":
    main() 