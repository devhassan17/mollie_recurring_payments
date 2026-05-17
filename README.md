# Mollie Subscription Renewals & Recurring Payments (Odoo 18)

[![Odoo Version](https://img.shields.io/badge/Odoo-18.0--Enterprise%2FCommunity-7C7BAD.svg?style=flat-square&logo=odoo)](https://www.odoo.com/)
[![License](https://img.shields.io/badge/License-LGPL--3-blue.svg?style=flat-square)](https://www.gnu.org/licenses/lgpl-3.0.html)
[![Mollie API](https://img.shields.io/badge/Mollie%20API-v2-FF5C2B.svg?style=flat-square)](https://docs.mollie.com/)

An enterprise-grade, highly automated Odoo 18 module that handles recurring subscription billing via the **Mollie Gateway**. 

This module intercepts Odoo's native subscription schedules, charges customers using stored payment mandates, and uses a savepoint-protected native payment registry to reconcile accounting ledgers automatically.

---

## 🌟 Key Features

* **🔄 Automatic Subscription Interception**: Connects directly with Odoo's native invoice cron job to process payments automatically for subscriptions that are due.
* **💳 Seamless Mandate Management**: Storing and validating Mollie customer (`cst_XXXX`) and direct debit mandate (`mdt_XXXX`) IDs directly on customer contact profiles.
* **🛡️ Strict Idempotency Controls**: Generates unique idempotency keys (`mollie-charge-{order_id}-{date}`) for all API transactions to prevent duplicate charges.
* **⚡ Intelligent Accounting & Auto-Reconcile**: Generates and posts draft invoices upon payment success, reconciling them using Odoo's native payment register wizard.
* **🚨 Automated Payment Reversals**: Monitors asynchronous transactions (like SEPA Direct Debit) and automatically reverses registered payments and resets invoices to unpaid if the payment subsequently fails on Mollie.
* **🎁 Smart B2B Voucher Support**: Maps product categories to Mollie voucher types (Eco, Meal, Gift, Sport, Holiday) with precision adjustments to avoid tax rounding discrepancies.
* **📊 Live Subscriptions Dashboard**: A visual overview of upcoming renewals, active mandates, and transaction status codes.

---

## 📖 Table of Contents

1. [System Dependencies](#-system-dependencies)
2. [Installation Guide](#%EF%B8%8F-installation-guide)
3. [Configuration](#%EF%B8%8F-configuration)
   * [1. Mollie Provider Configuration](#1-mollie-provider-configuration)
   * [2. Subscription Configuration](#2-subscription-configuration)
   * [3. Company-Level Isolation](#3-company-level-isolation)
   * [4. B2B Voucher & Gift Card Mapping](#4-b2b-voucher--gift-card-mapping)
4. [How It Works (Cron & Scheduled Actions)](#-how-it-works-cron--scheduled-actions)
5. [Technical Blueprint & Deep-Dive](#%EF%B8%8F-technical-blueprint--deep-dive)
6. [Running Unit Tests](#-running-unit-tests)
7. [License](#-license)

---

## 🔌 System Dependencies

This module is designed for Odoo 18 (Enterprise or Community) and requires the following modules:
* `base`
* `contacts`
* `sale`
* `sale_management`
* `website_sale`
* `payment_mollie` (Odoo's official Mollie provider extension)
* `sale_subscription` (Odoo Subscriptions core)
* `account` (Odoo Accounting/Invoicing engine)
* `marketing_automation`

---

## 🛠️ Installation Guide

1. **Deploy Module Files**: Copy the `mollie_recurring_payments` directory into your Odoo custom addons directory.
2. **Restart Odoo**: Restart your Odoo server instance to register the custom path.
3. **Update Apps List**: Log in as Administrator, activate Developer Mode, navigate to **Apps**, and click **Update Apps List**.
4. **Install Module**: Search for `Mollie Subscription Renewals Dashboard & Recurring Payments` and click **Install**.

---

## ⚙️ Configuration

### 1. Mollie Provider Configuration
To link your Odoo instance with Mollie:
1. Go to **Accounting / Invoicing** ➔ **Configuration** ➔ **Payment Providers**.
2. Select **Mollie**.
3. Set the state to **Test Mode** or **Enabled**.
4. Under the **Credentials** tab, enter your Mollie **API Key**.
5. Enable **SEPA Direct Debit** and **iDEAL** payment methods in your Mollie Dashboard (SEPA is required for subsequent automated recurring charges).

### 2. Subscription Configuration
1. Go to **Subscriptions** (or Sales) and create subscription products.
2. Ensure **Recurring Invoice** is enabled on the product template.
3. Set up your recurring plans (e.g. Monthly, Bi-monthly).

### 3. Company-Level Isolation
If you operate in a multi-company Odoo environment, you can isolate recurring charges to a single company:
1. Go to **Mollie** (root menu) ➔ **Configuration**.
2. Set the **Active Company** field.
3. Once configured, the recurring charge crons and status fetches will only process subscriptions belonging to the selected company, preventing cross-company interference.

### 4. B2B Voucher & Gift Card Mapping
If you accept meal vouchers, eco-cheques, or gift cards:
1. Go to **Accounting / Invoicing** ➔ **Configuration** ➔ **Payment Providers** ➔ **Mollie**.
2. Under the **Voucher Configuration** tab, check **Mollie: Use Vouchers**.
3. Add lines to map your Odoo **Product Categories** to corresponding **Mollie Voucher Types** (Eco, Meal, Gift, Sport Culture, Holiday).

---

## ⏱️ How It Works (Cron & Scheduled Actions)

The module automates recurring billing using Odoo's scheduled actions:

1. **Native Subscription Cron (`_cron_recurring_create_invoice`)**:
   * Runs daily to locate subscription sales orders that are due for billing today.
   * If a valid customer mandate is found, it automatically charges the customer's account using the stored Mollie mandate.
   * After capturing the payment, it hands control back to Odoo to generate the invoice lines and registers the payment automatically.
2. **Mollie Status Refresh Cron (`cron_mollie_refresh_last_payment_status`)**:
   * Runs every **5 minutes**.
   * Pulls real-time transaction updates for all active, non-terminal payments (like pending SEPA Direct Debits) from Mollie's servers.
   * Registers payments in Odoo once cleared, or automatically reverses them if they fail or expire.

---

## 🏗️ Technical Blueprint & Deep-Dive

For a complete look at the underlying architecture, data models, workflows, and technical design decisions (including idempotency controls, rate limiting, and voucher tax rounding corrections), please refer to our detailed technical guide:

👉 **[TECHNICAL_DOCUMENTATION.md](file:///Users/alihassan/Documents/Github/mollie_recurring_payments/TECHNICAL_DOCUMENTATION.md)**

---

## 🧪 Running Unit Tests

The module includes comprehensive unit tests in the `/tests` directory to verify the payment and reconciliation processes.

To run the test suite locally:
```bash
./odoo-bin -c <odoo_config_file> -i mollie_recurring_payments --test-tags=post_install,at_install
```

---

## 📄 License

This module is licensed under the **LGPL-3** license. 

Developed and maintained by **[Managemyweb.co](https://managemyweb.co)** (Maintainer: `ali@moyeecoffee.com`).
