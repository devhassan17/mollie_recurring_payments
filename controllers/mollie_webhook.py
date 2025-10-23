import logging
import requests
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class MollieRecurringWebhook(http.Controller):

    @http.route("/mollie/recurring/webhook", auth="public", methods=["POST"], csrf=False)
    def mollie_recurring_webhook(self, **post):
        """Triggered by Mollie when payment confirmed."""
        _logger.info("🌐 Mollie webhook received for recurring payment")
        payment_id = post.get("id")

        if not payment_id:
            return "no payment id", 400

        api_key = request.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(f"https://api.mollie.com/v2/payments/{payment_id}", headers=headers)

        if resp.status_code != 200:
            _logger.error(f"Failed fetching Mollie payment {payment_id}: {resp.text}")
            return "error", 400

        data = resp.json()
        customer_id = data.get("customerId")
        mandate_id = data.get("mandateId")

        _logger.info(f"📦 Webhook data → Customer: {customer_id}, Mandate: {mandate_id}")

        if customer_id:
            partner = request.env["res.partner"].sudo().search([("mollie_customer_id", "=", customer_id)], limit=1)
            if partner:
                partner.write({"mollie_mandate_id": mandate_id})
                _logger.info(f"✅ Updated partner {partner.name} with mandate {mandate_id}")
            else:
                _logger.warning(f"No partner found for Mollie customer ID {customer_id}")

        return "ok", 200
