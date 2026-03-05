# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import requests
import logging

_logger = logging.getLogger(__name__)


class MollieRecurringController(http.Controller):

    @http.route('/mollie/mandate/webhook', type='json', auth="public", csrf=False)
    def handle_webhook(self):
        """Handle Mollie webhook for mandate creation"""
        _logger.info("MANDATE RECURRING WEBHOOK CALLED")

        data = request.jsonrequest or {}
        payment_id = data.get("id")
        if not payment_id:
            # Mollie expects quick 200 responses; we return ok-style response
            return {"status": "error", "message": "no id"}

        mollie_provider = request.env['payment.provider'].sudo().search([('code', '=', 'mollie')], limit=1)
        api_key = mollie_provider.mollie_api_key if mollie_provider else False
        if not api_key:
            _logger.error("Webhook Mollie API key missing!")
            return {"status": "error", "message": "api key missing"}

        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            resp = requests.get(
                f"https://api.mollie.com/v2/payments/{payment_id}",
                headers=headers,
                timeout=15
            )
        except Exception as e:
            _logger.exception("Webhook payment fetch exception: %s", e)
            return {"status": "error", "message": "fetch exception"}

        if resp.status_code != 200:
            _logger.error("Webhook payment fetch failed: %s", resp.text)
            return {"status": "error", "message": "fetch failed"}

        payment_data = resp.json() if resp.content else {}
        cust = payment_data.get("customerId")
        mand = payment_data.get("_links", {}).get("mandate", {}).get("href", "").split("/")[-1]
        status = payment_data.get("status")

        _logger.info("Mandate webhook payment_data=%s", payment_data)

        if cust:
            partner = request.env['res.partner'].sudo().search([('mollie_customer_id', '=', cust)], limit=1)
            if partner:
                partner.sudo().write({
                    'mollie_mandate_id': mand,
                    'mollie_transaction_id': payment_id,
                    # If paid/authorized then mandate is valid
                    "mollie_mandate_status": "valid" if status in ("paid", "authorized") else status
                })
                _logger.info("Webhook updated partner %s with mandate %s", partner.name, mand)

        return {"status": "ok"}

    @http.route('/mollie/mandate/return', type='http', auth="public", website=True)
    def handle_return(self, **kwargs):
        _logger.info("Mollie return URL hit with params: %s", kwargs)
        return request.redirect('/shop/confirmation')

    @http.route('/mollie/subscription/webhook', type='http', auth="public", csrf=False, methods=['POST'])
    def handle_subscription_webhook(self, **kwargs):
        """
        Handle Mollie webhook for subscription payments.
        Mollie usually posts form-encoded body with: id=<payment_id>
        """
        _logger.info("SUBSCRIPTION WEBHOOK CALLED kwargs=%s", kwargs)

        payment_id = kwargs.get("id") or kwargs.get("payment_id")
        if not payment_id:
            _logger.warning("Subscription webhook called but no payment id found.")
            return "ok"

        mollie_provider = request.env['payment.provider'].sudo().search([('code', '=', 'mollie')], limit=1)
        api_key = mollie_provider.mollie_api_key if mollie_provider else False
        if not api_key:
            _logger.error("Subscription webhook: Mollie API key missing!")
            return "ok"

        # Always verify current status from Mollie (do not trust webhook payload)
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            resp = requests.get(
                f"https://api.mollie.com/v2/payments/{payment_id}",
                headers=headers,
                timeout=15
            )
        except Exception as e:
            _logger.exception("Subscription webhook Mollie fetch exception: %s", e)
            return "ok"

        if resp.status_code != 200:
            _logger.error("Subscription webhook Mollie fetch failed: %s", resp.text)
            return "ok"

        payment_data = resp.json() if resp.content else {}
        status = payment_data.get("status")
        metadata = payment_data.get("metadata") or {}
        meta_order_id = metadata.get("order_id")

        _logger.info("Subscription webhook payment_id=%s status=%s metadata=%s", payment_id, status, metadata)

        # 1) Primary match: your existing approach (last_payment_id)
        order = request.env['sale.order'].sudo().search([('last_payment_id', '=', payment_id)], limit=1)

        # 2) Fallback match: Mollie metadata order_id (VERY helpful)
        if not order and meta_order_id:
            try:
                order = request.env['sale.order'].sudo().browse(int(meta_order_id))
                if not order.exists():
                    order = False
            except Exception:
                order = False

        if not order:
            _logger.warning("No order found for Mollie payment ID %s", payment_id)
            return "ok"

        # Refresh status + apply accounting if paid (your method handles this)
        _logger.info("Processing subscription webhook for order %s and payment %s", order.name, payment_id)

        # If the order.last_payment_id is not set (rare case), set it so refresh works
        if not order.last_payment_id:
            order.sudo().write({"last_payment_id": payment_id})

        # This method:
        # - fetches latest payment status from Mollie
        # - writes mollie_last_payment_status / paid flags
        # - if paid => calls _process_mollie_payment_success()
        order.action_refresh_last_mollie_payment_status()

        return "ok"