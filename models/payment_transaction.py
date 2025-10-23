from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    is_subscription = fields.Boolean(
        string='Is Subscription Payment',
        compute='_compute_is_subscription',
        store=True
    )

    @api.depends('sale_order_ids', 'sale_order_ids.order_line.product_id.is_subscription')
    def _compute_is_subscription(self):
        for tx in self:
            tx.is_subscription = any(
                line.product_id.is_subscription
                for order in tx.sale_order_ids
                for line in order.order_line
            )

    def _get_specific_rendering_values(self, processing_values):
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'mollie' or not self.is_subscription:
            return res

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        
        # Add subscription-specific values for Mollie
        rendering_values = {
            'sequenceType': 'first',  # First payment for mandate
            'customerId': self.partner_id.mollie_customer_id,
            'webhookUrl': f'{base_url}/payment/mollie/webhook',
            'redirectUrl': f'{base_url}/payment/mollie/return',
            'method': 'ideal',  # Force iDEAL for first subscription payment
            'metadata': {
                'is_subscription': True,
                'transaction_id': self.id,
                'reference': self.reference,
            }
        }

        # Create Mollie customer if not exists
        if not self.partner_id.mollie_customer_id:
            self.provider_id._mollie_create_customer(self.partner_id)
            rendering_values['customerId'] = self.partner_id.mollie_customer_id

        res.update(rendering_values)
        return res

    def _process_notification_data(self, notification_data):
        res = super()._process_notification_data(notification_data)
        if self.provider_code == 'mollie' and self.state == 'done' and self.is_subscription:
            self._handle_subscription_payment(notification_data)
        return res

    def _handle_subscription_payment(self, notification_data):
        """Handle successful subscription payment"""
        try:
            payment_data = self.provider_id._mollie_get_client().payments.get(
                self.provider_reference
            )
            
            if not payment_data.get('mandateId'):
                _logger.error("No mandate ID in payment response")
                return

            mandate = self.env['mollie.mandate'].create({
                'mandate_id': payment_data['mandateId'],
                'customer_id': self.partner_id.mollie_customer_id,
                'partner_id': self.partner_id.id,
                'method': payment_data['method'],
                'status': 'valid',
                'order_id': self.sale_order_ids[0].id if self.sale_order_ids else False,
                'is_default': True
            })

            self.sale_order_ids.write({'active_mandate_id': mandate.id})
            _logger.info(
                "Created mandate %s from payment %s", 
                mandate.mandate_id, 
                self.provider_reference
            )

        except Exception as e:
            _logger.error("Failed to handle subscription payment: %s", str(e))