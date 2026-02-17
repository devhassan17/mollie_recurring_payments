from odoo.tests.common import TransactionCase
from odoo.addons.sale.tests.common import TestSaleCommon

class TestMollieSubscription(TransactionCase):

    def setUp(self):
        super(TestMollieSubscription, self).setUp()
        self.partner = self.env['res.partner'].create({'name': 'Test Partner'})
        self.product = self.env['product.product'].create({
            'name': 'Subscription Product',
            'list_price': 100.0,
            # recurring_invoice field must exist on product.product if not product.template
            # Assuming product.product inherits fields from template usually or it's on template
        })
        # Mock recurring_invoice on product template via product
        self.product.product_tmpl_id.recurring_invoice = True

        self.sale_order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'price_unit': 100.0,
            })]
        })
        self.sale_order.action_confirm()
        
        # Create an invoice
        # Odoo 16+ might use different logic, but _create_invoices usually works
        self.invoice = self.sale_order._create_invoices()
        self.invoice.action_post()
        
        # Determine journal
        self.journal = self.env['account.journal'].search([('type', '=', 'bank')], limit=1)
        if not self.journal:
            self.journal = self.env['account.journal'].create({
                'name': 'Bank',
                'type': 'bank',
                'code': 'BNK1',
            })

    def test_process_mollie_payment_success(self):
        """Test that _process_mollie_payment_success pays the invoice"""
        
        # Ensure invoice is posted but not paid
        self.assertEqual(self.invoice.payment_state, 'not_paid')
        
        # Simulate payment ID
        payment_id = 'tr_test123'
        self.sale_order.last_payment_id = payment_id
        
        # Call the method
        self.sale_order._process_mollie_payment_success(payment_id, 100.0)
        
        # Check if invoice is paid
        self.assertEqual(self.invoice.payment_state, 'paid')
        
        # Verify a payment exists and is linked
        self.assertTrue(self.invoice.payment_ids)
