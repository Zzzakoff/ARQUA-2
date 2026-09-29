from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from patch_engine.proposals import generate_response_proposal
from .models import Proposal, Scan


VALID_SPEC = b"""
openapi: 3.0.0
info:
  title: Test API
  version: 1.0.0
paths: {}
"""

SPEC_WITH_MANUAL = """
openapi: 3.0.3
info:
  title: Demo API
  version: 1.0.0
paths:
  /users:
    get:
      description: "Получить список пользователей"
      x-manual-analysis: "Проверено человеком"
      responses:
        "200":
          description: "Успешный ответ"
"""


class ScanUploadTests(TestCase):
    def test_valid_yaml_creates_scan(self):
        f = SimpleUploadedFile('api.yaml', VALID_SPEC, content_type='application/yaml')
        response = self.client.post(reverse('index'), {'specification': f})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Scan.objects.count(), 1)

    def test_invalid_extension_rejected(self):
        f = SimpleUploadedFile('api.txt', b'hello', content_type='text/plain')
        response = self.client.post(reverse('index'), {'specification': f})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Scan.objects.count(), 0)

    def test_non_openapi_yaml_rejected(self):
        f = SimpleUploadedFile('api.yaml', b'foo: bar', content_type='application/yaml')
        self.client.post(reverse('index'), {'specification': f})
        self.assertEqual(Scan.objects.count(), 0)


class ProposalEngineTests(TestCase):
    def test_manual_analytics_is_preserved(self):
        result = generate_response_proposal(
            SPEC_WITH_MANUAL, '/users', 'get', 404, 'Не найдено'
        )
        self.assertIn('Проверено человеком', result['after'])
        self.assertFalse(result['requires_manual_review'])
        self.assertEqual(result['confidence'], 'high')

    def test_missing_endpoint_fails(self):
        with self.assertRaises(ValueError):
            generate_response_proposal(SPEC_WITH_MANUAL, '/missing', 'get', 404, '')


class ReviewFlowTests(TestCase):
    def setUp(self):
        self.scan = Scan.objects.create(
            name='Review test',
            specification=SimpleUploadedFile(
                'review.yaml', SPEC_WITH_MANUAL.encode('utf-8'), content_type='application/yaml'
            ),
        )
        self.proposal = Proposal.objects.create(
            scan=self.scan,
            title='Добавить 404',
            path='/users',
            method='get',
            proposal_type='add_response',
            reason='Ответ 404 отсутствует в спецификации.',
            source_of_truth='code',
            confidence='high',
            before_text='before',
            after_text='after',
        )
        reviewer_group = Group.objects.create(name='reviewer')
        self.reviewer = User.objects.create_user(username='reviewer', password='test-pass-123')
        self.reviewer.groups.add(reviewer_group)
        self.viewer = User.objects.create_user(username='viewer', password='test-pass-123')

    def test_anonymous_cannot_accept(self):
        response = self.client.post(
            reverse('proposal_action', args=[self.proposal.id, 'accept'])
        )
        self.assertEqual(response.status_code, 302)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, 'pending')

    def test_non_reviewer_cannot_accept(self):
        self.client.login(username='viewer', password='test-pass-123')
        response = self.client.post(
            reverse('proposal_action', args=[self.proposal.id, 'accept'])
        )
        self.assertEqual(response.status_code, 403)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, 'pending')

    def test_reviewer_can_accept_by_post(self):
        self.client.login(username='reviewer', password='test-pass-123')
        response = self.client.post(
            reverse('proposal_action', args=[self.proposal.id, 'accept'])
        )
        self.assertEqual(response.status_code, 302)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, 'accepted')
        self.assertEqual(self.proposal.reviewed_by, self.reviewer)
        self.assertIsNotNone(self.proposal.reviewed_at)

    def test_get_does_not_change_status(self):
        self.client.login(username='reviewer', password='test-pass-123')
        response = self.client.get(
            reverse('proposal_action', args=[self.proposal.id, 'accept'])
        )
        self.assertEqual(response.status_code, 405)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, 'pending')

    def test_reviewer_can_open_edit_page(self):
        self.client.login(username='reviewer', password='test-pass-123')
        response = self.client.get(reverse('edit_proposal', args=[self.proposal.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Редактирование правки')

    def test_export_contains_only_accepted(self):
        accepted = Proposal.objects.create(
            scan=self.scan,
            title='Accepted proposal',
            path='/users',
            method='get',
            proposal_type='add_response',
            reason='reason',
            source_of_truth='code',
            confidence='high',
            status='accepted',
            before_text='a\n',
            after_text='b\n',
        )
        response = self.client.get(reverse('export_report', args=[self.scan.id, 'json']))
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response['Content-Disposition'])
        body = response.content.decode('utf-8')
        self.assertIn(accepted.title, body)
        self.assertNotIn(self.proposal.title, body)

    def test_reviewer_can_create_demo_proposal(self):
        self.client.login(username='reviewer', password='test-pass-123')
        response = self.client.post(reverse('scan_detail', args=[self.scan.id]), {
            'path': '/users',
            'method': 'get',
            'status_code': '404',
            'description': 'Пользователь не найден',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.scan.proposals.count(), 2)

    def test_non_reviewer_cannot_create_demo_proposal(self):
        self.client.login(username='viewer', password='test-pass-123')
        response = self.client.post(reverse('scan_detail', args=[self.scan.id]), {
            'path': '/users',
            'method': 'get',
            'status_code': '404',
            'description': 'Пользователь не найден',
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.scan.proposals.count(), 1)
