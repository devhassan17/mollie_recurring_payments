import requests
import logging
from odoo import _, models

_logger = logging.getLogger(__name__)

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _mollie_prepare_payment_request_payload(self):
        """ Override of payment to prepare Mollie payment request payload with subscription support. """
        payload = super()._mollie_prepare_payment_request_payload()
        
        # Odoo 17/18: self.sale_order_ids is the standard way to get linked orders
        order = self.sale_order_ids[:1]
        if not order:
            return payload

        is_subscription_order = any(line.product_id.recurring_invoice for line in order.order_line)
        if not is_subscription_order:
            return payload

        partner = self.partner_id
        mollie_provider = self.provider_id
        if not mollie_provider or not mollie_provider.mollie_api_key:
            return payload

        headers = {
            "Authorization": f"Bearer {mollie_provider.mollie_api_key}",
            "Content-Type": "application/json"
        }

        customer_id = partner.mollie_customer_id
        if not customer_id:
            try:
                customer_payload = {
                    "name": partner.name,
                    "email": partner.email,
                    "metadata": {"odoo_partner_id": partner.id},
                }
                resp = requests.post("https://api.mollie.com/v2/customers", json=customer_payload, headers=headers, timeout=10)
                if resp.status_code == 201:
                    customer_id = resp.json().get("id")
                    partner.sudo().write({"mollie_customer_id": customer_id})
                    _logger.info("Created Mollie customer %s for partner %s", customer_id, partner.name)
            except Exception as e:
                _logger.error("Mollie customer creation exception: %s", str(e))

        if customer_id:
            payload.update({
                'sequenceType': 'first',
                'customerId': customer_id,
            })
            # Ensure mandate is fetched (asynchronously/queued in a real production, but here we trigger sync)
            partner.action_fetch_mollie_mandate()
              
        return payload