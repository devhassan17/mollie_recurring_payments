{
    'name': 'mollie_recurring_payments',
    'version': '1.5',
    'category': 'Payment',
    'summary': 'Recurring payments with Mollie iDEAL for subscriptions',
    'description': """
        Enable recurring payments with Mollie iDEAL for subscription products
        Supports mandate creation and automatic recurring charges
    """,
    "depends": ["base", "contacts", "sale_management", "website_sale", "payment_mollie", 'sale_subscription', 'sale'],
    "data": [
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}