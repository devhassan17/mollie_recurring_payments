# -*- coding: utf-8 -*-
from odoo import models, api, fields
import requests
import logging
import time
from dateutil import parser as date_parser

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # -------------------------------------------------------------------------
    # Stored related fields for domain filters
    # -------------------------------------------------------------------------
    mollie_customer_id = fields.Char(
        string="Mollie Customer ID",
        related="partner_id.mollie_customer_id",
        store=True,
        readonly=True,
        index=True,
    )

    mollie_mandate_id = fields.Char(
        string="Mollie Mandate ID",
        related="partner_id.mollie_mandate_id",
        store=True,
        readonly=True,
        index=True,
    )

    mollie_transaction_id = fields.Char(
        string="Mollie Transaction ID",
        related="partner_id.mollie_transaction_id",
        store=True,
        readonly=True,
        index=True,
    )

    mollie_mandate_status = fields.Char(
        string="Mollie Mandate Status",
        related="partner_id.mollie_mandate_status",
        store=True,
        readonly=True,
        index=True,
    )

    subscription_type = fields.Selection(
        [
            ("monthly", "Monthly"),
            ("bimonthly", "Every 2 Months"),
        ],
        string="Subscription Type",
    )

    next_payment_date = fields.Date("Next Payment Date")
    last_payment_id = fields.Char("Last Mollie Payment ID", index=True)

    partner_email = fields.Char(
        string="Email",
        related="partner_id.email",
        store=True,
        readonly=True,
        index=True,
    )

    mollie_last_payment_status = fields.Char(string="Last Mollie Payment Status", readonly=True, index=True)
    mollie_last_payment_paid = fields.Boolean(string="Paid", readonly=True, index=True)
    mollie_last_payment_amount = fields.Monetary(string="Paid Amount", currency_field="currency_id", readonly=True)
    mollie_last_payment_paid_at = fields.Datetime(string="Paid At", readonly=True, index=True)
    mollie_last_payment_checked_at = fields.Datetime(string="Status Checked At", readonly=True)

    mollie_last_payment_unpaid_since = fields.Datetime(
        string="Unpaid Since",
        readonly=True,
        index=True,
    )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _is_subscription_order(self):
        """Check if this sale order includes subscription products."""
        return any(line.product_id.recurring_invoice for line in self.order_line)

    def _get_blocked_subscription_keywords(self):
        return ["churn", "closed", "cancel", "pause", "hold", "stop"]

    def _safe_text_contains_blocked_status(self, value):
        value = (value or "").strip().lower()
        if not value:
            return False
        return any(keyword in value for keyword in self._get_blocked_subscription_keywords())

    def _is_subscription_charge_blocked(self):
        """
        Extra runtime safety check.
        Stops churned / paused / closed / cancelled subscriptions from being sent to Mollie
        even if domain filters miss some customization/version-specific field.
        """
        self.ensure_one()

        blocked_boolean_fields = [
            "is_paused",
            "paused",
            "subscription_paused",
            "to_close",
            "is_closed",
        ]
        for field_name in blocked_boolean_fields:
            if field_name in self._fields and bool(self[field_name]):
                return True

        blocked_text_fields = [
            "subscription_state",
            "subscription_status",
            "stage_category",
            "state",
        ]
        for field_name in blocked_text_fields:
            if field_name in self._fields and self._safe_text_contains_blocked_status(self[field_name]):
                return True

        if "stage_id" in self._fields and self.stage_id:
            stage_parts = [
                getattr(self.stage_id, "name", ""),
                getattr(self.stage_id, "category", ""),
                getattr(self.stage_id, "code", ""),
            ]
            stage_text = " ".join([part for part in stage_parts if part])
            if self._safe_text_contains_blocked_status(stage_text):
                return True

        return False

    def _mollie_subscription_base_domain(self, today=None):
        today = today or fields.Date.today()
        domain = [
            ("plan_id", "!=", False),
            ("next_invoice_date", "=", today),
            ("state", "in", ["sale", "done"]),
            ("partner_id.mollie_mandate_id", "!=", False),
            ("partner_id.mollie_mandate_status", "=", "valid"),
        ]

        exclude_states = ["churn", "churned", "closed", "cancelled", "canceled", "done", "paused", "pause"]

        if "subscription_state" in self._fields:
            domain += [("subscription_state", "not in", exclude_states)]
        if "subscription_status" in self._fields:
            domain += [("subscription_status", "not in", exclude_states)]
        if "stage_category" in self._fields:
            domain += [("stage_category", "not in", exclude_states)]
        if "is_subscription" in self._fields:
            domain += [("is_subscription", "=", True)]
        if "is_paused" in self._fields:
            domain += [("is_paused", "=", False)]
        if "paused" in self._fields:
            domain += [("paused", "=", False)]
        if "subscription_paused" in self._fields:
            domain += [("subscription_paused", "=", False)]
        if "to_close" in self._fields:
            domain += [("to_close", "=", False)]
        if "is_closed" in self._fields:
            domain += [("is_closed", "=", False)]

        return domain

    def _mollie_subscription_status_refresh_domain(self):
        domain = [
            ("last_payment_id", "!=", False),
            ("plan_id", "!=", False),
            ("state", "in", ["sale", "done"]),
        ]

        exclude_states = ["churn", "churned", "closed", "cancelled", "canceled", "done", "paused", "pause"]

        if "subscription_state" in self._fields:
            domain += [("subscription_state", "not in", exclude_states)]
        if "subscription_status" in self._fields:
            domain += [("subscription_status", "not in", exclude_states)]
        if "stage_category" in self._fields:
            domain += [("stage_category", "not in", exclude_states)]
        if "is_subscription" in self._fields:
            domain += [("is_subscription", "=", True)]
        if "is_paused" in self._fields:
            domain += [("is_paused", "=", False)]
        if "paused" in self._fields:
            domain += [("paused", "=", False)]
        if "subscription_paused" in self._fields:
            domain += [("subscription_paused", "=", False)]
        if "to_close" in self._fields:
            domain += [("to_close", "=", False)]
        if "is_closed" in self._fields:
            domain += [("is_closed", "=", False)]

        return domain

    def _mollie_api_request(self, method, url, headers=None, json=None, timeout=15, max_retries=3):
        """
        Wrapper for Mollie API calls with 429 retry handling.
        """
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

    # -------------------------------------------------------------------------
    # Confirm flow: fetch mandate after confirm
    # -------------------------------------------------------------------------
    def action_confirm(self):
        res = super().action_confirm()

        for order in self:
            if not order._is_subscription_order():
                _logger.info("Order %s is not a subscription order. Skipping Mollie mandate creation.", order.name)
                continue

            mollie_provider = self.env["payment.provider"].search([("code", "=", "mollie")], limit=1)
            api_key = mollie_provider.mollie_api_key if mollie_provider else False

            if not api_key:
                _logger.error("Missing Mollie API key.")
                continue

            partner = order.partner_id
            time.sleep(5)
            partner.action_fetch_mollie_mandate()
            _logger.info("Fetched Mollie mandate for partner %s", partner.name)

        return res

    # -------------------------------------------------------------------------
    # Subscription cron: charge first, then create invoice (official cron)
    # -------------------------------------------------------------------------
    @api.model
    def _cron_recurring_create_invoice(self):
        today = fields.Date.today()
        orders = self.search(self._mollie_subscription_base_domain(today=today))

        if not orders:
            _logger.info("✅ No subscription payments due for today (%s)", today)
            return True

        _logger.info("📦 Found %d subscription(s) due for payment", len(orders))

        mollie_provider = self.env["payment.provider"].search([("code", "=", "mollie")], limit=1)
        if not mollie_provider or not mollie_provider.mollie_api_key:
            _logger.error("❌ Mollie API key is missing")
            return super()._cron_recurring_create_invoice()

        headers = {
            "Authorization": f"Bearer {mollie_provider.mollie_api_key}",
            "Content-Type": "application/json",
        }

        charged_orders = self.env["sale.order"]

        for index, order in enumerate(orders, start=1):
            if order._is_subscription_charge_blocked():
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

            _logger.info("💳 Charging %s for %s EUR (Order %s)", partner.name, amount, order.name)

            try:
                response = order._mollie_api_request(
                    method="POST",
                    url="https://api.mollie.com/v2/payments",
                    json=payload,
                    headers=headers,
                    timeout=15,
                    max_retries=3,
                )
                data = response.json() if response and response.content else {}

                if not response or response.status_code != 201:
                    order.message_post(body=f"❌ Mollie payment failed: {data}")
                    _logger.error("❌ Mollie payment failed for %s: %s", order.name, data)

                    # If Mollie is still rate-limiting after retries, stop loop cleanly
                    if response and response.status_code == 429:
                        _logger.warning("🛑 Stopping current batch due to Mollie 429 after retries.")
                        break
                    continue

                payment_id = data.get("id")
                order.message_post(
                    body=f"✅ Subscription payment exported to Mollie : <br/>Payment ID: <b>{payment_id}</b>"
                )

                order.sudo().write({
                    "last_payment_id": payment_id,
                    "mollie_last_payment_unpaid_since": False,
                    "mollie_last_payment_paid": False,
                    "mollie_last_payment_status": "open",
                })
                charged_orders |= order

                # Small delay to reduce burst requests
                if index < len(orders):
                    time.sleep(2)

            except Exception as e:
                _logger.exception("⚠️ Mollie exception for %s", order.name)
                order.message_post(body=f"⚠️ Mollie exception: {e}")

        if charged_orders:
            _logger.info("🧾 Creating invoices for %d successfully charged subscription(s)", len(charged_orders))
            super(SaleOrder, charged_orders)._cron_recurring_create_invoice()

            for order in charged_orders:
                invoice = order.invoice_ids.sorted("id", reverse=True)[:1]
                if invoice:
                    invoice.message_post(
                        body=f"💳 Paid via Mollie Subscription<br/>Payment ID: <b>{order.last_payment_id}</b>"
                    )

        return True

    # -------------------------------------------------------------------------
    # Manual + webhook + cron refresh payment status
    # -------------------------------------------------------------------------
    def action_refresh_last_mollie_payment_status(self):
        """Fetch last payment status from Mollie and apply accounting when paid."""
        mollie_provider = self.env["payment.provider"].search([("code", "=", "mollie")], limit=1)
        api_key = getattr(mollie_provider, "mollie_api_key", False)
        if not api_key:
            return

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        for order in self:
            payment_id = order.last_payment_id
            if not payment_id:
                continue

            try:
                resp = order._mollie_api_request(
                    method="GET",
                    url=f"https://api.mollie.com/v2/payments/{payment_id}",
                    headers=headers,
                    timeout=15,
                    max_retries=3,
                )
                if not resp or resp.status_code != 200:
                    text = resp.text if resp else "No response"
                    order.message_post(body=f"⚠️ Mollie status fetch failed for {payment_id}: {text}")
                    continue

                data = resp.json() if resp.content else {}
                status = data.get("status")
                paid = True if status == "paid" else False
                now = fields.Datetime.now()

                amount_value = 0.0
                try:
                    amount_value = float((data.get("amount") or {}).get("value") or 0.0)
                except Exception:
                    amount_value = 0.0

                paid_at = False
                paid_at_str = data.get("paidAt") or data.get("authorizedAt") or data.get("createdAt")
                if paid_at_str:
                    try:
                        paid_at = date_parser.isoparse(paid_at_str).replace(tzinfo=None)
                    except Exception:
                        paid_at = False

                vals = {
                    "mollie_last_payment_status": status,
                    "mollie_last_payment_paid": paid,
                    "mollie_last_payment_amount": amount_value,
                    "mollie_last_payment_paid_at": paid_at,
                    "mollie_last_payment_checked_at": now,
                }

                if paid:
                    vals["mollie_last_payment_unpaid_since"] = False
                    order._process_mollie_payment_success(payment_id, amount_value)
                else:
                    if not order.mollie_last_payment_unpaid_since:
                        vals["mollie_last_payment_unpaid_since"] = now

                order.sudo().write(vals)

            except Exception as e:
                _logger.exception("⚠️ Mollie status exception for order %s", order.name)
                order.message_post(body=f"⚠️ Mollie status exception: {e}")

    def _process_mollie_payment_success(self, payment_id, amount_value):
        """
        Process successful Mollie payment:
        - prevent duplicates
        - create account.payment
        - post + reconcile with latest unpaid invoice
        -> invoice.payment_state becomes paid automatically
        """
        self.ensure_one()
        _logger.info("✅ Processing Mollie payment success payment_id=%s order=%s", payment_id, self.name)

        existing_payment = self.env["account.payment"].sudo().search([
            ("mollie_payment_id", "=", payment_id),
            ("state", "in", ("posted", "reconciled")),
        ], limit=1)
        if existing_payment:
            _logger.info("⏭️ Mollie payment %s already processed in Odoo (%s).", payment_id, existing_payment.name)
            return True

        invoices = self.invoice_ids.filtered(lambda inv: inv.state == "posted" and inv.payment_state != "paid")
        if not invoices:
            _logger.info("⏭️ No posted unpaid invoices for order %s", self.name)
            return True

        invoice = invoices.sorted("id", reverse=True)[:1]
        if not invoice:
            return True
        invoice = invoice[0]

        if invoice.payment_state == "paid":
            return True

        journal = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        if not journal:
            _logger.error("❌ No bank journal found to register payment for order %s", self.name)
            return False

        payment_method_line = journal.inbound_payment_method_line_ids[:1]
        if not payment_method_line:
            _logger.error("❌ No inbound payment method line on journal %s", journal.display_name)
            return False

        pay_amount = invoice.amount_residual
        if amount_value and amount_value > 0:
            pay_amount = invoice.amount_residual or amount_value

        try:
            payment_vals = {
                "date": fields.Date.context_today(self),
                "amount": pay_amount,
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.partner_id.id,
                "journal_id": journal.id,
                "currency_id": invoice.currency_id.id,
                "payment_method_line_id": payment_method_line.id,
                "ref": f"Mollie Subscription Payment {payment_id}",
                "mollie_payment_id": payment_id,
            }

            payment = self.env["account.payment"].sudo().create(payment_vals)
            payment.action_post()

            inv_recv_lines = invoice.line_ids.filtered(
                lambda l: l.account_id.account_type == "asset_receivable" and not l.reconciled
            )
            pay_recv_lines = payment.move_id.line_ids.filtered(
                lambda l: l.account_id.account_type == "asset_receivable" and not l.reconciled
            )

            lines_to_reconcile = inv_recv_lines | pay_recv_lines
            if lines_to_reconcile:
                lines_to_reconcile.reconcile()

            _logger.info("✅ Payment %s posted and reconciled with invoice %s", payment.name, invoice.name)
            return True

        except Exception as e:
            _logger.exception("❌ Failed to register Mollie payment for order %s: %s", self.name, str(e))
            return False

    @api.model
    def cron_refresh_mollie_last_payment_status(self):
        orders = self.search(self._mollie_subscription_status_refresh_domain())
        if orders:
            orders.action_refresh_last_mollie_payment_status()
        return True