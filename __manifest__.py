{
    'name': 'mollie_recurring_payments',
    'version': '1.2',
    'category': 'Payment',
    'summary': 'Recurring payments with Mollie iDEAL for subscriptions',
    'description': """
        Enable recurring payments with Mollie iDEAL for subscription products
        Supports mandate creation and automatic recurring charges
    """,
    'depends': ['payment_mollie', 'sale', 'mail', 'sale_subscription'],
    'data': [
        'security/ir.model.access.csv',
        'data/data.xml',
        'views/mandate_views.xml',
        'views/subscription_views.xml',
        'views/templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}