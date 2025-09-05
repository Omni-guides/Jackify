"""
GUI Utilities for Jackify Frontend
"""
import re

ANSI_COLOR_MAP = {
    '30': 'black', '31': 'red', '32': 'green', '33': 'yellow', '34': 'blue', '35': 'magenta', '36': 'cyan', '37': 'white',
    '90': 'gray', '91': 'lightcoral', '92': 'lightgreen', '93': 'khaki', '94': 'lightblue', '95': 'violet', '96': 'lightcyan', '97': 'white'
}
ANSI_RE = re.compile(r'\x1b\[(\d+)(;\d+)?m')

def ansi_to_html(text):
    """Convert ANSI color codes to HTML"""
    result = ''
    last_end = 0
    color = None
    for match in ANSI_RE.finditer(text):
        start, end = match.span()
        code = match.group(1)
        if start > last_end:
            chunk = text[last_end:start]
            if color:
                result += f'<span style="color:{color}">{chunk}</span>'
            else:
                result += chunk
        if code == '0':
            color = None
        elif code in ANSI_COLOR_MAP:
            color = ANSI_COLOR_MAP[code]
        last_end = end
    if last_end < len(text):
        chunk = text[last_end:]
        if color:
            result += f'<span style="color:{color}">{chunk}</span>'
        else:
            result += chunk
    result = result.replace('\n', '<br>')
    return result 