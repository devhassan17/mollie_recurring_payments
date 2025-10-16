from odoo import http, fields
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class MollieRecurringController(http.Controller):

    @http.route('/mollie/webhook', type='http', auth='public', csrf=False)
    def mollie_webhook(self, **post):
        mollie_provider = request.env['payment.provider'].sudo().search(
            [('code', '=', 'mollie')], limit=1
        )
        mollie_client = mollie_provider._mollie_get_client()

        payment_id = post.get('id')
        if not payment_id:
            return "missing payment id"

        payment = mollie_client.payments.get(payment_id)
        metadata = payment.metadata or {}
        order_id = metadata.get("order_id")
        partner_id = metadata.get("partner_id")

        order = request.env['sale.order'].sudo().browse(int(order_id))
        partner = request.env['res.partner'].sudo().browse(int(partner_id))

        if payment.status == 'paid':
            _logger.info("Mollie webhook: Payment successful for order %s", order.name)

            # Fetch valid mandate
            mandates = mollie_client.customers.with_parent_id(partner.mollie_customer_id).mandates.list()
            valid_mandates = [m for m in mandates if m.status == 'valid']
            if valid_mandates:
                partner.mollie_mandate_id = valid_mandates[0].id
                _logger.info("Stored Mollie mandate %s for %s", partner.mollie_mandate_id, partner.name)

            # Create subscription
            if any(line.product_id.recurring_invoice for line in order.order_line):
                subscription = order._create_subscriptions()
                subscription.mollie_mandate_id = partner.mollie_mandate_id
                subscription.recurring_next_date = fields.Date.add(fields.Date.today(), months=1)
                _logger.info("Subscription %s created with Mollie mandate %s", subscription.code, partner.mollie_mandate_id)

            order.action_confirm()

        elif payment.status in ['failed', 'canceled']:
            _logger.warning("Mollie webhook: Payment failed for order %s", order.name)

        return "ok"
