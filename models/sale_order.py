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
    
    
    @api.model
    def _cron_recurring_create_invoice(self):
        """Extend official Odoo subscription cron with Mollie charging"""

        today = fields.Date.today()

        # Subscriptions due today
        orders = self.search([
            ('plan_id', '!=', False),
            ('next_invoice_date', '<=', today),
            ('state', 'in', ['sale', 'done']),
            ('partner_id.mollie_mandate_id', '!=', False),
            ('partner_id.mollie_mandate_status', '=', 'valid'),
        ])
        
        if not orders:
            _logger.info("✅ No subscription payments due for today (%s)", today)
            return True
        
        _logger.info("📦 Found %d subscription(s) due for payment", len(orders))

        mollie_provider = self.env['payment.provider'].search(
            [('code', '=', 'mollie')], limit=1
        )

        if not mollie_provider or not mollie_provider.mollie_api_key:
            _logger.error("❌ Mollie API key missing")
            return super()._cron_recurring_create_invoice()

        headers = {
            "Authorization": f"Bearer {mollie_provider.mollie_api_key}",
            "Content-Type": "application/json",
        }

        for order in orders:
            partner = order.partner_id
            amount = round(order.amount_total, 2)

            payload = {
                "amount": {
                    "currency": "EUR",
                    "value": f"{amount:.2f}",
                },
                "customerId": partner.mollie_customer_id,
                "mandateId": partner.mollie_mandate_id,
                "description": f"Subscription renewal for {order.name}",
                "sequenceType": "recurring",
                "metadata": {"order_id": order.id},
            }
            
            _logger.info("💳 Charging %s for %s EUR (Order %s, Plan: %s)", partner.name, amount, order.name, order.plan_id.name)

            try:
                response = requests.post(
                    "https://api.mollie.com/v2/payments",
                    json=payload,
                    headers=headers,
                    timeout=15,
                )
                data = response.json()

                if response.status_code != 201:
                    order.message_post(body=f"❌ Mollie payment failed: {data}")
                    continue

                payment_id = data.get("id")
                order.message_post(
                    body=f"✅ Mollie payment successful<br/>Payment ID: <b>{payment_id}</b>"
                )

                # 🔹 LET ODOO CREATE & POST THE INVOICE
                super(SaleOrder, order)._cron_recurring_create_invoice()

                # 🔹 Attach Mollie reference to latest invoice
                invoice = order.invoice_ids.sorted('id', reverse=True)[:1]
                if invoice:
                    invoice.message_post(
                        body=f"💳 Paid via Mollie Subscription<br/>Payment ID: <b>{payment_id}</b>"
                    )

                order.last_payment_id = payment_id

            except Exception as e:
                _logger.exception("⚠️ Mollie exception for %s", order.name)
                order.message_post(body=f"⚠️ Mollie exception: {e}")

        return True
        
