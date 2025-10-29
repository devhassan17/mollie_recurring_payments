from odoo import models, fields, api, _
import requests
import logging
from datetime import timedelta

_logger = logging.getLogger(__name__)


class MollieSubscriptionPaymentCron(models.Model):
    _name = "mollie.subscription.cron"
    _description = "Daily Mollie Subscription Payment Cron"

    @api.model
    def run_subscription_charges(self):
        """Run daily to charge all subscriptions with due dates."""
        today = fields.Date.today()
        api_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        if not api_key:
            _logger.error("Missing Mollie API key for subscription payments.")
            return
        
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        orders = self.env["sale.order"].search([
            ("state", "in", ["sale", "done"]),
            ("next_payment_date", "=", today),
            ("subscription_type", "!=", False),
        ])

        _logger.info("🔁 Checking %s subscription orders due for payment today", len(orders))

        for order in orders:
            partner = order.partner_id

            if not partner.mollie_customer_id or not partner.mollie_mandate_id:
                _logger.warning("Skipping %s: missing Mollie customer or mandate.", partner.name)
                continue

            payment_payload = {
                "amount": {
                    "currency": order.currency_id.name,
                    "value": f"{order.amount_total:.2f}"
                },
                "customerId": partner.mollie_customer_id,
                "sequenceType": "recurring",
                "description": f"Subscription renewal for order {order.name}",
                "mandateId": partner.mollie_mandate_id,
                "redirectUrl": f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/mollie/payment/return",
                "webhookUrl": f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/mollie/mandate/webhook",
            }

            response = requests.post("https://api.mollie.com/v2/payments", json=payment_payload, headers=headers, timeout=15)
            if response.status_code == 201:
                data = response.json()
                order.sudo().write({
                    "mollie_last_transaction_id": data.get("id"),
                    "last_payment_status": data.get("status"),
                })
                _logger.info("✅ Charged %s via Mollie: %s", partner.name, data.get("id"))
            else:
                _logger.error("❌ Mollie charge failed for %s: %s", partner.name, response.text)
                order.sudo().write({"last_payment_status": "failed"})

            # Update next payment date
            if order.subscription_type == "monthly":
                next_date = fields.Date.to_date(order.next_payment_date) + timedelta(days=30)
            elif order.subscription_type == "bimonthly":
                next_date = fields.Date.to_date(order.next_payment_date) + timedelta(days=60)
            else:
                next_date = False

            if next_date:
                order.sudo().write({"next_payment_date": next_date})
