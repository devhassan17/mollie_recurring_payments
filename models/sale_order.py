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

    mollie_last_charged_date = fields.Date(
        string="Last Charged Renewal Date",
        readonly=True,
        index=True,
        help="The specific renewal date (next_invoice_date) that was last successfully submitted to Mollie."
    )


    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _is_subscription_order(self):
        """Check if this sale order includes subscription products."""
        return any(line.product_id.recurring_invoice for line in self.order_line)

    def _get_blocked_subscription_keywords(self):
        return ["churn", "closed", "cancel", "pause", "hold", "stop", "renew", "renewed", "draft"]

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

        # 🛑 End Date Protection: Stop if the subscription has already reached its end date
        today = fields.Date.today()
        for field_name in ["end_date", "date_end"]:
            if field_name in self._fields and self[field_name] and self[field_name] <= today:
                _logger.info("⏭️ Subscription %s is blocked because its end date (%s) has passed or is today.", self.name, self[field_name])
                return True

        return False

    def _get_mollie_recurring_company_id(self):
        """Return the company ID configured for Mollie Recurring, or None if not set."""
        param = self.env['ir.config_parameter'].sudo().get_param(
            'mollie_recurring_payments.mollie_recurring_company_id'
        )
        try:
            return int(param) if param else None
        except (ValueError, TypeError):
            return None

    def _mollie_subscription_base_domain(self, today=None):
        today = today or fields.Date.today()
        domain = [
            ("plan_id", "!=", False),
            ("next_invoice_date", "=", today),
            ("state", "in", ["sale", "done"]),
            ("partner_id.mollie_mandate_id", "!=", False),
            ("partner_id.mollie_mandate_status", "=", "valid"),
        ]

        mollie_company_id = self._get_mollie_recurring_company_id()
        if mollie_company_id:
            domain = [("company_id", "=", mollie_company_id)] + domain

        exclude_states = [
            "churn", "churned", "closed", "cancelled", "canceled", "done", "paused", "pause",
            "renewed", "2_renewal", "4_renewed", "renewal", "draft", "1_draft"
        ]

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

        # 🛑 Domain level end-date check: Ensure we don't pick up subscriptions past or on their end date
        for field_name in ["end_date", "date_end"]:
            if field_name in self._fields:
                domain += ["|", (field_name, "=", False), (field_name, ">", today)]

        return domain

    def _mollie_subscription_status_refresh_domain(self):
        domain = [
            ("last_payment_id", "!=", False),
            ("plan_id", "!=", False),
            ("state", "in", ["sale", "done"]),
            # Only poll subscriptions whose last payment is not yet in a terminal state.
            # We also poll 'paid' orders if the amount is 0.0, to fix missing data from failed syncs.
            "|",
                ("mollie_last_payment_status", "not in", ["paid", "failed", "canceled", "expired"]),
                "&",
                    ("mollie_last_payment_status", "=", "paid"),
                    ("mollie_last_payment_amount", "=", 0.0),
        ]

        mollie_company_id = self._get_mollie_recurring_company_id()
        if mollie_company_id:
            domain = [("company_id", "=", mollie_company_id)] + domain

        exclude_states = [
            "churn", "churned", "closed", "cancelled", "canceled", "done", "paused", "pause",
            "renewed", "2_renewal", "4_renewed", "renewal", "draft", "1_draft"
        ]

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

    def _mollie_api_request(self, method, url, headers=None, json=None, timeout=15, max_retries=3, idempotency_key=None):
        """
        Wrapper for Mollie API calls with 429 retry handling and Idempotency support.
        """
        headers = headers or {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

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
                    method, url, attempt + 1, max_retries + 1, wait_seconds,
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
                    method, url, wait_seconds,
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
                continue

            mollie_provider = self.env["payment.provider"].search([("code", "=", "mollie"), ("company_id", "=", order.company_id.id)], limit=1)
            if not mollie_provider or not mollie_provider.mollie_api_key:
                continue

            # Fetch mandate in background/delay if needed, but here we do it directly
            order.partner_id.action_fetch_mollie_mandate()
        return res

    # -------------------------------------------------------------------------
    # Subscription cron: charge first, then create invoice (standard Odoo override)
    # -------------------------------------------------------------------------
    @api.model
    def _cron_recurring_create_invoice(self):
        """
        Overridden to inject Mollie recurring payment processing.
        Standard Odoo Subscriptions logic is called AFTER successful Mollie charge.
        """
        today = fields.Date.today()
        orders = self.search(self._mollie_subscription_base_domain(today=today))

        if not orders:
            _logger.info("✅ No Mollie subscription payments due for %s", today)
            return super()._cron_recurring_create_invoice()

        _logger.info("💳 Processing %d Mollie subscription(s) due for payment", len(orders))

        charged_orders = self.env["sale.order"]
        for order in orders:
            if order._is_subscription_charge_blocked():
                _logger.info("⏭️ Skipped Mollie charge for %s because subscription is blocked.", order.name)
                continue

            # 🛑 STRICT DUPLICATION CHECK: skip if already charged for this specific next_invoice_date (today)
            if order.mollie_last_charged_date == today:
                # If we already charged today and it's not a failure, be cautious
                if order.mollie_last_payment_status not in ('failed', 'canceled', 'expired'):
                    _logger.warning("⏭️ Order %s potentially already processed today (%s). Skipping to prevent duplication.", order.name, order.last_payment_id)
                    continue

            mollie_provider = self.env["payment.provider"].search([("code", "=", "mollie"), ("company_id", "=", order.company_id.id)], limit=1)
            if not mollie_provider or not mollie_provider.mollie_api_key:
                _logger.error("❌ Mollie API key missing for company %s", order.company_id.name)
                continue

            headers = {
                "Authorization": f"Bearer {mollie_provider.mollie_api_key}",
                "Content-Type": "application/json",
            }
            
            amount = round(order.amount_total, 2)
            # ✅ IDEMPOTENCY KEY: Unique for this Order + this Specific Renewal Date
            idempotency_key = f"mollie-charge-{order.id}-{today.isoformat()}"

            payload = {
                "amount": {"currency": order.currency_id.name or "EUR", "value": f"{amount:.2f}"},
                "customerId": order.partner_id.mollie_customer_id,
                "mandateId": order.partner_id.mollie_mandate_id,
                "description": f"Subscription renewal for {order.name}",
                "sequenceType": "recurring",
                "metadata": {"order_id": order.id, "renewal_date": today.isoformat()},
            }

            try:
                response = order._mollie_api_request(
                    method="POST",
                    url="https://api.mollie.com/v2/payments",
                    json=payload,
                    headers=headers,
                    idempotency_key=idempotency_key
                )
                data = response.json() if response is not None and response.content else {}

                if response is None or response.status_code not in (200, 201):
                    # 409 Conflict might happen if idempotency key is reused but payload differs (unlikely here)
                    order.message_post(body=f"❌ Mollie payment failed: {data.get('detail', data)}")
                    _logger.error("❌ Mollie payment failed for %s: %s", order.name, data)
                    continue

                payment_id = data.get("id")
                status = data.get("status")

                order.sudo().write({
                    "last_payment_id": payment_id,
                    "mollie_last_payment_status": status,
                    "mollie_last_payment_amount": amount,
                    "mollie_last_payment_checked_at": fields.Datetime.now(),
                    "mollie_last_charged_date": today,
                    "mollie_last_payment_paid": True if status in ("paid", "authorized", "pending") else False,
                })
                
                order.message_post(body=f"✅ Mollie Subscription Payment Initiated. ID: {payment_id} | Status: {status}")
                charged_orders |= order

            except Exception as e:
                _logger.exception("⚠️ Mollie exception for %s", order.name)
                order.message_post(body=f"⚠️ Mollie API exception: {str(e)}")

        if charged_orders:
            _logger.info("🧾 Deferring to standard Odoo to generate invoices alongside B2B subscriptions...")

        # Let standard Odoo run the exact way it usually does (unbound to any specific recordset).
        # It will natively search for ALL due subscriptions today (both B2B and our charged Mollie ones)
        # and create invoices for them without our module breaking the loop.
        try:
             res = super()._cron_recurring_create_invoice()
        except Exception:
             _logger.exception("⚠️ Standard subscription invoice creation failed")
             res = False

        if charged_orders:
            # Final reconciliation loop for those just charged.
            # Each order gets its own savepoint so that a serialization failure (e.g. a
            # concurrent "Refresh Payment Status" cron touching the same account_move rows)
            # only rolls back *that one order* and does not poison the entire transaction,
            # allowing subsequent orders to be reconciled successfully.
            _logger.info("💰 Reconciling the newly generated invoices for Mollie orders...")
            for order in charged_orders:
                try:
                    with self.env.cr.savepoint():
                        order._reconcile_with_mollie_payment()
                except Exception:
                    _logger.exception(
                        "⚠️ Failed to reconcile Mollie payment for order %s — "
                        "savepoint rolled back; other orders are unaffected.",
                        order.name,
                    )

        return res

    def _subscription_post_success_free_renewal(self):
        """
        Patch for Odoo Enterprise bug:
        `_subscription_post_success_free_renewal` is internally called on a
        multi-record set (e.g. two free subscriptions due on the same day)
        but the method calls ensure_one(), causing:
            ValueError: Expected singleton: sale.order(163087, 163092)

        We iterate per-record so enterprise always receives exactly one record.
        """
        for order in self:
            try:
                super(SaleOrder, order)._subscription_post_success_free_renewal()
            except Exception:
                _logger.exception(
                    "⚠️ _subscription_post_success_free_renewal failed for order %s", order.name
                )

    def _reconcile_with_mollie_payment(self):
        """Helper to find the latest unpaid invoice and reconcile it with the Mollie payment."""
        self.ensure_one()
        if not self.last_payment_id or not self.mollie_last_payment_paid:
            return

        self.env.flush_all()
        self.invalidate_recordset(['invoice_ids'])
        
        invoice = self.invoice_ids.filtered(
            lambda inv: inv.state == 'posted' and inv.payment_state not in ('in_payment', 'paid', 'reversed')
        ).sorted("id", reverse=True)[:1]

        if invoice:
            _logger.info("💰 Reconciling invoice %s for order %s with Mollie payment %s", invoice.name, self.name, self.last_payment_id)
            self._process_mollie_payment_success(self.last_payment_id, invoice.amount_total)

    # -------------------------------------------------------------------------
    # Manual + webhook + cron refresh payment status
    # -------------------------------------------------------------------------
    def action_refresh_last_mollie_payment_status(self):
        for order in self:
            mollie_provider = self.env["payment.provider"].search([
                ("code", "=", "mollie"),
                ("company_id", "=", order.company_id.id)
            ], limit=1)
            api_key = getattr(mollie_provider, "mollie_api_key", False)
            if not api_key:
                _logger.warning("❌ Mollie API key missing for order %s (Company: %s)", order.name, order.company_id.name)
                continue

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            payment_id = order.last_payment_id
            if not payment_id:
                continue

            old_status = order.mollie_last_payment_status
            try:
                resp = order._mollie_api_request(
                    method="GET",
                    url=f"https://api.mollie.com/v2/payments/{payment_id}",
                    headers=headers,
                    timeout=15,
                    max_retries=3,
                )
                if resp is None or resp.status_code != 200:
                    text = resp.text if resp is not None else "No response"
                    status_code = resp.status_code if resp is not None else "N/A"
                    _logger.warning("⚠️ Mollie status fetch failed for %s (Status %s): %s", payment_id, status_code, text)
                    continue

                data = resp.json() if resp.content else {}
                status = data.get("status")
                
                # SEPA Direct Debits (esp. in test mode) are often 'pending' for several days.
                # We consider them successful in Odoo if they are paid, authorized, or pending
                paid = True if status in ("paid", "authorized", "pending") else False
                now = fields.Datetime.now()

                amount_data = data.get("amount") or {}
                try:
                    amount_value = float(amount_data.get("value") or 0.0)
                except (ValueError, TypeError):
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

                    if old_status == 'pending' and status in ('paid', 'authorized'):
                        # Post manual message since it didn't ping during 'pending' registration
                        invoice = order.invoice_ids.filtered(lambda i: i.state == 'posted').sorted('id', reverse=True)[:1]
                        inv_name = invoice.name if invoice else "Invoice"
                        order.message_post(body=f"✅ Mollie payment {payment_id} has cleared. {inv_name} is now fully paid.")
                else:
                    if not order.mollie_last_payment_unpaid_since:
                        vals["mollie_last_payment_unpaid_since"] = now
                    # If status is terminal failure, reverse any Odoo payment already created
                    if status in ("failed", "canceled", "expired") and order.mollie_last_payment_status != status:
                        order._process_mollie_payment_failure(payment_id, status)

                order.sudo().write(vals)

            except Exception as e:
                _logger.exception("⚠️ Mollie status exception for order %s: %s", order.name, e)

    def _process_mollie_payment_failure(self, payment_id, status):
        """
        Reverse an Odoo payment that was created for a Mollie payment which subsequently
        failed/cancelled/expired. This un-reconciles the invoice and resets it to Not Paid.
        """
        self.ensure_one()
        _logger.info("⚠️ Mollie payment %s is '%s' — checking if reversal is needed for order %s", payment_id, status, self.name)

        existing_payment = self.env["account.payment"].sudo().search([
            ("mollie_payment_id", "=", payment_id),
        ], limit=1)

        if not existing_payment:
            _logger.info("ℹ️ No Odoo payment found for Mollie payment %s — nothing to reverse", payment_id)
            return

        if existing_payment.state == 'cancel':
            _logger.info("ℹ️ Payment %s is already cancelled — skipping reversal", existing_payment.name)
            return

        try:
            # action_cancel() on account.payment reverses the journal entry and un-reconciles
            existing_payment.sudo().action_cancel()
            _logger.info("🔄 Payment %s cancelled/reversed for Mollie payment %s (status=%s)",
                         existing_payment.name, payment_id, status)
            self.message_post(
                body=f"🔴 Mollie payment {payment_id} was {status}.\n"
                     f"Odoo payment {existing_payment.name} has been reversed.\n"
                     f"Invoice is back to Not Paid — please retry or contact customer."
            )
        except Exception:
            _logger.exception("❌ Failed to reverse Odoo payment %s for Mollie payment %s",
                              existing_payment.name, payment_id)

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

        # Duplicate check: use move_id.state (Odoo 17+/18 — account.payment.state != 'posted')
        existing_payment = self.env["account.payment"].sudo().search([
            ("mollie_payment_id", "=", payment_id),
        ], limit=1)
        if existing_payment and existing_payment.move_id and existing_payment.move_id.state in ("posted",):
            _logger.info("⏭️ Mollie payment %s already posted in Odoo (%s).", payment_id, existing_payment.name)
            return True
        elif existing_payment:
            _logger.info("🔁 Found existing payment %s but state=%s — will attempt reconciliation again.", existing_payment.name, existing_payment.move_id.state if existing_payment.move_id else 'no move')

        # Force a fresh database read of invoice_ids to avoid stale cache
        self.env.flush_all()
        self.invalidate_recordset(['invoice_ids'])
        all_invoices = self.invoice_ids
        _logger.info("🔍 All invoice_ids for order %s: %s", self.name, all_invoices.mapped(lambda i: f'{i.name}(state={i.state},pay_state={i.payment_state})'))
        invoices = all_invoices.filtered(lambda inv: inv.state in ("draft", "posted") and inv.payment_state not in ("in_payment", "paid", "reversed"))
        _logger.info("🔍 Invoices eligible for reconciliation on order %s: %s", self.name, invoices.mapped('name'))
        if not invoices:
            _logger.warning("⚠️ No eligible invoices for order %s — all are already paid or there are no invoices.", self.name)
            return True

        invoice = invoices.sorted("id", reverse=True)[:1]
        if not invoice:
            return True
        invoice = invoice[0]

        if invoice.state == "draft":
            invoice.action_post()

        if invoice.payment_state in ("in_payment", "paid"):
            return True

        invoice_company = invoice.company_id or self.company_id
        journal = self.env["account.journal"].with_company(invoice_company).search([
            ("type", "=", "bank"),
            ("company_id", "=", invoice_company.id),
        ], limit=1)
        if not journal:
            _logger.error("❌ No bank journal found for company %s (order %s)", invoice_company.name, self.name)
            return False

        payment_method_line = journal.inbound_payment_method_line_ids[:1]
        if not payment_method_line:
            _logger.error("❌ No inbound payment method line on journal %s", journal.display_name)
            return False

        pay_amount = invoice.amount_residual or amount_value

        try:
            # Use Odoo's native payment register wizard — handles all journal configurations
            # (including Outstanding Receipts transit accounts) and auto-reconciles with invoice.
            payment_register = self.env['account.payment.register'].with_company(invoice_company).with_context(
                active_model='account.move',
                active_ids=invoice.ids,
            ).sudo().create({
                'payment_date': fields.Date.context_today(self),
                'amount': pay_amount,
                'journal_id': journal.id,
                'payment_method_line_id': payment_method_line.id,
            })
            
            existing_msg_ids = self.message_ids.ids
            payments = payment_register._create_payments()

            if self.mollie_last_payment_status == 'pending':
                new_msgs = self.message_ids.filtered(lambda m: m.id not in existing_msg_ids)
                for msg in new_msgs:
                    if msg.body and 'paid' in str(msg.body).lower() and 'invoice' in str(msg.body).lower():
                        msg.sudo().unlink()

            # Tag the created payment(s) with the Mollie payment ID for future deduplication
            if payments:
                payments.sudo().write({'mollie_payment_id': payment_id})
                _logger.info("🏷️ Tagged payment(s) %s with mollie_payment_id=%s", payments.mapped('name'), payment_id)

            invoice.invalidate_recordset(['payment_state', 'amount_residual'])
            _logger.info(
                "✅ Mollie payment reconciled | Invoice %s payment_state=%s amount_residual=%s",
                invoice.name, invoice.payment_state, invoice.amount_residual,
            )
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