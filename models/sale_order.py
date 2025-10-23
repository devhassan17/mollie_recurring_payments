from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    mollie_mandate_ids = fields.One2many(
        'mollie.mandate', 
        'order_id', 
        string='Mollie Mandates'
    )
    
    def _get_payment_providers(self):
        """Override to filter payment providers for subscription orders"""
        providers = super()._get_payment_providers()
        if self.is_recurring_order:
            _logger.info("[MOLLIE DEBUG] Getting payment providers for subscription order %s", self.name)
            return providers.filtered(lambda p: p.code == 'mollie')
        return providers
    
    def _prepare_subscription_payment_values(self, amount, currency):
        """Prepare values for subscription payment"""
        self.ensure_one()
        partner = self.partner_id
        provider = self.env['payment.provider'].search([('code', '=', 'mollie')], limit=1)
        
        # Ensure customer exists in Mollie
        if not partner.mollie_customer_id:
            provider._mollie_create_customer(partner)
            
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        
        return {
            'amount': {
                'currency': currency.name,
                'value': f"{amount:.2f}"
            },
            'customerId': partner.mollie_customer_id,
            'sequenceType': 'first',  # This is key for subscription setup
            'method': 'ideal',
            'description': f"Initial payment for subscription {self.name}",
            'webhookUrl': f"{base_url}/payment/mollie/webhook",
            'redirectUrl': f"{base_url}/payment/mollie/return",
            'metadata': {
                'order_id': self.id,
                'is_subscription': True,
                'partner_id': partner.id,
            }
        }

    def _get_transaction_route(self):
        """Override to add subscription info to Mollie payment"""
        route = super()._get_transaction_route()
        
        if self.is_subscription_order and route.get('provider_code') == 'mollie':
            route['subscription'] = True
            
        return route

    def _mollie_create_recurring_payment(self, provider, amount, description, mandate_id):
        """Create recurring payment using existing mandate"""
        self.ensure_one()
        if not self.is_subscription_order:
            return super()._mollie_create_recurring_payment(
                provider, amount, description, mandate_id
            )
            
        partner = self.partner_id
        if not partner.mollie_customer_id:
            return False
            
        try:
            mollie = provider._get_mollie_client()
            payment_data = {
                'amount': {
                    'currency': self.currency_id.name,
                    'value': f"{amount:.2f}"
                },
                'customerId': partner.mollie_customer_id,
                'sequenceType': 'recurring',  # This indicates a recurring payment
                'mandateId': mandate_id,
                'description': description,
                'metadata': {
                    'order_id': self.id,
                    'is_subscription': True,
                    'partner_id': partner.id,
                }
            }
            
            payment = mollie.payments.create(payment_data)
            _logger.info(
                "Created recurring payment %s for subscription order %s",
                payment['id'], self.name
            )
            return payment
            
        except Exception as e:
            _logger.error("Failed to create recurring payment: %s", e)
            raise UserError(f"Failed to create recurring payment: {str(e)}")

    def _handle_payment_success(self, provider_code, tx_id):
        """Handle successful payment and setup mandate if needed"""
        res = super()._handle_payment_success(provider_code, tx_id)
        
        if (provider_code == 'mollie' and 
            self.is_subscription_order and 
            not self.active_mandate_id):
                
            tx = self.env['payment.transaction'].browse(tx_id)
            if tx.state == 'done':
                try:
                    # Create mandate from the first payment
                    mandate = self.env['mollie.mandate'].create({
                        'mandate_id': tx.provider_reference,  # Mollie payment ID
                        'customer_id': self.partner_id.mollie_customer_id,
                        'partner_id': self.partner_id.id,
                        'method': 'ideal',
                        'status': 'valid',
                        'order_id': self.id,
                        'is_default': True
                    })
                    
                    self.message_post(
                        body=f"Mandate {mandate.mandate_id} created from subscription payment"
                    )
                    
                except Exception as e:
                    _logger.error("Failed to create mandate: %s", str(e))
        
        return res
    
    def _create_mollie_mandate_from_transaction(self, transaction):
        """Create mandate from successful transaction"""
        provider = transaction.provider_id
        if provider.code != 'mollie':
            return False
            
        mollie = provider._get_mollie_client()
        payment = mollie.payments.get(transaction.provider_reference)
        
        if payment['sequenceType'] != 'first':
            payment = mollie.payments.create({
                'amount': {
                    'currency': self.currency_id.name,
                    'value': '0.01'
                },
                'customerId': self.partner_id.mollie_customer_id,
                'sequenceType': 'first',
                'method': 'ideal',
                'description': f"Mandate setup for order {self.name}",
                'metadata': {
                    'order_id': self.id,
                    'type': 'first_payment_mandate',
                    'partner_id': self.partner_id.id,
                }
            })
        
        # Create or update mandate
        mandate_data = {
            'mandate_id': payment['mandateId'],
            'customer_id': self.partner_id.mollie_customer_id,
            'partner_id': self.partner_id.id,
            'method': payment['method'],
            'status': 'valid',
            'order_id': self.id,
            'is_default': True
        }
        
        existing_mandate = self.env['mollie.mandate'].search([
            ('mandate_id', '=', payment['mandateId'])
        ], limit=1)
        
        if existing_mandate:
            existing_mandate.write(mandate_data)
            mandate = existing_mandate
        else:
            mandate = self.env['mollie.mandate'].create(mandate_data)
        
        self.message_post(
            body=f"Mandate {mandate.mandate_id} created automatically from website order"
        )
        return mandate
    
    @api.model_create_multi
    def create(self, vals_list):
        """Check for existing valid mandates when creating orders"""
        orders = super().create(vals_list)
        for order in orders:
            if order.is_recurring_order and order.partner_id:
                # Check for existing valid mandates
                existing_mandate = self.env['mollie.mandate'].search([
                    ('partner_id', '=', order.partner_id.id),
                    ('status', '=', 'valid')
                ], limit=1)
                if existing_mandate:
                    # Link the existing mandate to the order
                    existing_mandate.write({'order_id': order.id})
                    order.message_post(
                        body=f"Found existing valid mandate {existing_mandate.mandate_id} "
                             f"for partner {order.partner_id.name}"
                    )
        return orders
    
    active_mandate_id = fields.Many2one(
        'mollie.mandate',
        string='Active Mandate',
        compute='_compute_active_mandate',
        store=True
    )
    
    is_mandate_approved = fields.Boolean(
        string='Mandate Approved', 
        compute='_compute_mandate_status'
    )
    
    is_recurring_order = fields.Boolean(string='Recurring Order')
    recurrence_interval = fields.Integer(string='Recurrence Interval (months)', default=1)
    
    @api.depends('mollie_mandate_ids', 'mollie_mandate_ids.status')
    def _compute_active_mandate(self):
        for order in self:
            valid_mandate = order.mollie_mandate_ids.filtered(
                lambda m: m.status == 'valid'
            )
            order.active_mandate_id = valid_mandate[0] if valid_mandate else False
    
    @api.depends('active_mandate_id')
    def _compute_mandate_status(self):
        for order in self:
            order.is_mandate_approved = bool(order.active_mandate_id)
    
    def action_create_subscription_payment(self):
        """Create a payment for subscription order"""
        self.ensure_one()
        if not self.is_recurring_order:
            raise UserError(_('This action is only available for subscription orders'))

        _logger.info("[MOLLIE DEBUG] Creating subscription payment for order %s", self.name)
        
        # Create payment transaction
        values = self._prepare_subscription_payment()
        transaction = self.env['payment.transaction'].sudo().create(values)
        
        _logger.info("[MOLLIE DEBUG] Created payment transaction: %s", transaction)
        
        # Process the payment
        processing_values = transaction._get_processing_values()
        
        if processing_values.get('redirect_url'):
            return {
                'type': 'ir.actions.act_url',
                'url': processing_values['redirect_url'],
                'target': 'self',
            }
            
        return True
        
        if not provider:
            raise UserError("Mollie payment provider not found. Please install Mollie payments module.")
        
        # Create first payment for mandate setup
        amount = self.amount_total or 1.00  # Minimum amount for iDEAL
        description = f"Mandate setup for order {self.name}"
        
        # Use the payment provider method
        payment_data = self._mollie_create_first_payment(provider, amount, description)
        
        if payment_data:
            # Store temporary payment reference
            self.message_post(
                body=f"Mollie mandate setup initiated. Payment ID: {payment_data['id']}. Redirect URL: {payment_data['_links']['checkout']['href']}"
            )
            
            # Return action to redirect to Mollie
            return {
                'type': 'ir.actions.act_url',
                'url': payment_data['_links']['checkout']['href'],
                'target': 'self',
            }
        
        raise UserError("Failed to create mandate setup payment")
    
    def _prepare_subscription_payment(self):
        """Prepare payment data for subscription"""
        self.ensure_one()
        
        provider = self.env['payment.provider'].search([('code', '=', 'mollie')], limit=1)
        if not provider:
            raise UserError(_('Mollie payment provider not found'))
            
        # Get base URL for redirects
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        
        payment_data = {
            'amount': {
                'currency': self.currency_id.name,
                'value': f"{self.amount_total:.2f}"
            },
            'description': f"Subscription payment for {self.name}",
            'redirectUrl': f"{base_url}/payment/mollie/return",
            'webhookUrl': f"{base_url}/payment/mollie/webhook",
            'metadata': {
                'order_id': self.id,
                'is_subscription': True
            },
            'sequenceType': 'first',  # First payment for subscription
            'method': 'ideal'  # Force iDEAL for first payment
        }
            
            payment = mollie.payments.create(payment_data)
            _logger.info("Created first payment %s for order %s", payment['id'], self.name)
            return payment
        except Exception as e:
            _logger.error("Failed to create first payment: %s", e)
            raise UserError(f"Failed to create payment: {str(e)}")
    
    def action_create_recurring_payment(self):
        """Create recurring payment using existing mandate"""
        self.ensure_one()
        
        if not self.active_mandate_id:
            raise UserError("No valid mandate found for this order. Please setup mandate first.")
        
        provider = self.env['payment.provider'].search([
            ('code', '=', 'mollie')
        ], limit=1)
        
        amount = self.amount_total
        description = f"Recurring payment for order {self.name}"
        
        payment_data = self._mollie_create_recurring_payment(
            provider, amount, description, self.active_mandate_id.mandate_id
        )
        
        if payment_data:
            self.message_post(body=f"Recurring payment created: {payment_data['id']}. Status: {payment_data['status']}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Success',
                    'message': f'Recurring payment created successfully. Payment ID: {payment_data["id"]}',
                    'type': 'success',
                    'sticky': False,
                }
            }
        
        raise UserError("Failed to create recurring payment")
    
    def _mollie_create_recurring_payment(self, provider, amount, description, mandate_id):
        """Create recurring payment using existing mandate"""
        partner = self.partner_id
        
        if not partner.mollie_customer_id:
            _logger.error("No Mollie customer ID for partner %s", partner.id)
            return False
            
        try:
            mollie = provider._mollie_get_client()
            payment_data = {
                'amount': {
                    'currency': self.currency_id.name,
                    'value': f"{amount:.2f}"
                },
                'customerId': partner.mollie_customer_id,
                'sequenceType': 'recurring',
                'method': 'ideal',
                'mandateId': mandate_id,
                'description': description,
                'metadata': {
                    'order_id': self.id,
                    'type': 'recurring_payment',
                    'partner_id': partner.id,
                }
            }
            
            payment = mollie.payments.create(payment_data)
            _logger.info("Created recurring payment %s for order %s", payment['id'], self.name)
            return payment
        except Exception as e:
            _logger.error("Failed to create recurring payment: %s", e)
            raise UserError(f"Failed to create recurring payment: {str(e)}")

class ResPartner(models.Model):
    _inherit = 'res.partner'
    
    mollie_customer_id = fields.Char(string='Mollie Customer ID')
    mollie_mandate_ids = fields.One2many('mollie.mandate', 'partner_id', string='Mollie Mandates')