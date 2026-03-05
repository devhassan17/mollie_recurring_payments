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

    def _mollie_subscription_base_domain(self, today=None):
        today = today or fields.Date.today()
        domain = [
            ("plan_id", "!=", False),
            ("next_invoice_date", "=", today),
            ("state", "in", ["sale", "done"]),
            ("partner_id.mollie_mandate_id", "!=", False),
            ("partner_id.mollie_mandate_status", "=", "valid"),
        ]

        exclude_states = ["churn", "churned", "closed", "cancelled", "canceled", "done"]

        if "subscription_state" in self._fields:
            domain += [("subscription_state", "not in", exclude_states)]
        if "subscription_status" in self._fields:
            domain += [("subscription_status", "not in", exclude_states)]
        if "is_subscription" in self._fields:
            domain += [("is_subscription", "=", True)]

        return domain

    def _mollie_subscription_status_refresh_domain(self):
        domain = [
            ("last_payment_id", "!=", False),
            ("plan_id", "!=", False),
            ("state", "in", ["sale", "done"]),
        ]

        exclude_states = ["churn", "churned", "closed", "cancelled", "canceled", "done"]

        if "subscription_state" in self._fields:
            domain += [("subscription_state", "not in", exclude_states)]
        if "subscription_status" in self._fields:
            domain += [("subscription_status", "not in", exclude_states)]
        if "is_subscription" in self._fields:
            domain += [("is_subscription", "=", True)]

        return domain

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

            _logger.info("💳 Charging %s for %s EUR (Order %s)", partner.name, amount, order.name)

            try:
                response = requests.post(
                    "https://api.mollie.com/v2/payments",
                    json=payload,
                    headers=headers,
                    timeout=15,
                )
                data = response.json() if response.content else {}

                if response.status_code != 201:
                    order.message_post(body=f"❌ Mollie payment failed: {data}")
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
                resp = requests.get(
                    f"https://api.mollie.com/v2/payments/{payment_id}",
                    headers=headers,
                    timeout=15
                )
                if resp.status_code != 200:
                    order.message_post(body=f"⚠️ Mollie status fetch failed for {payment_id}: {resp.text}")
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

                    # ✅ This is the key: when Mollie becomes paid later, we apply payment & reconcile
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

        # 0) If payment already processed, stop (idempotency)
        existing_payment = self.env["account.payment"].sudo().search([
            ("mollie_payment_id", "=", payment_id),
            ("state", "in", ("posted", "reconciled")),
        ], limit=1)
        if existing_payment:
            _logger.info("⏭️ Mollie payment %s already processed in Odoo (%s).", payment_id, existing_payment.name)
            return True

        # 1) Find latest posted invoice that is not paid
        invoices = self.invoice_ids.filtered(lambda inv: inv.state == "posted" and inv.payment_state != "paid")
        if not invoices:
            _logger.info("⏭️ No posted unpaid invoices for order %s", self.name)
            return True

        invoice = invoices.sorted("id", reverse=True)[:1]
        if not invoice:
            return True
        invoice = invoice[0]

        # If already paid (double safety)
        if invoice.payment_state == "paid":
            return True

        # 2) Select a bank journal
        journal = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        if not journal:
            _logger.error("❌ No bank journal found to register payment for order %s", self.name)
            return False

        # 3) Payment method line
        payment_method_line = journal.inbound_payment_method_line_ids[:1]
        if not payment_method_line:
            _logger.error("❌ No inbound payment method line on journal %s", journal.display_name)
            return False

        # 4) Amount: safer to use invoice residual (in case Mollie sent full but invoice has rounding/partial)
        pay_amount = invoice.amount_residual
        if amount_value and amount_value > 0:
            # If invoice residual is zero or less (rare), fallback to Mollie
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

            # 5) Reconcile receivable lines properly
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