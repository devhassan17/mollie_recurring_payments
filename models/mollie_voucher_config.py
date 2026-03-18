from odoo import fields, models

class MollieVoucherConfig(models.Model):
    _name = 'mollie.voucher.config'
    _description = 'Mollie Voucher Configuration'

    provider_id = fields.Many2one('payment.provider', string='Payment Provider', ondelete='cascade', required=True)
    category_id = fields.Many2one('product.category', string='Product Category', required=True)
    mollie_voucher_type = fields.Selection([
        ('eco', 'Eco'),
        ('meal', 'Meal'),
        ('gift', 'Gift'),
        ('sport_culture', 'Sport Culture'),
        ('holiday', 'Holiday')
    ], string='Mollie Voucher Type', required=True, default='gift')

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    mollie_voucher_ids = fields.One2many(
        'mollie.voucher.config', 'provider_id', string='Mollie Voucher Configuration'
    )
    mollie_use_vouchers = fields.Boolean(
        string='Mollie: Use Vouchers', 
        help='If enabled, line items with categories will be sent to Mollie.'
    )

    def _get_supported_payment_method_codes(self):
        """ Override to include 'giftcard' in supported Mollie methods. """
        codes = super()._get_supported_payment_method_codes()
        if self.code == 'mollie':
            codes.append('giftcard')
        return codes
