{
    'name': 'mollie_recurring_payments',
    'version': '2.0',
    'category': 'Accounting/Payment',
    'summary': 'Enable recurring payments via Mollie for subscriptions with auto-retry and email alerts',
    'description': """
        Extend Mollie payment integration to support recurring subscriptions,
        auto retries, mandate management, and customer/admin notifications.
    """,
    'depends': ['payment_mollie', 'sale', 'mail', 'sale_subscription'],
    'data': [
        'views/res_partner_view.xml',
        'views/mollie_subscription_view.xml',
    ],
    'installable': True,
    'application': False,
}