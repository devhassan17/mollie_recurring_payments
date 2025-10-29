from odoo import models, api, _, fields
import requests
import logging
import time 

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
            customer_id = None
            if not partner.mollie_customer_id:
                customer_id = self._create_mollie_customer(partner, headers)
                if not customer_id:
                    _logger.error("Failed to create Mollie customer for %s. Cannot proceed with mandate.", partner.name)
                    continue
            else:
                customer_id = partner.mollie_customer_id
                _logger.info("Using existing Mollie customer: %s", customer_id)

            # 🛑 Validate customer exists in Mollie before proceeding
            if not self._validate_mollie_customer(customer_id, headers):
                _logger.error("Customer %s not found in Mollie. Creating new customer.", customer_id)
                customer_id = self._create_mollie_customer(partner, headers)
                if not customer_id:
                    _logger.error("Failed to recreate Mollie customer. Aborting mandate creation.")
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
                _logger.info("Mandate payment created for %s", partner.name)      
                
                time.sleep(5)
                partner.action_fetch_mollie_mandate()
                _logger.info("Fetched Mollie mandate for partner %s after payment creation.", partner.name)
                
            else:
                _logger.error("Mandate payment failed: %s", p_resp.text)
                

        return res
    
    def _create_mollie_customer(self, partner, headers):
        """Create Mollie customer and return customer ID"""
        try:
            payload = {
                "name": partner.name or f"Customer {partner.id}",
                "email": partner.email or "",
                "metadata": {"odoo_partner_id": partner.id},
            }
            
            resp = requests.post("https://api.mollie.com/v2/customers", json=payload, headers=headers, timeout=10)
            
            if resp.status_code == 201:
                customer_data = resp.json()
                customer_id = customer_data.get("id")
                partner.sudo().write({"mollie_customer_id": customer_id})
                _logger.info("✅ Created Mollie customer %s for %s", customer_id, partner.name)
                return customer_id
            else:
                _logger.error("❌ Customer creation failed: %s - %s", resp.status_code, resp.text)
                return None
                
        except Exception as e:
            _logger.error("❌ Exception creating Mollie customer: %s", str(e))
            return None

    def _validate_mollie_customer(self, customer_id, headers):
        """Validate that a customer exists in Mollie"""
        try:
            url = f"https://api.mollie.com/v2/customers/{customer_id}"
            resp = requests.get(url, headers=headers, timeout=10)
            return resp.status_code == 200
        except:
            return False

