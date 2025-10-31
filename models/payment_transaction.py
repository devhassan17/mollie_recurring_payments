import requests
import logging
from odoo import _, models

_logger = logging.getLogger(__name__)

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _mollie_prepare_payment_request_payload(self):
        """ Override of payment to prepare Mollie payment request payload with subscription support. """
        payload = super()._mollie_prepare_payment_request_payload()
        partner = self.partner_id
        
        mollie_provider = self.env['payment.provider'].search([('code', '=', 'mollie')], limit=1)
        api_key = mollie_provider.mollie_api_key
        
        order = self.env['sale.order'].search([('name', '=', self.reference)], limit=1)
        is_subscription_order = any(line.product_id.recurring_invoice for line in order.order_line)
        
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        if is_subscription_order:
            
            customer_id = partner.mollie_customer_id
            
            if not customer_id:
                customer_payload = {
                    "name": partner.name,
                    "email": partner.email,
                    "metadata": {"odoo_partner_id": partner.id},
                }
                resp = requests.post("https://api.mollie.com/v2/customers", json=customer_payload, headers=headers)
                if resp.status_code == 201:
                    partner.mollie_customer_id = resp.json().get("id")
                    customer_id = resp.json().get("id")
                    _logger.info("Created Mollie customer for %s", partner.name)
                else:
                    _logger.error("Customer creation failed: %s", resp.text)

                payload.update({
                    'sequenceType': 'first',
                    'customerId': customer_id,
                })

                partner.action_fetch_mollie_mandate()
            else:
                payload.update({
                    'sequenceType': 'first',
                    'customerId': customer_id,
                })

                partner.action_fetch_mollie_mandate()
              
        return payload