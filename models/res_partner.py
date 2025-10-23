import requests
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"

    mollie_customer_id = fields.Char("Mollie Customer ID", readonly=True)
    mollie_mandate_id = fields.Char("Mollie Mandate ID", readonly=True)


    @api.model
    def fetch_mollie_mandate(self):
        """Fetch the latest Mollie mandate for this partner"""
        self.ensure_one()

        if not self.mollie_customer_id:
            _logger.warning("⚠️ No Mollie customer ID for partner %s", self.name)
            return

        mollie_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        if not mollie_key:
            _logger.error("❌ Mollie API key not found in system parameters.")
            return

        url = f"https://api.mollie.com/v2/customers/{self.mollie_customer_id}/mandates"
        headers = {"Authorization": f"Bearer {mollie_key}"}

        _logger.info("📡 Fetching Mollie mandates for customer %s", self.mollie_customer_id)
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            _logger.error("❌ Mollie API error: %s", r.text)
            return

        data = r.json()
        mandates = data.get("_embedded", {}).get("mandates", [])
        if not mandates:
            _logger.info("No mandates found for customer %s", self.mollie_customer_id)
            return

        # Get latest active mandate
        latest = next((m for m in mandates if m.get("status") == "valid"), None)
        if latest:
            mandate_id = latest.get("id")
            self.mollie_mandate_id = mandate_id
            _logger.info("✅ Updated %s with mandate ID %s", self.name, mandate_id)
        else:
            _logger.info("No valid mandates found for %s", self.name)
            
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
