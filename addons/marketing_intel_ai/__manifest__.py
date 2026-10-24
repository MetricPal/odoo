{
    'name': 'Marketing Intelligence: AI analysis',
    'version': '20.0.1.0.0',
    'category': 'Marketing',
    'summary': 'AI-written analysis, SWOT, campaign options and risks for each research run',
    'description': 'An AI agent reads the brand profile, goals and the evidence of a research run and proposes an '
                   'analysis, a SWOT, campaign options and risks as validated structured output. Nothing is executed: '
                   'people review the options and choose one.',
    'author': 'metric.io',
    'depends': ['marketing_intel', 'ai_agent'],
    'data': [
        'views/brief_views.xml',
    ],
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
