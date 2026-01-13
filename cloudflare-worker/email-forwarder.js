/**
 * Cloudflare Email Worker - Email to Webhook Forwarder
 *
 * This Worker receives emails via Cloudflare Email Routing
 * and forwards them to your application's webhook endpoint.
 *
 * Setup:
 * 1. Create a new Worker in Cloudflare Dashboard
 * 2. Copy this code
 * 3. Set environment variables:
 *    - WEBHOOK_URL: Your webhook endpoint (e.g., https://your-domain.com/webhook/cloudflare)
 *    - WEBHOOK_SECRET: Shared secret for authentication (optional but recommended)
 *    - FORWARD_TO: (Optional) Email address to forward to after processing (must be verified in Cloudflare)
 * 4. Create an Email Route to forward emails to this Worker
 */

export default {
  // Required fetch handler (for HTTP requests to the Worker URL)
  async fetch(_request, _env, _ctx) {
    return new Response(
      JSON.stringify({
        status: "ok",
        message: "UBB Email Forwarder Worker",
        description: "This worker receives emails via Cloudflare Email Routing and forwards them to a webhook.",
        endpoints: {
          email: "Receives emails from Cloudflare Email Routing",
        },
      }),
      {
        headers: { "Content-Type": "application/json" },
      }
    );
  },

  // Email handler (for emails routed to this Worker)
  async email(message, env, ctx) {
    // Get webhook URL from environment
    const webhookURL = env.WEBHOOK_URL;
    if (!webhookURL) {
      console.error("WEBHOOK_URL environment variable not set");
      // Reject the email so it bounces back
      message.setReject("Configuration error: webhook not configured");
      return;
    }

    try {
      // Extract email metadata
      const subject = message.headers.get("subject") || "No Subject";
      const from = message.from || "Unknown";
      const to = message.to || "";

      // Get the raw email content
      const rawEmail = await new Response(message.raw).text();

      // Prepare webhook payload
      const webhookPayload = {
        sender: from,
        recipient: to,
        subject: subject,
        raw_body: rawEmail,
        received_at: new Date().toISOString(),
        headers: {
          "message-id": message.headers.get("message-id"),
          "date": message.headers.get("date"),
          "content-type": message.headers.get("content-type"),
        },
      };

      // Prepare headers for webhook request
      const headers = {
        "Content-Type": "application/json",
        "User-Agent": "Cloudflare-Email-Worker/1.0",
      };

      // Add authorization if secret is configured
      if (env.WEBHOOK_SECRET) {
        headers["Authorization"] = `Bearer ${env.WEBHOOK_SECRET}`;
      }

      // Send to webhook
      const response = await fetch(webhookURL, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(webhookPayload),
      });

      if (!response.ok) {
        const errorText = await response.text();
        console.error(`Webhook failed: ${response.status} - ${errorText}`);
        // Reject on webhook failure so sender knows there was an issue
        message.setReject(`Webhook processing failed: ${response.status}`);
        return;
      }

      console.log(`Email forwarded successfully: ${subject} from ${from}`);

      // Forward to destination address if configured (fixes "Dropped" status in Activity Log)
      // The destination must be a verified email address in Cloudflare Email Routing
      if (env.FORWARD_TO) {
        await message.forward(env.FORWARD_TO);
        console.log(`Email also forwarded to: ${env.FORWARD_TO}`);
      }

    } catch (error) {
      console.error(`Error processing email: ${error.message}`);
      message.setReject(`Processing error: ${error.message}`);
    }
  },
};
