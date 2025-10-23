from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = "sale.order"

    mollie_transaction_id = fields.Char(string="Mollie Transaction ID", readonly=True)
    mollie_mandate_id = fields.Char(string="Mollie Mandate ID", readonly=True)
    mollie_payment_status = fields.Selection([
        ("open", "Open"),
        ("paid", "Paid"),
        ("failed", "Failed"),
        ("expired", "Expired"),
        ("canceled", "Canceled"),
        ("authorized", "Authorized"),
    ], string="Mollie Payment Status", readonly=True)
