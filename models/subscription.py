from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class SaleSubscription(models.Model):
    _inherit = 'sale.subscription'
    
    mollie_mandate_ids = fields.One2many(
        'mollie.mandate', 
        'subscription_id', 
        string='Mollie Mandates'
    )
    
    active_mandate_id = fields.Many2one(
        'mollie.mandate',
        string='Active Mandate',
        compute='_compute_active_mandate',
        store=True
    )
    
    mollie_customer_id = fields.Char(
        related='partner_id.mollie_customer_id',
        string='Mollie Customer ID'
    )
    
    is_mandate_approved = fields.Boolean(
        string='Mandate Approved', 
        compute='_compute_mandate_status'
    )
    
    @api.depends('mollie_mandate_ids', 'mollie_mandate_ids.status')
    def _compute_active_mandate(self):
        for subscription in self:
            valid_mandate = subscription.mollie_mandate_ids.filtered(
                lambda m: m.status == 'valid'
            )
            subscription.active_mandate_id = valid_mandate[0] if valid_mandate else False
    
    @api.depends('active_mandate_id')
    def _compute_mandate_status(self):
        for subscription in self:
            subscription.is_mandate_approved = bool(subscription.active_mandate_id)
    
    def action_create_mollie_mandate(self):
        """Create first Mollie payment to establish mandate"""
        self.ensure_one()
        
        provider = self.env['payment.provider'].search([
            ('code', '=', 'mollie')
        ], limit=1)
        
        if not provider:
            raise UserError(_("Mollie payment provider not found. Please install Mollie payments module."))
        
        # Create first payment for mandate setup
        amount = self.recurring_total or 1.00  # Minimum amount for iDEAL
        description = f"Mandate setup for subscription {self.code}"
        
        payment_data = provider._mollie_create_first_payment(self, amount, description)
        
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
        
        raise UserError(_("Failed to create mandate setup payment"))
    
    def action_create_recurring_payment(self):
        """Create recurring payment using existing mandate"""
        self.ensure_one()
        
        if not self.active_mandate_id:
            raise UserError(_("No valid mandate found for this subscription. Please setup mandate first."))
        
        provider = self.env['payment.provider'].search([
            ('code', '=', 'mollie')
        ], limit=1)
        
        amount = self.recurring_total
        description = f"Subscription renewal {self.code}"
        
        payment_data = provider._mollie_create_recurring_payment(
            self, 
            amount, 
            description, 
            self.active_mandate_id.mandate_id
        )
        
        if payment_data:
            self.message_post(body=f"Recurring payment created: {payment_data['id']}. Status: {payment_data['status']}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Recurring payment created successfully. Payment ID: %s', payment_data['id']),
                    'type': 'success',
                    'sticky': False,
                }
            }
        
        raise UserError(_("Failed to create recurring payment"))

class ResPartner(models.Model):
    _inherit = 'res.partner'
    
    mollie_customer_id = fields.Char(string='Mollie Customer ID')
    mollie_mandate_ids = fields.One2many('mollie.mandate', 'partner_id', string='Mollie Mandates')