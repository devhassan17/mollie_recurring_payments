from odoo import models, fields

class ProductProduct(models.Model):
    _inherit = 'product.product'
    
    is_subscription = fields.Boolean(
        related='product_tmpl_id.is_subscription',
        store=True,
        readonly=False
    )
    
    subscription_interval = fields.Integer(
        string='Billing Interval (months)',
        default=1,
        help='Number of months between recurring payments'
    )