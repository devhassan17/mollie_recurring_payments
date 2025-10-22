import logging
import requests
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"

    mollie_mandate_id = fields.Char(string="Mollie Mandate ID", readonly=True)
    mollie_customer_id = fields.Char(string="Mollie Customer ID", readonly=True)

    def fetch_mollie_mandate(self):
        """Fetch or create Mollie customer, then fetch their mandate."""
        mollie_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        if not mollie_key:
            _logger.error("❌ Mollie API key not found in system parameters.")
            return False

        headers = {
            "Authorization": f"Bearer {mollie_key}",
            "Content-Type": "application/json",
        }

        for partner in self:
            _logger.info(f"🔍 Processing Mollie data for partner: {partner.name} (ID={partner.id})")

            # ✅ 1. Create customer if missing
            if not partner.mollie_customer_id:
                _logger.info(f"🆕 No Mollie Customer ID found for {partner.name}. Creating one...")
                payload = {
                    "name": partner.name or "Unknown Customer",
                    "email": partner.email or "noemail@example.com",
                    "metadata": {"odoo_partner_id": partner.id},
                }
                resp = requests.post("https://api.mollie.com/v2/customers", headers=headers, json=payload)
                if resp.status_code == 201:
                    data = resp.json()
                    partner.mollie_customer_id = data["id"]
                    _logger.info(f"✅ Created Mollie customer for {partner.name}: {data['id']}")
                else:
                    _logger.error(f"❌ Failed to create Mollie customer for {partner.name}: {resp.text}")
                    continue

            # ✅ 2. Fetch mandates for that customer
            url = f"https://api.mollie.com/v2/customers/{partner.mollie_customer_id}/mandates"
            _logger.debug(f"📡 Fetching mandates: {url}")
            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                _logger.error(
                    f"❌ Mollie API returned {response.status_code} for {partner.name}: {response.text}"
                )
                continue

            data = response.json()
            mandates = data.get("_embedded", {}).get("mandates", [])
            _logger.info(f"✅ Found {len(mandates)} mandates for {partner.name}")

            # ✅ 3. Save valid mandate
            valid = [m for m in mandates if m.get("status") == "valid"]
            if valid:
                partner.mollie_mandate_id = valid[0]["id"]
                _logger.info(f"💾 Saved mandate for {partner.name}: {valid[0]['id']}")
            else:
                _logger.warning(f"⚠️ No valid mandates found for {partner.name}")

        _logger.info("🎯 Mollie mandate sync complete.")
        return True
