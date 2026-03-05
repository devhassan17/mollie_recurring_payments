# -*- coding: utf-8 -*-
from odoo import models, api, fields
import requests
import logging
from datetime import timedelta

_logger = logging.getLogger(__name__)


class MollieSubscriptionCron(models.Model):
    _name = "mollie.subscription.cron"
    _description = "Mollie Subscription Payment Processor"

    def _mollie_subscription_due_domain(self, today=None):
        """
        Domain for subscriptions we are allowed to charge.

        IMPORTANT:
        - Churned subscriptions can still be state sale/done and still have next_invoice_date,
          so we must explicitly exclude churn/closed/cancelled lifecycle states when possible.
        """
        today = today or fields.Date.today()

        domain = [
            ("plan_id", "!=", False),  # Has a subscription plan
            ("next_invoice_date", "=", today),  # Due today
            ("partner_id.mollie_mandate_id", "!=", False),  # Has Mollie mandate
            ("partner_id.mollie_mandate_status", "=", "valid"),  # Mandate is valid
            ("state", "in", ["sale", "done"]),  # Active orders
        ]

        # ✅ Exclude churned/closed subscriptions (field name differs per version/customization)
        exclude_states = ["churn", "churned", "closed", "cancelled", "canceled", "done"]

        SaleOrder = self.env["sale.order"]
        if "subscription_state" in SaleOrder._fields:
            domain += [("subscription_state", "not in", exclude_states)]
        if "subscription_status" in SaleOrder._fields:
            domain += [("subscription_status", "not in", exclude_states)]
        if "is_subscription" in SaleOrder._fields:
            domain += [("is_subscription", "=", True)]

        return domain

    @api.model
    def run_subscription_charges(self):
        """Runs daily subscription charges for Mollie recurring customers"""
        _logger.info("🔁 Running Mollie subscription payment cron...")

        SaleOrder = self.env["sale.order"]
        today = fields.Date.today()

        # ✅ UPDATED: exclude churned/closed subs
        orders = SaleOrder.search(self._mollie_subscription_due_domain(today=today))

        if not orders:
            _logger.info("✅ No subscription payments due for today (%s)", today)
            return True

        _logger.info("📦 Found %d subscription(s) due for payment", len(orders))

        mollie_provider = self.env["payment.provider"].search([("code", "=", "mollie")], limit=1)
        api_key = mollie_provider.mollie_api_key if mollie_provider else False

        if not api_key:
            _logger.error("❌ Mollie API key missing in Mollie Module")
            return False

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        for order in orders:
            partner = order.partner_id
            amount = round(order.amount_total, 2)

            payload = {
                "amount": {"currency": "EUR", "value": f"{amount:.2f}"},
                "customerId": partner.mollie_customer_id,
                "mandateId": partner.mollie_mandate_id,
                "description": f"Subscription renewal for {order.name}",
                "sequenceType": "recurring",
                "metadata": {"order_id": order.id},
            }

            _logger.info(
                "💳 Charging %s for %s EUR (Order %s, Plan: %s)",
                partner.name,
                amount,
                order.name,
                order.plan_id.name,
            )

            try:
                response = requests.post(
                    "https://api.mollie.com/v2/payments",
                    json=payload,
                    headers=headers,
                    timeout=15,
                )
                response_data = response.json() if response.content else {}

                if response.status_code == 201:
                    payment_id = response_data.get("id")
                    order.message_post(
                        body=f"✅ Mollie subscription payment successful. Payment ID: {payment_id}"
                    )
                    _logger.info("✅ Payment success for %s, Mollie ID %s", order.name, payment_id)

                    next_date = self._calculate_next_payment_date(order, today)

                    order.sudo().write(
                        {
                            "next_invoice_date": next_date,  # Update next invoice date
                            "last_payment_id": payment_id,
                        }
                    )

                else:
                    _logger.error("❌ Payment failed for %s: %s", order.name, response_data)
                    order.message_post(body=f"❌ Mollie subscription payment failed: {response_data}")

            except Exception as e:
                _logger.exception("⚠️ Exception during payment for order %s: %s", order.name, str(e))
                order.message_post(body=f"⚠️ Mollie payment exception: {str(e)}")

        _logger.info("🏁 Mollie subscription payment cron completed successfully.")
        return True

    def _calculate_next_payment_date(self, order, current_date):
        """Calculate next payment date based on plan type"""
        plan_name = (order.plan_id.name or "").lower()

        if "3 monthly" in plan_name:
            return current_date + timedelta(days=90)
        elif "2 monthly" in plan_name:
            return current_date + timedelta(days=60)
        else:  # Monthly (default)
            return current_date + timedelta(days=30)