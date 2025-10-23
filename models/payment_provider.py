import logging
from odoo import models, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'
    
    def _mollie_get_client(self):
        """Get Mollie client instance"""
        if not self.mollie_api_key:
            raise UserError(_('Mollie API key is not set'))
        return self.env['payment.provider']._mollie_make_request(endpoint='', method='GET', sudo=True)
    
    def _get_default_payment_method_id(self, extra_params=None):
        """Force iDEAL for subscription first payments"""
        self.ensure_one()
        tx_id = extra_params and extra_params.get('transaction_id')
        if tx_id and self.code == 'mollie':
            tx = self.env['payment.transaction'].browse(tx_id)
            if tx.exists() and tx.is_subscription:
                return 'ideal'
        return super()._get_default_payment_method_id(extra_params)

    def _mollie_prepare_payment_request(self, values):
        """Prepare the request to Mollie"""
        base_vals = super()._mollie_prepare_payment_request(values)
        
        # Only modify for subscription payments
        tx = self.env['payment.transaction'].browse(values.get('reference'))
        if not tx.is_subscription:
            return base_vals

        # Add subscription-specific values
        base_vals.update({
            'sequenceType': 'first',
            'method': 'ideal',
            'customerId': tx.partner_id.mollie_customer_id,
            'metadata': {
                'is_subscription': True,
                'transaction_id': tx.id,
                'reference': tx.reference
            }
        })
        
        return base_vals

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
            customer_data = {
                'name': partner.name,
                'email': partner.email,
            }
            
            response = self._mollie_make_request(
                endpoint='/customers',
                method='POST',
                payload=customer_data,
                sudo=True
            )
            
            if response and response.get('id'):
                # Store Mollie customer ID on partner
                partner.write({'mollie_customer_id': response['id']})
                _logger.info("Created Mollie customer %s for partner %s", response['id'], partner.id)
                return response['id']
                
        except Exception as e:
            _logger.error("Failed to create Mollie customer: %s", e)
        return False