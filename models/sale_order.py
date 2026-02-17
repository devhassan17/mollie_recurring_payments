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
    # 🔥 IMPORTANT UPDATE FOR MARKETING AUTOMATION DOMAINS:
    # These related fields MUST be stored to appear in domain filters reliably.
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

    # ✅ OK to update every cron (for audit/logging)
    mollie_last_payment_checked_at = fields.Datetime(string="Status Checked At", readonly=True)

    # ✅ NEW: This is the stable date to use for "after 7 days unpaid" automations.
    # It is set ONCE when Mollie status becomes unpaid and is NOT changed again until paid.
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

    # -------------------------------------------------------------------------
    # Confirm flow: fetch mandate after confirm
    # -------------------------------------------------------------------------
    def action_confirm(self):
        """When a sale order is confirmed, create Mollie customer + mandate."""
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
        """Extend official Odoo subscription cron with Mollie charging."""
        today = fields.Date.today()
        orders = self.search(
            [
                ("plan_id", "!=", False),
                ("next_invoice_date", "=", today),
                ("state", "in", ["sale", "done"]),
                ("partner_id.mollie_mandate_id", "!=", False),
                ("partner_id.mollie_mandate_status", "=", "valid"),
            ]
        )

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
        now = fields.Datetime.now()

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

                # If Mollie call fails, DO NOT touch unpaid_since here.
                # unpaid_since is controlled only by status refresh method.
                if response.status_code != 201:
                    order.message_post(body=f"❌ Mollie payment failed: {data}")
                    continue

                payment_id = data.get("id")
                order.message_post(
                    body=f"✅ Subscription payment exported to Mollie : <br/>Payment ID: <b>{payment_id}</b>"
                )

                # ✅ New renewal payment created => reset the unpaid timer so automation starts fresh
                order.sudo().write({
                    "last_payment_id": payment_id,
                    "mollie_last_payment_unpaid_since": False,   # important
                    "mollie_last_payment_paid": False,           # optional but recommended
                    "mollie_last_payment_status": "open",        # optional (or False)
                })
                charged_orders |= order

            except Exception as e:
                _logger.exception("⚠️ Mollie exception for %s", order.name)
                order.message_post(body=f"⚠️ Mollie exception: {e}")

        # Create invoices only for successfully charged orders
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
    # Manual + cron refresh payment status (for Marketing Automation triggers too)
    # -------------------------------------------------------------------------
    def action_refresh_last_mollie_payment_status(self):
        """Fetch last payment status from Mollie for dashboard and order form."""
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
                resp = requests.get(f"https://api.mollie.com/v2/payments/{payment_id}", headers=headers, timeout=15)
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

                # ✅ Freeze unpaid_since while unpaid:
                # - if unpaid_since is already set, NEVER update it again until paid.
                vals = {
                    "mollie_last_payment_status": status,
                    "mollie_last_payment_paid": paid,
                    "mollie_last_payment_amount": amount_value,
                    "mollie_last_payment_paid_at": paid_at,
                    "mollie_last_payment_checked_at": now,  # ok to update every run
                }

                if paid:
                    # payment recovered, clear unpaid_since
                    vals["mollie_last_payment_unpaid_since"] = False
                    
                    # Process database payment/invoice reconciliation if purely status check reveals it's paid
                    # This handles the case where webhook hits OR manual refresh hits
                    # We check if we need to reconcile
                    order._process_mollie_payment_success(payment_id, amount_value)
                else:
                    # set unpaid_since only once
                    if not order.mollie_last_payment_unpaid_since:
                        vals["mollie_last_payment_unpaid_since"] = now

                order.sudo().write(vals)

            except Exception as e:
                _logger.exception("⚠️ Mollie status exception for order %s", order.name)
                order.message_post(body=f"⚠️ Mollie status exception: {e}")

    def _process_mollie_payment_success(self, payment_id, amount_value):
        """Process successful Mollie payment: create payment and reconcile invoice."""
        self.ensure_one()
        _logger.info("Processing successful payment %s for order %s", payment_id, self.name)
        
        # Find unpaid posted invoices
        invoices = self.invoice_ids.filtered(lambda inv: inv.state == 'posted' and inv.payment_state not in ('paid', 'in_payment'))
        
        if not invoices:
            _logger.info("No unpaid invoices found for order %s to reconcile with payment %s", self.name, payment_id)
            return

        # Use the latest invoice if multiple exist (subscription logic usually creates one at a time)
        # Prioritize the one matching the amount if possible, or just the latest
        invoice = invoices.sorted('id', reverse=True)[:1]
        
        if not invoice:
            return

        # Check if already paid to avoid double payment
        # (Though we filtered for not paid/in_payment, double check if we just paid it in this transaction?)
        # Odoo's payment registration wizard handles this usually.
        
        # Get a journal. Try to find a Bank journal.
        journal = self.env['account.journal'].search([('type', '=', 'bank')], limit=1)
        if not journal:
            _logger.error("No bank journal found to register payment for order %s", self.name)
            return

        # Create payment
        payment_method_line = journal.inbound_payment_method_line_ids[:1]
        
        try:
            payment_vals = {
                'date': fields.Date.context_today(self),
                'amount': amount_value,
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'partner_id': self.partner_id.id,
                'journal_id': journal.id,
                'currency_id': self.currency_id.id,
                'payment_method_line_id': payment_method_line.id,
                'ref': f"Mollie Subscription Payment {payment_id}",
            }
            payment = self.env['account.payment'].create(payment_vals)
            payment.action_post()
            
            # Reconcile
            (invoice.line_ids + payment.line_ids).filtered(
                lambda line: line.account_id == invoice.line_ids.filtered(
                    lambda l: l.account_type == 'asset_receivable'
                ).account_id
            ).reconcile()
            
            _logger.info("Successfully registered payment %s for invoice %s", payment.name, invoice.name)
            
        except Exception as e:
            _logger.exception("Failed to register payment for order %s: %s", self.name, str(e))

    @api.model
    def cron_refresh_mollie_last_payment_status(self):
        """Cron: refresh status for all subscription orders having a last_payment_id."""
        orders = self.search(
            [
                ("last_payment_id", "!=", False),
                ("plan_id", "!=", False),
                ("state", "in", ["sale", "done"]),
            ]
        )
        if orders:
            orders.action_refresh_last_mollie_payment_status()
        return True
