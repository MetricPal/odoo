"""Draft recipes: no demonstration business records and no automatic activation."""
from odoo import _
from odoo.exceptions import UserError

RECIPES = [
    ('invoices', 'Overdue invoice reminders', 'Invoicing', 'Reminders', 'account.move', 'date',
     'Email the customer when an invoice is overdue, then escalate to a call and the accountant.',
     [('condition', 'Posted and not paid'), ('mail_post', 'Email the customer a reminder'),
      ('wait', 'Wait 7 days'), ('branch', 'Paid yet?'), ('mail_post', 'Thank the customer'),
      ('next_activity', 'Call the customer'), ('wait', 'Wait another 16 days'),
      ('mail_post', 'Alert the accountant')]),
    ('leads', 'New lead assignment and first call', 'CRM', 'Data updates', 'crm.lead', 'create',
     'Assign a salesperson, send a welcome message, book a call and check completion.',
     [('object_write', 'Assign a salesperson'), ('chat', 'WhatsApp welcome'),
      ('next_activity', 'Book a first call'), ('wait', 'Wait one day'),
      ('branch', 'Was the call completed?'), ('mail_post', 'Notify the salesperson'),
      ('next_activity', 'Follow up on the missed call')]),
    ('onboarding', 'New employee onboarding', 'Employees', 'Create records', 'hr.employee', 'create',
     'Create onboarding tasks, ask IT for a laptop, call a webhook and welcome the employee on their first day.',
     [('object_create', 'Create onboarding tasks'), ('next_activity', 'Ask IT for a laptop'),
      ('webhook', 'Notify the onboarding service'), ('wait', 'Wait until the first day'),
      ('mail_post', 'Send a welcome email')]),
    ('stock', 'Daily low-stock check', 'Inventory', 'Scheduled', 'product.product', 'schedule',
     'Create a draft request for quotation for low stock. Ask for approval above your limit.',
     [('condition', 'Below minimum stock'), ('object_create', 'Create draft request for quotation'),
      ('branch', 'Above the approval limit?'), ('approval', 'Review the purchase request'),
      ('mail_post', 'Notify the buyer')]),
    ('orders', 'Send confirmed orders to another system', 'Sales', 'Integrations', 'sale.order', 'stage',
     'Send a confirmed order to your logistics endpoint and record the outcome.',
     [('webhook', 'Send order to logistics'), ('object_write', 'Mark order as sent')]),
    ('won', 'Won deal starts a project', 'CRM', 'Create records', 'crm.lead', 'stage',
     'Create a project, add the customer as a follower and notify the team.',
     [('object_create', 'Create project'), ('followers', 'Add the customer as a follower'),
      ('mail_post', 'Notify the team')]),
    ('quotation', 'Quotation follow-up', 'Sales', 'Reminders', 'sale.order', 'date',
     'Remind the salesperson and email the customer if a quotation is not confirmed in five days.',
     [('condition', 'Quotation is not confirmed'), ('next_activity', 'Remind the salesperson'),
      ('mail_post', 'Email the customer')]),
    ('applicants', 'Applicant stage emails', 'Recruitment', 'Data updates', 'hr.applicant', 'stage',
     'Send the right email and set the interviewer when an applicant changes stage.',
     [('mail_post', 'Email the applicant'), ('object_write', 'Set the interviewer')]),
    ('expiry', 'Contract and document expiry', 'Employees', 'Scheduled', 'hr.employee', 'date',
     'Remind HR before an employment document expires.',
     [('next_activity', 'Remind HR'), ('mail_post', 'Notify the employee')]),
    ('purchase', 'Purchase order approval above a limit', 'Purchase', 'Approvals', 'purchase.order', 'manual',
     'Review purchases above your limit, then confirm the order through its Odoo action.',
     [('condition', 'Above the approval limit'), ('approval', 'Purchase manager approves'),
      ('code', 'Confirm the purchase order'), ('mail_post', 'Notify the buyer')]),
    ('expenses', 'Expense report approval', 'Expenses', 'Approvals', 'hr.expense', 'manual',
     'Ask the configured approvers to review the expense, then notify its owner.',
     [('approval', 'Review the expense'), ('mail_post', 'Notify the employee')]),
]


def catalog():
    return [dict(key=r[0], name=r[1], app=r[2], category=r[3], model=r[4],
                 trigger=r[5], description=r[6], blocks=[s[1] for s in r[7]])
            for r in RECIPES]


def create_template(model, key):
    recipe = next((r for r in RECIPES if r[0] == key), None)
    if not recipe:
        raise UserError(_('Choose an existing workflow template.'))
    _key, name, _app, _kind, model_name, trigger, description, steps = recipe
    target = model.env['ir.model']._get(model_name)
    if not target:
        raise UserError(_('Install the %s application before using this template.', recipe[2]))
    workflow = model.create({'name': name, 'description': description,
                             'model_id': target.id, 'trigger': trigger})
    created = model.env['workflow.step']
    for index, (kind, label) in enumerate(steps):
        logic = kind in ('condition', 'branch', 'wait', 'approval')
        created |= model.env['workflow.step'].create({
            'workflow_id': workflow.id, 'name': label, 'sequence': index * 10,
            'kind': kind if logic else 'action', 'action_type': 'object_write' if logic else kind,
            'wait_hours': 168 if key == 'invoices' and index == 2 else
                          384 if key == 'invoices' and index == 6 else 24,
        })
    if key == 'invoices':
        workflow.write({'date_field_id': model.env['ir.model.fields']._get(model_name, 'invoice_date_due').id,
                        'offset_days': 7, 'domain': "[('move_type', '=', 'out_invoice')]"})
        created[0].domain = "[('state', '=', 'posted'), ('payment_state', '!=', 'paid')]"
        created[3].write({'domain': "[('payment_state', '=', 'paid')]", 'false_id': created[5].id})
        created[4].end = True
    elif key == 'onboarding':
        created[3].wait_date_id = model.env['ir.model.fields']._get('hr.employee', 'contract_date_start')
    elif key == 'leads':
        created[4].false_id = created[6]
        created[5].end = True
    elif key == 'stock':
        created[2].false_id = created[4]
    elif trigger == 'stage':
        field = 'stage_id' if model_name in ('crm.lead', 'hr.applicant') else 'state'
        workflow.trigger_field_id = model.env['ir.model.fields']._get(model_name, field)
    return workflow
