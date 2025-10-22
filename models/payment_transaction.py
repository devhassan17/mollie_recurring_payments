import logging
from odoo import models, api

_logger = logging.getLogger(__name__)

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    @api.model
    def _mollie_form_feedback(self, data):
        """Called when Mollie sends a webhook or payment confirmation."""
        _logger.info("💳 Mollie webhook received: %s", data)
        result = super()._mollie_form_feedback(data)

        # Find related partner
        tx = self.search([('reference', '=', data.get('ref'))])
        if tx and tx.partner_id:
            _logger.info(f"🔁 Triggering Mollie mandate sync for partner {tx.partner_id.name}")
            tx.partner_id.fetch_mollie_mandate()
        else:
            _logger.warning("⚠️ No transaction or partner found for Mollie webhook data: %s", data)

        return result
