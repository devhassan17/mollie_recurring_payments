from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class SaleOrderRecurring(models.Model):
    _inherit = 'sale.order'

    mollie_mandate_id = fields.Char("Mollie Mandate ID")
    mollie_retry_count = fields.Integer(default=0)
    mollie_max_retries = fields.Integer(default=3)
    mollie_last_retry_date = fields.Datetime()
    mollie_failure_reason = fields.Char()
    mollie_suspended = fields.Boolean(default=False)
    recurring_next_date = fields.Date("Next Recurring Payment Date")

    @api.model
    def cron_retry_failed_mollie_payments(self):
        """Automatically process recurring payments via Mollie."""
        mollie_provider = self.env['payment.provider'].sudo().search(
            [('code', '=', 'mollie')], limit=1
        )
        if not mollie_provider:
            _logger.error("❌ Mollie provider not found.")
            return

        mollie_client = mollie_provider._mollie_get_client()

        orders = self.sudo().search([
            ('mollie_mandate_id', '!=', False),
            ('mollie_suspended', '=', False),
            ('recurring_next_date', '<=', fields.Date.today())
        ])

        for order in orders:
            partner = order.partner_id
            try:
                _logger.info("🔁 Processing recurring payment for %s", order.name)

                payment = mollie_client.payments.create({
                    "amount": {
                        "currency": order.currency_id.name,
                        "value": f"{order.amount_total:.2f}",
                    },
                    "customerId": partner.mollie_customer_id,
                    "mandateId": order.mollie_mandate_id,
                    "sequenceType": "first",
                    "description": f"Recurring payment for order {order.name}",
                    "metadata": {"order_id": order.id},
                })

                if payment.status == 'paid':
                    order.write({
                        'mollie_retry_count': 0,
                        'mollie_failure_reason': False,
                        'recurring_next_date': fields.Date.add(fields.Date.today(), months=1)
                    })
                    _logger.info("✅ Recurring payment succeeded for %s", order.name)
                    self._send_success_email(order)
                else:
                    order.mollie_retry_count += 1
                    order.mollie_failure_reason = payment.status
                    self._send_failure_email(order)
                    _logger.warning("⚠️ Payment failed for %s: attempt %s", order.name, order.mollie_retry_count)

                    if order.mollie_retry_count >= order.mollie_max_retries:
                        order.mollie_suspended = True
                        _logger.warning("⛔ Order %s suspended after max retries", order.name)
                        self._notify_admin(order)

            except Exception as e:
                order.mollie_failure_reason = str(e)
                order.mollie_retry_count += 1
                _logger.error("💥 Mollie error for %s: %s", order.name, e)
                self._send_failure_email(order)

    def _send_failure_email(self, order):
        template = self.env.ref('mollie_recurring_payments.mail_template_mollie_failed_payment', raise_if_not_found=False)
        if template:
            template.send_mail(order.id, force_send=True)

    def _send_success_email(self, order):
        template = self.env.ref('mollie_recurring_payments.mail_template_mollie_success_payment', raise_if_not_found=False)
        if template:
            template.send_mail(order.id, force_send=True)

    def _notify_admin(self, order):
        template = self.env.ref('mollie_recurring_payments.mail_template_mollie_admin_notice', raise_if_not_found=False)
        if template:
            template.send_mail(order.id, force_send=True)

    def action_mollie_retry_payment(self):
        """Manual retry from backend."""
        self.cron_retry_failed_mollie_payments()
