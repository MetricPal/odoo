# Routing Examples

## Marketing with many WhatsApp inbound numbers

```text
Marketing
└── WhatsApp
    ├── OUTBOUND: Marketing WhatsApp
    │
    └── INBOUND
        ├── +60111111111 -> Marketing
        ├── +60122222222 -> Marketing
        ├── +60133333333 -> Marketing
        └── +60144444444 -> Marketing
```

## Sales uses a different inbound number

```text
Sales
└── WhatsApp
    ├── OUTBOUND: Sales WhatsApp
    └── INBOUND
        └── +60155555555 -> Sales
```

The same endpoint cannot be attached to both Marketing and Sales.

## Telegram

```text
Marketing
└── Telegram
    ├── OUTBOUND: Marketing Telegram
    └── INBOUND
        ├── Marketing Bot A
        ├── Marketing Bot B
        └── Marketing Group/Channel endpoint(s)
```

## Social

```text
Marketing
├── LinkedIn
│   ├── OUTBOUND: 1
│   └── INBOUND: N
├── Instagram
│   ├── OUTBOUND: 1
│   └── INBOUND: N
├── Facebook
│   ├── OUTBOUND: 1
│   └── INBOUND: N
├── X
│   ├── OUTBOUND: 1
│   └── INBOUND: N
└── TikTok
    ├── OUTBOUND: 1
    └── INBOUND: N
```

## Email and SMS

These are intentionally omitted from the above Omni tree because Odoo owns them natively.

```text
Marketing
├── Odoo Email Marketing
└── Odoo SMS Marketing
```

If a unified reporting/inbox layer is needed later, use integration adapters rather than duplicate senders.
