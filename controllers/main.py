import json
import logging
import requests
from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)

class MollieRecurringController(http.Controller):
    
    @http.route(['/payment/mollie/recurring/return/<int:order_id>', '/payment/mollie/return'], 
                type='http', auth='public', website=True, csrf=False)
    def mollie_recurring_return(self, order_id=None, **kwargs):
        """Handle return from Mollie after iDEAL/mandate setup payment"""
        order = False
        _logger.info("[MOLLIE DEBUG] Return URL called with order_id: %s, kwargs: %s", order_id, kwargs)
        
        if order_id:
            order = request.env['sale.order'].browse(order_id).sudo()
            _logger.info("[MOLLIE DEBUG] Found order from order_id: %s", order.name if order else 'Not found')
        
        if not order:
            # Try to find order from transaction reference
            transaction_reference = kwargs.get('ref')  # Mollie uses 'ref' not 'reference'
            _logger.info("[MOLLIE DEBUG] Looking for transaction with reference: %s", transaction_reference)
            
            if transaction_reference:
                transaction = request.env['payment.transaction'].sudo().search([
                    ('reference', '=', transaction_reference)
                ], limit=1)
                _logger.info("[MOLLIE DEBUG] Found transaction: %s", transaction.reference if transaction else 'Not found')
                
                if transaction and transaction.sale_order_ids:
                    order = transaction.sale_order_ids[0]
                    _logger.info("[MOLLIE DEBUG] Found order from transaction: %s", order.name)
        
        if not order or not order.exists():
            _logger.error("[MOLLIE DEBUG] No valid order found in return URL")
            return request.redirect('/')
        
        payment_id = kwargs.get('id')
        if payment_id:
            try:
                # Verify payment status with Mollie
                provider = request.env['payment.provider'].sudo().search([
                    ('code', '=', 'mollie')
                ], limit=1)
                
                if not provider:
                    _logger.error("Mollie payment provider not found")
                    return request.redirect('/')
                
                mollie = provider._mollie_get_client()
                payment_data = mollie.payments.get(payment_id)
                
                if payment_data['status'] in ['paid', 'authorized']:
                    # Payment successful - mandate should be created
                    order.message_post(
                        body=f"Mandate setup payment successful. Payment ID: {payment_id}. "
                             f"Mandate should be available via webhook shortly."
                    )
                    
                    # Mark order as recurring if it was intended to be
                    if not order.is_recurring_order:
                        order.write({'is_recurring_order': True})
                    
                    return request.render('mollie_recurring.mandate_setup_success', {
                        'order': order
                    })
                else:
                    order.message_post(
                        body=f"Mandate setup payment failed. Payment ID: {payment_id}. Status: {payment_data['status']}"
                    )
                    return request.render('mollie_recurring.mandate_setup_failed', {
                        'order': order,
                        'status': payment_data['status']
                    })
                    
            except Exception as e:
                _logger.error("Error verifying mandate payment: %s", e)
                order.message_post(body=f"Error verifying mandate payment: {str(e)}")
        
        return request.redirect('/')
    
    @http.route(['/payment/mollie/webhook', '/payment/mollie/recurring/webhook'], 
                type='http', auth='public', methods=['POST'], csrf=False)
    def mollie_recurring_webhook(self, **kwargs):
        """Handle Mollie webhook notifications for payments and mandates"""
        try:
            # Get webhook data
            _logger.info("[MOLLIE DEBUG] Webhook received with kwargs: %s", kwargs)
            
            # Check for data in both request.httprequest.data and kwargs
            data = {}
            if request.httprequest.data:
                try:
                    data = json.loads(request.httprequest.data)
                except json.JSONDecodeError:
                    _logger.warning("[MOLLIE DEBUG] Could not parse webhook data as JSON")
            
            # Get reference from kwargs if not in data
            if kwargs.get('ref'):
                data['ref'] = kwargs.get('ref')
            if kwargs.get('id'):
                data['id'] = kwargs.get('id')
                
            _logger.info("[MOLLIE DEBUG] Processing webhook data: %s", data)
            
            # Handle different webhook types
            if data.get('resource') == 'payment':
                self._handle_payment_webhook(data)
            elif data.get('resource') == 'mandate':
                self._handle_mandate_webhook(data)
            else:
                # If no resource type, assume it's a payment notification
                self._handle_payment_webhook(data)
                
            return 'OK'
        except Exception as e:
            _logger.error("[MOLLIE DEBUG] Error processing webhook: %s", str(e), exc_info=True)
            return 'ERROR'
    
    def _handle_payment_webhook(self, data):
        """Handle payment webhook for recurring payments and mandate creation"""
        payment_id = data.get('id')
        if not payment_id:
            return
            
        provider = request.env['payment.provider'].sudo().search([
            ('code', '=', 'mollie')
        ], limit=1)
        
        if not provider:
            _logger.error("[MOLLIE DEBUG] Payment provider not found for webhook")
            return
            
        _logger.info("[MOLLIE DEBUG] Processing payment webhook for payment %s", payment_id)
            
        try:
            # Get payment details directly from Mollie API
            api_key = request.env["ir.config_parameter"].sudo().get_param('mollie.api_key_test')
            if not api_key:
                api_key = request.env["ir.config_parameter"].sudo().get_param('mollie.api_key_prod')
            
            headers = {"Authorization": f"Bearer {api_key}"}
            resp = requests.get(f"https://api.mollie.com/v2/payments/{payment_id}", headers=headers, timeout=10)
            
            if resp.status_code != 200:
                _logger.error("Failed to fetch payment: %s", resp.text)
                return
                
            payment_data = resp.json()
            _logger.info("Got payment data: %s", payment_data)
            
            metadata = payment_data.get('metadata', {})
            order_id = metadata.get('order_id')
            customer_id = payment_data.get('customerId')
            mandate_id = payment_data.get('mandateId')
            
            if order_id:
                order = request.env['sale.order'].sudo().browse(int(order_id))
                if order.exists():
                    if payment_data['status'] == 'paid':
                        order.message_post(
                            body=f"Recurring payment confirmed via webhook. Payment ID: {payment_id}"
                        )
                        _logger.info("Recurring payment %s confirmed for order %s", payment_id, order.name)
                        
                        # If this is a recurring payment, create the next order
                        if metadata.get('type') == 'recurring_payment' and order.is_recurring_order:
                            self._create_next_recurring_order(order)
                            
                    elif payment_data['status'] == 'failed':
                        order.message_post(
                            body=f"Recurring payment failed via webhook. Payment ID: {payment_id}. Status: {payment_data['status']}"
                        )
                        _logger.warning("Recurring payment %s failed for order %s", payment_id, order.name)
                        
        except Exception as e:
            _logger.error("Error handling payment webhook: %s", e)
    
    def _handle_mandate_webhook(self, data):
        """Handle mandate webhook for iDEAL and recurring payments setup"""
        mandate_data = data
        _logger.info("[MOLLIE DEBUG] Processing mandate webhook: %s", mandate_data)
        
        try:
            # First, get payment details if this came from an iDEAL payment
            if mandate_data.get('method') == 'ideal':
                _logger.info("[MOLLIE DEBUG] Processing iDEAL mandate creation")
                payment_id = mandate_data.get('payment_id')
                if payment_id:
                    provider = request.env['payment.provider'].sudo().search([
                        ('code', '=', 'mollie')
                    ], limit=1)
                    if provider:
                        mollie = provider._get_mollie_client()
                        payment = mollie.payments.get(payment_id)
                        if payment.get('metadata', {}).get('order_id'):
                            mandate_data['order_id'] = payment['metadata']['order_id']
            
            mandate = request.env['mollie.mandate'].sudo().create_mandate_from_webhook(mandate_data)
            if mandate:
                _logger.info("[MOLLIE DEBUG] Successfully created mandate %s", mandate_data.get('id'))
                
                # If mandate is valid, link it to relevant orders
                if mandate.status == 'valid' and mandate.partner_id:
                    # Find orders for this partner that need mandates
                    orders = request.env['sale.order'].sudo().search([
                        ('partner_id', '=', mandate.partner_id.id),
                        ('is_mandate_approved', '=', False),
                        ('is_recurring_order', '=', True)
                    ])
                    
                    for order in orders:
                        order.write({
                            'mollie_mandate_ids': [(4, mandate.id)]
                        })
                        order.message_post(
                            body=f"Mandate approved and linked to order. Mandate ID: {mandate.mandate_id}"
                        )
                        _logger.info("Linked mandate %s to order %s", mandate.mandate_id, order.name)
            else:
                _logger.warning("Failed to process mandate webhook for data: %s", mandate_data)
                
        except Exception as e:
            _logger.error("Error handling mandate webhook: %s", e)
    
    def _create_next_recurring_order(self, order):
        """Create next recurring order when payment is successful"""
        try:
            # Copy the original order
            new_order = order.copy({
                'name': f"{order.name}-RENEWAL",
                'date_order': fields.Datetime.now(),
                'is_recurring_order': True,
                'mollie_mandate_ids': [(6, 0, order.mollie_mandate_ids.ids)]
            })
            
            # Copy order lines
            for line in order.order_line:
                line.copy({
                    'order_id': new_order.id,
                })
            
            new_order.message_post(
                body=f"Recurring order created automatically after successful payment. Original order: {order.name}"
            )
            order.message_post(
                body=f"New recurring order created: {new_order.name}"
            )
            
            _logger.info("Created new recurring order %s from %s", new_order.name, order.name)
            return new_order
            
        except Exception as e:
            _logger.error("Error creating next recurring order: %s", e)
            order.message_post(body=f"Failed to create next recurring order: {str(e)}")
            return False
    
    @http.route('/subscription/mandate/setup/<int:order_id>', 
                type='http', auth='user', website=True)
    def website_mandate_setup(self, order_id, **kwargs):
        """Website route for mandate setup"""
        order = request.env['sale.order'].browse(order_id)
        
        if not order.exists() or order.partner_id != request.env.user.partner_id:
            return request.redirect('/my/orders')
        
        # Check if already has mandate
        if order.is_mandate_approved:
            return request.redirect('/my/orders')
        
        # Create mandate setup payment
        try:
            action = order.action_create_mollie_mandate()
            if action and action.get('url'):
                return request.redirect(action['url'])
            else:
                return request.render('mollie_recurring.setup_error', {
                    'error': 'Failed to create mandate setup payment'
                })
        except Exception as e:
            _logger.error("Error in website mandate setup: %s", e)
            return request.render('mollie_recurring.setup_error', {
                'error': str(e)
            })
    
    @http.route('/my/recurring-orders', type='http', auth='user', website=True)
    def my_recurring_orders(self, **kwargs):
        """Website page showing user's recurring orders"""
        orders = request.env['sale.order'].search([
            ('partner_id', '=', request.env.user.partner_id.id),
            ('is_recurring_order', '=', True),
            ('state', 'in', ['sale', 'done'])
        ])
        
        return request.render('mollie_recurring.my_recurring_orders', {
            'orders': orders,
            'page_name': 'recurring_orders',
        })