from odoo import models, fields, api
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)

class SaleOrderRecurring(models.Model):
    _inherit = 'sale.order'

    is_subscription = fields.Boolean(string="Recurring Order", default=False)
    recurring_interval = fields.Selection([
        ('week', 'Weekly'),
        ('month', 'Monthly'),
        ('year', 'Yearly'),
    ], string="Recurring Every", default='month')

    mollie_mandate_id = fields.Char("Mollie Mandate ID")
    mollie_retry_count = fields.Integer(default=0)
    mollie_max_retries = fields.Integer(default=3)
    mollie_last_retry_date = fields.Datetime()
    mollie_failure_reason = fields.Char()
    mollie_suspended = fields.Boolean(default=False)
    recurring_next_date = fields.Date(string="Next Billing Date")

    # ---- Cron Job Entry Point ----
    @api.model
    def cron_retry_failed_mollie_payments(self):
        """Auto-charge Mollie recurring payments for all active recurring orders."""
        mollie_provider = self.env['payment.provider'].sudo().search(
            [('code', '=', 'mollie')], limit=1
        )
        if not mollie_provider:
            _logger.error("No Mollie provider found. Skipping cron.")
            return

        mollie_client = mollie_provider._mollie_get_client()

        # Select eligible orders for renewal
        orders = self.sudo().search([
            ('is_subscription', '=', True),
            ('mollie_mandate_id', '!=', False),
            ('mollie_suspended', '=', False),
            ('recurring_next_date', '<=', fields.Date.today())
        ])

        for order in orders:
            partner = order.partner_id
            try:
                payment = mollie_client.payments.create({
                    "amount": {
                        "currency": order.currency_id.name,
                        "value": f"{order.amount_total:.2f}",
                    },
                    "customerId": getattr(partner, 'mollie_customer_id', None),
                    "mandateId": order.mollie_mandate_id,
                    "sequenceType": "recurring",
                    "description": f"Recurring payment for order {order.name}",
                    "metadata": {"order_id": order.id},
                })

                if payment.status == 'paid':
                    order.mollie_retry_count = 0
                    order.mollie_failure_reason = False
                    order.mollie_last_retry_date = fields.Datetime.now()
                    order.recurring_next_date = self._get_next_billing_date(order)
                    _logger.info("Recurring payment succeeded for %s", order.name)

                    # Create renewal order automatically
                    self._create_renewal_order(order)

                else:
                    self._handle_failed_payment(order, payment.status)

            except Exception as e:
                _logger.error("Mollie recurring payment error for %s: %s", order.name, e)
                self._handle_failed_payment(order, str(e))

    # ---- Helpers ----
    def _get_next_billing_date(self, order):
        if order.recurring_interval == 'week':
            return fields.Date.add(fields.Date.today(), days=7)
        elif order.recurring_interval == 'year':
            return fields.Date.add(fields.Date.today(), years=1)
        return fields.Date.add(fields.Date.today(), months=1)

    def _handle_failed_payment(self, order, reason):
        order.mollie_failure_reason = reason
        order.mollie_retry_count += 1
        order.mollie_last_retry_date = fields.Datetime.now()
        _logger.warning("Payment failed for %s: attempt %s (%s)",
                        order.name, order.mollie_retry_count, reason)

        self._send_failure_email(order)

        if order.mollie_retry_count >= order.mollie_max_retries:
            order.mollie_suspended = True
            _logger.warning("Order %s suspended after max retries", order.name)
            self._notify_admin(order)

    def _create_renewal_order(self, order):
        """Duplicate the previous order for next billing cycle."""
        new_order = order.copy({
            'state': 'draft',
            'invoice_status': 'to invoice',
            'recurring_next_date': self._get_next_billing_date(order),
        })
        _logger.info("Created renewal order %s for %s", new_order.name, order.name)

    def _send_failure_email(self, order):
        template = self.env.ref('payment_mollie_recurring.mail_template_mollie_failed_payment', raise_if_not_found=False)
        if template:
            template.send_mail(order.id, force_send=True)

    def _notify_admin(self, order):
        template = self.env.ref('payment_mollie_recurring.mail_template_mollie_admin_notice', raise_if_not_found=False)
        if template:
            template.send_mail(order.id, force_send=True)

    def action_mollie_retry_payment(self):
        """Manual retry for admin use."""
        self.cron_retry_failed_mollie_payments()
