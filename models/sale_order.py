import requests
import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"

    mollie_customer_id = fields.Char("Mollie Customer ID", readonly=True)
    mollie_mandate_id = fields.Char("Mollie Mandate ID", readonly=True)

    def create_recurring_payment(self, amount, description):
        """Charge the customer again using their saved mandate."""
        api_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        for partner in self:
            if not partner.mollie_customer_id or not partner.mollie_mandate_id:
                _logger.warning(f"Partner {partner.name} missing Mollie customer or mandate.")
                continue

            payload = {
                "amount": {"currency": "EUR", "value": f"{amount:.2f}"},
                "customerId": partner.mollie_customer_id,
                "mandateId": partner.mollie_mandate_id,
                "sequenceType": "recurring",
                "description": description,
                "webhookUrl": "https://yourdomain.com/mollie/recurring/webhook"
            }

            r = requests.post("https://api.mollie.com/v2/payments", headers=headers, json=payload)
            if r.status_code == 201:
                _logger.info(f"✅ Created recurring payment for {partner.name}: {r.json()['id']}")
            else:
                _logger.error(f"❌ Recurring payment failed for {partner.name}: {r.text}")
