"""Synthetic HTTP only; no tokens, recipients or messages from a real account."""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

package = types.ModuleType('_wa_diagnostic_test')
package.__path__ = [str(Path(__file__).resolve().parents[1] / 'providers')]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location(package.__name__ + '.test_message', Path(package.__path__[0]) / 'test_message.py')
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


def transport(data, status=200):
    session = MagicMock()
    session.__enter__.return_value = session
    response = MagicMock(status_code=status)
    response.__enter__.return_value = response
    response.iter_content.return_value = [json.dumps(data).encode()]
    session.post.return_value = response
    return session


def success(recipient='60123456789'):
    return {'messaging_product':'whatsapp', 'contacts':[{'wa_id':recipient}], 'messages':[{'id':'wamid.synthetic'}]}


class TestDiagnostic(unittest.TestCase):
    def send(self, session, **changes):
        args = dict(version='v99.0', phone='12345', token='synthetic-only', recipient='60123456789')
        args.update(changes)
        return diagnostic.send_test(**args, session_factory=lambda:session)

    def test_exact_fixed_message_bearer_fixed_host_and_no_retries(self):
        session = transport(success())
        self.assertEqual(self.send(session), ('accepted','wamid.synthetic'))
        session.post.assert_called_once()
        args, options = session.post.call_args
        self.assertEqual(args[0], 'https://graph.facebook.com/v99.0/12345/messages')
        self.assertNotIn('synthetic-only', args[0])
        self.assertEqual(options['headers'], {'Authorization':'Bearer synthetic-only'})
        self.assertEqual(options['json'], {'messaging_product':'whatsapp','recipient_type':'individual',
            'to':'60123456789','type':'text','text':{'body':diagnostic.TEST_MESSAGE,'preview_url':False}})
        self.assertFalse(options['allow_redirects'])
        self.assertTrue(options['verify'])
        self.assertFalse(session.trust_env)

    def test_timeout_after_send_is_unknown_and_never_retried(self):
        session = transport(success())
        session.post.side_effect = TimeoutError('sensitive provider detail')
        self.assertEqual(self.send(session), ('unknown','unconfirmed'))
        session.post.assert_called_once()

    def test_confirmed_rejection_is_safe_failure_without_provider_details(self):
        for status in (400,401,403,404,429):
            session = transport({'error':{'code':190,'message':'synthetic-only'}},status)
            self.assertEqual(self.send(session), ('failed','rejected'))
            session.post.assert_called_once()

    def test_5xx_redirect_malformed_rejection_or_wrong_recipient_are_unknown(self):
        for data,status in ((success(),500),(success(),302),({'error':{'message':'token'}},400),
                            (success('999'),200),({'messaging_product':'whatsapp','messages':[{'id':'wamid.test'}]},200)):
            with self.subTest(status=status,data=data):
                self.assertEqual(self.send(transport(data,status)), ('unknown','unconfirmed'))

    def test_response_size_and_json_are_bounded(self):
        session = transport(success())
        for raw in (b'x'*16385, b'not-json'):
            session.post.return_value.iter_content.return_value = [raw]
            self.assertEqual(self.send(session), ('unknown','unconfirmed'))

    def test_invalid_inputs_fail_before_any_network(self):
        session = transport(success())
        for change in ({'version':None},{'phone':'../other'},{'recipient':'https://evil.test'},
                       {'token':'bad\nheader'},{'token':'x'*8193}):
            with self.assertRaises(ValueError):
                self.send(session,**change)
        session.post.assert_not_called()

    def test_slow_stream_becomes_unknown_without_another_post(self):
        session = transport(success())
        with patch.object(diagnostic.time, 'monotonic', side_effect=[0, 26]):
            self.assertEqual(self.send(session), ('unknown','unconfirmed'))
        session.post.assert_called_once()
