import logging
import requests
from odoo import models, api, _

_logger = logging.getLogger(__name__)

class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"


    def _mollie_prepare_payment_payload(self, values):
        payload = super()._mollie_prepare_payment_payload(values)
        partner = self.partner_id

        mollie_key = (
            self.provider_id.mollie_api_key
            or self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        )
        headers = {"Authorization": f"Bearer {mollie_key}"}

        # ✅ Step 1. Create Mollie Customer if not exists
        if not partner.mollie_customer_id:
            _logger.info(f"🧾 Creating Mollie customer for {partner.name}")
            resp = requests.post(
                "https://api.mollie.com/v2/customers",
                headers=headers,
                json={
                    "name": partner.name,
                    "email": partner.email,
                    "metadata": {"odoo_partner_id": partner.id},
                },
            )
            if resp.status_code == 201:
                data = resp.json()
                partner.sudo().write({"mollie_customer_id": data["id"]})
                _logger.info(f"✅ Mollie customer created: {data['id']}")
            else:
                _logger.error(f"❌ Mollie customer creation failed: {resp.text}")

        # ✅ Step 2. Use SEPA Direct Debit for recurring subscription
        payload.update({
            "method": "directdebit",
            "sequenceType": "first",  # Required for recurring payments
            "customerId": partner.mollie_customer_id,
            "description": f"Initial payment for {self.reference}",
            "redirectUrl": f"{self.provider_id.get_base_url()}/payment/mollie/return?ref={self.reference}",
            "webhookUrl": f"{self.provider_id.get_base_url()}/payment/mollie/webhook?ref={self.reference}",
        })

        return payload

    @api.model
    def _set_done(self):
        res = super()._set_done()

        for tx in self:
            if tx.provider_id.code != 'mollie' or not tx.sale_order_ids:
                continue

            order = tx.sale_order_ids[0]
            mollie_key = tx.provider_id.mollie_api_key or self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
            headers = {"Authorization": f"Bearer {mollie_key}"}

            # Step 1: Fetch the payment from Mollie
            payment_url = f"https://api.mollie.com/v2/payments/{tx.provider_reference}"
            _logger.info(f"📡 Fetching Mollie payment details for {tx.provider_reference}")
            r = requests.get(payment_url, headers=headers)

            if r.status_code != 200:
                _logger.error(f"❌ Failed to fetch payment: {r.text}")
                continue

            payment_data = r.json()
            customer_id = payment_data.get("customerId")
            mandate_id = payment_data.get("mandateId")

            _logger.info(f"✅ Mollie Payment fetched. customer_id={customer_id}, mandate_id={mandate_id}")

            # Step 2: Save info to order and partner
            if customer_id:
                partner = order.partner_id
                partner.sudo().write({"mollie_customer_id": customer_id})
                _logger.info(f"💾 Stored Mollie Customer ID {customer_id} for partner {partner.name}")
                

                if mandate_resp.status_code == 201:
                    mandate_data = mandate_resp.json()
                    mandate_id = mandate_data["id"]
                    partner.sudo().write({"mollie_mandate_id": mandate_id})
                    order.sudo().write({"mollie_mandate_id": mandate_id})
                    _logger.info(f"✅ Created Mollie Mandate: {mandate_id}")
                else:
                    _logger.error(f"❌ Mandate creation failed: {mandate_resp.text}")


            if mandate_id:
                partner.sudo().write({"mollie_mandate_id": mandate_id})
                order.sudo().write({"mollie_mandate_id": mandate_id})
                _logger.info(f"💾 Stored Mollie Mandate ID {mandate_id} for order {order.name}")

            # Step 3: Update payment and post message
            order.sudo().write({
                "mollie_transaction_id": tx.provider_reference,
                "mollie_payment_status": "paid"
            })
            order.message_post(body=_("✅ Mollie payment completed: %s") % tx.provider_reference)

        return res
