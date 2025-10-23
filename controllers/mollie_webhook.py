import logging
import requests
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class MollieWebhookController(http.Controller):

    @http.route('/mollie/recurring/webhook', type='json', auth="public", methods=['POST'], csrf=False)
    def handle_webhook(self):
        data = request.jsonrequest
        _logger.info("Mollie webhook received: %s", data)

        payment_id = data.get("id")
        if not payment_id:
            return {"status": "error", "message": "no id"}, 400

        api_key = request.env["ir.config_parameter"].sudo().get_param('mollie.api_key_test')
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(f"https://api.mollie.com/v2/payments/{payment_id}", headers=headers, timeout=10)
        if resp.status_code != 200:
            _logger.error("Fetch payment failed: %s", resp.text)
            return {"status": "error", "message": "failed"}, 400

        payment_data = resp.json()
        cust = payment_data.get("customerId")
        mand = payment_data.get("mandateId")

        if cust:
            partner = request.env['res.partner'].sudo().search([('mollie_customer_id','=',cust)], limit=1)
            if partner:
                partner.sudo().write({'mollie_mandate_id': mand})
                _logger.info("Updated partner %s with mandate %s", partner.name, mand)

        return {"status": "ok"}, 200
