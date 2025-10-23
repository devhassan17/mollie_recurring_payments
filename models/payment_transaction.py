import logging
import requests
from odoo import models, api, _

_logger = logging.getLogger(__name__)

class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    @api.model
    def _set_done(self):
        res = super()._set_done()

        for tx in self:
            if tx.provider_id.code == 'mollie' and tx.sale_order_ids:
                order = tx.sale_order_ids[0]
                partner = order.partner_id

                # Basic payment info
                order.mollie_transaction_id = tx.provider_reference
                order.mollie_payment_status = 'paid'

                # Fetch details from Mollie API
                try:
                    api_key = tx.provider_id.mollie_api_key or self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
                    headers = {"Authorization": f"Bearer {api_key}"}
                    r = requests.get(f"https://api.mollie.com/v2/payments/{tx.provider_reference}", headers=headers)
                    r.raise_for_status()
                    data = r.json()

                    mollie_customer = data.get("customerId")
                    mollie_mandate = data.get("mandateId")

                    if mollie_customer:
                        partner.mollie_customer_id = mollie_customer
                        _logger.info(f"💾 Mollie customer stored for {partner.name}: {mollie_customer}")

                    if mollie_mandate:
                        partner.mollie_mandate_id = mollie_mandate
                        order.mollie_mandate_id = mollie_mandate
                        _logger.info(f"💾 Mollie mandate stored for {partner.name}: {mollie_mandate}")

                    order.message_post(body=_("✅ Mollie payment completed: %s") % tx.provider_reference)

                except Exception as e:
                    _logger.error(f"❌ Error fetching Mollie payment details: {e}")

        return res
