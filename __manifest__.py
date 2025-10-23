{
    'name': 'mollie_recurring_payments',
    'version': '1.2',
    'category': 'Payment',
    'summary': 'Recurring payments with Mollie iDEAL for subscriptions',
    'description': """
        Enable recurring payments with Mollie iDEAL for subscription products
        Supports mandate creation and automatic recurring charges
    """,
    'depends': ['payment_mollie', 'sale_subscription', 'sale', 'mail'],
    'data': [
        'views/mandate_views.xml',
        'views/payment_provider_views.xml',
        'views/templates.xml',
        'views/sale_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}