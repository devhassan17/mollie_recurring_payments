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

            # Step 1: Create or get customer
            customer_id = self._get_or_create_mollie_customer(partner, headers)
            if not customer_id:
                _logger.error("Failed to get/create Mollie customer for %s. Cannot proceed with mandate.", partner.name)
                continue

            # Step 2: Check if valid mandate already exists
            if partner.mollie_mandate_id and partner.mollie_mandate_status == "valid":
                _logger.info("Partner %s already has a valid mandate, skipping new mandate creation.", partner.name)
                continue

            # Step 3: Create mandate via first payment
            success = self._create_mandate_via_first_payment(partner, customer_id, order, headers)
            if not success:
                _logger.error("Failed to create mandate for partner %s", partner.name)

        return res
    
    def _get_or_create_mollie_customer(self, partner, headers):
        """Get existing Mollie customer or create new one"""
        # If customer already exists, validate it
        if partner.mollie_customer_id:
            if self._validate_mollie_customer(partner.mollie_customer_id, headers):
                _logger.info("Using existing Mollie customer: %s", partner.mollie_customer_id)
                return partner.mollie_customer_id
            else:
                _logger.warning("Existing customer %s not found in Mollie, creating new one", partner.mollie_customer_id)
        
        # Create new customer
        return self._create_mollie_customer(partner, headers)

    def _create_mollie_customer(self, partner, headers):
        """Create Mollie customer and return customer ID"""
        try:
            payload = {
                "name": partner.name or f"Customer {partner.id}",
                "email": partner.email or "",
                "metadata": {"odoo_partner_id": partner.id},
            }
            
            _logger.info("Creating Mollie customer with payload: %s", payload)
            resp = requests.post("https://api.mollie.com/v2/customers", json=payload, headers=headers, timeout=10)
            
            if resp.status_code == 201:
                customer_data = resp.json()
                customer_id = customer_data.get("id")
                partner.sudo().write({"mollie_customer_id": customer_id})
                _logger.info("✅ Created Mollie customer %s for %s", customer_id, partner.name)
                return customer_id
            else:
                _logger.error("❌ Customer creation failed: %s - %s", resp.status_code, resp.text)
                if resp.status_code == 422:
                    error_data = resp.json()
                    _logger.error("Validation errors: %s", error_data.get('detail', 'Unknown error'))
                return None
                
        except Exception as e:
            _logger.error("❌ Exception creating Mollie customer: %s", str(e))
            return None

    def _validate_mollie_customer(self, customer_id, headers):
        """Validate that a customer exists in Mollie"""
        try:
            url = f"https://api.mollie.com/v2/customers/{customer_id}"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return True
            elif resp.status_code == 404:
                _logger.warning("Customer %s not found in Mollie", customer_id)
                return False
            else:
                _logger.error("Error validating customer %s: %s", customer_id, resp.status_code)
                return False
        except Exception as e:
            _logger.error("Exception validating customer %s: %s", customer_id, str(e))
            return False

    def _create_mandate_via_first_payment(self, partner, customer_id, order, headers):
        """Create mandate by making a first payment with sequenceType='first'"""
        try:
            # Create mandate authorization payment (€0.01)
            payment_payload = {
                "amount": {
                    "currency": order.currency_id.name, 
                    "value": "0.01"  # Small amount for mandate authorization
                },
                "description": f"Mandate authorization for {partner.name}",
                "method": ["ideal", "creditcard"],  # Multiple methods for better success
                "customerId": customer_id,
                "redirectUrl": f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/mollie/mandate/return?partner_id={partner.id}",
                "webhookUrl": f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/mollie/mandate/webhook",
                "sequenceType": "first",  # This triggers mandate creation
                "metadata": {
                    "odoo_partner_id": partner.id,
                    "purpose": "mandate_authorization"
                }
            }

            _logger.info("Creating mandate payment for customer %s", customer_id)
            p_resp = requests.post("https://api.mollie.com/v2/payments", json=payment_payload, headers=headers, timeout=30)
            
            if p_resp.status_code == 201:
                payment_data = p_resp.json()
                transaction_id = payment_data.get("id")
                checkout_url = payment_data.get("_links", {}).get("checkout", {}).get("href")
                
                # Store transaction and payment details
                partner.sudo().write({
                    "mollie_transaction_id": transaction_id,
                    "mollie_mandate_status": payment_data.get("status", "pending")
                })
                
                _logger.info("✅ Mandate payment created for %s", partner.name)
                _logger.info("Transaction ID: %s", transaction_id)
                _logger.info("Payment status: %s", payment_data.get("status"))
                _logger.info("Checkout URL: %s", checkout_url)
                
                # Important: Customer MUST complete the payment to create the mandate
                _logger.info("⚠️ Customer must complete payment at: %s", checkout_url)
                
                # Schedule mandate check after some time
                self._schedule_mandate_check(partner, customer_id)
                return True
                
            else:
                error_data = p_resp.json() if p_resp.content else {}
                _logger.error("❌ Mandate payment creation failed: %s - %s", p_resp.status_code, error_data)
                if p_resp.status_code == 422:
                    _logger.error("Validation errors: %s", error_data.get('detail', 'Unknown validation error'))
                return False
                
        except Exception as e:
            _logger.error("❌ Exception creating mandate payment: %s", str(e))
            return False

    def _schedule_mandate_check(self, partner, customer_id):
        """Schedule a delayed mandate check"""
        try:
            # Create a one-time cron to check for mandates
            cron_vals = {
                "name": f"Check Mollie Mandate for {partner.name}",
                "model_id": self.env["ir.model"]._get_id("res.partner"),
                "state": "code",
                "code": f"model.browse({partner.id}).action_fetch_mollie_mandate()",
                "interval_type": "minutes",
                "interval_number": 2,  # Check after 2 minutes
                "numbercall": 1,
                "doall": False,
                "active": True,
            }
            self.env["ir.cron"].sudo().create(cron_vals)
            _logger.info("Scheduled mandate check for partner %s", partner.name)
        except Exception as e:
            _logger.error("Failed to schedule mandate check: %s", str(e))