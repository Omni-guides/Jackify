"""File progress parsing methods for ProgressParser (Mixin)."""

import logging
import re
from typing import Optional

from jackify.shared.progress_models import FileProgress, OperationType

logger = logging.getLogger(__name__)


class ProgressParserFilesMixin:
    """Mixin providing file progress parsing methods."""

    def _extract_file_progress(self, line: str) -> Optional[FileProgress]:
        """Extract file-level progress information."""
        if not line or not isinstance(line, str):
            return None
        if len(line) > 10000:
            return None
        if '\x00' in line:
            line = line.replace('\x00', '')

        file_progress_match = re.search(
            r'\[FILE_PROGRESS\]\s+(Downloading|Extracting|Validating|Installing|Converting|Building|Writing|Verifying|Completed|Checking existing):\s+(.+?)\s+\((\d+(?:\.\d+)?)%\)\s*(?:\[(.+?)\])?\s*(?:\((\d+)/(\d+)\))?',
            line,
            re.IGNORECASE
        )
        if file_progress_match:
            operation_str = file_progress_match.group(1).strip()
            filename = file_progress_match.group(2).strip()
            percent = float(file_progress_match.group(3))
            speed_str = file_progress_match.group(4).strip() if file_progress_match.group(4) else None
            counter_current = int(file_progress_match.group(5)) if file_progress_match.group(5) else None
            counter_total = int(file_progress_match.group(6)) if file_progress_match.group(6) else None

            operation_map = {
                'downloading': OperationType.DOWNLOAD,
                'extracting': OperationType.EXTRACT,
                'validating': OperationType.VALIDATE,
                'installing': OperationType.INSTALL,
                'building': OperationType.INSTALL,
                'writing': OperationType.INSTALL,
                'verifying': OperationType.VALIDATE,
                'checking existing': OperationType.VALIDATE,
                'converting': OperationType.INSTALL,
                'compiling': OperationType.INSTALL,
                'hashing': OperationType.VALIDATE,
                'completed': OperationType.UNKNOWN,
            }
            operation = operation_map.get(operation_str.lower(), OperationType.UNKNOWN)

            if counter_current and counter_total and not self._should_display_file(filename):
                file_progress = FileProgress(
                    filename="__phase_progress__",
                    operation=operation,
                    percent=percent,
                    speed=-1.0
                )
                file_progress._file_counter = (counter_current, counter_total)
                file_progress._hidden = True
                return file_progress

            if not self._should_display_file(filename):
                return None

            if operation_str.lower() == 'completed':
                percent = 100.0

            speed = -1.0
            if speed_str:
                speed = self._parse_speed_from_string(speed_str)
            file_progress = FileProgress(
                filename=filename,
                operation=operation,
                percent=percent,
                speed=speed
            )
            size_info = self._extract_data_info(line)
            if size_info:
                file_progress.current_size, file_progress.total_size = size_info

            if counter_current is not None and counter_total is not None:
                if operation_str.lower() == 'converting':
                    file_progress._texture_counter = (counter_current, counter_total)
                elif operation_str.lower() == 'building':
                    file_progress._bsa_counter = (counter_current, counter_total)
                else:
                    file_progress._file_counter = (counter_current, counter_total)

            return file_progress

        if re.search(r'\[.*?\]\s*(?:Downloading|Installing|Extracting)\s+(?:Mod|Files|Archives)', line, re.IGNORECASE):
            return None

        match = re.search(
            r'(?:Installing|Downloading|Extracting|Validating):\s*(.+?)\s*\((\d+(?:\.\d+)?)%\)'
            r'\s*(?:\[([^\]]+)\])?',
            line, re.IGNORECASE
        )
        if match:
            filename = match.group(1).strip()
            percent = float(match.group(2))
            speed_str = match.group(3)
            operation = self._detect_operation_from_line(line)
            file_progress = FileProgress(
                filename=filename,
                operation=operation,
                percent=percent
            )
            if speed_str:
                file_progress.speed = self._parse_speed_from_string(speed_str)
            size_info = self._extract_data_info(line)
            if size_info:
                file_progress.current_size, file_progress.total_size = size_info
            return file_progress

        match = re.search(r'(.+?\.(?:7z|zip|rar|bsa|dds|exe|esp|esm|esl|wabbajack))\s*[:-]\s*(\d+(?:\.\d+)?)%', line, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            percent = float(match.group(2))
            operation = self._detect_operation_from_line(line)
            file_progress = FileProgress(
                filename=filename,
                operation=operation,
                percent=percent
            )
            size_info = self._extract_data_info(line)
            if size_info:
                file_progress.current_size, file_progress.total_size = size_info
            return file_progress

        match = re.search(r'(.+?\.(?:7z|zip|rar|bsa|dds|exe|esp|esm|esl|wabbajack))\s*[\[@]\s*([^\]]+)\]?', line, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            speed_str = match.group(2).strip().rstrip(']')
            speed = self._parse_speed(speed_str)
            operation = self._detect_operation_from_line(line)
            file_progress = FileProgress(
                filename=filename,
                operation=operation,
                speed=speed
            )
            size_info = self._extract_data_info(line)
            if size_info:
                file_progress.current_size, file_progress.total_size = size_info
            return file_progress

        match = re.search(r'([A-Za-z0-9][^\s]*?[-_A-Za-z0-9]+\.(?:7z|zip|rar|bsa|dds|exe|esp|esm|esl|wabbajack))\s+(?:at|@|:|-)?\s*(\d+(?:\.\d+)?)%', line, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            percent = float(match.group(2))
            operation = self._detect_operation_from_line(line)
            return FileProgress(
                filename=filename,
                operation=operation,
                percent=percent
            )

        match = re.search(r'([A-Za-z0-9][^\s]*?[-_A-Za-z0-9]+\.(?:7z|zip|rar|bsa|dds|exe|esp|esm|esl|wabbajack))\s*[\(]?\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/?\s*of\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)', line, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            current_val = float(match.group(2))
            current_unit = match.group(3).upper()
            total_val = float(match.group(4))
            total_unit = match.group(5).upper()
            current_bytes = self._convert_to_bytes(current_val, current_unit)
            total_bytes = self._convert_to_bytes(total_val, total_unit)
            percent = (current_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0
            operation = self._detect_operation_from_line(line)
            return FileProgress(
                filename=filename,
                operation=operation,
                percent=percent,
                current_size=current_bytes,
                total_size=total_bytes
            )

        match = re.search(r'([A-Za-z0-9][^\s]*?[-_A-Za-z0-9]+\.(?:7z|zip|rar|bsa|dds|exe|esp|esm|esl|wabbajack))\s+(?:downloading|extracting|validating|installing)\s+at\s+(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\s*/s', line, re.IGNORECASE)
        if match:
            filename = match.group(1).strip()
            speed_val = float(match.group(2))
            speed_unit = match.group(3).upper()
            speed = self._convert_to_bytes(speed_val, speed_unit)
            operation = self._detect_operation_from_line(line)
            return FileProgress(
                filename=filename,
                operation=operation,
                speed=speed
            )

        return None

    def _parse_file_with_percent(self, match: re.Match) -> Optional[FileProgress]:
        """Parse file progress from percentage match."""
        filename = match.group(1).strip()
        percent = float(match.group(2))
        operation = OperationType.UNKNOWN
        return FileProgress(
            filename=filename,
            operation=operation,
            percent=percent
        )

    def _parse_file_with_speed(self, match: re.Match) -> Optional[FileProgress]:
        """Parse file progress from speed match."""
        filename = match.group(1).strip()
        speed_str = match.group(2).strip()
        speed = self._parse_speed(speed_str)
        operation = OperationType.UNKNOWN
        return FileProgress(
            filename=filename,
            operation=operation,
            speed=speed
        )

    def _detect_operation_from_line(self, line: str) -> OperationType:
        """Detect operation type from line content."""
        line_lower = line.lower()
        if 'download' in line_lower:
            return OperationType.DOWNLOAD
        elif 'extract' in line_lower:
            return OperationType.EXTRACT
        elif 'validat' in line_lower:
            return OperationType.VALIDATE
        elif 'install' in line_lower or 'build' in line_lower or 'convert' in line_lower:
            return OperationType.INSTALL
        else:
            return OperationType.UNKNOWN

    def _extract_completed_file(self, line: str) -> Optional[str]:
        """Extract filename from completion messages like 'Finished downloading filename.7z'."""
        match = re.search(
            r'Finished\s+(?:downloading|extracting|validating|installing)\s+(.+?)(?:\.\s|\.$|\s+Hash:)',
            line,
            re.IGNORECASE
        )
        if match:
            filename = match.group(1).strip()
            filename = filename.rstrip('. ')
            return filename
        return None
