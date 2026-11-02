import json

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import Proposal, Scan


REPORT = {
    'run_id': '772e8463',
    'timestamp': '2026-09-27T09:34:01.650825+00:00',
    'spec_path': 'openapi.yaml',
    'src_path': './app',
    'spec_endpoints': 3,
    'code_endpoints': 2,
    'items': [
        {
            'id': 'bba82743dd08',
            'endpoint': 'GET /users',
            'category': 'missing_endpoint',
            'location': 'endpoint',
            'detail': 'Endpoint declared in spec but missing in code',
            'spec_evidence': 'GET /users',
            'code_evidence': None,
            'severity': 'error',
        },
        {
            'id': 'fadec000445e',
            'endpoint': 'GET /users/{user_id}',
            'category': 'parameter_drift',
            'location': 'parameters.include_meta',
            'detail': "Parameter 'include_meta' is present in code but missing in spec",
            'spec_evidence': None,
            'code_evidence': 'query parameter',
            'severity': 'warning',
        },
    ],
    'summary': {'error': 1, 'warning': 1, 'info': 0, 'total': 2},
    'findings': [
        {
            'drift_item_id': 'fadec000445e',
            'source_of_truth': 'CODE',
            'confidence': 'high',
            'reasoning': 'The code declares the query parameter while the specification does not.',
            'patch': {
                'target': 'spec',
                'patch_type': 'add_field',
                'location': '/users/{user_id}/get/parameters',
                'content': 'name: include_meta\nin: query',
            },
        }
    ],
}


class DriftImportTests(TestCase):
    def test_report_creates_scan_and_proposals(self):
        report = SimpleUploadedFile(
            'drift-report.json',
            json.dumps(REPORT).encode('utf-8'),
            content_type='application/json',
        )
        response = self.client.post(reverse('index'), {'drift_report': report})
        self.assertEqual(response.status_code, 302)
        scan = Scan.objects.get()
        self.assertEqual(scan.run_id, '772e8463')
        self.assertEqual(scan.drift_count, 2)
        self.assertEqual(scan.proposals.count(), 2)
        proposal = scan.proposals.get(drift_id='fadec000445e')
        self.assertEqual(proposal.severity, 'warning')
        self.assertEqual(proposal.source_of_truth, 'CODE')
        self.assertEqual(proposal.confidence, 'high')
        self.assertEqual(proposal.patch_target, 'spec')
        self.assertIn('include_meta', proposal.patch_content)

    def test_invalid_report_is_rejected(self):
        report = SimpleUploadedFile('bad.json', b'{"foo": 1}', content_type='application/json')
        response = self.client.post(reverse('index'), {'drift_report': report})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Scan.objects.count(), 0)


class ReviewFlowTests(TestCase):
    def setUp(self):
        self.scan = Scan.objects.create(name='Review test', drift_count=1, error_count=1)
        self.proposal = Proposal.objects.create(
            scan=self.scan,
            drift_id='abc123',
            title='Расхождение типов',
            path='/users',
            method='get',
            proposal_type='type_drift',
            severity='error',
            location='response.200.schema.id',
            reason='Type mismatch',
            spec_evidence='string',
            code_evidence='integer',
            source_of_truth='CODE',
            confidence='high',
            patch_target='spec',
            patch_type='change_type',
            patch_location='/users/get/responses/200/schema/id/type',
            patch_content='integer',
        )
        group = Group.objects.create(name='reviewer')
        self.reviewer = User.objects.create_user(username='reviewer', password='test-pass-123')
        self.reviewer.groups.add(group)
        self.viewer = User.objects.create_user(username='viewer', password='test-pass-123')

    def test_non_reviewer_cannot_accept(self):
        self.client.login(username='viewer', password='test-pass-123')
        response = self.client.post(reverse('proposal_action', args=[self.proposal.id, 'accept']))
        self.assertEqual(response.status_code, 403)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, 'pending')

    def test_reviewer_can_accept(self):
        self.client.login(username='reviewer', password='test-pass-123')
        response = self.client.post(reverse('proposal_action', args=[self.proposal.id, 'accept']))
        self.assertEqual(response.status_code, 302)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, 'accepted')
        self.assertEqual(self.proposal.reviewed_by, self.reviewer)

    def test_reviewer_can_edit_patch(self):
        self.client.login(username='reviewer', password='test-pass-123')
        response = self.client.post(
            reverse('edit_proposal', args=[self.proposal.id]),
            {'reason': 'Updated reason', 'patch_content': 'number'},
        )
        self.assertEqual(response.status_code, 302)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, 'edited')
        self.assertEqual(self.proposal.patch_content, 'number')
        self.assertEqual(self.proposal.reason, 'Updated reason')

    def test_export_contains_only_accepted(self):
        self.proposal.status = 'accepted'
        self.proposal.save(update_fields=['status'])
        Proposal.objects.create(
            scan=self.scan,
            title='Rejected',
            path='/other',
            method='post',
            proposal_type='parameter_drift',
            severity='warning',
            reason='Other',
            status='rejected',
        )
        response = self.client.get(reverse('export_report', args=[self.scan.id, 'json']))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content.decode('utf-8'))
        self.assertEqual(len(payload['accepted']), 1)
        self.assertEqual(payload['accepted'][0]['drift_id'], 'abc123')


class ProjectIntegrationTests(TestCase):
    def setUp(self):
        from pathlib import Path
        import tempfile
        from django.test import override_settings
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        override = override_settings(MEDIA_ROOT=self._media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(username='projectowner', password='test-pass-123')
        self.client.login(username='projectowner', password='test-pass-123')
        self.spec = (Path(__file__).resolve().parent.parent / 'tests' / 'fixtures' / 'specs' / 'simple.yaml').read_bytes()
        self.app = (Path(__file__).resolve().parent.parent / 'tests' / 'fixtures' / 'apps' / 'simple_app' / 'app.py').read_bytes()

    def _archive(self, extra=None):
        import io, zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('sample/app.py', self.app)
            archive.writestr('sample/openapi.yaml', self.spec)
            if extra:
                for name, content in extra.items():
                    archive.writestr(name, content)
        return SimpleUploadedFile('sample.zip', buffer.getvalue(), content_type='application/zip')

    def test_upload_runs_real_analyzer_and_saves_report(self):
        response = self.client.post(reverse('create_project_scan'), {
            'name': 'Test FastAPI', 'project_archive': self._archive(), 'llm_provider': 'ollama',
        })
        self.assertEqual(response.status_code, 302)
        scan = Scan.objects.get(name='Test FastAPI')
        self.assertEqual(scan.scan_status, 'completed')
        self.assertTrue(scan.project_archive.name)
        self.assertEqual(len(scan.archive_sha256), 64)
        self.assertEqual(scan.drift_count, scan.proposals.count())
        self.assertGreater(scan.drift_count, 0)
        self.assertTrue(scan.drift_report.name)
        self.assertTrue(scan.proposals.exclude(taxonomy='').exists())
        self.assertTrue(scan.proposals.exclude(priority='').exists())

    def test_invalid_zip_path_is_rejected(self):
        import io, zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('../escape.py', 'print(123)')
        response = self.client.post(reverse('create_project_scan'), {
            'project_archive': SimpleUploadedFile('evil.zip', buffer.getvalue()),
            'llm_provider': 'ollama',
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Scan.objects.filter(project_archive__contains='evil.zip').exists())

    def test_missing_spec_creates_failed_scan_with_message(self):
        import io, zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('project/app.py', 'from fastapi import FastAPI\napp = FastAPI()')
        response = self.client.post(reverse('create_project_scan'), {
            'project_archive': SimpleUploadedFile('missing.zip', buffer.getvalue()),
            'llm_provider': 'ollama',
        })
        self.assertEqual(response.status_code, 302)
        scan = Scan.objects.get(name='missing')
        self.assertEqual(scan.scan_status, 'failed')
        self.assertIn('OpenAPI', scan.analysis_error)

    def test_private_project_is_hidden_from_other_user(self):
        self.client.post(reverse('create_project_scan'), {
            'project_archive': self._archive(), 'llm_provider': 'ollama',
        })
        scan = Scan.objects.get(name='sample')
        other = User.objects.create_user(username='somebody', password='test-pass-123')
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse('scan_detail', args=[scan.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse('export_report', args=[scan.id, 'json'])).status_code, 404)

    def test_without_login_project_upload_redirects(self):
        self.client.logout()
        self.assertEqual(self.client.post(reverse('create_project_scan')).status_code, 302)

    def test_llm_unavailable_does_not_delete_findings(self):
        self.client.post(reverse('create_project_scan'), {
            'project_archive': self._archive(), 'use_llm': 'on', 'llm_provider': 'groq',
        })
        scan = Scan.objects.get(name='sample')
        self.assertEqual(scan.scan_status, 'completed')
        self.assertGreater(scan.proposals.count(), 0)
        self.assertIn(scan.llm_status, ('unavailable', 'partial'))

    def test_external_spec_upload_and_file_download(self):
        import io, zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('fastapi/app.py', self.app)
        response = self.client.post(reverse('create_project_scan'), {
            'name': 'Separate OpenAPI',
            'project_archive': SimpleUploadedFile('external.zip', buffer.getvalue()),
            'specification': SimpleUploadedFile('openapi.yaml', self.spec),
            'llm_provider': 'ollama',
        })
        self.assertEqual(response.status_code, 302)
        scan = Scan.objects.get(name='Separate OpenAPI')
        self.assertEqual(scan.scan_status, 'completed')
        self.assertEqual(self.client.get(reverse('scan_download', args=[scan.pk, 'zip'])).status_code, 200)
        self.assertEqual(self.client.get(reverse('scan_download', args=[scan.pk, 'openapi'])).status_code, 200)
