import importlib.util
import io
import json
import os
from pathlib import Path
import smtplib
import tempfile
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / 'notify-image-build.py'
SPEC = importlib.util.spec_from_file_location('notify_image_build', SCRIPT)
notifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notifier)


class BuildNotificationTests(unittest.TestCase):
    def setUp(self):
        self.context = {'repository': 'jumpserver-east/luna', 'branch': 'ferror@v4.10.19-lts',
                        'ref': 'a' * 40, 'actor': 'pusher', 'event': 'push'}
        self.env = {
            'SMTP_HOST': 'smtp.example.com', 'SMTP_PORT': '587',
            'SMTP_USERNAME': 'builds', 'SMTP_PASSWORD': 'test-only-password',
            'SMTP_FROM': 'builds@example.com', 'BUILD_RESULT': 'success',
            'BUILD_IMAGE': 'ghcr.io/jumpserver-east/web:ferror-test',
            'GITHUB_REPOSITORY': 'jumpserver-east/docker-web', 'GITHUB_RUN_ID': '1234',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_ACTOR': 'dispatch-bot',
            'GITHUB_TRIGGERING_ACTOR': 'dispatch-bot',
            'ORIGIN_CONTEXT': json.dumps(self.context),
        }

    def test_always_uses_workflow_actor(self):
        api = Mock(return_value={'email': 'actor@example.com'})
        self.assertEqual(notifier.recipient(self.context, {}, {}, 'token', api), 'actor@example.com')
        self.assertEqual(api.call_args.args[0], 'users/pusher')

    def test_manual_build_uses_original_actor_mapping(self):
        context = {**self.context, 'event': 'workflow_dispatch', 'actor': 'Nickyang00'}
        api = Mock()
        self.assertEqual(notifier.recipient(context, {}, {'nickyang00': 'nick@example.com'}, 'token', api),
                         'nick@example.com')
        api.assert_not_called()

    def test_noreply_uses_mapping_and_is_never_a_recipient(self):
        api = Mock(return_value={'email': '123+pusher@users.noreply.github.com'})
        self.assertEqual(notifier.recipient(self.context, {}, {'pusher': 'real@example.com'}, 'token', api),
                         'real@example.com')
        self.assertEqual(notifier.recipient(self.context, {}, {}, 'token', api), '')

    def test_unavailable_api_does_not_use_commit_payload(self):
        api = Mock(return_value={})
        event = {'head_commit': {'id': 'a' * 40, 'author': {'email': 'author@example.com'}}}
        self.assertEqual(notifier.recipient(self.context, event, {}, '', api), '')

    def test_unknown_actor_does_not_fall_back_to_another_user(self):
        self.assertEqual(notifier.recipient({**self.context, 'actor': 'unknown'}, {},
                                            {'pusher': 'pusher@example.com'}, '',
                                            Mock(return_value={})), '')

    def test_private_email_requires_actor_mapping(self):
        api = Mock(return_value={'email': None})
        self.assertEqual(notifier.recipient(self.context, {}, {}, 'token', api), '')
        self.assertEqual(notifier.recipient(self.context, {}, {'PUSHER': 'actor@example.com'},
                                            'token', api), 'actor@example.com')

    def test_invalid_mapping_falls_back_to_same_actors_public_email(self):
        api = Mock(return_value={'email': 'actor@example.com'})
        self.assertEqual(notifier.recipient(self.context, {}, {'pusher': 'not-an-address'},
                                            'token', api), 'actor@example.com')
        self.assertEqual(api.call_args.args[0], 'users/pusher')

    def test_missing_actor_does_not_query_github(self):
        api = Mock()
        self.assertEqual(notifier.recipient({**self.context, 'actor': ''}, {}, {}, 'token', api), '')
        api.assert_not_called()

    def test_forwarded_context_preserves_luna_origin(self):
        self.assertEqual(notifier.origin(self.env, {}), self.context)

    def test_workflow_run_context_uses_upstream_actor_and_event(self):
        env = {**self.env, 'ORIGIN_CONTEXT': '', 'GITHUB_EVENT_NAME': 'workflow_run',
               'SOURCE_REPOSITORY': 'jumpserver-east/jumpserver', 'SOURCE_BRANCH': 'customer@v5',
               'SOURCE_REF': 'b' * 40}
        event = {'workflow_run': {'event': 'push', 'actor': {'login': 'original'}}}
        context = notifier.origin(env, event)
        self.assertEqual(context['actor'], 'original')
        self.assertEqual(context['event'], 'push')
        self.assertEqual(context['ref'], 'b' * 40)

    def test_origin_uses_explicit_notification_actor_and_event(self):
        env = {**self.env, 'ORIGIN_CONTEXT': '', 'GITHUB_EVENT_NAME': 'push',
               'NOTIFICATION_ACTOR': 'workflow-user', 'NOTIFICATION_EVENT': 'workflow_dispatch'}
        context = notifier.origin(env, {})
        self.assertEqual(context['actor'], 'workflow-user')
        self.assertEqual(context['event'], 'workflow_dispatch')

    def test_direct_run_uses_triggering_actor_when_no_explicit_actor(self):
        env = {**self.env, 'ORIGIN_CONTEXT': '', 'GITHUB_TRIGGERING_ACTOR': 'operator'}
        self.assertEqual(notifier.origin(env, {})['actor'], 'operator')

    def test_direct_run_falls_back_to_github_actor(self):
        env = {**self.env, 'ORIGIN_CONTEXT': '', 'GITHUB_TRIGGERING_ACTOR': '',
               'GITHUB_ACTOR': 'operator'}
        self.assertEqual(notifier.origin(env, {})['actor'], 'operator')

    def test_rerun_notifies_rerun_operator_and_preserves_source(self):
        for forwarded in ('', self.env['ORIGIN_CONTEXT']):
            with self.subTest(forwarded=bool(forwarded)):
                env = {**self.env, 'GITHUB_RUN_ATTEMPT': '2', 'ORIGIN_CONTEXT': forwarded,
                       'NOTIFICATION_ACTOR': 'rerun-operator'}
                context = notifier.origin(env, {})
                self.assertEqual(context['actor'], 'rerun-operator')
                if forwarded:
                    self.assertEqual(context['repository'], self.context['repository'])
                    self.assertEqual(context['ref'], self.context['ref'])

    def test_workflow_run_uses_origin_rerun_actor_until_build_is_rerun(self):
        env = {**self.env, 'ORIGIN_CONTEXT': '', 'NOTIFICATION_EVENT': 'workflow_run',
               'NOTIFICATION_ACTOR': 'build-operator'}
        event = {'workflow_run': {'event': 'push', 'actor': {'login': 'first-operator'},
                                  'triggering_actor': {'login': 'origin-rerun-operator'}}}
        self.assertEqual(notifier.origin(env, event)['actor'], 'origin-rerun-operator')
        self.assertEqual(notifier.origin({**env, 'GITHUB_RUN_ATTEMPT': '2'}, event)['actor'],
                         'build-operator')

    def test_external_repository_and_header_injection_are_rejected(self):
        env = {**self.env, 'ORIGIN_CONTEXT': json.dumps({**self.context, 'repository': 'other/repo'})}
        with self.assertRaises(ValueError):
            notifier.origin(env, {})
        for value in ('person@example.com\nBcc: other@example.com', 'a@example.com,b@example.com',
                      '123+author@users.noreply.github.com', None):
            self.assertEqual(notifier.address(value), '')

    def test_result_email_includes_all_sources_image_and_log_link(self):
        sources = {
            'jumpserver-east/lina': {'branch': 'v4.10.19-lts', 'ref': 'v4.10.19-lts'},
            'jumpserver-east/luna': {'branch': self.context['branch'], 'ref': 'a' * 40},
            'jumpserver-east/docker-web': {'branch': 'dev', 'ref': 'dev'},
        }
        for result, label in notifier.RESULTS.items():
            with self.subTest(result=result):
                mail = notifier.message({**self.env, 'BUILD_RESULT': result}, self.context,
                                        sources, 'author@example.com')
                self.assertIn(label, str(mail['Subject']))
                body = mail.get_content()
                for expected in ('ferror@v4.10.19-lts', 'v4.10.19-lts', 'a' * 40, 'dev',
                                 'ghcr.io/jumpserver-east/web:ferror-test',
                                 'https://github.com/jumpserver-east/docker-web/actions/runs/1234'):
                    self.assertIn(expected, body)

    def test_dispatch_failure_is_not_reported_as_image_build_result(self):
        mail = notifier.message({**self.env, 'BUILD_RESULT': 'failure', 'NOTIFICATION_PHASE': 'dispatch'},
                                self.context, {}, 'author@example.com')
        self.assertIn('构建请求提交失败', str(mail['Subject']))
        self.assertIn('构建未完成源码解析', mail.get_content())

    def test_smtp_starttls_happens_before_login_and_send(self):
        mail = notifier.message(self.env, self.context, {}, 'author@example.com')
        with patch.object(notifier.smtplib, 'SMTP') as smtp:
            notifier.deliver(mail, self.env)
        client = smtp.return_value
        names = [call[0] for call in client.method_calls]
        self.assertEqual(names, ['ehlo', 'starttls', 'ehlo', 'login', 'send_message'])
        client.send_message.assert_called_once_with(mail)

    def test_smtp_465_uses_implicit_tls(self):
        mail = notifier.message(self.env, self.context, {}, 'author@example.com')
        with patch.object(notifier.smtplib, 'SMTP_SSL') as smtp, patch.object(notifier.smtplib, 'SMTP') as plain:
            notifier.deliver(mail, {**self.env, 'SMTP_PORT': '465'})
        plain.assert_not_called()
        smtp.return_value.starttls.assert_not_called()

    def test_missing_configuration_skips_delivery_with_warning(self):
        with patch.dict(os.environ, {'BUILD_RESULT': 'success'}, clear=True), \
                patch('sys.stdout', io.StringIO()) as output, patch.object(notifier, 'deliver') as send:
            self.assertEqual(notifier.main(), 0)
        send.assert_not_called()
        self.assertIn('::warning::邮件未发送', output.getvalue())

    def test_end_to_end_failure_report_sends_one_mail_without_printing_address(self):
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / 'event.json'
            event.write_text('{}')
            env = {**self.env, 'GITHUB_EVENT_PATH': str(event), 'BUILD_RESULT': 'failure'}
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(notifier, 'recipient', return_value='author@example.com'), \
                    patch.object(notifier, 'deliver') as send, patch('sys.stdout', io.StringIO()) as output:
                self.assertEqual(notifier.main(), 0)
                send.assert_called_once()
                self.assertEqual(send.call_args.args[0]['To'], 'author@example.com')
                self.assertIn('失败', str(send.call_args.args[0]['Subject']))
                self.assertNotIn('author@example.com', output.getvalue())
                send.side_effect = smtplib.SMTPAuthenticationError(535, b'test-only-password')
                self.assertEqual(notifier.main(), 1)
                self.assertNotIn('test-only-password', output.getvalue())


if __name__ == '__main__':
    unittest.main(verbosity=2)
