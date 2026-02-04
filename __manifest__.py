{
    'name': 'Mollie Subscription Renewals Dashboard',
    'version': '18.0.1.9.0',
    'category': 'Payment',
    'summary': 'Track Odoo subscription renewals charged via Mollie (Paid/Unpaid) with a dashboard',
    'description': """
Adds a Mollie App menu in Odoo 18.

- Shows all subscription renewal orders (sale orders with a subscription plan)
- Displays Mollie last payment status (paid / failed / open / etc.)
- Reads Mollie API to refresh payment status
- Adds cron to refresh statuses periodically
""",
    'depends': [
        'base', 'contacts', 'sale', 'sale_management',
        'website_sale', 'payment_mollie', 'sale_subscription' , "marketing_automation"
    ],
    'data': [
        'security/ir.model.access.csv',

        # ✅ IMPORTANT: action/view file must load BEFORE menu
        'views/mollie_dashboard_views.xml',
        'views/mollie_menu.xml',

        'views/res_partner_views.xml',
        'views/sale_order_views.xml',
        'data/cron_data.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
