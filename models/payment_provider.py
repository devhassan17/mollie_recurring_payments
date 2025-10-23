import logging
from odoo import models, api

_logger = logging.getLogger(__name__)

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'
    
    @api.model
    def _mollie_create_customer(self, partner):
        """Create customer in Mollie for recurring payments"""
        if self.code != 'mollie':
            return False
            
        try:
            # Get Mollie client from the official module
            mollie = self._mollie_get_client()
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