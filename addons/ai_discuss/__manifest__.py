{
    'name': 'AI Agent: Discuss and chatter',
    'version': '20.0.1.1.0',
    'category': 'Productivity',
    'summary': 'Chat with AI assistants in Discuss and ask them from a record\'s chatter',
    'description': 'Each AI agent gets its own chat partner, so people can find and ask the assistants they may use '
                   'where they already talk. OdooBot stays the system voice (ADR 0013).',
    'depends': ['ai_agent', 'mail'],
    'data': ['security/ir.access.csv', 'views/route_ask_views.xml'],
    'assets': {
        'web.assets_backend': ['ai_discuss/static/src/**/*'],
        'web.assets_unit_tests': ['ai_discuss/static/tests/**/*'],
    },
    'post_init_hook': '_post_init',
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
