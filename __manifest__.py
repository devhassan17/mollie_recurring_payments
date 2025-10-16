{
    'name': 'mollie_recurring_payments',
    'version': '1.0',
    'category': 'Accounting/Payment',
    'summary': 'Enable recurring payments via Mollie for subscriptions with auto-retry and email alerts',
    'description': """
        Extend Mollie payment integration to support recurring subscriptions,
        auto retries, mandate management, and customer/admin notifications.
    """,
    'depends': ['payment_mollie_official', 'sale_subscription', 'mail'],
    'data': [
        'data/mollie_cron.xml',
        'data/mail_templates.xml',
        'views/subscription_view.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
