{
    'name': 'Social Marketing: campaign tracking',
    'version': '20.0.1.0.0',
    'category': 'Marketing/Social Marketing',
    'summary': 'Tie Social campaigns and posts to UTM campaigns and track their links',
    'description': 'Each Social campaign gets a UTM campaign (the one Link Tracker, CRM, Sales and Email '
                   'Marketing use). Links in a post become tracked short links when it is submitted, so '
                   'the approver reviews the exact text and every link destination, and clicks, leads and '
                   'sales are reported per campaign, platform (source) and Social Media (medium).',
    'author': 'metric.io',
    'depends': ['omni_social', 'link_tracker'],
    'data': ['views/social_utm_views.xml'],
    'post_init_hook': '_post_init_hook',
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
