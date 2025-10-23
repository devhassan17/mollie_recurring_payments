from odoo import models, fields, api
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
    
    def action_create_mollie_mandate(self):
        """Create first Mollie payment to establish mandate"""
        self.ensure_one()
        
        provider = self.env['payment.provider'].search([
            ('code', '=', 'mollie')
        ], limit=1)
        
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
    
    def _mollie_create_first_payment(self, provider, amount, description):
        """Create first payment using Mollie provider"""
        partner = self.partner_id
        
        # Ensure customer exists in Mollie
        if not partner.mollie_customer_id:
            provider._mollie_create_customer(partner)
        
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        
        try:
            mollie = provider._mollie_get_client()
            payment_data = {
                'amount': {
                    'currency': self.currency_id.name,
                    'value': f"{amount:.2f}"
                },
                'customerId': partner.mollie_customer_id,
                'sequenceType': 'first',
                'method': 'ideal',
                'description': description,
                'redirectUrl': f"{base_url}/payment/mollie/recurring/return/{self.id}",
                'webhookUrl': f"{base_url}/payment/mollie/recurring/webhook",
                'metadata': {
                    'order_id': self.id,
                    'type': 'first_payment_mandate',
                    'partner_id': partner.id,
                }
            }
            
            payment = mollie.payments.create(payment_data)
            _logger.info(f"Created first payment {payment['id']} for order {self.name}")
            return payment
        except Exception as e:
            _logger.error(f"Failed to create first payment: {e}")
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
            _logger.error(f"No Mollie customer ID for partner {partner.id}")
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
            _logger.info(f"Created recurring payment {payment['id']} for order {self.name}")
            return payment
        except Exception as e:
            _logger.error(f"Failed to create recurring payment: {e}")
            raise UserError(f"Failed to create recurring payment: {str(e)}")

class ResPartner(models.Model):
    _inherit = 'res.partner'
    
    mollie_customer_id = fields.Char(string='Mollie Customer ID')
    mollie_mandate_ids = fields.One2many('mollie.mandate', 'partner_id', string='Mollie Mandates')