from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)

class MollieSubscription(models.Model):
    _name = "mollie.subscription"
    _description = "Mollie Recurring Subscription"

    name = fields.Char(required=True)
    partner_id = fields.Many2one("res.partner", required=True, string="Customer")
    amount = fields.Float(string="Amount (€)", required=True)
    next_payment_date = fields.Date(string="Next Billing Date", required=True)
    last_payment_date = fields.Date(string="Last Payment Date")
    interval_months = fields.Integer(string="Interval (Months)", default=1)
    active = fields.Boolean(default=True)

    mollie_payment_id = fields.Char(string="Last Mollie Payment ID")
    mollie_payment_status = fields.Selection([
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("failed", "Failed"),
        ("canceled", "Canceled")
    ], string="Payment Status", default="pending")

    @api.model
    def cron_process_recurring_payments(self):
        """Automatically bill all active Mollie subscriptions."""
        today = fields.Date.today()
        subs = self.search([("next_payment_date", "<=", today), ("active", "=", True)])

        _logger.info(f"🔁 Found {len(subs)} subscriptions due for payment.")

        for sub in subs:
            partner = sub.partner_id

            if not partner.mollie_mandate_id or not partner.mollie_customer_id:
                _logger.warning(f"⚠️ Partner {partner.name} has no Mollie mandate. Skipping...")
                continue

            _logger.info(f"💳 Processing recurring payment for {partner.name}: €{sub.amount:.2f}")
            result = partner.mollie_create_recurring_payment(sub.amount, f"Subscription {sub.name}")

            if result:
                sub.mollie_payment_id = result["id"]
                sub.mollie_payment_status = result.get("status", "pending")
                sub.last_payment_date = today
                sub.next_payment_date = fields.Date.add(today, months=sub.interval_months)
                _logger.info(f"✅ Recurring payment created for {partner.name}")
            else:
                sub.mollie_payment_status = "failed"
                _logger.error(f"❌ Failed to process recurring payment for {partner.name}")
