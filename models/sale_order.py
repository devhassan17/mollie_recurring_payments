from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = "sale.order"

    mollie_transaction_id = fields.Char("Mollie Transaction ID", copy=False, readonly=True)
