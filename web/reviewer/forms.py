import json
from django import forms
from django.core.validators import FileExtensionValidator
from .models import Scan

try:
    import yaml
except ImportError:
    yaml = None


ALLOWED_EXT = ['yaml', 'yml', 'json']
MAX_SIZE = 5 * 1024 * 1024


class ScanForm(forms.ModelForm):
    name = forms.CharField(
        required=False,
        label='Название',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Мой API',
        }),
    )
    specification = forms.FileField(
        label='OpenAPI YAML/JSON',
        validators=[FileExtensionValidator(allowed_extensions=ALLOWED_EXT)],
        widget=forms.ClearableFileInput(attrs={
            'accept': '.yaml,.yml,.json',
            'class': 'form-control',
        }),
    )

    class Meta:
        model = Scan
        fields = ['name', 'specification']

    def clean_specification(self):
        f = self.cleaned_data['specification']

        if f.size > MAX_SIZE:
            raise forms.ValidationError('Файл больше 5 МБ.')

        ext = f.name.rsplit('.', 1)[-1].lower()
        if ext not in ALLOWED_EXT:
            raise forms.ValidationError('Допустимы только .yaml, .yml, .json.')

        try:
            text = f.read().decode('utf-8')
        except UnicodeDecodeError:
            raise forms.ValidationError('Файл не является текстом в UTF-8.')
        finally:
            f.seek(0)

        try:
            if ext in ('yaml', 'yml'):
                if yaml is None:
                    raise forms.ValidationError('PyYAML не установлен: pip install pyyaml')
                data = yaml.safe_load(text)
            else:
                data = json.loads(text)
        except forms.ValidationError:
            raise
        except Exception as e:
            raise forms.ValidationError(f'Не удалось распарсить файл: {e}')

        if not isinstance(data, dict) or 'openapi' not in data:
            raise forms.ValidationError(
                'Это не OpenAPI-спецификация: нет поля "openapi".'
            )
        return f

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('name') and cleaned.get('specification'):
            cleaned['name'] = cleaned['specification'].name
        return cleaned
