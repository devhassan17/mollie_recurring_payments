from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class MollieMandate(models.Model):
    _name = 'mollie.mandate'
    _description = 'Mollie Mandate'
    _rec_name = 'mandate_id'

    mandate_id = fields.Char(string='Mollie Mandate ID', required=True, index=True)
    customer_id = fields.Char(string='Mollie Customer ID', required=True)
    partner_id = fields.Many2one('res.partner', string='Customer', required=True)
    method = fields.Selection([
        ('directdebit', 'Direct Debit'),
        ('ideal', 'iDEAL')
    ], string='Payment Method')
    status = fields.Selection([
        ('valid', 'Valid'),
        ('invalid', 'Invalid'),
        ('pending', 'Pending')
    ], string='Status')
    order_id = fields.Many2one('sale.order', string='Sales Order')
    
    _sql_constraints = [
        ('unique_mandate_id', 'unique(mandate_id)', 'Mandate ID must be unique!')
    ]