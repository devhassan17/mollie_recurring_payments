# -*- coding: utf-8 -*-
from odoo import models, api, fields
import requests
import logging
import time
from datetime import timedelta

_logger = logging.getLogger(__name__)


class MollieSubscriptionCron(models.Model):
    _name = "mollie.subscription.cron"
    _description = "Mollie Subscription Payment Processor"

    def _get_blocked_subscription_keywords(self):
        return ["churn", "closed", "cancel", "pause", "hold", "stop"]

    def _safe_text_contains_blocked_status(self, value):
        value = (value or "").strip().lower()
        if not value:
            return False
        return any(keyword in value for keyword in self._get_blocked_subscription_keywords())

    def _is_subscription_charge_blocked(self, order):
        """
        Extra runtime safety check for churned / paused / closed subscriptions.
        """
        blocked_boolean_fields = [
            "is_paused",
            "paused",
            "subscription_paused",
            "to_close",
            "is_closed",
        ]
        for field_name in blocked_boolean_fields:
            if field_name in order._fields and bool(order[field_name]):
                return True

        blocked_text_fields = [
            "subscription_state",
            "subscription_status",
            "stage_category",
            "state",
        ]
        for field_name in blocked_text_fields:
            if field_name in order._fields and self._safe_text_contains_blocked_status(order[field_name]):
                return True

        if "stage_id" in order._fields and order.stage_id:
            stage_parts = [
                getattr(order.stage_id, "name", ""),
                getattr(order.stage_id, "category", ""),
                getattr(order.stage_id, "code", ""),
            ]
            stage_text = " ".join([part for part in stage_parts if part])
            if self._safe_text_contains_blocked_status(stage_text):
                return True

        return False

    def _mollie_subscription_due_domain(self, today=None):
        """
        Domain for subscriptions we are allowed to charge.
        """
        today = today or fields.Date.today()

        domain = [
            ("plan_id", "!=", False),
            ("next_invoice_date", "=", today),
            ("partner_id.mollie_mandate_id", "!=", False),
            ("partner_id.mollie_mandate_status", "=", "valid"),
            ("state", "in", ["sale", "done"]),
        ]

        exclude_states = ["churn", "churned", "closed", "cancelled", "canceled", "done", "paused", "pause"]

        SaleOrder = self.env["sale.order"]
        if "subscription_state" in SaleOrder._fields:
            domain += [("subscription_state", "not in", exclude_states)]
        if "subscription_status" in SaleOrder._fields:
            domain += [("subscription_status", "not in", exclude_states)]
        if "stage_category" in SaleOrder._fields:
            domain += [("stage_category", "not in", exclude_states)]
        if "is_subscription" in SaleOrder._fields:
            domain += [("is_subscription", "=", True)]
        if "is_paused" in SaleOrder._fields:
            domain += [("is_paused", "=", False)]
        if "paused" in SaleOrder._fields:
            domain += [("paused", "=", False)]
        if "subscription_paused" in SaleOrder._fields:
            domain += [("subscription_paused", "=", False)]
        if "to_close" in SaleOrder._fields:
            domain += [("to_close", "=", False)]
        if "is_closed" in SaleOrder._fields:
            domain += [("is_closed", "=", False)]

        return domain

    def _mollie_api_request(self, method, url, headers=None, json=None, timeout=15, max_retries=3):
        headers = headers or {}
        last_response = None

        for attempt in range(max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json,
                    timeout=timeout,
                )
                last_response = response

                if response.status_code != 429:
                    return response

                retry_after = response.headers.get("Retry-After")
                try:
                    wait_seconds = int(retry_after) if retry_after else 60
                except Exception:
                    wait_seconds = 60

                _logger.warning(
                    "⚠️ Mollie rate limit hit on %s %s. Attempt %s/%s. Waiting %s seconds.",
                    method,
                    url,
                    attempt + 1,
                    max_retries + 1,
                    wait_seconds,
                )

                if attempt >= max_retries:
                    return response

                time.sleep(wait_seconds)

            except requests.RequestException:
                if attempt >= max_retries:
                    raise
                wait_seconds = 5 * (attempt + 1)
                _logger.warning(
                    "⚠️ Mollie request exception on %s %s. Retrying in %s seconds.",
                    method,
                    url,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

        return last_response

    @api.model
    def run_subscription_charges(self):
        """Runs daily subscription charges for Mollie recurring customers"""
        _logger.info("🔁 Running Mollie subscription payment cron...")

        SaleOrder = self.env["sale.order"]
        today = fields.Date.today()

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

        for index, order in enumerate(orders, start=1):
            if self._is_subscription_charge_blocked(order):
                _logger.info("⏭️ Skipping blocked subscription order %s", order.name)
                order.message_post(body="⏭️ Skipped Mollie export because subscription is churned / paused / closed.")
                continue

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
                response = self._mollie_api_request(
                    method="POST",
                    url="https://api.mollie.com/v2/payments",
                    json=payload,
                    headers=headers,
                    timeout=15,
                    max_retries=3,
                )
                response_data = response.json() if response and response.content else {}

                if response and response.status_code == 201:
                    payment_id = response_data.get("id")
                    order.message_post(
                        body=f"✅ Mollie subscription payment successful. Payment ID: {payment_id}"
                    )
                    _logger.info("✅ Payment success for %s, Mollie ID %s", order.name, payment_id)

                    next_date = self._calculate_next_payment_date(order, today)

                    order.sudo().write(
                        {
                            "next_invoice_date": next_date,
                            "last_payment_id": payment_id,
                        }
                    )

                    if index < len(orders):
                        time.sleep(2)

                else:
                    _logger.error("❌ Payment failed for %s: %s", order.name, response_data)
                    order.message_post(body=f"❌ Mollie subscription payment failed: {response_data}")

                    if response and response.status_code == 429:
                        _logger.warning("🛑 Stopping current batch due to Mollie 429 after retries.")
                        break

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
        else:
            return current_date + timedelta(days=30)