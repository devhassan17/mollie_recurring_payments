import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class MollieRecurringController(http.Controller):
    
    @http.route('/payment/mollie/recurring/return/<int:subscription_id>', 
                type='http', auth='public', website=True, csrf=False)
    def mollie_recurring_return(self, subscription_id, **kwargs):
        """Handle return from Mollie after mandate setup payment"""
        subscription = request.env['sale.subscription'].browse(subscription_id).sudo()
        
        if not subscription.exists():
            return request.redirect('/')
        
        payment_id = kwargs.get('id')
        if payment_id:
            try:
                # Verify payment status with Mollie
                acquirer = request.env['payment.acquirer'].sudo().search([
                    ('provider', '=', 'mollie')
                ], limit=1)
                
                mollie = acquirer._mollie_get_client()
                payment_data = mollie.payments.get(payment_id)
                
                if payment_data['status'] in ['paid', 'authorized']:
                    # Payment successful - mandate should be created
                    subscription.message_post(
                        body=f"Mandate setup payment successful. Payment ID: {payment_id}. "
                             f"Mandate should be available via webhook shortly."
                    )
                    return request.render('mollie_recurring.mandate_setup_success', {
                        'subscription': subscription
                    })
                else:
                    subscription.message_post(
                        body=f"Mandate setup payment failed. Payment ID: {payment_id}. Status: {payment_data['status']}"
                    )
                    return request.render('mollie_recurring.mandate_setup_failed', {
                        'subscription': subscription,
                        'status': payment_data['status']
                    })
                    
            except Exception as e:
                _logger.error(f"Error verifying mandate payment: {e}")
                subscription.message_post(body=f"Error verifying mandate payment: {str(e)}")
        
        return request.redirect('/')
    
    @http.route('/payment/mollie/recurring/webhook', 
                type='http', auth='public', methods=['POST'], csrf=False)
    def mollie_recurring_webhook(self, **kwargs):
        """Handle Mollie webhook notifications for recurring payments"""
        try:
            data = json.loads(request.httprequest.data)
            _logger.info(f"Mollie recurring webhook received: {data}")
            
            if data.get('resource') == 'payment':
                self._handle_payment_webhook(data)
            elif data.get('resource') == 'mandate':
                self._handle_mandate_webhook(data)
                
            return 'OK'
        except Exception as e:
            _logger.error(f"Error processing Mollie webhook: {e}")
            return 'ERROR'
    
    def _handle_payment_webhook(self, data):
        """Handle payment webhook for recurring payments"""
        payment_id = data.get('id')
        if not payment_id:
            return
            
        acquirer = request.env['payment.acquirer'].sudo().search([
            ('provider', '=', 'mollie')
        ], limit=1)
        
        try:
            mollie = acquirer._mollie_get_client()
            payment_data = mollie.payments.get(payment_id)
            metadata = payment_data.get('metadata', {})
            subscription_id = metadata.get('subscription_id')
            
            if subscription_id:
                subscription = request.env['sale.subscription'].sudo().browse(int(subscription_id))
                if subscription.exists():
                    if payment_data['status'] == 'paid':
                        subscription.message_post(
                            body=f"Recurring payment confirmed via webhook. Payment ID: {payment_id}"
                        )
                        _logger.info(f"Recurring payment {payment_id} confirmed for subscription {subscription.code}")
                    elif payment_data['status'] == 'failed':
                        subscription.message_post(
                            body=f"Recurring payment failed via webhook. Payment ID: {payment_id}. Status: {payment_data['status']}"
                        )
                        _logger.warning(f"Recurring payment {payment_id} failed for subscription {subscription.code}")
                        
        except Exception as e:
            _logger.error(f"Error handling payment webhook: {e}")
    
    def _handle_mandate_webhook(self, data):
        """Handle mandate webhook - this is crucial for recurring payments"""
        mandate_data = data
        _logger.info(f"Processing mandate webhook: {mandate_data}")
        
        try:
            mandate = request.env['mollie.mandate'].sudo().create_mandate_from_webhook(mandate_data)
            if mandate:
                _logger.info(f"Successfully processed mandate webhook for mandate {mandate_data.get('id')}")
                
                # If mandate is valid, link it to relevant subscription
                if mandate.status == 'valid' and mandate.partner_id:
                    # Find subscriptions for this partner that need mandates
                    subscriptions = request.env['sale.subscription'].sudo().search([
                        ('partner_id', '=', mandate.partner_id.id),
                        ('is_mandate_approved', '=', False)
                    ])
                    
                    for subscription in subscriptions:
                        subscription.write({
                            'mollie_mandate_ids': [(4, mandate.id)]
                        })
                        subscription.message_post(
                            body=f"Mandate approved and linked to subscription. Mandate ID: {mandate.mandate_id}"
                        )
                        _logger.info(f"Linked mandate {mandate.mandate_id} to subscription {subscription.code}")
            else:
                _logger.warning(f"Failed to process mandate webhook for data: {mandate_data}")
                
        except Exception as e:
            _logger.error(f"Error handling mandate webhook: {e}")