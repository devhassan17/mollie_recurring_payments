# from odoo import models, api, _

# class PaymentTransaction(models.Model):
#     _inherit = "payment.transaction"

#     @api.model
#     def _set_done(self):
#         res = super()._set_done()

#         for tx in self:
#             if tx.provider_id.code == 'mollie' and tx.sale_order_ids:
#                 order = tx.sale_order_ids[0]
#                 order.mollie_transaction_id = tx.provider_reference
#                 order.mollie_payment_status = 'paid'
#                 order.message_post(body=_("✅ Mollie payment completed: %s") % tx.provider_reference)
#         return res


from odoo import models, api, _

class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    @api.model
    def _set_done(self):
        res = super()._set_done()

        for tx in self:
            if tx.provider_id.code == 'mollie' and tx.sale_order_ids:
                order = tx.sale_order_ids[0]

                # Basic transaction info
                order.mollie_transaction_id = tx.provider_reference
                order.mollie_payment_status = 'paid'

                # Try to retrieve mandate ID from Mollie API (if available)
                mandate_id = False
                try:
                    mollie_data = tx.provider_id._mollie_make_request(
                        f"/customers/{tx.provider_reference}/mandates"
                    )
                    if mollie_data and 'data' in mollie_data and len(mollie_data['data']):
                        mandate_id = mollie_data['data'][0].get('id')
                except Exception as e:
                    _logger.warning(f"Could not fetch Mollie mandate: {e}")

                if mandate_id:
                    order.mollie_mandate_id = mandate_id
                    order.message_post(body=_("✅ Mollie Mandate ID stored: %s") % mandate_id)

                # Post confirmation message
                order.message_post(body=_("✅ Mollie payment completed: %s") % tx.provider_reference)

        return res
