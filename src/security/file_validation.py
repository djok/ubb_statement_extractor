"""File validation utilities for secure file handling.

Provides protection against:
- ZIP bomb attacks (excessive compression ratios)
- Path traversal attacks (../ in filenames)
- Oversized files
- Invalid filenames
"""

import hashlib
import io
import os
import re
import zipfile
from typing import Optional, Tuple


class FileValidator:
    """Validates files for security issues before processing."""

    # Size limits
    MAX_ZIP_SIZE = 10 * 1024 * 1024  # 10MB compressed
    MAX_UNCOMPRESSED_SIZE = 50 * 1024 * 1024  # 50MB uncompressed
    MAX_COMPRESSION_RATIO = 100  # Max 100:1 compression ratio (ZIP bomb detection)
    MAX_FILES_IN_ZIP = 10  # Maximum files allowed in ZIP

    # Filename validation
    SAFE_FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
    ALLOWED_EXTENSIONS = {".pdf", ".zip"}

    @classmethod
    def sanitize_filename(cls, filename: str) -> str:
        """Sanitize filename to prevent path traversal and injection attacks.

        Args:
            filename: Original filename from user input

        Returns:
            Sanitized filename safe for filesystem operations

        Raises:
            ValueError: If filename is invalid or contains dangerous characters
        """
        if not filename:
            raise ValueError("Filename cannot be empty")

        # Remove path components (prevent path traversal)
        filename = os.path.basename(filename)

        # Remove null bytes (prevent null byte injection)
        filename = filename.replace("\x00", "")

        # Remove path traversal sequences
        filename = filename.replace("..", "")
        filename = filename.replace("/", "")
        filename = filename.replace("\\", "")

        # Validate remaining characters
        if not cls.SAFE_FILENAME_PATTERN.match(filename):
            # Generate safe filename from hash if invalid
            safe_hash = hashlib.sha256(filename.encode()).hexdigest()[:16]
            # Try to preserve extension
            ext = ""
            for allowed_ext in cls.ALLOWED_EXTENSIONS:
                if filename.lower().endswith(allowed_ext):
                    ext = allowed_ext
                    break
            if ext:
                filename = f"{safe_hash}{ext}"
            else:
                raise ValueError(f"Invalid filename: contains disallowed characters")

        # Ensure filename is not empty after sanitization
        if not filename or filename in (".", ".."):
            raise ValueError("Invalid filename after sanitization")

        return filename

    @classmethod
    def validate_zip(cls, zip_data: bytes) -> Tuple[bool, Optional[str]]:
        """Validate ZIP file for security issues.

        Checks for:
        - File size limits
        - ZIP bomb (excessive compression ratio)
        - Path traversal in archived filenames
        - Maximum file count

        Args:
            zip_data: Raw ZIP file bytes

        Returns:
            Tuple of (is_valid, error_message)
            If valid, error_message is None
        """
        # Check compressed size
        if len(zip_data) > cls.MAX_ZIP_SIZE:
            return False, f"ZIP file too large: {len(zip_data):,} bytes (max: {cls.MAX_ZIP_SIZE:,})"

        try:
            with zipfile.ZipFile(io.BytesIO(zip_data), "r") as zf:
                # Check file count
                file_list = zf.namelist()
                if len(file_list) > cls.MAX_FILES_IN_ZIP:
                    return False, f"Too many files in ZIP: {len(file_list)} (max: {cls.MAX_FILES_IN_ZIP})"

                if len(file_list) == 0:
                    return False, "ZIP archive is empty"

                total_uncompressed = 0

                for info in zf.infolist():
                    # Check for path traversal in archived filenames
                    if ".." in info.filename:
                        return False, f"Path traversal detected in ZIP: {info.filename}"

                    if info.filename.startswith("/"):
                        return False, f"Absolute path in ZIP: {info.filename}"

                    if info.filename.startswith("\\"):
                        return False, f"Absolute path in ZIP: {info.filename}"

                    # Track total uncompressed size
                    total_uncompressed += info.file_size

                    # Check compression ratio (ZIP bomb detection)
                    if info.compress_size > 0:
                        ratio = info.file_size / info.compress_size
                        if ratio > cls.MAX_COMPRESSION_RATIO:
                            return (
                                False,
                                f"ZIP bomb detected: compression ratio {ratio:.0f}:1 "
                                f"exceeds maximum {cls.MAX_COMPRESSION_RATIO}:1",
                            )

                # Check total uncompressed size
                if total_uncompressed > cls.MAX_UNCOMPRESSED_SIZE:
                    return (
                        False,
                        f"Total uncompressed size too large: {total_uncompressed:,} bytes "
                        f"(max: {cls.MAX_UNCOMPRESSED_SIZE:,})",
                    )

        except zipfile.BadZipFile:
            return False, "Invalid ZIP file format"
        except Exception as e:
            return False, f"ZIP validation error: {str(e)}"

        return True, None

    @classmethod
    def validate_base64_size(cls, base64_data: str, max_decoded_size: int) -> Tuple[bool, Optional[str]]:
        """Validate base64 encoded data size before decoding.

        Args:
            base64_data: Base64 encoded string
            max_decoded_size: Maximum allowed decoded size in bytes

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Base64 encoded data is ~4/3 the size of decoded data
        # So decoded size is approximately len(base64_data) * 3 / 4
        estimated_size = len(base64_data) * 3 // 4

        if estimated_size > max_decoded_size:
            return (
                False,
                f"Encoded data too large: estimated {estimated_size:,} bytes "
                f"(max: {max_decoded_size:,})",
            )

        return True, None
