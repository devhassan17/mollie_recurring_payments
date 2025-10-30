from odoo import models, api, fields
import requests
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

class MollieSubscriptionCron(models.Model):
    _name = "mollie.subscription.cron"
    _description = "Mollie Subscription Payment Processor"

    @api.model
    def run_subscription_charges(self):
        """Runs daily subscription charges for Mollie recurring customers"""
        _logger.info("🔁 Running Mollie subscription payment cron...")

        SaleOrder = self.env["sale.order"]
        today = fields.Date.today()

        orders = SaleOrder.search([
            ("subscription_type", "in", ["monthly", "bimonthly"]),
            ("next_payment_date", "=", today),
            ("last_payment_date", "!=", today),  
            ("partner_id.mollie_mandate_id", "!=", False),
            ("partner_id.mollie_mandate_status", "=", "valid"),
            ("state", "in", ["sale", "done"]),
        ])

        if not orders:
            _logger.info("✅ No subscriptions due for today (%s)", today)
            return True

        _logger.info("📦 Found %d subscription(s) due for payment", len(orders))

        api_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
        if not api_key:
            _logger.error("❌ Mollie API key missing in system parameters!")
            return False

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        for order in orders:
            partner = order.partner_id
            amount = round(order.amount_total, 2)

            payload = {
                "amount": {
                    "currency": "EUR",
                    "value": f"{amount:.2f}"
                },
                "customerId": partner.mollie_customer_id,
                "mandateId": partner.mollie_mandate_id,
                "description": f"Subscription renewal for {order.name}",
                "sequenceType": "recurring",
                "metadata": {"order_id": order.id},
            }

            _logger.info("💳 Charging %s for %s EUR (Order %s)", partner.name, amount, order.name)

            try:
                response = requests.post("https://api.mollie.com/v2/payments", json=payload, headers=headers, timeout=15)
                response_data = response.json()

                if response.status_code == 201:
                    payment_id = response_data.get("id")
                    order.message_post(body=f"✅ Mollie subscription payment successful. Payment ID: {payment_id}")
                    _logger.info("✅ Payment success for %s, Mollie ID %s", order.name, payment_id)

                    # Set next payment date
                    if order.subscription_type == "monthly":
                        next_date = today + timedelta(days=30)
                    else:  # bimonthly
                        next_date = today + timedelta(days=60)

                    order.sudo().write({
                        "next_payment_date": next_date,
                        "last_payment_id": payment_id,
                    })

                else:
                    _logger.error("❌ Payment failed for %s: %s", order.name, response_data)
                    order.message_post(body=f"❌ Mollie subscription payment failed: {response_data}")

            except Exception as e:
                _logger.exception("⚠️ Exception during payment for order %s: %s", order.name, str(e))
                order.message_post(body=f"⚠️ Mollie payment exception: {str(e)}")

        _logger.info("🏁 Mollie subscription payment cron completed successfully.")
        return True
