# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request
from mollie.api.client import Client
import logging

_logger = logging.getLogger(__name__)

class MollieRecurringController(http.Controller):

    @http.route('/mollie/webhook', type='http', auth='public', csrf=False)
    def mollie_webhook(self, **post):
        api_key = request.env['ir.config_parameter'].sudo().get_param('mollie.api_key')
        if not api_key:
            _logger.error("❌ Mollie API key not configured.")
            return "API key missing"

        mollie_client = Client()
        mollie_client.set_api_key(api_key)

        payment_id = post.get('id')
        if not payment_id:
            return "missing payment id"

        try:
            payment = mollie_client.payments.get(payment_id)
        except Exception as e:
            _logger.error("Error fetching Mollie payment %s: %s", payment_id, e)
            return "error"

        metadata = payment.metadata or {}
        order_id = metadata.get("order_id")
        if not order_id:
            _logger.warning("No order_id found in Mollie payment metadata.")
            return "missing order id"

        order = request.env['sale.order'].sudo().browse(int(order_id))
        partner = order.partner_id

        if payment.status == 'paid':
            _logger.info("✅ Mollie webhook: Payment successful for order %s", order.name)

            try:
                mandates = mollie_client.customer_mandates.list(partner.mollie_customer_id)
                valid_mandates = [m for m in mandates if m['status'] == 'valid']
                if valid_mandates:
                    partner.mollie_mandate_id = valid_mandates[0]['id']
                    order.mollie_mandate_id = valid_mandates[0]['id']
                    _logger.info("Stored Mollie mandate %s for %s", valid_mandates[0]['id'], partner.name)
                else:
                    _logger.warning("No valid mandates found for customer %s", partner.mollie_customer_id)
            except Exception as e:
                _logger.error("Failed to fetch mandates for %s: %s", partner.name, e)

            order.action_confirm()

            # create subscription if product is recurring
            if any(line.product_id.recurring_invoice for line in order.order_line):
                subscription = order._create_subscriptions()
                subscription.mollie_mandate_id = order.mollie_mandate_id
                subscription.recurring_next_date = fields.Date.add(fields.Date.today(), months=1)
                _logger.info("Subscription %s created with Mollie mandate %s", subscription.code, subscription.mollie_mandate_id)

        elif payment.status in ['failed', 'canceled']:
            order.mollie_failure_reason = payment.status
            _logger.warning("⚠️ Mollie webhook: Payment %s for order %s", payment.status, order.name)

        return "ok"
