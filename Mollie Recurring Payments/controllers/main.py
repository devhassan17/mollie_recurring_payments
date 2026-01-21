from odoo import http
from odoo.http import request
import requests
import logging

_logger = logging.getLogger(__name__)

class MollieRecurringController(http.Controller):

    @http.route('/mollie/mandate/webhook', type='json', auth="public", csrf=False)
    def handle_webhook(self):
        """Handle Mollie webhook for mandate creation"""
        _logger.info("MANDATE RECURRING WEBHOOK CALLED")
        
        data = request.jsonrequest
        payment_id = data.get("id")
        if not payment_id:
            return {"status": "error", "message": "no id"}, 400

        mollie_provider = self.env['payment.provider'].search([('code', '=', 'mollie')], limit=1)
        api_key = mollie_provider.mollie_api_key
        if not api_key:
            _logger.error("Webhook Mollie API key missing!")
            return {"status": "error"}, 400
        
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(f"https://api.mollie.com/v2/payments/{payment_id}", headers=headers, timeout=10)
        if resp.status_code != 200:
            _logger.error("Webhook payment fetch failed: %s", resp.text)
            return {"status": "error"}, 400

        payment_data = resp.json()
        cust = payment_data.get("customerId")
        mand = payment_data.get("_links", {}).get("mandate", {}).get("href", "").split("/")[-1]

        _logger.info("payment_data: ", payment_data)

        status = payment_data.get("status")

        if cust:
            partner = request.env['res.partner'].sudo().search([('mollie_customer_id','=',cust)], limit=1)
            if partner:
                partner.sudo().write({
                    'mollie_mandate_id': mand, 
                    'mollie_transaction_id': payment_id, 
                    # 'mollie_mandate_status': status,
                    "mollie_mandate_status": "valid" if status in ("paid", "authorized") else status

                })
                _logger.info("Webhook updated partner %s with mandate %s", partner.name, mand)

        return {"status": "ok"}

    @http.route('/mollie/mandate/return', type='http', auth="public", website=True)
    def handle_return(self, **kwargs):
        _logger.info("Mollie return URL hit with params: %s", kwargs)
        return request.redirect('/shop/confirmation')
