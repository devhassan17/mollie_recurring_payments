import logging
import requests
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"

    mollie_mandate_id = fields.Char(string="Mollie Mandate ID", readonly=True)
    mollie_customer_id = fields.Char(string="Mollie Customer ID", readonly=True)

    def fetch_mollie_mandate(self):
        """Fetch the customer's mandate from Mollie API and store it."""
        mollie_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        if not mollie_key:
            _logger.error("❌ Mollie API key not found in system parameters.")
            return False

        for partner in self:
            _logger.info(f"🔍 Checking Mollie mandates for partner ID={partner.id}, Name={partner.name}")

            if not partner.mollie_customer_id:
                _logger.warning(f"⚠️ Partner {partner.name} has no Mollie Customer ID. Skipping.")
                continue

            url = f"https://api.mollie.com/v2/customers/{partner.mollie_customer_id}/mandates"
            headers = {
                "Authorization": f"Bearer {mollie_key}",
                "Content-Type": "application/json",
            }

            _logger.debug(f"📡 Sending request to Mollie API: {url}")
            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                _logger.error(
                    f"❌ Mollie API returned {response.status_code} for partner {partner.name}: {response.text}"
                )
                continue

            data = response.json()
            mandates = data.get("_embedded", {}).get("mandates", [])
            _logger.info(f"✅ {len(mandates)} mandates found for {partner.name}")

            valid = [m for m in mandates if m.get("status") == "valid"]
            if valid:
                partner.mollie_mandate_id = valid[0]["id"]
                _logger.info(f"💾 Mandate saved for {partner.name}: {valid[0]['id']}")
            else:
                _logger.warning(f"⚠️ No valid mandates found for {partner.name}")

        _logger.info("🎯 Mandate fetch operation complete.")
        return True
