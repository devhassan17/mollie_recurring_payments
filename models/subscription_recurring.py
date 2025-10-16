from odoo import models, fields, api
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)

class SubscriptionRecurring(models.Model):
    _inherit = 'sale.subscription'

    mollie_mandate_id = fields.Char("Mollie Mandate ID")
    mollie_retry_count = fields.Integer(default=0)
    mollie_max_retries = fields.Integer(default=3)
    mollie_last_retry_date = fields.Datetime()
    mollie_failure_reason = fields.Char()
    mollie_suspended = fields.Boolean(default=False)

    @api.model
    def cron_retry_failed_mollie_payments(self):
        mollie_provider = self.env['payment.provider'].sudo().search(
            [('code', '=', 'mollie')], limit=1
        )
        mollie_client = mollie_provider._mollie_get_client()

        subs = self.sudo().search([
            ('mollie_mandate_id', '!=', False),
            ('mollie_suspended', '=', False),
            ('recurring_next_date', '<=', fields.Date.today())
        ])

        for sub in subs:
            partner = sub.partner_id
            try:
                payment = mollie_client.payments.create({
                    "amount": {
                        "currency": sub.currency_id.name,
                        "value": f"{sub.recurring_total:.2f}",
                    },
                    "customerId": partner.mollie_customer_id,
                    "mandateId": sub.mollie_mandate_id,
                    "sequenceType": "recurring",
                    "description": f"Recurring payment for subscription {sub.code}",
                    "metadata": {"subscription_id": sub.id},
                })

                if payment.status == 'paid':
                    sub.mollie_retry_count = 0
                    sub.recurring_next_date = fields.Date.add(fields.Date.today(), months=1)
                    _logger.info("Recurring payment succeeded for %s", sub.code)
                else:
                    sub.mollie_retry_count += 1
                    sub.mollie_failure_reason = payment.status
                    _logger.warning("Payment failed for %s, attempt %s", sub.code, sub.mollie_retry_count)
                    self._send_failure_email(sub)

                    if sub.mollie_retry_count >= sub.mollie_max_retries:
                        sub.mollie_suspended = True
                        _logger.warning("Subscription %s suspended after max retries", sub.code)
                        self._notify_admin(sub)

            except Exception as e:
                sub.mollie_failure_reason = str(e)
                sub.mollie_retry_count += 1
                _logger.error("Mollie error for %s: %s", sub.code, e)
                self._send_failure_email(sub)

    def _send_failure_email(self, sub):
        template = self.env.ref('payment_mollie_recurring.mail_template_mollie_failed_payment')
        template.send_mail(sub.id, force_send=True)

    def _notify_admin(self, sub):
        template = self.env.ref('payment_mollie_recurring.mail_template_mollie_admin_notice')
        template.send_mail(sub.id, force_send=True)

    def action_mollie_retry_payment(self):
        self.cron_retry_failed_mollie_payments()
