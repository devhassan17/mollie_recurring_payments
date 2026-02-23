from odoo import models, fields, api

class AccountMove(models.Model):
    _inherit = "account.move"

    mollie_last_payment_status = fields.Char(
        string="Mollie Last Payment Status",
        compute="_compute_mollie_from_so",
        store=True,
        index=True
    )

    @api.depends('invoice_line_ids.sale_line_ids.order_id')
    def _compute_mollie_from_so(self):
        for move in self:
            move.mollie_last_payment_status = False
            sale_orders = move.invoice_line_ids.sale_line_ids.order_id
            so = sale_orders[:1]
            if so:
                move.mollie_last_payment_status = so.mollie_last_payment_status