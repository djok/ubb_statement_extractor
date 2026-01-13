"""Pydantic schemas for API requests and responses."""

from typing import Optional, Union

from pydantic import BaseModel, ConfigDict


class PostalAttachment(BaseModel):
    """Attachment from Postal webhook."""

    filename: str
    content_type: str
    size: int
    data: str  # Base64 encoded

    model_config = ConfigDict(extra="allow")


class PostalWebhook(BaseModel):
    """Postal webhook payload for incoming emails.

    Based on real Postal webhook analysis (2026-01-11).
    """

    id: int
    rcpt_to: str
    mail_from: str
    subject: Optional[str] = None
    timestamp: Union[int, float]  # Can be float like 1768140573.649431

    # Message metadata
    token: Optional[str] = None
    message_id: Optional[str] = None
    size: Optional[str] = None  # String in Postal response
    spam_status: Optional[str] = None
    bounce: bool = False
    received_with_ssl: Optional[bool] = None

    # Email headers
    to: Optional[str] = None  # Full To header with name
    cc: Optional[str] = None
    from_header: Optional[str] = None  # "from" is reserved, use alias
    date: Optional[str] = None  # RFC 2822 date string
    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    auto_submitted: Optional[str] = None
    reply_to: Optional[str] = None

    # Body content
    plain_body: Optional[str] = None
    html_body: Optional[str] = None

    # Attachments
    attachment_quantity: int = 0
    attachments: list[PostalAttachment] = []

    # Allow extra fields we don't know about yet
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ProcessingResult(BaseModel):
    """Result of processing an email with attachment."""

    success: bool
    message: str
    email_id: int
    zip_filename: Optional[str] = None
    json_filename: Optional[str] = None
    transactions_count: Optional[int] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str


class WebhookResponse(BaseModel):
    """Response for webhook endpoint."""

    status: str
    timestamp: str
    message: Optional[str] = None


class CloudflareEmailWebhook(BaseModel):
    """Cloudflare Email Worker webhook payload.

    This is sent by a Cloudflare Worker that receives emails
    via Email Routing and forwards them to this endpoint.
    """

    sender: str  # Email sender address
    subject: Optional[str] = None
    raw_body: str  # Full raw email content (RFC 5322)
    received_at: str  # ISO 8601 timestamp

    # Optional metadata
    recipient: Optional[str] = None  # Original recipient address
    headers: Optional[dict] = None  # Parsed email headers

    model_config = ConfigDict(extra="allow")
