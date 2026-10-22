{
    'name': 'Contacts: social and chat channels',
    'version': '20.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': "Show each contact's social profiles and Omnichannel chats in Contacts",
    'description': 'Adds platform tags (WhatsApp, Telegram, Instagram, LinkedIn…) to contact lists and cards, a '
                   'Social & chat section on the contact form, and a Customers filter. Chats linked to a contact in '
                   'Omnichannel appear automatically; social profiles can be added by hand.',
    'author': 'metric.io',
    'depends': ['contacts', 'account', 'hr', 'omni_channel'],
    'data': [
        'security/security.xml',
        'views/partner_views.xml',
    ],
    'assets': {'web.assets_backend': ['omni_contacts/static/src/partner_channels.scss']},
    'post_init_hook': '_post_init_hook',
    'auto_install': True,
    'license': 'LGPL-3',
    'installable': True,
}
