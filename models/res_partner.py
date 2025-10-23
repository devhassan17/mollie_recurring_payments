import requests
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"

    mollie_customer_id = fields.Char("Mollie Customer ID", readonly=True)
    mollie_mandate_id = fields.Char("Mollie Mandate ID", readonly=True)


    def fetch_mollie_mandate(self, *args):
        """
        Fetch or create Mollie customer, then fetch their mandate.

        Accepts *args to be safe when invoked from a button (RPC may pass ids).
        Operates on self (recordset).
        """
        _logger.info("🔔 fetch_mollie_mandate called with args=%s on partners=%s", args, self.ids)

        mollie_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        if not mollie_key:
            _logger.error("❌ Mollie API key not found in system parameters.")
            return False

        headers = {
            "Authorization": f"Bearer {mollie_key}",
            "Content-Type": "application/json",
        }

        for partner in self:
            try:
                _logger.info("🔍 Processing Mollie data for partner: %s (ID=%s)", partner.name, partner.id)

                # 1) Ensure Mollie customer exists
                if not partner.mollie_customer_id:
                    _logger.info("🆕 No Mollie Customer ID for %s. Creating...", partner.name)
                    payload = {
                        "name": partner.name or "Unknown Customer",
                        "email": partner.email or "noemail@example.com",
                        "metadata": {"odoo_partner_id": partner.id},
                    }
                    resp = requests.post("https://api.mollie.com/v2/customers", headers=headers, json=payload, timeout=10)
                    if resp.status_code in (200, 201):
                        data = resp.json()
                        partner.sudo().write({"mollie_customer_id": data["id"]})
                        _logger.info("✅ Created Mollie customer for %s: %s", partner.name, data["id"])
                    else:
                        _logger.error("❌ Failed to create Mollie customer for %s: %s", partner.name, resp.text)
                        continue  # try next partner

                # 2) Fetch mandates
                url = f"https://api.mollie.com/v2/customers/{partner.mollie_customer_id}/mandates"
                _logger.debug("📡 Fetching mandates for %s: %s", partner.name, url)
                r = requests.get(url, headers=headers, timeout=10)
                if r.status_code != 200:
                    _logger.error("❌ Mollie API returned %s for %s: %s", r.status_code, partner.name, r.text)
                    continue

                data = r.json()
                mandates = data.get("_embedded", {}).get("mandates", [])
                _logger.info("✅ Found %s mandates for %s", len(mandates), partner.name)

                valid = [m for m in mandates if m.get("status") == "valid"]
                if valid:
                    mandate_id = valid[0]["id"]
                    partner.sudo().write({"mollie_mandate_id": mandate_id})
                    _logger.info("💾 Saved mandate for %s: %s", partner.name, mandate_id)
                else:
                    _logger.warning("⚠️ No valid mandates found for %s", partner.name)

            except requests.RequestException as e:
                _logger.error("⚠️ Network / requests error while talking to Mollie for %s: %s", partner.name, e)
            except Exception as e:
                _logger.exception("💥 Unexpected error in fetch_mollie_mandate for %s: %s", partner.name, e)

        _logger.info("🎯 Mollie mandate sync complete for partners: %s", self.ids)
        return True
            
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
