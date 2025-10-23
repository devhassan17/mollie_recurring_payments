from odoo import models, fields, api, _ 
import logging
import requests
from datetime import date, timedelta

_logger = logging.getLogger(__name__)

class MollieSubscription(models.Model):
    _name = "mollie.subscription"
    _description = "Mollie Recurring Subscription"

    name = fields.Char(required=True)
    partner_id = fields.Many2one('res.partner', required=True)
    amount = fields.Float(string="Amount (€)", required=True)
    interval = fields.Selection([('1 month', '1 Month'), ('3 months','3 Months')], string="Interval", default='1 month')
    next_payment_date = fields.Date(default=fields.Date.today)
    active = fields.Boolean(default=True)
    mollie_subscription_id = fields.Char(string="Mollie Subscription ID", readonly=True)
    mollie_payment_status = fields.Selection([('pending','Pending'),('active','Active'),('cancelled','Cancelled')], string="Status", default='pending')

    def action_create_mollie_subscription(self):
        for sub in self:
            partner = sub.partner_id
            if not partner.mollie_customer_id or not partner.mollie_mandate_id:
                raise models.ValidationError(_("Partner must have Mollie Customer ID and Mandate before creating a subscription."))

            api_key = self.env["ir.config_parameter"].sudo().get_param("mollie.api_key_test")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "amount": {"currency": "EUR", "value": f"{sub.amount:.2f}"},
                "interval": sub.interval,
                "description": sub.name,
                "mandateId": partner.mollie_mandate_id,
                "customerId": partner.mollie_customer_id,
                "webhookUrl": "https://<your-domain>/mollie/recurring/webhook"
            }
            resp = requests.post("https://api.mollie.com/v2/customers/%s/subscriptions" % partner.mollie_customer_id,
                                 headers=headers, json=payload, timeout=10)
            if resp.status_code in (200, 201):
                data = resp.json()
                sub.sudo().write({
                    "mollie_subscription_id": data.get("id"),
                    "mollie_payment_status": data.get("status")
                })
                _logger.info("Created Mollie subscription %s for partner %s", data.get("id"), partner.name)
            else:
                _logger.error("Failed to create Mollie subscription: %s", resp.text)
                raise models.UserError(_("Failed to create Mollie subscription: %s") % resp.text)

    @api.model
    def cron_recurring_charges(self):
        today = fields.Date.today()
        subs = self.search([('next_payment_date', '<=', today), ('active', '=', True)])
        for sub in subs:
            _logger.info("Processing subscription %s", sub.name)
            # Trigger payment manually or rely on Mollie subscription payments
            sub.next_payment_date = sub.next_payment_date + timedelta(days=30)
