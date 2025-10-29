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
        ('monthly', 'Monthly'),
        ('bimonthly', 'Every 2 Months'),
    ], string="Subscription Type")

    next_payment_date = fields.Date("Next Payment Date")
    last_payment_status = fields.Char("Last Payment Status", readonly=True)
    mollie_last_transaction_id = fields.Char("Last Mollie Transaction ID", readonly=True)

    
    def _is_subscription_order(self):
        """Check if this sale order includes subscription products."""
        return any(line.product_id.recurring_invoice for line in self.order_line)

    def action_confirm(self):
        """When a sale order is confirmed, create Mollie customer + mandate."""
        res = super().action_confirm()

        for order in self:
            order.next_payment_date = fields.Date.today() + timedelta(days=30 if order.subscription_type == "monthly" else 60)

            if not order._is_subscription_order():
                _logger.info("Order %s is not a subscription order. Skipping Mollie mandate creation.", order.name)
                continue
            
            api_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
            if not api_key:
                _logger.error("Missing Mollie API key.")
                continue
            
            partner = order.partner_id
            time.sleep(5)
            partner.action_fetch_mollie_mandate()
            _logger.info("Fetched Mollie mandate for partner %s", partner.name)
            _logger.info("Partner %s", partner)

        return res
        
    

""" PUSH THIS CODE TO OFFICIAL MOLLIE MODULE WITH THE FOLLOWING CHANGE in File Name models/payment_transaction.py in function _mollie_prepare_payment_request_payload:

# --- EDITED Recurring logic ---
 def _mollie_prepare_payment_request_payload(self):
        user_lang = self.env.context.get('lang')
        base_url = self.provider_id.get_base_url()
        redirect_url = urls.url_join(base_url, MollieController._return_url)
        webhook_url = urls.url_join(base_url, MollieController._webhook_url)
        decimal_places = CURRENCY_MINOR_UNITS.get(
            self.currency_id.name, self.currency_id.decimal_places
        )
    
        # Fetch partner info
        partner = self.partner_id
    
        payload = {
            'description': self.reference,
            'amount': {
                'currency': self.currency_id.name,
                'value': f"{self.amount:.{decimal_places}f}",
            },
            'locale': user_lang if user_lang in const.SUPPORTED_LOCALES else 'en_US',
            'method': [const.PAYMENT_METHODS_MAPPING.get(
                self.payment_method_code, self.payment_method_code
            )],
            'redirectUrl': f'{redirect_url}?ref={self.reference}',
            'webhookUrl': f'{webhook_url}?ref={self.reference}',
        }
    
        # --- EDITED Recurring logic ---
        api_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        order = self.env['sale.order'].search([('name', '=', self.reference)], limit=1)
        is_subscription_order = any(line.product_id.recurring_invoice for line in order.order_line)
        
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        if is_subscription_order:
            
            customer_id = partner.mollie_customer_id
            
            if not customer_id:
                customer_payload = {
                    "name": partner.name,
                    "email": partner.email,
                    "metadata": {"odoo_partner_id": partner.id},
                }
                resp = requests.post("https://api.mollie.com/v2/customers", json=customer_payload, headers=headers)
                if resp.status_code == 201:
                    partner.mollie_customer_id = resp.json().get("id")
                    customer_id = resp.json().get("id")
                    _logger.info("Created Mollie customer for %s", partner.name)
                else:
                    _logger.error("Customer creation failed: %s", resp.text)

                payload.update({
                    'sequenceType': 'first',
                    'customerId': customer_id,
                })

                partner.action_fetch_mollie_mandate()
            else:
                payload.update({
                    'sequenceType': 'first',
                    'customerId': customer_id,
                })

                partner.action_fetch_mollie_mandate()
              
        return payload

"""