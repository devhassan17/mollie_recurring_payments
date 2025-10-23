import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'
    
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
            _logger.info(f"Created Mollie customer {customer['id']} for partner {partner.id}")
            return customer['id']
        except Exception as e:
            _logger.error(f"Failed to create Mollie customer: {e}")
            raise UserError(_("Failed to create Mollie customer: %s") % str(e))
    
    def _mollie_create_first_payment(self, subscription, amount, description):
        """Create first payment to establish mandate"""
        if self.code != 'mollie':
            return False
            
        partner = subscription.partner_id
        
        # Ensure customer exists in Mollie
        if not partner.mollie_customer_id:
            self._mollie_create_customer(partner)
        
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        
        try:
            mollie = self._mollie_get_client()
            payment_data = {
                'amount': {
                    'currency': subscription.currency_id.name,
                    'value': f"{amount:.2f}"
                },
                'customerId': partner.mollie_customer_id,
                'sequenceType': 'first',
                'method': 'ideal',
                'description': description,
                'redirectUrl': f"{base_url}/payment/mollie/recurring/return/{subscription.id}",
                'webhookUrl': f"{base_url}/payment/mollie/recurring/webhook",
                'metadata': {
                    'subscription_id': subscription.id,
                    'type': 'first_payment_mandate',
                    'partner_id': partner.id,
                }
            }
            
            payment = mollie.payments.create(payment_data)
            _logger.info(f"Created first payment {payment['id']} for subscription {subscription.id}")
            return payment
        except Exception as e:
            _logger.error(f"Failed to create first payment: {e}")
            raise UserError(_("Failed to create payment: %s") % str(e))
    
    def _mollie_create_recurring_payment(self, subscription, amount, description, mandate_id):
        """Create recurring payment using existing mandate"""
        if self.code != 'mollie':
            return False
            
        partner = subscription.partner_id
        
        if not partner.mollie_customer_id:
            _logger.error(f"No Mollie customer ID for partner {partner.id}")
            return False
            
        try:
            mollie = self._mollie_get_client()
            payment_data = {
                'amount': {
                    'currency': subscription.currency_id.name,
                    'value': f"{amount:.2f}"
                },
                'customerId': partner.mollie_customer_id,
                'sequenceType': 'recurring',
                'method': 'ideal',
                'mandateId': mandate_id,
                'description': description,
                'metadata': {
                    'subscription_id': subscription.id,
                    'type': 'recurring_payment',
                    'partner_id': partner.id,
                }
            }
            
            payment = mollie.payments.create(payment_data)
            _logger.info(f"Created recurring payment {payment['id']} for subscription {subscription.id}")
            return payment
        except Exception as e:
            _logger.error(f"Failed to create recurring payment: {e}")
            raise UserError(_("Failed to create recurring payment: %s") % str(e))