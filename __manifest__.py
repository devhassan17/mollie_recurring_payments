{
    'name': 'Mollie Subscription Renewals Dashboard & Recurring Payments',
    'version': '18.0.6.4.0',
    'category': 'Payment',
    'author': 'Managemyweb.co',
    'website': 'https://managemyweb.co',
    'maintainer': 'ali@moyeecoffee.com',
    'summary': 'Automated Odoo 18 subscription renewals with Mollie. Includes dashboard, mandate sync, and intelligent auto-reconciliation.',
    'description': """
Mollie Recurring Payments for Odoo 18 Subscriptions.

Key Features:
- **Subscription Renewals Dashboard**: Real-time tracking of upcoming renewals and Mollie payment statuses (Paid, Failed, Pending, etc.).
- **Automated Mandate & Customer Sync**: Automatically fetches and verifies Mollie mandates upon sale order confirmation.
- **Background Recurring Charges**: Cron-driven processing that charges Mollie mandates and creates Odoo invoices automatically.
- **Intelligent Accounting**: Automatically reconciles posted invoices with successful Mollie payments.
- **Payment Reversal on Failure**: Automatically reverses Odoo payments if Mollie status changes to Failed, Canceled, or Expired.
- **Real-time Updates**: Webhook support for instant mandate and payment status synchronization.
- **Charge Safety**: Prevents charging for churned, paused, or closed subscriptions.
""",
    'depends': [
        'base', 'contacts', 'sale', 'sale_management',
        'website_sale', 'payment_mollie', 'sale_subscription' , "marketing_automation" , "account",
    ],
    'data': [
        'security/ir.model.access.csv',

        'views/mollie_dashboard_views.xml',
        'views/mollie_config_settings_views.xml',  # must load before mollie_menu.xml (menu refs the action)
        'views/mollie_menu.xml',

        'views/res_partner_views.xml',
        'views/sale_order_views.xml',
        'views/payment_provider_views.xml',
        'data/payment_method_data.xml',
        'data/cron_data.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
