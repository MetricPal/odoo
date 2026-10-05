# UI Wireframes

These are implementation-oriented wireframes for Odoo 20 Community views. They are intentionally simple and Odoo-native rather than a custom SPA.

## 1. Dashboard

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Omni Channel                                      [Configure]       │
├───────────────┬───────────────┬───────────────┬─────────────────────┤
│ Inbound       │ Outbound      │ Conversations │ Failed Deliveries   │
│    1,248      │     936       │      318      │         12          │
├───────────────┴───────────────┴───────────────┴─────────────────────┤
│ Message Volume                                                       │
│             ╭──────────────╮                                        │
│        ╭────╯              ╰────╮                                   │
│   ─────╯                         ╰──────                             │
├─────────────────────────────────────────────────────────────────────┤
│ Channel Health                                                       │
│ WhatsApp    ● Healthy    Telegram ● Healthy    Instagram ● Warning │
│ LinkedIn    ● Healthy    X         ● Healthy    TikTok    ● Offline │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. Channel List

```text
Channels                                      [New]

Filters: [Module] [Channel] [Status] [Company]
Group By: [Module] [Channel]

┌────────────┬───────────┬─────────────┬───────────┬───────────────┐
│ Name       │ Module    │ Channel     │ Outbound  │ Inbound       │
├────────────┼───────────┼─────────────┼───────────┼───────────────┤
│ Marketing  │ Marketing │ WhatsApp    │ ● 1       │ 5 endpoints   │
│ Marketing  │ Marketing │ Telegram    │ ● 1       │ 2 endpoints   │
│ Sales      │ Sales     │ WhatsApp    │ ● 1       │ 3 endpoints   │
│ Recruiting │ Recruit.  │ LinkedIn    │ ● 1       │ 1 endpoint    │
└────────────┴───────────┴─────────────┴───────────┴───────────────┘
```

## 3. Channel Kanban

```text
┌────────────────────────┐
│ WhatsApp               │
│ Marketing              │
│                        │
│ OUTBOUND      ● Ready  │
│ 1 sender               │
│                        │
│ INBOUND       5        │
│ +6011...               │
│ +6012...               │
│ +6013...               │
│ +6014...               │
│ +6015...               │
│                        │
│ [Healthy] [Messages]   │
└────────────────────────┘
```

## 4. Channel Form

```text
┌─────────────────────────────────────────────────────────────┐
│ Marketing / WhatsApp                         [Active]       │
├─────────────────────────────────────────────────────────────┤
│ GENERAL                                                     │
│ Name: Marketing WhatsApp     Module: Marketing              │
│ Channel: WhatsApp            Company: My Company             │
├─────────────────────────────────────────────────────────────┤
│ OUTBOUND — exactly one                                      │
│ Sender: Marketing Business Account                           │
│ Identity: +60...            Status: ● Connected              │
├─────────────────────────────────────────────────────────────┤
│ INBOUND ENDPOINTS — one to many                              │
│ ┌──────────────┬──────────────┬────────────┬─────────────┐  │
│ │ Endpoint     │ Address      │ Purpose    │ Status      │  │
│ ├──────────────┼──────────────┼────────────┼─────────────┤  │
│ │ WhatsApp #1  │ +6011...     │ Marketing  │ ● Active    │  │
│ │ WhatsApp #2  │ +6012...     │ Marketing  │ ● Active    │  │
│ │ WhatsApp #3  │ +6013...     │ Marketing  │ ● Active    │  │
│ └──────────────┴──────────────┴────────────┴─────────────┘  │
│                                                             │
│ CAPABILITIES                                                │
│ [✓ Private] [✓ Bulk] [✓ Group] [✓ Media] [✓ Template]      │
├─────────────────────────────────────────────────────────────┤
│ HEALTH / WEBHOOK / AUDIT                                    │
└─────────────────────────────────────────────────────────────┘
```

## 5. Conversation Kanban

```text
NEW                 OPEN                 WAITING             CLOSED
┌───────────────┐   ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ John           │   │ Sarah          │   │ Ali            │   │ Mary           │
│ WhatsApp       │   │ Instagram      │   │ Telegram       │   │ LinkedIn       │
│ 2 unread       │   │ 1 unread       │   │ waiting 2h    │   │ resolved       │
└───────────────┘   └───────────────┘   └───────────────┘   └───────────────┘
```

## 6. Conversation Form

```text
┌──────────────────────────────────────────────────────────────────┐
│ John Smith     WhatsApp     Marketing       Assigned: Hassan     │
├───────────────────────────────────────┬──────────────────────────┤
│                                       │ CONTACT / BUSINESS       │
│ Customer: Hi, I saw your campaign... │ John Smith               │
│                                       │ CRM Lead #1024           │
│ Marketing: Thanks! How can we help?  │ Campaign: October Sale   │
│                                       │                          │
│ Customer: ...                         │ CHANNEL                  │
│                                       │ WhatsApp                  │
│                                       │ Endpoint: +6012...       │
├───────────────────────────────────────┤                          │
│ [Type message...]       [Send]        │                          │
└───────────────────────────────────────┴──────────────────────────┘
```

## 7. Social Post Form

```text
┌─────────────────────────────────────────────────────────────┐
│ Create Social Post                         [Save] [Submit]   │
├─────────────────────────────────────────────────────────────┤
│ Channel / Account: Instagram / Marketing                    │
│                                                             │
│ Content                                                     │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ October campaign copy...                                │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ Media: [ + Add Image ] [ + Add Video ]                     │
│                                                             │
│ PREVIEW                                                     │
│ ┌──────────────────────────┐                                │
│ │       Social Preview     │                                │
│ └──────────────────────────┘                                │
│                                                             │
│ Status: Draft → Pending Approval → Approved → Published     │
└─────────────────────────────────────────────────────────────┘
```

## Design Principle
The most important visual distinction in the entire module is:

`OUTBOUND = 1 logical sender` versus `INBOUND = N endpoints`.

Every relevant form and list should reinforce this distinction.

## Outbound Sender Pool UI

The Channel Form must distinguish **Inbound Endpoints (N)** from **Outbound Sender Configurations (N)** and show exactly one active outbound sender.

```text
┌─────────────────────────────────────────────────────────────┐
│ Marketing / WhatsApp                                       │
├─────────────────────────────────────────────────────────────┤
│ OUTBOUND SENDERS                              [+ Add Sender] │
│                                                             │
│ ( ) WhatsApp Business #1   +60 11...   ✓ Healthy            │
│     Last checked: 10:42                    [Check Health]  │
│                                                             │
│ (●) WhatsApp Business #2   +60 12...   ✓ Healthy            │
│     ACTIVE — Runtime Sender                [Check Health]  │
│                                                             │
│ ( ) WhatsApp Business #3   +60 13...   ⚠ Unauthorized       │
│     Last checked: 10:40                    [Check Health]  │
└─────────────────────────────────────────────────────────────┘
```

Use a radio group, not independent checkboxes. Changing selection must use **Check & Activate**. Failed health checks keep the current active sender unchanged.

### Activation Dialog

```text
Activate this outbound sender?
Marketing / WhatsApp
WhatsApp Business #1
+60 11...

The provider will be checked before activation.

[Cancel] [Check & Activate]
```

### Health Failure

```text
Sender cannot be activated
✕ Authorization expired
The current active sender has NOT been changed.
[Close]
```

Do not provide automatic failover controls. If the active sender later becomes unhealthy, show a prominent warning and require administrator action.

## 9.5 Inbound Safety / Blocklist UI

Conversation actions:
`[Reply] [Assign] [Report Spam] [Block Sender] [More]`

Top-level menu:
`Omni-Channel -> Blocked Identities`

Blocked list columns: Identity, Channel, Module, Reason, Source, Status, Blocked At.

AI moderation may display:
`Spam risk: 94% | Recommendation: Block | Reason: repeated irrelevant promotional messages`

AI recommendations are not blocks until explicitly approved.

Approval dialog:
`AI recommends blocking this sender -> [Dismiss] [Approve Block]`

Sender block confirmation must display identity, channel, module, scope and reason. All approval actions are audited.
