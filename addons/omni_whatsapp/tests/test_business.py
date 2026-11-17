"""Templates and template messages with fake HTTP; never contact Meta."""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROVIDERS = Path(__file__).resolve().parents[1] / 'providers'
package = types.ModuleType('_wa_business_test')
package.__path__ = [str(PROVIDERS)]
sys.modules[package.__name__] = package
for name in ('connection', 'business'):
    spec = importlib.util.spec_from_file_location(f'{package.__name__}.{name}', PROVIDERS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
business = sys.modules[package.__name__ + '.business']

TOKEN, WABA, PHONE, TO = 'synthetic-only', '123456789', '234567890', '60123456789'
TEMPLATE = {'name': 'spring_offer_7', 'language': 'en', 'body': ['Sara']}


def http(data, status=200):
    session = MagicMock()
    session.__enter__.return_value = session
    response = MagicMock(status_code=status)
    response.__enter__.return_value = response
    response.iter_content.return_value = [json.dumps(data).encode()]
    session.post.return_value = session.get.return_value = response
    return session


def error(code, **extra):
    return {'error': dict({'code': code, 'message': 'internal detail'}, **extra)}


class TestBusiness(unittest.TestCase):
    def run_with(self, session, function, *args, **kwargs):
        with patch.object(business, '_session', lambda: session):
            return function(*args, **kwargs)

    def send(self, session, template=TEMPLATE, recipient=TO):
        return self.run_with(session, business.send_template, 'v99.0', PHONE, TOKEN, recipient, template)

    def test_one_template_message_exact_request(self):
        session = http({'messaging_product': 'whatsapp', 'contacts': [{'wa_id': TO}],
                        'messages': [{'id': 'wamid.synthetic'}]})
        self.assertEqual(self.send(session), ('accepted', 'wamid.synthetic', 0))
        (url,), options = session.post.call_args
        self.assertEqual(url, 'https://graph.facebook.com/v99.0/234567890/messages')
        self.assertEqual(options['headers'], {'Authorization': 'Bearer ' + TOKEN})
        self.assertEqual(options['json'], {
            'messaging_product': 'whatsapp', 'recipient_type': 'individual', 'to': TO, 'type': 'template',
            'template': {'name': 'spring_offer_7', 'language': {'code': 'en'}, 'components': [
                {'type': 'body', 'parameters': [{'type': 'text', 'text': 'Sara'}]}]}})
        self.assertIs(options['allow_redirects'], False)
        self.assertIs(options['verify'], True)
        self.assertEqual(session.post.call_count, 1)
        self.assertIs(session.trust_env, False)

    def test_nothing_is_sent_for_input_that_is_not_a_plain_template(self):
        for template in ({**TEMPLATE, 'name': 'Spring Offer'}, {**TEMPLATE, 'language': 'english'},
                         {**TEMPLATE, 'body': ['two\nlines']}, {**TEMPLATE, 'body': ['']},
                         {**TEMPLATE, 'components': []}, 'spring_offer_7'):
            session = http({})
            self.assertEqual(self.send(session, template), ('not_sent', 'configuration', 0))
            session.post.assert_not_called()
        session = http({})
        self.assertEqual(self.send(session, recipient='+60123456789')[0], 'not_sent')
        session.post.assert_not_called()

    def test_refusals_are_told_apart(self):
        cases = [(429, 4, 'rate_limited'), (400, 130429, 'rate_limited'), (400, 131049, 'daily_limit'),
                 (401, 190, 'unauthorized'), (400, 131026, 'invalid_recipient'), (400, 132001, 'template'),
                 (404, 132015, 'template')]
        for status, code, expected in cases:
            with self.subTest(code=code):
                outcome, detail, _delay = self.send(http(error(code), status))
                self.assertEqual((outcome, detail), ('not_sent', expected))

    def test_an_unclear_answer_is_never_reported_as_not_sent(self):
        self.assertEqual(self.send(http({'unexpected': True}))[0], 'unknown')
        self.assertEqual(self.send(http(error(1), 500))[0], 'unknown')
        self.assertEqual(self.send(http({'messaging_product': 'whatsapp', 'messages': []}))[0], 'unknown')
        session = http({})
        session.post.side_effect = TimeoutError
        self.assertEqual(self.send(session)[0], 'unknown')

    def test_template_components(self):
        components = business.template_components(
            body='Hi {{1}}, welcome {{2}}.', example=['Sara', 'Sara Lim'], header='Spring', footer='Reply STOP',
            button_label='Shop now', button_url='https://shop.example/spring')
        self.assertEqual(components, [
            {'type': 'HEADER', 'format': 'TEXT', 'text': 'Spring'},
            {'type': 'BODY', 'text': 'Hi {{1}}, welcome {{2}}.', 'example': {'body_text': [['Sara', 'Sara Lim']]}},
            {'type': 'FOOTER', 'text': 'Reply STOP'},
            {'type': 'BUTTONS', 'buttons': [{'type': 'URL', 'text': 'Shop now', 'url': 'https://shop.example/spring'}]},
        ])
        self.assertEqual(business.template_components(body='No fields here.', example=[]),
                         [{'type': 'BODY', 'text': 'No fields here.'}])
        for code, arguments in (('fields', dict(body='Hi {{2}}.', example=['Sara'])),
                                ('fields', dict(body='Hi {{1}}.', example=[])),
                                ('header', dict(body='Hi.', example=[], header='x' * 61)),
                                ('button', dict(body='Hi.', example=[], button_label='Go', button_url='http://x'))):
            with self.assertRaisesRegex(business.BusinessRejected, code):
                business.template_components(**arguments)

    def submit(self, session):
        return self.run_with(session, business.submit_template, 'v99.0', WABA, TOKEN, name='spring_offer_7',
                             language='en', components=[{'type': 'BODY', 'text': 'Hi.'}])

    def test_submit_a_marketing_template(self):
        session = http({'id': '900100', 'status': 'PENDING', 'category': 'MARKETING'})
        self.assertEqual(self.submit(session), {'id': '900100', 'status': 'review'})
        (url,), options = session.post.call_args
        self.assertEqual(url, 'https://graph.facebook.com/v99.0/123456789/message_templates')
        self.assertEqual(options['json']['category'], 'MARKETING')
        self.assertEqual(session.post.call_count, 1)
        with self.assertRaises(business.BusinessRejected) as refused:
            self.submit(http(error(100, error_user_msg='There is already English content for this template.'), 400))
        self.assertEqual((str(refused.exception), refused.exception.detail),
                         ('refused', 'There is already English content for this template.'))
        with self.assertRaisesRegex(business.BusinessRejected, 'credentials'):
            self.submit(http(error(190), 401))
        with self.assertRaisesRegex(business.BusinessRejected, 'unknown'):
            self.submit(http({'surprise': 1}))

    def test_read_templates_follows_cursors_on_the_fixed_address_only(self):
        first = {'data': [{'id': '1', 'name': 'spring_offer_7', 'language': 'en', 'status': 'APPROVED'},
                          {'id': '2', 'name': 'old', 'language': 'ms', 'status': 'REJECTED',
                           'rejected_reason': 'INVALID_FORMAT'},
                          {'id': '3', 'name': 'later', 'language': 'en', 'status': 'SOMETHING_NEW'}],
                 'paging': {'cursors': {'after': 'CURSOR'}, 'next': 'https://evil.example/next'}}
        second = {'data': [{'id': '4', 'name': 'paused_one', 'language': 'en', 'status': 'PAUSED'}]}
        session = MagicMock()
        session.__enter__.return_value = session
        responses = []
        for data in (first, second):
            response = MagicMock(status_code=200)
            response.__enter__.return_value = response
            response.iter_content.return_value = [json.dumps(data).encode()]
            responses.append(response)
        session.get.side_effect = responses
        found = self.run_with(session, business.list_templates, 'v99.0', WABA, TOKEN)
        self.assertEqual([(item['name'], item['status'], item['reason']) for item in found], [
            ('spring_offer_7', 'approved', ''), ('old', 'rejected', 'INVALID_FORMAT'), ('paused_one', 'paused', '')])
        urls = [call.args[0] for call in session.get.call_args_list]
        self.assertTrue(all(url.startswith('https://graph.facebook.com/v99.0/123456789/message_templates?')
                            for url in urls))
        self.assertIn('after=CURSOR', urls[1])
        with self.assertRaisesRegex(business.BusinessRejected, 'credentials'):
            self.run_with(http({}, 403), business.list_templates, 'v99.0', WABA, TOKEN)


if __name__ == '__main__':
    unittest.main()
