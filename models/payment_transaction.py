import logging
import requests
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    @api.model
    def _set_done(self):
        """Extend Mollie transaction post-payment to store mandate IDs."""
        res = super()._set_done()

        mollie_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        if not mollie_key:
            _logger.error("❌ Mollie API key missing — cannot fetch mandate.")
            return res

        headers = {
            "Authorization": f"Bearer {mollie_key}",
            "Content-Type": "application/json",
        }

        for tx in self:
            if tx.provider_id.code != "mollie" or not tx.sale_order_ids:
                continue

            order = tx.sale_order_ids[0]
            order.mollie_transaction_id = tx.provider_reference
            order.mollie_payment_status = "paid"

            try:
                # 1️⃣ Get payment info from Mollie
                payment_url = f"https://api.mollie.com/v2/payments/{tx.provider_reference}"
                _logger.info(f"🔍 Fetching Mollie payment info for {tx.provider_reference}")
                payment_resp = requests.get(payment_url, headers=headers)

                if payment_resp.status_code != 200:
                    _logger.error(f"❌ Failed to fetch Mollie payment info: {payment_resp.text}")
                    continue

                payment_data = payment_resp.json()
                mollie_method = payment_data.get("method")
                mollie_customer_id = payment_data.get("customerId")

                _logger.info(f"💳 Payment method: {mollie_method}, Customer: {mollie_customer_id}")

                # 2️⃣ Only fetch mandate if direct debit
                if mollie_method == "directdebit" and mollie_customer_id:
                    mandate_url = f"https://api.mollie.com/v2/customers/{mollie_customer_id}/mandates"
                    _logger.info(f"📡 Fetching mandates for customer {mollie_customer_id}")
                    mandates_resp = requests.get(mandate_url, headers=headers)

                    if mandates_resp.status_code != 200:
                        _logger.error(f"❌ Failed to get mandates: {mandates_resp.text}")
                        continue

                    mandates = mandates_resp.json().get("_embedded", {}).get("mandates", [])
                    valid = [m for m in mandates if m.get("status") == "valid"]

                    if valid:
                        mandate_id = valid[0]["id"]
                        order.mollie_mandate_id = mandate_id
                        if order.partner_id:
                            order.partner_id.mollie_mandate_id = mandate_id
                            order.partner_id.mollie_customer_id = mollie_customer_id
                        _logger.info(f"✅ Stored valid mandate ID: {mandate_id}")
                        order.message_post(body=_("✅ Mollie Mandate stored: %s") % mandate_id)
                    else:
                        _logger.warning("⚠️ No valid mandates found for this customer.")
                else:
                    _logger.info(f"ℹ️ Payment method {mollie_method} does not create mandates.")

            except Exception as e:
                _logger.exception(f"💥 Error while fetching Mollie mandate: {e}")

            # Post success log
            order.message_post(body=_("✅ Mollie payment completed: %s") % tx.provider_reference)

        return res
