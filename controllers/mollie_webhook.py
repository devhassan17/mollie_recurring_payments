import logging
import requests
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class MollieRecurringWebhook(http.Controller):

    @http.route("/mollie/recurring/webhook", auth="public", methods=["POST"], csrf=False)
    def mollie_recurring_webhook(self, **kwargs):
        """Handle Mollie webhook for recurring payments."""
        payload = request.jsonrequest or kwargs
        _logger.info("🌐 Mollie recurring webhook received.")
        _logger.debug(f"📦 Webhook payload: {payload}")

        payment_id = payload.get("id")
        if not payment_id:
            _logger.error("❌ No payment ID found in webhook payload.")
            return "no id", 400

        mollie_key = request.env["ir.config_parameter"].sudo().get_param("mollie.api_key_live") or \
                     request.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
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
        _logger.info(f"✅ Mollie payment fetched for payment ID={payment_id}")

        customer_id = data.get("customerId")
        mandate_id = data.get("mandateId")
        status = data.get("status")
        order_id = data.get("metadata", {}).get("order_id")

        _logger.debug(f"👤 Customer ID: {customer_id}, 🧾 Mandate ID: {mandate_id}, 📦 Order: {order_id}")

        # ✅ 1. Update partner
        partner = request.env["res.partner"].sudo().search([("mollie_customer_id", "=", customer_id)], limit=1)
        if partner and mandate_id:
            partner.write({"mollie_mandate_id": mandate_id})
            _logger.info(f"💾 Partner '{partner.name}' updated with mandate {mandate_id}")

        # ✅ 2. Update sale order (if any)
        if order_id:
            sale_order = request.env["sale.order"].sudo().search([("id", "=", int(order_id))], limit=1)
            if sale_order:
                sale_order.write({
                    "mollie_payment_status": status,
                    "mollie_transaction_id": payment_id,
                    "mollie_mandate_id": mandate_id
                })
                sale_order.message_post(body=f"🔁 Mollie recurring payment {status}: {payment_id}")
                _logger.info(f"✅ Updated sale order {sale_order.name} with payment status: {status}")

        return "ok", 200
    
    
