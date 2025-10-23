import logging
import requests
from odoo import models, api, _

_logger = logging.getLogger(__name__)

class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    def _mollie_prepare_payment_payload(self, values):
        payload = super()._mollie_prepare_payment_payload(values)
        partner = self.partner_id
        api_key = self.provider_id.mollie_api_key or self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        headers = {"Authorization": f"Bearer {api_key}"}

        # Create Mollie Customer if missing
        if not partner.mollie_customer_id:
            _logger.info("Creating Mollie customer for partner %s", partner.name)
            resp = requests.post(
                "https://api.mollie.com/v2/customers",
                headers=headers,
                json={
                    "name": partner.name,
                    "email": partner.email,
                    "metadata": {"odoo_partner_id": partner.id},
                },
                timeout=10
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                partner.sudo().write({"mollie_customer_id": data.get("id")})
                _logger.info("Mollie customer created: %s", data.get("id"))
            else:
                _logger.error("Mollie customer creation failed: %s", resp.text)

        # Use customer id for payment and first sequence to get mandate
        if partner.mollie_customer_id:
            payload.update({
                "customerId": partner.mollie_customer_id,
                "sequenceType": "first",
            })

        return payload

    @api.model
    def _set_done(self):
        res = super()._set_done()
        for tx in self:
            if tx.provider_id.code != 'mollie' or not tx.sale_order_ids:
                continue

            order = tx.sale_order_ids[0]
            api_key = tx.provider_id.mollie_api_key or self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
            headers = {"Authorization": f"Bearer {api_key}"}

            payment_url = f"https://api.mollie.com/v2/payments/{tx.provider_reference}"
            _logger.info("Fetching Mollie payment %s", tx.provider_reference)
            resp = requests.get(payment_url, headers=headers, timeout=10)
            if resp.status_code != 200:
                _logger.error("Failed fetch payment %s: %s", tx.provider_reference, resp.text)
                continue
            data = resp.json()
            customer_id = data.get("customerId")
            mandate_id = data.get("mandateId")

            _logger.info("Mollie returned customer_id=%s, mandate_id=%s", customer_id, mandate_id)

            partner = order.partner_id
            if customer_id:
                partner.sudo().write({"mollie_customer_id": customer_id})
            if mandate_id:
                partner.sudo().write({"mollie_mandate_id": mandate_id})
                order.sudo().write({"mollie_mandate_id": mandate_id})

            order.sudo().write({
                "mollie_transaction_id": tx.provider_reference,
                "mollie_payment_status": "paid",
            })
            order.message_post(body=_("Mollie payment completed: %s") % tx.provider_reference)

        return res
