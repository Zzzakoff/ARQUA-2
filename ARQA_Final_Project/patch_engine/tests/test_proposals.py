from unittest import TestCase

from patch_engine.proposals import generate_response_proposal


SPEC = """
openapi: 3.0.3
info:
  title: Demo API
  version: 1.0.0
paths:
  /users:
    get:
      description: "Получить список пользователей"
      x-manual-analysis: "Проверено человеком: endpoint используется мобильным клиентом"
      responses:
        "200":
          description: "Успешный ответ"
"""


class ProposalTests(TestCase):
    def test_manual_analytics_is_preserved(self):
        result = generate_response_proposal(
            SPEC, '/users', 'get', 404, 'Пользователь не найден'
        )
        self.assertIn(
            'Проверено человеком: endpoint используется мобильным клиентом',
            result['after'],
        )
        self.assertIn('404', result['after'])
        self.assertIn('Получить список пользователей', result['after'])
        self.assertFalse(result['requires_manual_review'])
        self.assertEqual(result['confidence'], 'high')
        self.assertEqual(result['source_of_truth'], 'code / live API')

    def test_missing_endpoint_fails(self):
        with self.assertRaises(ValueError):
            generate_response_proposal(SPEC, '/missing', 'get', 404, '')

    def test_manual_analytics_collected(self):
        result = generate_response_proposal(SPEC, '/users', 'get', 500, 'Ошибка')
        self.assertIn('x-manual-analysis', result['manual_analytics'])
        self.assertIn('Проверено человеком', result['manual_analytics'])
