"""Security audit logging for UBB Statement Extractor.

Provides structured logging for:
- Authentication events (success/failure)
- Admin actions (reprocess, delete)
- Webhook events
- Security events (rate limiting, invalid signatures)
"""

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class AuditEvent:
    """Structured audit event."""

    timestamp: str
    event_type: str  # auth_success, auth_failure, admin_action, webhook, security
    severity: str  # info, warning, high, critical
    user_id: Optional[str]
    ip_address: Optional[str]
    action: str
    resource: Optional[str]
    details: Dict[str, Any]
    success: bool
    error: Optional[str] = None


class AuditLogger:
    """Structured audit logging with BigQuery support."""

    BUFFER_SIZE = 50  # Flush to BigQuery after this many events

    def __init__(self, log_dir: str = "/app/data"):
        """Initialize audit logger.

        Args:
            log_dir: Directory for audit log files
        """
        self.logger = logging.getLogger("security.audit")
        self._buffer: List[Dict] = []
        self._lock = threading.Lock()

        # Setup file handler
        log_path = Path(log_dir) / "audit.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        handler = logging.FileHandler(str(log_path))
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

        # Also log to console for debugging
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s - AUDIT - %(message)s")
        )
        self.logger.addHandler(console_handler)

    def _log(self, event: AuditEvent) -> None:
        """Log an audit event."""
        event_dict = asdict(event)
        event_json = json.dumps(event_dict, ensure_ascii=False)

        # Log to file
        self.logger.info(event_json)

        # Buffer for BigQuery batch insert
        with self._lock:
            self._buffer.append(event_dict)
            if len(self._buffer) >= self.BUFFER_SIZE:
                self._flush_to_bigquery()

    def _flush_to_bigquery(self) -> None:
        """Flush buffered events to BigQuery."""
        if not self._buffer:
            return

        events = self._buffer.copy()
        self._buffer.clear()

        try:
            from ..services.bigquery.client import BigQueryClient

            bq = BigQueryClient()
            errors = bq.client.insert_rows_json(
                bq.full_table_id("audit_log"), events
            )
            if errors:
                self.logger.error(f"BigQuery audit insert errors: {errors}")
        except Exception as e:
            # Log error but don't fail - audit logs are in file
            self.logger.error(f"Failed to flush audit to BigQuery: {e}")

    def flush(self) -> None:
        """Force flush buffered events to BigQuery."""
        with self._lock:
            self._flush_to_bigquery()

    # Authentication events

    def auth_success(
        self, user_id: str, ip: str, method: str = "zitadel"
    ) -> None:
        """Log successful authentication."""
        self._log(
            AuditEvent(
                timestamp=datetime.utcnow().isoformat(),
                event_type="auth_success",
                severity="info",
                user_id=user_id,
                ip_address=ip,
                action="login",
                resource=None,
                details={"method": method},
                success=True,
            )
        )

    def auth_failure(
        self, ip: str, reason: str, username: Optional[str] = None
    ) -> None:
        """Log failed authentication attempt."""
        self._log(
            AuditEvent(
                timestamp=datetime.utcnow().isoformat(),
                event_type="auth_failure",
                severity="warning",
                user_id=None,
                ip_address=ip,
                action="login_failed",
                resource=None,
                details={"reason": reason, "username": username},
                success=False,
                error=reason,
            )
        )

    # Admin actions

    def admin_action(
        self,
        user_id: str,
        action: str,
        details: Dict[str, Any],
        ip: Optional[str] = None,
    ) -> None:
        """Log administrative action."""
        self._log(
            AuditEvent(
                timestamp=datetime.utcnow().isoformat(),
                event_type="admin_action",
                severity="high",
                user_id=user_id,
                ip_address=ip,
                action=action,
                resource=None,
                details=details,
                success=True,
            )
        )

    def admin_action_critical(
        self,
        user_id: str,
        action: str,
        details: Dict[str, Any],
        ip: Optional[str] = None,
    ) -> None:
        """Log critical administrative action (e.g., data deletion)."""
        self._log(
            AuditEvent(
                timestamp=datetime.utcnow().isoformat(),
                event_type="admin_action",
                severity="critical",
                user_id=user_id,
                ip_address=ip,
                action=action,
                resource=None,
                details=details,
                success=True,
            )
        )

    # Webhook events

    def webhook_received(
        self,
        ip: str,
        email_id: int,
        valid_signature: bool,
        subject: Optional[str] = None,
    ) -> None:
        """Log webhook receipt."""
        self._log(
            AuditEvent(
                timestamp=datetime.utcnow().isoformat(),
                event_type="webhook",
                severity="info" if valid_signature else "warning",
                user_id=None,
                ip_address=ip,
                action="postal_webhook",
                resource=None,
                details={
                    "email_id": email_id,
                    "valid_signature": valid_signature,
                    "subject": subject,
                },
                success=valid_signature,
            )
        )

    def webhook_rejected(
        self, ip: str, reason: str, email_id: Optional[int] = None
    ) -> None:
        """Log rejected webhook."""
        self._log(
            AuditEvent(
                timestamp=datetime.utcnow().isoformat(),
                event_type="webhook",
                severity="warning",
                user_id=None,
                ip_address=ip,
                action="webhook_rejected",
                resource=None,
                details={"reason": reason, "email_id": email_id},
                success=False,
                error=reason,
            )
        )

    # Security events

    def security_event(
        self,
        ip: str,
        event: str,
        details: Dict[str, Any],
        severity: str = "high",
    ) -> None:
        """Log security-related event."""
        self._log(
            AuditEvent(
                timestamp=datetime.utcnow().isoformat(),
                event_type="security",
                severity=severity,
                user_id=None,
                ip_address=ip,
                action=event,
                resource=None,
                details=details,
                success=False,
            )
        )

    def rate_limit_exceeded(self, ip: str, endpoint: str) -> None:
        """Log rate limit exceeded event."""
        self.security_event(
            ip=ip,
            event="rate_limit_exceeded",
            details={"endpoint": endpoint},
            severity="warning",
        )

    def invalid_signature(self, ip: str, endpoint: str) -> None:
        """Log invalid signature event."""
        self.security_event(
            ip=ip,
            event="invalid_signature",
            details={"endpoint": endpoint},
            severity="high",
        )

    def file_validation_failed(
        self, ip: str, filename: str, reason: str
    ) -> None:
        """Log file validation failure."""
        self.security_event(
            ip=ip,
            event="file_validation_failed",
            details={"filename": filename, "reason": reason},
            severity="warning",
        )


# Global audit logger instance
audit = AuditLogger()
