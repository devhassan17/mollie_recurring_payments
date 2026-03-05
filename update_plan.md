1. **Models/account_move.py:**
Add `mollie_subscription_payment_id` field.
Add `mollie_payment_status` field to the invoice? 

2. **Models/sale_order.py:**
When creating invoices:
```python
            for order in charged_orders:
                invoice = order.invoice_ids.sorted("id", reverse=True)[:1]
                if invoice:
                    invoice.mollie_subscription_payment_id = order.last_payment_id
```

When receiving webhook payment id:
Update to search by `mollie_subscription_payment_id` on the invoice directly, or keep searching sale order but find the invoice using this ID!
