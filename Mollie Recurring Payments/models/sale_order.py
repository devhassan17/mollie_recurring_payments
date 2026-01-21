from odoo import models, api, _, fields
import requests
import logging
import time 
from datetime import timedelta

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = "sale.order"
     
    mollie_customer_id = fields.Char(
        string="Mollie Customer ID",
        related="partner_id.mollie_customer_id",
        store=False,
        readonly=True
    )
    
    mollie_mandate_id = fields.Char(
        string="Mollie Mandate ID",
        related="partner_id.mollie_mandate_id",
        store=False,
        readonly=True
    )
    
    mollie_transaction_id = fields.Char(
        string="Mollie Transaction ID",
        related="partner_id.mollie_transaction_id",
        store=False,
        readonly=True
    )

    mollie_mandate_status = fields.Char(
        string="Mollie Mandate Status",
        related="partner_id.mollie_mandate_status",
        store=False,
        readonly=True
    )
    
    
    subscription_type = fields.Selection([
        ("monthly", "Monthly"),
        ("bimonthly", "Every 2 Months"),
    ], string="Subscription Type")

    next_payment_date = fields.Date("Next Payment Date")
    last_payment_id = fields.Char("Last Mollie Payment ID")
    
    def _is_subscription_order(self):
        """Check if this sale order includes subscription products."""
        return any(line.product_id.recurring_invoice for line in self.order_line)

    def action_confirm(self):
        """When a sale order is confirmed, create Mollie customer + mandate."""
        res = super().action_confirm()

        for order in self:
            if not order._is_subscription_order():
                _logger.info("Order %s is not a subscription order. Skipping Mollie mandate creation.", order.name)
                continue
            
            mollie_provider = self.env['payment.provider'].search([('code', '=', 'mollie')], limit=1)
            api_key = mollie_provider.mollie_api_key
            
            if not api_key:
                _logger.error("Missing Mollie API key.")
                continue
            
            partner = order.partner_id
            time.sleep(5)
            partner.action_fetch_mollie_mandate()
            _logger.info("Fetched Mollie mandate for partner %s", partner.name)
            _logger.info("Partner %s", partner)

        return res
        
