import logging
import requests
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"

    mollie_mandate_id = fields.Char(string="Mollie Mandate ID", readonly=True)
    mollie_customer_id = fields.Char(string="Mollie Customer ID", readonly=True)

    def _get_mollie_key(self):
        """Get Mollie API key (prefers live if available)."""
        return (
            self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_live")
            or self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        )

    def fetch_mollie_mandate(self):
        """Fetch or create Mollie customer, then retrieve mandate."""
        mollie_key = self._get_mollie_key()
        if not mollie_key:
            _logger.error("❌ Mollie API key not found in system parameters.")
            return False

        headers = {
            "Authorization": f"Bearer {mollie_key}",
            "Content-Type": "application/json",
        }

        for partner in self:
            _logger.info(f"🔍 Syncing Mollie data for partner: {partner.name} (ID={partner.id})")

            # 1️⃣ Create Mollie Customer if missing
            if not partner.mollie_customer_id:
                payload = {
                    "name": partner.name or "Unknown Customer",
                    "email": partner.email or "noemail@example.com",
                    "metadata": {"odoo_partner_id": partner.id},
                }
                r = requests.post("https://api.mollie.com/v2/customers", headers=headers, json=payload)
                if r.status_code == 201:
                    data = r.json()
                    partner.mollie_customer_id = data["id"]
                    _logger.info(f"✅ Mollie customer created: {data['id']}")
                else:
                    _logger.error(f"❌ Failed to create Mollie customer: {r.text}")
                    continue

            # 2️⃣ Fetch Mandates
            url = f"https://api.mollie.com/v2/customers/{partner.mollie_customer_id}/mandates"
            r = requests.get(url, headers=headers)
            if r.status_code != 200:
                _logger.error(f"❌ Error fetching mandates: {r.text}")
                continue

            data = r.json()
            mandates = data.get("_embedded", {}).get("mandates", [])
            valid_mandates = [m for m in mandates if m.get("status") == "valid"]

            if valid_mandates:
                mandate = valid_mandates[0]
                partner.mollie_mandate_id = mandate["id"]
                _logger.info(f"💾 Valid Mollie mandate stored: {mandate['id']}")
            else:
                _logger.warning(f"⚠️ No valid mandates found for {partner.name}")

        return True

    def mollie_create_recurring_payment(self, amount, description="Recurring Payment"):
        """Trigger a recurring payment using saved mandate + customer."""
        self.ensure_one()
        mollie_key = self._get_mollie_key()
        if not mollie_key:
            _logger.error("❌ Mollie API key not found.")
            return False

        if not self.mollie_customer_id or not self.mollie_mandate_id:
            _logger.warning(
                f"⚠️ Missing Mollie Customer or Mandate for {self.name}. Fetching now..."
            )
            self.fetch_mollie_mandate()

        if not (self.mollie_customer_id and self.mollie_mandate_id):
            _logger.error(f"❌ Cannot create recurring payment — no valid mandate for {self.name}")
            return False

        headers = {
            "Authorization": f"Bearer {mollie_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "amount": {"currency": "EUR", "value": f"{amount:.2f}"},
            "customerId": self.mollie_customer_id,
            "sequenceType": "recurring",
            "mandateId": self.mollie_mandate_id,
            "description": description,
            "metadata": {"partner_id": self.id},
            "redirectUrl": "https://yourdomain.com/payment/success",
            "webhookUrl": "https://yourdomain.com/mollie/recurring/webhook",
        }

        _logger.info(f"🔁 Creating Mollie recurring payment for {self.name}: €{amount:.2f}")
        r = requests.post("https://api.mollie.com/v2/payments", headers=headers, json=payload)

        if r.status_code == 201:
            data = r.json()
            payment_id = data.get("id")
            _logger.info(f"✅ Recurring payment created successfully (ID={payment_id})")
            return data
        else:
            _logger.error(f"❌ Failed to create recurring payment: {r.status_code} {r.text}")
            return False
