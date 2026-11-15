{
    'name': 'Marketing: design studio',
    'version': '20.0.1.0.0',
    'category': 'Marketing',
    'summary': 'Posts, carousels, stories, posters and email headers from templates, drawn with the brand kit',
    'description': 'Design studio, step 3a: a brand kit on the brand (logos, colours, fonts), designs made by '
                   'filling a template (square and portrait post, story, carousel, poster, email header), AI '
                   'pictures and text suggestions from the Marketing assistant, export as PNG or PDF, and use in a '
                   'social post, an email or a proof. Nothing is sent or published from a design.',
    'author': 'metric.io',
    'depends': ['marketing_intel_research', 'marketing_intel_writing', 'marketing_intel_work', 'mass_mailing',
                'omni_social'],
    'data': [
        'security/ir.access.csv',
        'data/templates.xml',
        'views/design_views.xml',
    ],
    'demo': [
        'demo/design_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'marketing_intel_design/static/src/**/*',
        ],
        'web.assets_unit_tests': [
            'marketing_intel_design/static/tests/**/*',
        ],
    },
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
