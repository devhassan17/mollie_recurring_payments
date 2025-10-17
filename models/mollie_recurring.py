# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging
from datetime import timedelta
from mollie.api.client import Client

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"

    mollie_customer_id = fields.Char("Mollie Customer ID")
    mollie_mandate_id = fields.Char("Mollie Mandate ID")


class SaleOrderRecurring(models.Model):
    _inherit = 'sale.order'

    mollie_mandate_id = fields.Char("Mollie Mandate ID")
    mollie_retry_count = fields.Integer(default=0)
    mollie_max_retries = fields.Integer(default=3)
    mollie_last_retry_date = fields.Datetime()
    mollie_failure_reason = fields.Char()
    mollie_suspended = fields.Boolean(default=False)
    recurring_next_date = fields.Date("Next Recurring Payment Date")

    # 🔑 Fetch Mollie client from config parameter
    def _get_mollie_client(self):
        api_key = self.env['ir.config_parameter'].sudo().get_param('mollie.api_key')
        if not api_key:
            _logger.error("❌ Mollie API key not set in System Parameters (key: mollie.api_key)")
            raise ValueError("Mollie API key not configured in Odoo System Parameters.")
        mollie_client = Client()
        mollie_client.set_api_key(api_key)
        return mollie_client

    # 🕒 CRON for Recurring Payments
    @api.model
    def cron_retry_failed_mollie_payments(self):
        mollie_client = self._get_mollie_client()

        orders = self.sudo().search([
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
                    "customerId": partner.mollie_customer_id,
                    "mandateId": order.mollie_mandate_id,
                    "sequenceType": "recurring",
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
                    order.write({
                        'mollie_retry_count': order.mollie_retry_count + 1,
                        'mollie_failure_reason': payment.status
                    })
                    _logger.warning("⚠️ Payment failed for %s, attempt %s", order.name, order.mollie_retry_count)
                    self._send_failure_email(order)

                    if order.mollie_retry_count >= order.mollie_max_retries:
                        order.mollie_suspended = True
                        _logger.warning("⛔ Order %s suspended after max retries", order.name)
                        self._notify_admin(order)

            except Exception as e:
                order.write({
                    'mollie_failure_reason': str(e),
                    'mollie_retry_count': order.mollie_retry_count + 1
                })
                _logger.error("💥 Mollie error for %s: %s", order.name, e)
                self._send_failure_email(order)

    # ✉️ Notification Helpers
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
        self.cron_retry_failed_mollie_payments()
