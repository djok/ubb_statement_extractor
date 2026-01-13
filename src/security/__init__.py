"""Security module for UBB Statement Extractor.

Provides:
- File validation (ZIP bomb, path traversal protection)
- Audit logging
- Security headers middleware
- Zitadel OAuth2/OIDC integration
- Authentication helpers
"""

from .file_validation import FileValidator
from .audit import AuditLogger, audit
from .headers import SecurityHeadersMiddleware
from .zitadel import (
    ZitadelAuth,
    ZitadelAuthError,
    zitadel,
    get_current_user,
    get_admin_user,
    require_role,
)

__all__ = [
    "FileValidator",
    "AuditLogger",
    "audit",
    "SecurityHeadersMiddleware",
    "ZitadelAuth",
    "ZitadelAuthError",
    "zitadel",
    "get_current_user",
    "get_admin_user",
    "require_role",
]
