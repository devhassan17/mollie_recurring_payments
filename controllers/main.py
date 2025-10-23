import logging
import requests
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class MollieRecurringController(http.Controller):

    @http.route('/mollie/recurring/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def handle_webhook(self):
        data = request.jsonrequest or {}
        _logger.info("[MOLLIE DEBUG] Webhook received: %s", data)

        payment_id = data.get("id")
        if not payment_id:
            _logger.error("[MOLLIE DEBUG] Webhook missing payment id.")
            return {"status": "error", "message": "Missing payment id"}, 400

        # ✅ Determine API key dynamically (test/live)
        config = request.env["ir.config_parameter"].sudo()
        api_key = (
            config.get_param("mollie.api_key_live")
            if config.get_param("mollie_mode") == "live"
            else config.get_param("mollie.api_key_test")
        )

        if not api_key:
            _logger.error("[MOLLIE DEBUG] Mollie API key not configured.")
            return {"status": "error", "message": "Missing API key"}, 400

        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            resp = requests.get(
                f"https://api.mollie.com/v2/payments/{payment_id}",
                headers=headers,
                timeout=10,
            )
            if resp.status_code != 200:
                _logger.error(
                    "[MOLLIE DEBUG] Failed fetching payment %s: %s",
                    payment_id,
                    resp.text,
                )
                return {"status": "error", "message": "Payment fetch failed"}, 400
        except Exception as e:
            _logger.exception("[MOLLIE DEBUG] Error calling Mollie API: %s", str(e))
            return {"status": "error", "message": str(e)}, 500

        payment_data = resp.json()
        customer_id = payment_data.get("customerId")
        mandate_id = payment_data.get("mandateId")

        if not customer_id:
            _logger.warning("[MOLLIE DEBUG] No customerId in payment data: %s", payment_data)
            return {"status": "ok", "message": "No customerId (non-recurring payment)"}, 200

        partner = request.env["res.partner"].sudo().search(
            [("mollie_customer_id", "=", customer_id)], limit=1
        )

        if not partner:
            _logger.warning(
                "[MOLLIE DEBUG] No partner found for Mollie customer %s", customer_id
            )
            return {"status": "ok", "message": "Customer not found"}, 200

        if mandate_id:
            partner.sudo().write({"mollie_mandate_id": mandate_id})
            _logger.info(
                "[MOLLIE DEBUG] Updated partner %s with mandate %s",
                partner.name,
                mandate_id,
            )

        return {"status": "ok"}, 200
