{
    'name': 'Marketing: research desk',
    'version': '20.0.1.0.0',
    'category': 'Marketing',
    'summary': 'Ask a research question; the marketing assistant searches the web and our data, with sources',
    'description': 'A marketing person asks a research question in the Marketing assistant\'s chat (Research on, or '
                   '/research); the Marketing '
                   'assistant searches the public web (when web search is on for its Hermes profile) and reads our '
                   'data (campaigns, results by channel, market changes), and answers with numbered sources. Lines '
                   'of an answer can be saved as market changes on the brand, or the answer turned into a suggested '
                   'campaign. Nothing is sent or published.',
    'author': 'metric.io',
    'depends': ['marketing_intel_ai', 'marketing_intel_team', 'marketing_intel_tracking', 'ai_discuss'],
    'data': [
        'security/ir.access.csv',
        'views/research_views.xml',
    ],
    'demo': [
        'demo/research_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'marketing_intel_research/static/src/**/*',
        ],
        'web.assets_unit_tests': [
            'marketing_intel_research/static/tests/**/*',
        ],
    },
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
