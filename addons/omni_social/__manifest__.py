{'name': 'Social',
 'version': '20.0.2.0.0',
 'summary': 'Review incoming social activity and publish approved content',
 'category': 'Marketing/Social Marketing',
 'author': 'metric.io',
 'license': 'LGPL-3',
 'depends': ['omni_channel'],
 'external_dependencies': {'python': ['requests', 'cryptography'], 'bin': ['ffprobe']},
 'data': ['security/access.xml', 'security/ir.access.csv', 'views/social.xml'],
 'assets': {'web.assets_backend': ['omni_social/static/src/credentials.js',
                                   'omni_social/static/src/credentials.xml']},
 'icon': '/omni_social/static/description/icon.svg',
 'application': True,
 'installable': True,
 'description': 'Read incoming social activity, review exact content in Approval Center, then '
                'publish or reply from the correct account. Includes manual sync and separate '
                'private-message agreement controls.'}
