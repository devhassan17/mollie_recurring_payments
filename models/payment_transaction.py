import requests
import logging
from odoo import _, models

_logger = logging.getLogger(__name__)

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _mollie_prepare_payment_request_payload(self):
        """ Override to prepare Mollie payment request payload with subscription and voucher support. """
        payload = super()._mollie_prepare_payment_request_payload()
        
        # Odoo 17/18: self.sale_order_ids is the standard way to get linked orders
        order = self.sale_order_ids[:1]
        if not order:
            return payload

        partner = self.partner_id
        mollie_provider = self.provider_id
        if not mollie_provider or not mollie_provider.mollie_api_key:
            return payload

        headers = {
            "Authorization": f"Bearer {mollie_provider.mollie_api_key}",
            "Content-Type": "application/json"
        }

        # 1. Handle Subscription metadata if applicable
        # Check both product.product and product.template for recurring_invoice (Odoo 18 compat)
        is_subscription_order = any(
            line.product_id.recurring_invoice or
            (line.product_id.product_tmpl_id and line.product_id.product_tmpl_id.recurring_invoice)
            for line in order.order_line
            if not line.display_type
        )
        if is_subscription_order:
            customer_id = partner.mollie_customer_id
            if not customer_id:
                try:
                    customer_payload = {
                        "name": partner.name,
                        "email": partner.email,
                        "metadata": {"odoo_partner_id": partner.id},
                    }
                    resp = requests.post("https://api.mollie.com/v2/customers", json=customer_payload, headers=headers, timeout=10)
                    if resp.status_code == 201:
                        customer_id = resp.json().get("id")
                        partner.sudo().write({"mollie_customer_id": customer_id})
                        _logger.info("Created Mollie customer %s for partner %s", customer_id, partner.name)
                except Exception as e:
                    _logger.error("Mollie customer creation exception: %s", str(e))

            if customer_id:
                payload.update({
                    'sequenceType': 'first',
                    'customerId': customer_id,
                })
                # Ensure mandate is fetched (asynchronously/queued in a real production, but here we trigger sync)
                partner.action_fetch_mollie_mandate()

        # 2. Add Line Items for Voucher/Gift Card support if enabled
        if mollie_provider.mollie_use_vouchers:
            lines = []
            voucher_mapping = {v.category_id.id: v.mollie_voucher_type for v in mollie_provider.mollie_voucher_ids}
            
            for line in order.order_line:
                if line.display_type:
                    continue
                
                # Determine Mollie voucher category
                mollie_category = voucher_mapping.get(line.product_id.categ_id.id)
                
                # Mollie rule: totalAmount = unitPrice × quantity (ALL tax-excluded)
                # vatAmount MUST be derived from totalAmount using Mollie's formula:
                #   vatAmount = totalAmount × (vatRate / (100 + vatRate))
                # Using price_total - price_subtotal causes rounding drift because
                # Odoo's price_total is computed from original unitPrice, not our rounded totalAmount.
                unit_price = round(line.price_unit, 2)
                qty = int(line.product_uom_qty)
                total_excl = round(unit_price * qty, 2)  # tax-excluded total = unitPrice × qty
                vat_rate_sum = sum(t.amount for t in line.tax_id)
                # Mollie's exact formula to avoid vatAmount mismatch errors
                if vat_rate_sum:
                    vat_amount = round(total_excl * (vat_rate_sum / (100 + vat_rate_sum)), 2)
                else:
                    vat_amount = 0.0


                line_data = {
                    'description': line.name,
                    'quantity': qty,
                    'unitPrice': {
                        'currency': order.currency_id.name,
                        'value': f"{unit_price:.2f}"
                    },
                    'totalAmount': {
                        'currency': order.currency_id.name,
                        'value': f"{total_excl:.2f}"  # ✅ unitPrice × qty, NOT price_total
                    },
                    'vatAmount': {
                        'currency': order.currency_id.name,
                        'value': f"{vat_amount:.2f}"
                    },
                    # Mollie requires vatRate as a string (e.g. "21.00")
                    'vatRate': f"{sum(t.amount for t in line.tax_id):.2f}"
                }
                if mollie_category:
                    line_data['category'] = mollie_category
                
                lines.append(line_data)
            
            if lines:
                payload['lines'] = lines
              
        return payload