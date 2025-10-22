from odoo import models, api, _

class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    @api.model
    def _set_done(self):
        res = super()._set_done()

        for tx in self:
            if tx.provider_id.code == 'mollie' and tx.sale_order_ids:
                order = tx.sale_order_ids[0]
                order.mollie_transaction_id = tx.provider_reference
                order.mollie_payment_status = 'paid'
                order.message_post(body=_("✅ Mollie payment completed: %s") % tx.provider_reference)
        return res
