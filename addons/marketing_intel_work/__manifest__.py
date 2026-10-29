{
    'name': 'Marketing: work management',
    'version': '20.0.1.0.0',
    'category': 'Marketing',
    'summary': 'Campaign tasks (Project), request intake, proofs with versions and compare, team workload',
    'description': 'Each campaign gets its task list in Project, with owners and due dates; templates and copies '
                   'carry their tasks with the same timing. Anyone can file a marketing request that becomes a '
                   'campaign brief. Creatives and copy go through proofs: versions, side-by-side compare, approve or '
                   'request changes; an approved proof fills the channel draft, and a campaign is not sent for review '
                   'while a proof is still open. A workload report shows each person\'s tasks, campaigns and reviews.',
    'author': 'metric.io',
    'depends': ['marketing_intel_plan', 'project', 'project_gantt_view'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'data/stages.xml',
        'views/work_views.xml',
    ],
    'auto_install': True,
    'icon': '/marketing_intel_work/static/description/icon.svg',
    'license': 'LGPL-3',
    'installable': True,
}
