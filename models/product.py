from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    is_subscription = fields.Boolean(
        string='Is Subscription Product',
        help='If enabled, this product will be treated as a subscription with recurring payments'
    )
    subscription_interval = fields.Integer(
        string='Billing Interval (months)',
        default=1,
        help='Number of months between recurring payments'
    )