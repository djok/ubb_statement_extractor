# Cloudflare Email Worker - Email to Webhook Forwarder

This Worker receives emails via Cloudflare Email Routing and forwards them to your webhook endpoint.

## Why This Approach?

**Cloudflare Tunnel does NOT support SMTP traffic (port 25)** for receiving emails from the internet.

This solution uses Cloudflare Email Routing + Workers as a workaround:
1. Cloudflare receives emails on your domain (handles port 25)
2. Email Worker processes the email and extracts content
3. Worker sends HTTP POST to your webhook (works with Cloudflare Tunnel!)

## Architecture

```
External Mail Server (Gmail, Bank, etc.)
        │
        ▼ SMTP (port 25)
┌───────────────────────────┐
│  Cloudflare Email Routing │
│   (handles port 25)       │
└───────────────────────────┘
        │
        ▼ Internal
┌───────────────────────────┐
│   Cloudflare Worker       │
│   (this code)             │
└───────────────────────────┘
        │
        ▼ HTTPS (via Cloudflare Tunnel)
┌───────────────────────────┐
│  Your Docker Application  │
│  /webhook/cloudflare      │
└───────────────────────────┘
```

## Setup Instructions

### 1. Enable Email Routing

1. Go to Cloudflare Dashboard → Your Domain → Email → Email Routing
2. Click "Enable Email Routing"
3. Add MX records as instructed (Cloudflare will guide you)

### 2. Deploy the Worker

**Option A: Via Cloudflare Dashboard (Easiest)**

1. Go to Cloudflare Dashboard → Workers & Pages
2. Create a new Worker
3. Copy the contents of `email-forwarder.js`
4. Save and Deploy

**Option B: Via Wrangler CLI**

```bash
# Install Wrangler
npm install -g wrangler

# Login to Cloudflare
wrangler login

# Deploy
cd cloudflare-worker
wrangler deploy
```

### 3. Configure Environment Variables

In Cloudflare Dashboard → Workers → Your Worker → Settings → Variables:

| Variable | Description | Required |
|----------|-------------|----------|
| `WEBHOOK_URL` | Your webhook endpoint URL | Yes |
| `WEBHOOK_SECRET` | Shared secret for authentication | Recommended |
| `FORWARD_TO` | Email address to forward after processing (must be verified in Cloudflare) | Optional |

Example:
- `WEBHOOK_URL`: `https://ubb-extractor.example.com/webhook/cloudflare`
- `WEBHOOK_SECRET`: Generate with `openssl rand -hex 32`
- `FORWARD_TO`: `your-email@gmail.com` (optional, for keeping a copy)

### 4. Create Email Route

1. Go to Email Routing → Routing rules
2. Create a new route:
   - Custom address: `statements@yourdomain.com` (or catch-all `*`)
   - Action: "Send to a Worker"
   - Worker: Select your deployed worker

### 5. Configure Your Application

Add to your `.env`:

```env
# Cloudflare webhook authentication (must match Worker's WEBHOOK_SECRET)
CLOUDFLARE_WEBHOOK_SECRET=your-secret-here
```

## Testing

1. Send a test email to your configured address
2. Check Worker logs in Cloudflare Dashboard → Workers → Logs
3. Check your application logs for received webhooks

## Webhook Payload Format

The Worker sends this JSON to your endpoint:

```json
{
  "sender": "sender@example.com",
  "recipient": "statements@yourdomain.com",
  "subject": "Your Bank Statement",
  "raw_body": "... full RFC 5322 email content ...",
  "received_at": "2024-01-15T10:30:00.000Z",
  "headers": {
    "message-id": "<unique-id@example.com>",
    "date": "Mon, 15 Jan 2024 10:30:00 +0000",
    "content-type": "multipart/mixed; boundary=..."
  }
}
```

## Troubleshooting

### Emails show "Dropped" in Activity Log

**This is expected behavior** when not using `FORWARD_TO`. Cloudflare shows "Dropped" when:
- The Worker processes the email but doesn't call `forward()`, `reply()`, or `setReject()`
- This does NOT mean your email wasn't processed!

**How to verify emails are processed:**
1. Check Worker logs - you should see "Email forwarded successfully"
2. Check your application logs - webhook should be received
3. Check BigQuery/GCS for imported data

**How to fix the "Dropped" status:**
1. Add a verified email address in Cloudflare Dashboard → Email → Email Routing → Destination addresses
2. Add `FORWARD_TO` environment variable to your Worker with that email
3. Emails will now show as "Forwarded" and you'll get a copy in your inbox

### Emails not arriving

1. Check MX records are correctly configured
2. Verify Email Routing is enabled
3. Check the routing rule is active

### Webhook not receiving data

1. Check Worker logs for errors
2. Verify WEBHOOK_URL is correct
3. Ensure your endpoint is accessible via Cloudflare Tunnel

### Authentication errors

1. Verify WEBHOOK_SECRET matches in both Worker and application
2. Check the Authorization header format: `Bearer <secret>`

## Pricing

- **Email Routing**: Free for all Cloudflare plans
- **Workers**: Free tier includes 100,000 requests/day
- **Paid Workers**: $5/month for 10 million requests

## Security Considerations

1. Always use HTTPS for WEBHOOK_URL
2. Use WEBHOOK_SECRET to authenticate requests
3. Your application should validate the Authorization header
4. Cloudflare Tunnel adds an additional security layer

## References

- [Cloudflare Email Routing](https://developers.cloudflare.com/email-routing/)
- [Email Workers](https://developers.cloudflare.com/email-routing/email-workers/)
- [Runtime API](https://developers.cloudflare.com/email-routing/email-workers/runtime-api/)
