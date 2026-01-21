{
    'name': 'mollie_recurring_payments',
    'version': '1.0.0',
    'category': 'Payment',
    'author': 'Managemyweb.co',
    "website": "https://fairchain.org/mollie_recurring_payments/",
    "category": "Payment",
    "license": "LGPL-3",
    "images": ["static/description/banner.png"],
    'summary': 'Recurring payments with Mollie iDEAL for subscriptions',
    'description': """
        Enable recurring payments with Mollie iDEAL for subscription products
        Supports mandate creation and automatic recurring charges
    """,
    "depends": ["base", "contacts", "sale_management", "website_sale", "payment_mollie", 'sale_subscription', 'sale'],
    "data": [
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
        "data/cron_data.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
    "support": "programmer.alihassan@gmail.com",
    "price": 199.99,
    "currency": "USD",
}