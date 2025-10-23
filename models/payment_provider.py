import logging
from odoo import models, api
from mollie.api.client import Client

_logger = logging.getLogger(__name__)

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'
    
    def _get_mollie_client(self):
        """Get Mollie client instance"""
        if not self.mollie_api_key:
            raise ValueError('Mollie API key is not set')
        client = Client()
        client.set_api_key(self.mollie_api_key)
        return client
    
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