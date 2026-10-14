{
    'name': 'AI Agent',
    'version': '20.0.1.3.1',
    'category': 'Productivity',
    'summary': 'Work with supervised Hermes assistants using permitted business context',
    'description': 'Configure supervised Hermes assistants, choose permitted knowledge and '
                   'business data, ask questions, prepare drafts and inspect immutable run history. '
                   'This initial release supports internal read-and-draft assistance; business '
                   'changes and external actions remain disabled.',
    'author': 'metric.io',
    'license': 'LGPL-3',
    'depends': ['mail', 'web', 'approval_center'],
    'data': ['security/security.xml', 'security/ir.access.csv',
             'data/cron.xml', 'views/agent_views.xml', 'views/configuration_views.xml',
             'views/conversation_views.xml', 'views/wizard_views.xml', 'views/model_picker_views.xml', 'views/menus.xml'],
    'assets': {'web.assets_backend': ['ai_agent/static/src/model_picker.js', 'ai_agent/static/src/model_picker.xml', 'ai_agent/static/src/model_picker.scss']},
    'icon': '/ai_agent/static/description/icon.svg',
    'application': True,
    'installable': True,
}
