"""FastAPI application for receiving emails from Postal."""

import hashlib
import hmac
import json
import logging
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyzipper
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from ..extractor import UBBStatementExtractor
from ..security import audit
from ..security.headers import SecurityHeadersMiddleware
from ..services.bigquery.client import BigQueryClient
from ..services.bigquery.importer import BigQueryImporter
from ..services.bigquery.idempotency import generate_file_checksum
from ..services.bigquery.exceptions import DuplicateStatementError, BigQueryError
from ..services.processor import EmailProcessor
from .schemas import CloudflareEmailWebhook, HealthResponse, PostalWebhook

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize processor
processor = EmailProcessor()

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# API key security for admin endpoints
api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def verify_postal_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify Postal webhook HMAC-SHA256 signature.

    Args:
        body: Raw request body bytes
        signature: Signature from X-Postal-Signature header
        secret: HMAC secret key

    Returns:
        True if signature is valid
    """
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


async def verify_admin_key(api_key: str = Depends(api_key_header)) -> bool:
    """Verify admin API key for protected endpoints.

    Args:
        api_key: API key from X-Admin-Key header

    Returns:
        True if valid

    Raises:
        HTTPException: If key is missing or invalid
    """
    expected = os.getenv("ADMIN_API_KEY")
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_API_KEY not configured"
        )
    if not api_key or not hmac.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing admin API key"
        )
    return True


app = FastAPI(
    title="UBB Statement Extractor API",
    description="API for receiving bank statement emails from Postal and extracting data",
    version="2.0.0",
)

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Add rate limiter state
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded errors."""
    client_ip = request.client.host if request.client else "unknown"
    audit.security_event(
        ip=client_ip,
        event="rate_limit_exceeded",
        details={"path": str(request.url.path), "limit": str(exc.detail)}
    )
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please try again later."}
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(status="ok")


@app.post("/webhook/postal")
@limiter.limit("60/minute")
async def postal_webhook(request: Request) -> dict[str, Any]:
    """
    Receive emails from Postal mail server.

    Processes ZIP attachments containing UBB bank statement PDFs
    and extracts transaction data to JSON.

    Security layers:
    - Rate limiting (60/minute)
    - Optional HMAC signature validation (if POSTAL_WEBHOOK_SECRET is set)
    - IP logging for audit trail
    - Cloudflare Tunnel provides additional protection
    """
    client_ip = request.client.host if request.client else "unknown"

    # Read raw body for signature verification
    body = await request.body()

    # Optional HMAC signature verification
    # Postal doesn't natively support signatures, but we support it if configured
    # (e.g., via a proxy that adds signatures)
    secret = os.getenv("POSTAL_WEBHOOK_SECRET")
    if secret:
        signature = request.headers.get("X-Postal-Signature", "")
        if not verify_postal_signature(body, signature, secret):
            audit.webhook_received(ip=client_ip, email_id=0, valid_signature=False)
            logger.warning(f"Invalid webhook signature from {client_ip}")
            raise HTTPException(
                status_code=401,
                detail="Invalid webhook signature"
            )
    else:
        # No secret configured - rely on other security layers
        # Log a warning on first request only
        if not getattr(postal_webhook, "_no_secret_warned", False):
            logger.warning(
                "POSTAL_WEBHOOK_SECRET not configured. "
                "Webhook endpoint relies on rate limiting and Cloudflare Tunnel for security."
            )
            postal_webhook._no_secret_warned = True

    # Parse JSON body
    try:
        data = json.loads(body)
    except Exception as e:
        logger.error(f"Failed to parse JSON body: {e}")
        return {"status": "error", "message": "Invalid JSON body"}

    # Log basic info
    email_id = data.get("id", 0)
    subject = data.get("subject", "N/A")
    attachments = data.get("attachments", [])

    # Log successful webhook receipt
    audit.webhook_received(ip=client_ip, email_id=email_id, valid_signature=True)
    logger.info(f"Received webhook: id={email_id}, subject={subject}")
    logger.info(f"Attachments: {len(attachments)}")

    # Parse webhook payload
    try:
        webhook = PostalWebhook(**data)
    except Exception as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        return {
            "status": "error",
            "message": f"Invalid webhook payload: {str(e)}",
            "email_id": email_id,
        }

    # Process email
    result = processor.process(webhook)

    # Convert dataclass result to dict for JSON response
    return {
        "status": "success" if result.success else "error",
        "message": result.message,
        "email_id": result.email_id,
        "total_transactions": result.total_transactions,
        "processed_zips": [asdict(z) for z in result.processed_zips],
    }


@app.post("/webhook/cloudflare")
@limiter.limit("60/minute")
async def cloudflare_webhook(request: Request) -> dict[str, Any]:
    """
    Receive emails from Cloudflare Email Workers.

    This endpoint receives webhook calls from a Cloudflare Worker
    that intercepts emails via Email Routing and forwards them here.

    The Worker should POST JSON with:
    - sender: Email sender address
    - subject: Email subject
    - raw_body: Full raw email content (RFC 5322 format)
    - received_at: ISO 8601 timestamp

    Security layers:
    - Rate limiting (60/minute)
    - Optional shared secret validation (if CLOUDFLARE_WEBHOOK_SECRET is set)
    - Cloudflare Tunnel provides additional protection
    """
    client_ip = request.client.host if request.client else "unknown"

    # Read raw body
    body = await request.body()

    # Optional shared secret verification
    secret = os.getenv("CLOUDFLARE_WEBHOOK_SECRET")
    if secret:
        auth_header = request.headers.get("Authorization", "")
        expected = f"Bearer {secret}"
        if not hmac.compare_digest(auth_header, expected):
            audit.webhook_received(ip=client_ip, email_id=0, valid_signature=False)
            logger.warning(f"Invalid Cloudflare webhook secret from {client_ip}")
            raise HTTPException(
                status_code=401,
                detail="Invalid webhook secret"
            )

    # Parse JSON body
    try:
        data = json.loads(body)
    except Exception as e:
        logger.error(f"Failed to parse JSON body: {e}")
        return {"status": "error", "message": "Invalid JSON body"}

    # Parse webhook payload
    try:
        webhook = CloudflareEmailWebhook(**data)
    except Exception as e:
        logger.error(f"Failed to parse Cloudflare webhook payload: {e}")
        return {
            "status": "error",
            "message": f"Invalid webhook payload: {str(e)}",
        }

    # Log receipt
    audit.webhook_received(ip=client_ip, email_id=hash(webhook.received_at) % 1000000, valid_signature=True)
    logger.info(f"Received Cloudflare webhook: from={webhook.sender}, subject={webhook.subject}")

    # Convert raw email to Postal-like format for processor
    # Parse the raw email to extract attachments
    import email
    from email import policy
    import base64

    try:
        msg = email.message_from_string(webhook.raw_body, policy=policy.default)

        attachments = []
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                filename = part.get_filename() or "attachment"
                content_type = part.get_content_type()
                payload = part.get_payload(decode=True)
                if payload:
                    attachments.append({
                        "filename": filename,
                        "content_type": content_type,
                        "size": len(payload),
                        "data": base64.b64encode(payload).decode("utf-8"),
                    })

        # Create a Postal-like webhook object for the processor
        postal_data = {
            "id": hash(webhook.received_at) % 1000000,
            "rcpt_to": webhook.recipient or "",
            "mail_from": webhook.sender,
            "subject": webhook.subject or msg.get("Subject", ""),
            "timestamp": 0,  # Will be parsed from received_at
            "attachments": attachments,
            "attachment_quantity": len(attachments),
            "plain_body": "",
            "html_body": "",
        }

        # Extract plain/html body
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    postal_data["plain_body"] = part.get_content() or ""
                elif content_type == "text/html":
                    postal_data["html_body"] = part.get_content() or ""
        else:
            postal_data["plain_body"] = msg.get_content() or ""

        postal_webhook = PostalWebhook(**postal_data)

    except Exception as e:
        logger.error(f"Failed to parse raw email: {e}")
        return {
            "status": "error",
            "message": f"Failed to parse email: {str(e)}",
        }

    # Process email using existing processor
    result = processor.process(postal_webhook)

    from dataclasses import asdict
    return {
        "status": "success" if result.success else "error",
        "message": result.message,
        "email_id": result.email_id,
        "total_transactions": result.total_transactions,
        "processed_zips": [asdict(z) for z in result.processed_zips],
    }


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "UBB Statement Extractor API",
        "version": "2.0.0",
        "endpoints": {
            "health": "/health",
            "webhook_postal": "/webhook/postal",
            "webhook_cloudflare": "/webhook/cloudflare",
            "reprocess": "/admin/reprocess (POST)",
        },
    }


# Admin endpoints for reprocessing

def extract_zip(zip_path: Path, password: str, temp_dir: str) -> str:
    """Extract PDF from password-protected ZIP file."""
    with pyzipper.AESZipFile(str(zip_path), "r") as zf:
        zf.setpassword(password.encode())
        pdf_files = [name for name in zf.namelist() if name.lower().endswith(".pdf")]
        if not pdf_files:
            raise ValueError("No PDF file found in ZIP archive")
        pdf_name = pdf_files[0]
        zf.extract(pdf_name, temp_dir)
        return os.path.join(temp_dir, pdf_name)


def process_single_zip(
    zip_path: Path,
    password: str,
    json_output_dir: Path,
    importer: BigQueryImporter,
    force: bool = False,
) -> dict:
    """Process a single ZIP file: extract PDF, parse, save JSON, upload to GCS, import to BigQuery."""
    temp_dir = None
    result = {
        "filename": zip_path.name,
        "status": "error",
        "message": "",
        "statement_id": None,
        "transactions": 0,
    }

    try:
        # Read ZIP data for GCS upload
        zip_data = zip_path.read_bytes()

        # Extract PDF from ZIP
        temp_dir = tempfile.mkdtemp()
        pdf_path = extract_zip(zip_path, password, temp_dir)

        # Read PDF data for GCS upload
        pdf_data = Path(pdf_path).read_bytes()

        # Parse PDF
        extractor = UBBStatementExtractor(pdf_path)
        statement = extractor.parse()

        result["iban"] = statement.statement.iban
        result["date"] = str(statement.statement.statement_date)
        result["transactions"] = len(statement.transactions)

        # Save JSON
        json_filename = f"{zip_path.stem}.json"
        json_path = json_output_dir / json_filename
        json_content = statement.to_json(indent=2)

        json_output_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json_content, encoding="utf-8")

        # Upload to GCS if enabled
        gcs_pdf_path = None
        gcs_json_path = None
        gcs_zip_path = None

        if os.getenv("GCS_BUCKET"):
            try:
                from ..services.storage import StatementUploader
                uploader = StatementUploader()
                iban = statement.statement.iban
                stmt_date = statement.statement.statement_date

                upload_result = uploader.upload_all(
                    iban=iban,
                    statement_date=stmt_date,
                    pdf_data=pdf_data,
                    json_data=json_content,
                    zip_data=zip_data,
                )

                gcs_pdf_path = upload_result.pdf_path
                gcs_json_path = upload_result.json_path
                gcs_zip_path = upload_result.zip_path
                logger.info(f"Uploaded to GCS: {iban}/{stmt_date}")
            except Exception as e:
                logger.warning(f"GCS upload failed (continuing anyway): {e}")

        # Import to BigQuery
        checksum = generate_file_checksum(json_content.encode("utf-8"))

        try:
            statement_id = importer.import_statement(
                statement=statement,
                source_filename=json_filename,
                source_checksum=checksum,
                gcs_pdf_path=gcs_pdf_path,
                gcs_json_path=gcs_json_path,
                gcs_zip_path=gcs_zip_path,
            )
            result["status"] = "success"
            result["statement_id"] = statement_id
            result["message"] = "Imported successfully"
        except DuplicateStatementError as e:
            if force:
                # Delete existing and re-import
                from ..services.bigquery.idempotency import generate_statement_id
                stmt_id = generate_statement_id(statement.statement)
                bq = BigQueryClient()
                try:
                    bq.delete_statement(stmt_id)

                    statement_id = importer.import_statement(
                        statement=statement,
                        source_filename=json_filename,
                        source_checksum=checksum,
                        gcs_pdf_path=gcs_pdf_path,
                        gcs_json_path=gcs_json_path,
                        gcs_zip_path=gcs_zip_path,
                    )
                    result["status"] = "replaced"
                    result["statement_id"] = statement_id
                    result["message"] = "Replaced existing statement"
                except Exception as delete_error:
                    if "streaming buffer" in str(delete_error):
                        result["status"] = "streaming_buffer"
                        result["message"] = "Cannot replace: data is in BigQuery streaming buffer (wait ~90 min)"
                    else:
                        raise
            else:
                result["status"] = "duplicate"
                result["message"] = str(e)

    except Exception as e:
        result["message"] = str(e)
        logger.exception(f"Error processing {zip_path.name}: {e}")

    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

    return result


@app.post("/admin/reprocess")
@limiter.limit("5/hour")
async def reprocess_zips(
    request: Request,
    force: bool = True,
    _: bool = Depends(verify_admin_key)
) -> dict:
    """
    Reprocess all ZIP files in /app/data/zip.

    Requires X-Admin-Key header with valid API key.

    Args:
        force: If True, delete existing statements and re-import.
               If False, skip duplicates.

    Returns:
        Summary of reprocessed files.
    """
    # Log admin action
    client_ip = request.client.host if request.client else "unknown"
    audit.admin_action(
        user_id="admin",
        ip=client_ip,
        action="reprocess_zips",
        details={"force": force}
    )

    password = os.getenv("PDF_PASSWORD", "")
    if not password:
        raise HTTPException(status_code=500, detail="PDF_PASSWORD not configured")

    zip_dir = Path("/app/data/zip")
    json_dir = Path("/app/data/json")

    if not zip_dir.exists():
        raise HTTPException(status_code=404, detail=f"ZIP directory not found: {zip_dir}")

    zip_files = sorted(zip_dir.glob("*.zip"))
    if not zip_files:
        return {"status": "ok", "message": "No ZIP files found", "files": []}

    importer = BigQueryImporter()
    results = []

    for zip_path in zip_files:
        logger.info(f"Reprocessing: {zip_path.name}")
        result = process_single_zip(
            zip_path=zip_path,
            password=password,
            json_output_dir=json_dir,
            importer=importer,
            force=force,
        )
        results.append(result)

    summary = {
        "total": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "replaced": sum(1 for r in results if r["status"] == "replaced"),
        "duplicate": sum(1 for r in results if r["status"] == "duplicate"),
        "streaming_buffer": sum(1 for r in results if r["status"] == "streaming_buffer"),
        "error": sum(1 for r in results if r["status"] == "error"),
    }

    return {
        "status": "ok",
        "summary": summary,
        "files": results,
    }


@app.delete("/admin/data")
@limiter.limit("1/day")
async def truncate_all_data(
    request: Request,
    confirm: str = "",
    _: bool = Depends(verify_admin_key)
) -> dict:
    """
    Truncate ALL data from BigQuery tables.
    Uses TRUNCATE which is faster and ignores streaming buffer.

    Requires X-Admin-Key header with valid API key.

    Args:
        confirm: Must be "DELETE_ALL" to confirm deletion.

    Returns:
        Status of truncated tables.
    """
    if confirm != "DELETE_ALL":
        raise HTTPException(
            status_code=400,
            detail="Must confirm with ?confirm=DELETE_ALL"
        )

    # Log critical admin action
    client_ip = request.client.host if request.client else "unknown"
    audit.admin_action(
        user_id="admin",
        ip=client_ip,
        action="truncate_all_data",
        details={"confirm": confirm}
    )
    logger.warning(f"CRITICAL: Truncating all data requested from {client_ip}")

    bq = BigQueryClient()
    results = bq.truncate_all_tables()

    return {
        "status": "ok",
        "truncated": results,
    }
