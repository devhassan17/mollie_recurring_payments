import logging
from odoo import models, api
from mollie.api.client import Client

_logger = logging.getLogger(__name__)

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'
    
    def _mollie_get_client(self):
        """Get Mollie client instance - using the official module's method"""
        return self.env['payment.provider']._get_mollie_client()
    
    def _get_default_payment_method_id(self, extra_params=None):
        """Set iDEAL as default method for subscription products"""
        self.ensure_one()
        if (extra_params and extra_params.get('subscription') and 
            self.code == 'mollie'):
            return 'ideal'
        return super()._get_default_payment_method_id(extra_params)

    def _process_payment_data(self, payment_data, order=None):
        """Add subscription-specific data to payment if needed"""
        if not order or not order.is_subscription_order:
            return super()._process_payment_data(payment_data)
            
        # Only modify Mollie payments for subscription orders
        if self.code == 'mollie':
            payment_data.update({
                'sequenceType': 'first',  # Required for first subscription payment
                'customerId': order.partner_id.mollie_customer_id,
                'metadata': {
                    'is_subscription': True,
                    'order_id': order.id,
                    'partner_id': order.partner_id.id,
                }
            })
            
        return payment_data
    
    @api.model
    def _mollie_create_customer(self, partner):
        """Create customer in Mollie for recurring payments"""
        if self.code != 'mollie':
            return False
            
        try:
            # Get Mollie client using the new method
            mollie = self._get_mollie_client()
            customer = mollie.customers.create({
                'name': partner.name,
                'email': partner.email,
            })
            
            # Store Mollie customer ID on partner
            partner.write({'mollie_customer_id': customer['id']})
            _logger.info("Created Mollie customer %s for partner %s", customer['id'], partner.id)
            return customer['id']
        except Exception as e:
            _logger.error("Failed to create Mollie customer: %s", e)
            return False