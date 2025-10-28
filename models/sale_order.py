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
    
    mollie_transaction_id = fields.Char(
        string="Mollie Transaction ID",
        related="partner_id.mollie_transaction_id",
        store=False,
        readonly=True
    )

    mollie_mandate_status = fields.Char(
        string="Mollie Mandate Status",
        related="partner_id.mollie_mandate_status",
        store=False,
        readonly=True
    )
    
    def _is_subscription_order(self):
        """Check if this sale order includes subscription products."""
        return any(line.product_id.recurring_invoice for line in self.order_line)

    def action_confirm(self):
        """When a sale order is confirmed, create Mollie customer + mandate."""
        res = super().action_confirm()

        for order in self:
            
            if not order._is_subscription_order():
                _logger.info("Order %s is not a subscription order. Skipping Mollie mandate creation.", order.name)
                continue
            
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

            # 🛑 Prevent duplicate mandate payment creation
            if partner.mollie_mandate_id and partner.mollie_mandate_status == "valid":
                _logger.info("Partner %s already has a valid mandate, skipping new mandate creation.", partner.name)
                continue
            
            # Create mandate via iDEAL payment
            payment_payload = {
                "amount": {"currency": order.currency_id.name, "value": "0.01"},
                "description": f"Mandate authorization for {partner.name}",
                "method": ["ideal"],
                "customerId": partner.mollie_customer_id,
                "redirectUrl": f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/mollie/mandate/return",
                "webhookUrl": f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/mollie/mandate/webhook",
                "sequenceType": "first",
            }

            p_resp = requests.post("https://api.mollie.com/v2/payments", json=payment_payload, headers=headers)
            if p_resp.status_code == 201:
                payment_data = p_resp.json()
                transaction_id = payment_data.get("id")
                partner.sudo().write({"mollie_transaction_id": transaction_id})
                partner.sudo().write({"mollie_mandate_status": payment_data.get("status")})
                _logger.info("Mandate payment created for %s", partner.name)
                
                # 🔁 Schedule mandate fetch after few seconds
                self.env.cr.commit()
                self.env["ir.cron"].sudo().create({
                    "name": f"Fetch Mollie Mandate for {partner.name}",
                    "model_id": self.env["ir.model"]._get_id("res.partner"),
                    "state": "code",
                    "code": f"env['res.partner'].browse({partner.id}).action_fetch_mollie_mandate()",
                    "interval_type": "minutes",
                    "interval_number": 1,
                    "numbercall": 1,
                    "active": True,
                })
            else:
                _logger.error("Mandate payment failed: %s", p_resp.text)
                
    

        


        return res
