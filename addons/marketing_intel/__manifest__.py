{
    'name': 'Marketing Intelligence',
    'version': '20.0.1.1.0',
    'category': 'Marketing',
    'summary': 'Approved sources and competitors, recurring research, change detection and weekly briefs',
    'description': 'Phase 1 of intelligent marketing: describe your brand and goals, propose competitors and '
                   'sources of truth for approval, collect them on a schedule (web pages and RSS feeds, HTTPS '
                   'only, robots.txt respected), keep dated evidence, detect what changed and get a weekly brief '
                   'as a Report Studio report. Each run can carry an analysis with SWOT, campaign options '
                   'and a risk register (written by people or, with marketing_intel_ai, proposed by an AI agent).',
    'author': 'metric.io',
    'depends': ['mail', 'report_studio'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'views/intel_views.xml',
        'data/cron.xml',
        'data/channels.xml',
    ],
    'application': True,
    'license': 'LGPL-3',
    'installable': True,
}
