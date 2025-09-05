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

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def terminate_children(signum, frame):
    """Signal handler to terminate child processes on exit"""
    print("Received signal, shutting down...")
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