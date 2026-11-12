{
    'name': 'Marketing: assistant jobs',
    'version': '20.0.1.0.0',
    'category': 'Marketing',
    'summary': 'Recurring work the marketing assistant does, with its health',
    'description': 'Ready-made jobs the Marketing assistant runs on a schedule and hands to an owner: weekly social '
                   'post drafts, comment reply drafts, a weekly newsletter draft, new leads summaries, a weekly '
                   'performance summary, campaigns at risk, a competitor watch, a monthly department report, a budget '
                   'burn alert and a team workload alert. Jobs only prepare: drafts, notes and to-dos, never a send '
                   'or a publish. Jobs and health shows each job\'s last and next run, success, AI use and health '
                   '(Healthy, Failing, Waiting for a person, Paused).',
    'author': 'metric.io',
    'depends': ['marketing_intel_tracking', 'marketing_intel_team', 'marketing_intel_ai', 'omni_social', 'mass_mailing'],
    'data': [
        'security/ir.access.csv',
        'data/jobs.xml',
        'data/cron.xml',
        'views/job_views.xml',
    ],
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
