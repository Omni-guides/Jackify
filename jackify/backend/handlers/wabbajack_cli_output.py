"""Output filters for wabbajack-cli, shared by the GUI and CLI installers."""
import re

ANSI_RE = re.compile(rb'\x1b\[[0-9;?]*[ -/]*[@-~]')
_TS_PREFIX = r'(?:\d+:\d{2}:\d{2}(?:\.\d+)?\s+\[\w+\]\s+)?'
# Lines already shown as progress, or too chatty for the log view (Found SteamGame lists every
# game in the user's Steam library)
QUIET_LINE_RE = re.compile(
    r'^' + _TS_PREFIX + r'(?:'
    r'\[Downloading\]\s'
    r'|\[\s*\d+%\]\s'
    r'|[A-Za-z][A-Za-z ]*: .*\(\d+%(?:, [^)]*)?\)$'
    r'|Nexus API call finished'
    r'|Downloading Nexus File:'
    r'|Found SteamGame '
    r')'
)
DEBUG_LINE_RE = re.compile(r'^\d+:\d{2}:\d{2}(?:\.\d+)?\s+\[(?:DEBUG|TRACE)\]')
