from odoo import models, api, _, fields
import requests
import logging

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = "sale.order"
    
    
    mollie_customer_id = fields.Char(
        string="Mollie Customer ID",
        related="partner_id.mollie_customer_id",
        store=False,
        readonly=True
    )
    
    mollie_mandate_id = fields.Char(
        string="Mollie Mandate ID",
        related="partner_id.mollie_mandate_id",
        store=False,
        readonly=True
    )

    def action_confirm(self):
        """When a sale order is confirmed, create Mollie customer + mandate."""
        res = super().action_confirm()

        for order in self:
            partner = order.partner_id
            api_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
            if not api_key:
                _logger.error("Missing Mollie API key.")
                continue

            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

            # Create customer if missing
            if not partner.mollie_customer_id:
                payload = {
                    "name": partner.name,
                    "email": partner.email,
                    "metadata": {"odoo_partner_id": partner.id},
                }
                resp = requests.post("https://api.mollie.com/v2/customers", json=payload, headers=headers)
                if resp.status_code == 201:
                    partner.mollie_customer_id = resp.json().get("id")
                    _logger.info("Created Mollie customer for %s", partner.name)
                else:
                    _logger.error("Customer creation failed: %s", resp.text)
                    continue

            # Create mandate via iDEAL payment
            payment_payload = {
                "amount": {"currency": order.currency_id.name, "value": f"{order.amount_total:.2f}"},
                "description": f"Mandate authorization for {partner.name}",
                "method": ["ideal"],
                "customerId": partner.mollie_customer_id,
                "redirectUrl": f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/mollie/mandate/return",
                "webhookUrl": f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/mollie/mandate/webhook",
                "sequenceType": "first",
            }

            p_resp = requests.post("https://api.mollie.com/v2/payments", json=payment_payload, headers=headers)
            if p_resp.status_code == 201:
                _logger.info("Mandate payment created for %s", partner.name)
            else:
                _logger.error("Mandate payment failed: %s", p_resp.text)

        return res
