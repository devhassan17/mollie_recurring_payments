# -*- coding: utf-8 -*-
from odoo import models, fields


class AccountPayment(models.Model):
    _inherit = "account.payment"

    mollie_payment_id = fields.Char(index=True)