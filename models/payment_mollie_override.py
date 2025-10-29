from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class PaymentProviderMollie(models.Model):
    _inherit = 'payment.provider'
    
    def _mollie_create_payment_data(self, transaction, custom_create_values=None):
        """Override payment data creation for subscription orders"""
        payment_data = super()._mollie_create_payment_data(transaction, custom_create_values)
        
        # Check if this is a subscription order
        order = self.env['sale.order'].search([('name', '=', transaction.reference)])
        if order and self._is_subscription_order(order):
            _logger.info("Subscription order detected: %s. Removing sequenceType from payment.", order.name)
            
            # For subscription orders, remove sequenceType if we don't have customerId
            if payment_data.get('sequenceType') == 'first' and not payment_data.get('customerId'):
                payment_data.pop('sequenceType', None)
                _logger.info("Removed sequenceType from payment data for order %s", order.name)
        
        return payment_data
    
    def _is_subscription_order(self, order):
        """Check if order contains subscription products"""
        return any(line.product_id.recurring_invoice for line in order.order_line)