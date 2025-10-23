from odoo import models, fields, api
import requests
import logging

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"

    mollie_customer_id = fields.Char("Mollie Customer ID", readonly=True)
    mollie_mandate_id = fields.Char("Mollie Mandate ID", readonly=True)

    def action_fetch_mollie_mandate(self):
        """Manually fetch Mollie mandates for this partner."""
        for partner in self:
            if not partner.mollie_customer_id:
                _logger.warning("Partner %s has no Mollie customer ID", partner.name)
                continue

            api_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
            if not api_key:
                _logger.error("Missing Mollie API key.")
                continue

            headers = {"Authorization": f"Bearer {api_key}"}
            url = f"https://api.mollie.com/v2/customers/{partner.mollie_customer_id}/mandates"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                _logger.error("Failed to fetch mandates: %s", resp.text)
                continue

            data = resp.json().get("_embedded", {}).get("mandates", [])
            valid = [m for m in data if m.get("status") == "valid"]
            if valid:
                partner.sudo().write({"mollie_mandate_id": valid[0].get("id")})
                _logger.info("Stored valid mandate %s for %s", valid[0].get("id"), partner.name)
