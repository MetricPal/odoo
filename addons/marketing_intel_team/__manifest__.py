{
    'name': 'Marketing: team, roles and dashboards',
    'version': '20.0.1.2.0',
    'category': 'Marketing',
    'summary': 'Head of department, Senior and Junior roles, the senior review, and a control panel per role',
    'description': 'Marketing roles (ADR 0016): juniors send their work to a senior review, seniors release within '
                   'limits set by the head of department, above them the head of department approves. The control '
                   'panel opens on My day (junior), My team (senior) or Department (head of department), with '
                   'Explain this, a setup checklist and the health of the assistant and automations.',
    'author': 'metric.io',
    'depends': ['marketing_intel_work', 'marketing_intel_flow', 'hr', 'ai_agent'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'data/approval.xml',
        'views/team_views.xml',
        'views/plan_views.xml',
        'wizard/senior_decision_views.xml',
    ],
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
