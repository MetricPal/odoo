{
    'name': 'Marketing: AI assistant',
    'version': '20.0.1.1.0',
    'category': 'Marketing',
    'summary': 'AI suggests campaigns, writes every channel and sends them for review; you approve',
    'description': 'An AI agent suggests campaigns, an analysis and risks, and can run a campaign: it fills the brief, writes each channel and sends it for review. Answers are validated; nothing goes out before a person approves.',
    'author': 'metric.io',
    'depends': ['marketing_intel', 'marketing_intel_plan', 'ai_agent'],
    'data': [
        'views/brief_views.xml',
        'views/autopilot_views.xml',
    ],
    'auto_install': True,
    'icon': '/marketing_intel_ai/static/description/icon.svg',
    'license': 'LGPL-3',
    'installable': True,
}
