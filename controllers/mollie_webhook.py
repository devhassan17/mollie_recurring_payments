import logging
import requests
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class MollieRecurringWebhook(http.Controller):

    @http.route("/mollie/recurring/webhook", auth="public", methods=["POST"], csrf=False)
    def mollie_recurring_webhook(self, **post):
        """Triggered after Mollie payment confirmation."""
        _logger.info("🌐 Mollie recurring webhook received.")
        _logger.debug(f"📦 Webhook payload: {post}")

        payment_id = post.get("id")
        if not payment_id:
            _logger.error("❌ No payment ID found in webhook payload.")
            return "no id", 400

        mollie_key = request.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        if not mollie_key:
            _logger.error("❌ Mollie API key missing in system parameters.")
            return "api key missing", 400

        headers = {"Authorization": f"Bearer {mollie_key}"}
        payment_url = f"https://api.mollie.com/v2/payments/{payment_id}"

        _logger.debug(f"📡 Fetching payment details from Mollie API: {payment_url}")
        r = requests.get(payment_url, headers=headers)

        if r.status_code != 200:
            _logger.error(f"❌ Mollie payment fetch failed: {r.status_code} - {r.text}")
            return "fail", 400

        data = r.json()
        _logger.info(f"✅ Mollie payment fetched successfully for payment ID={payment_id}")

        customer_id = data.get("customerId")
        mandate_id = data.get("mandateId")

        _logger.debug(f"👤 Customer ID: {customer_id}, 🧾 Mandate ID: {mandate_id}")

        if not (customer_id and mandate_id):
            _logger.warning("⚠️ No customer or mandate ID in payment response.")
            return "no customer/mandate", 200

        partner = (
            request.env["res.partner"]
            .sudo()
            .search([("mollie_customer_id", "=", customer_id)], limit=1)
        )

        if partner:
            _logger.info(f"💾 Updating partner '{partner.name}' with mandate ID {mandate_id}")
            partner.write({"mollie_mandate_id": mandate_id})
        else:
            _logger.warning(f"⚠️ No partner found with Mollie customer ID: {customer_id}")

        _logger.info("✅ Mollie recurring webhook processing complete.")
        return "ok", 200
