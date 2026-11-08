{
    'name': 'Workflows: AI drafting',
    'version': '20.0.1.1.0',
    'category': 'Productivity',
    'summary': 'Draft a workflow with an AI Agent, and ask an agent from a workflow step',
    'depends': ['workflow_center', 'ai_agent'],
    'data': ['views/workflow_views.xml', 'views/step_views.xml'],
    'assets': {
        'web.assets_backend': ['workflow_ai/static/src/workflow_ai.js', 'workflow_ai/static/src/workflow_ai.scss'],
    },
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
