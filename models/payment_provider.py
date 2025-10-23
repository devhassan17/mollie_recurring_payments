import logging
import json
import requests
from odoo import models, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'
    
    def _create_first_ideal_payment(self, order, return_url=None):
        """Create first iDEAL payment to setup mandate"""
        self.ensure_one()
        if self.state != 'enabled' or self.code != 'mollie':
            raise UserError(_('Mollie payment provider not properly configured'))
            
        if not self.mollie_api_key:
            raise UserError(_('Mollie API key is not set'))

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return_url = return_url or f"{base_url}/payment/mollie/mandate/return"
        webhook_url = f"{base_url}/payment/mollie/mandate/webhook"

        # Prepare payment data for mandate setup
        payment_data = {
            'amount': {
                'currency': order.currency_id.name,
                'value': '0.01'  # Minimum amount for mandate setup
            },
            'method': 'ideal',
            'description': f'Mandate setup for {order.name}',
            'redirectUrl': return_url,
            'webhookUrl': webhook_url,
            'customerId': order.partner_id.mollie_customer_id,
            'sequenceType': 'first',  # This is key for mandate setup
            'metadata': {
                'order_id': order.id,
                'customer_id': order.partner_id.mollie_customer_id,
                'type': 'mandate_setup'
            }
        }

        # Create Mollie customer if not exists
        if not order.partner_id.mollie_customer_id:
            customer_data = {
                'name': order.partner_id.name,
                'email': order.partner_id.email,
            }
            
            customer_response = requests.post(
                'https://api.mollie.com/v2/customers',
                headers={'Authorization': f'Bearer {self.mollie_api_key}'},
                json=customer_data
            )
            
            if customer_response.status_code != 201:
                raise UserError(_('Failed to create Mollie customer'))
                
            customer = customer_response.json()
            order.partner_id.write({'mollie_customer_id': customer['id']})
            payment_data['customerId'] = customer['id']

        # Create the payment
        payment_response = requests.post(
            'https://api.mollie.com/v2/payments',
            headers={'Authorization': f'Bearer {self.mollie_api_key}'},
            json=payment_data
        )

        if payment_response.status_code != 201:
            raise UserError(_('Failed to create mandate setup payment'))

        return payment_response.json()
    
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