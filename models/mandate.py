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
        ('creditcard', 'Credit Card'),
        ('paypal', 'PayPal'),
        ('ideal', 'iDEAL')
    ], string='Payment Method')
    status = fields.Selection([
        ('valid', 'Valid'),
        ('invalid', 'Invalid'),
        ('pending', 'Pending')
    ], string='Status')
    is_default = fields.Boolean(string='Default Mandate')
    created_at = fields.Datetime(string='Created At', default=fields.Datetime.now)
    order_id = fields.Many2one('sale.order', string='Sales Order')
    
    @api.model
    def create_mandate_from_webhook(self, webhook_data):
        """Create or update mandate from Mollie webhook"""
        try:
            mandate_id = webhook_data.get('id')
            customer_id = webhook_data.get('customerId')
            status = webhook_data.get('status')
            method = webhook_data.get('method')
            
            # Find partner by customer ID
            partner = self.env['res.partner'].search([
                ('mollie_customer_id', '=', customer_id)
            ], limit=1)
            
            if not partner:
                _logger.warning(f"No partner found for Mollie customer {customer_id}")
                return False
                
            existing_mandate = self.search([('mandate_id', '=', mandate_id)], limit=1)
            if existing_mandate:
                existing_mandate.write({
                    'status': status,
                    'method': method
                })
                _logger.info(f"Updated mandate {mandate_id} status to {status}")
                return existing_mandate
            else:
                mandate = self.create({
                    'mandate_id': mandate_id,
                    'customer_id': customer_id,
                    'partner_id': partner.id,
                    'status': status,
                    'method': method
                })
                _logger.info(f"Created new mandate {mandate_id} for partner {partner.id}")
                return mandate
        except Exception as e:
            _logger.error(f"Error creating mandate from webhook: {e}")
            return False
