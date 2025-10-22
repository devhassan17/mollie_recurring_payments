from odoo import models

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _set_done(self):
        res = super()._set_done()
        if self.acquirer_id.provider == 'mollie' and self.sale_order_ids:
            for order in self.sale_order_ids:
                order.mollie_transaction_id = self.acquirer_reference
                order.mollie_payment_status = 'paid'
                if self.acquirer_reference and self.mandate_id:
                    order.mollie_mandate_id = self.mandate_id
        return res
