from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from reviewer.models import Scan

SPEC='''openapi: 3.0.3\ninfo:\n  title: Demo API\n  version: 1.0.0\npaths:\n  /users:\n    get:\n      description: "Получить список пользователей"\n      x-manual-analysis: "Проверено человеком: endpoint используется мобильным клиентом"\n      responses:\n        "200":\n          description: "Успешный ответ"\n'''
class Command(BaseCommand):
    def handle(self,*args,**kwargs):
        scan=Scan(name='Демо OpenAPI')
        scan.specification.save('demo.yaml',ContentFile(SPEC.encode('utf-8')),save=True)
        self.stdout.write(self.style.SUCCESS('Демо-спецификация создана.'))
