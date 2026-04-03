# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mollie_recurring_company_id = fields.Many2one(
        'res.company',
        string="Mollie Recurring Company",
        config_parameter='mollie_recurring_payments.mollie_recurring_company_id',
        help=(
            "Select the company for which Mollie Recurring Payments are active. "
            "The background cron jobs (payment charges and status refresh) will ONLY "
            "process subscriptions belonging to this company. Other companies are unaffected."
        ),
    )
