from odoo import models, fields, api, _
import logging
import requests

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"

    mollie_customer_id = fields.Char("Mollie Customer ID", copy=False, readonly=True)
    mollie_mandate_id = fields.Char("Mollie Mandate ID", copy=False, readonly=True)

    def fetch_mollie_mandate(self):
        """Manually fetch Mollie mandates for this partner."""
        for partner in self:
            if not partner.mollie_customer_id:
                _logger.warning("Partner %s has no Mollie customer ID.", partner.name)
                continue
            api_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
            if not api_key:
                _logger.error("Mollie API key missing.")
                continue
            headers = {"Authorization": f"Bearer {api_key}"}
            url = f"https://api.mollie.com/v2/customers/{partner.mollie_customer_id}/mandates"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                _logger.error("Failed fetching mandates for %s: %s", partner.name, resp.text)
                continue
            data = resp.json()
            mandates = data.get("_embedded", {}).get("mandates", [])
            valid = [m for m in mandates if m.get("status") == "valid"]
            if valid:
                mandate = valid[0]
                partner.sudo().write({"mollie_mandate_id": mandate.get("id")})
                _logger.info("Stored mandate %s for partner %s", mandate.get("id"), partner.name)
            else:
                _logger.warning("No valid mandates for partner %s", partner.name)
                

