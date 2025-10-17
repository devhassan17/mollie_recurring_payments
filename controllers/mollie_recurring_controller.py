from odoo import http, fields
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class MollieRecurringController(http.Controller):

    @http.route('/mollie/webhook', type='http', auth='public', csrf=False)
    def mollie_webhook(self, **post):
        _logger.info("🔔 Mollie webhook triggered: %s", post)

        mollie_provider = request.env['payment.provider'].sudo().search(
            [('code', '=', 'mollie')], limit=1
        )
        if not mollie_provider:
            _logger.error("❌ No Mollie provider found for webhook.")
            return "provider not found"

        mollie_client = mollie_provider._mollie_get_client()

        payment_id = post.get('id')
        if not payment_id:
            _logger.warning("⚠️ Missing payment ID in webhook payload.")
            return "missing payment id"

        try:
            payment = mollie_client.payments.get(payment_id)
        except Exception as e:
            _logger.error("❌ Error fetching Mollie payment %s: %s", payment_id, e)
            return "error"

        metadata = getattr(payment, "metadata", {}) or {}
        order_id = metadata.get("order_id")
        partner_id = metadata.get("partner_id")

        if not order_id:
            _logger.warning("⚠️ No order_id found in Mollie payment metadata: %s", metadata)
            return "missing order id"

        order = request.env['sale.order'].sudo().browse(int(order_id))
        partner = request.env['res.partner'].sudo().browse(int(partner_id)) if partner_id else order.partner_id

        if not order.exists():
            _logger.error("❌ Sale order %s not found in DB.", order_id)
            return "order not found"

        _logger.info("💳 Mollie webhook received for order %s (status=%s)", order.name, payment.status)

        # ✅ Handle successful payment
        if payment.status == 'paid':
            _logger.info("✅ Payment successful for order %s", order.name)

            # ✅ Fetch valid mandate for this customer
            try:
                mandates = mollie_client.customer_mandates.list(customer_id=partner.mollie_customer_id)
                valid_mandates = [m for m in mandates if getattr(m, "status", "") == "valid"]

                if valid_mandates:
                    mandate_id = valid_mandates[0].id
                    partner.sudo().write({'mollie_mandate_id': mandate_id})
                    order.sudo().write({'mollie_mandate_id': mandate_id})
                    _logger.info("💾 Stored Mollie mandate %s for partner %s and order %s", mandate_id, partner.name, order.name)
                else:
                    _logger.warning("⚠️ No valid Mollie mandates found for customer %s", partner.mollie_customer_id)

            except Exception as e:
                _logger.error("❌ Failed to fetch Mollie mandates for %s: %s", partner.name, e)

            # ✅ Create subscription for recurring products
            try:
                if any(line.product_id.recurring_invoice for line in order.order_line):
                    subscription = order._create_subscriptions()
                    subscription.write({
                        'mollie_mandate_id': order.mollie_mandate_id,
                        'recurring_next_date': fields.Date.add(fields.Date.today(), months=1)
                    })
                    _logger.info("🧾 Subscription %s created with Mollie mandate %s", subscription.code, subscription.mollie_mandate_id)
            except Exception as e:
                _logger.error("⚠️ Failed to create subscription for %s: %s", order.name, e)

            # Confirm the order
            try:
                order.action_confirm()
                _logger.info("📦 Order %s confirmed successfully", order.name)
            except Exception as e:
                _logger.error("⚠️ Failed to confirm order %s: %s", order.name, e)

        elif payment.status in ['failed', 'canceled']:
            _logger.warning("❌ Mollie payment %s for order %s", payment.status, order.name)
            order.sudo().write({'mollie_failure_reason': payment.status})

        return "ok"
