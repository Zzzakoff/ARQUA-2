import json

from django import forms
from django.core.validators import FileExtensionValidator

from .models import Scan

try:
    import yaml
except ImportError:
    yaml = None


SPEC_EXTENSIONS = ['yaml', 'yml', 'json']
MAX_SIZE = 10 * 1024 * 1024


class ScanForm(forms.ModelForm):
    name = forms.CharField(
        required=False,
        label='Название',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Например, Users API',
        }),
    )
    drift_report = forms.FileField(
        label='Drift report JSON',
        validators=[FileExtensionValidator(allowed_extensions=['json'])],
        widget=forms.ClearableFileInput(attrs={
            'accept': '.json,application/json',
            'class': 'form-control',
        }),
    )
    specification = forms.FileField(
        required=False,
        label='OpenAPI YAML/JSON',
        validators=[FileExtensionValidator(allowed_extensions=SPEC_EXTENSIONS)],
        widget=forms.ClearableFileInput(attrs={
            'accept': '.yaml,.yml,.json',
            'class': 'form-control',
        }),
    )

    class Meta:
        model = Scan
        fields = ['name', 'drift_report', 'specification']

    def clean_drift_report(self):
        uploaded = self.cleaned_data['drift_report']
        if uploaded.size > MAX_SIZE:
            raise forms.ValidationError('Drift report больше 10 МБ.')
        try:
            payload = json.loads(uploaded.read().decode('utf-8'))
        except Exception:
            raise forms.ValidationError('Drift report должен быть корректным JSON.')
        finally:
            uploaded.seek(0)
        if not isinstance(payload, dict):
            raise forms.ValidationError('Drift report должен содержать JSON-объект.')
        if not isinstance(payload.get('items'), list):
            raise forms.ValidationError('В drift report отсутствует массив items.')
        required = {'id', 'endpoint', 'category', 'location', 'detail', 'severity'}
        for index, item in enumerate(payload['items'], start=1):
            if not isinstance(item, dict) or not required.issubset(item):
                raise forms.ValidationError(f'Некорректный drift item #{index}.')
        self.cleaned_data['report_payload'] = payload
        return uploaded

    def clean_specification(self):
        uploaded = self.cleaned_data.get('specification')
        if not uploaded:
            return uploaded
        if uploaded.size > MAX_SIZE:
            raise forms.ValidationError('OpenAPI-файл больше 10 МБ.')
        ext = uploaded.name.rsplit('.', 1)[-1].lower()
        try:
            text = uploaded.read().decode('utf-8')
        except UnicodeDecodeError:
            raise forms.ValidationError('OpenAPI-файл должен быть в UTF-8.')
        finally:
            uploaded.seek(0)
        try:
            if ext in ('yaml', 'yml'):
                if yaml is None:
                    raise forms.ValidationError('Для YAML требуется PyYAML.')
                data = yaml.safe_load(text)
            else:
                data = json.loads(text)
        except forms.ValidationError:
            raise
        except Exception as exc:
            raise forms.ValidationError(f'Не удалось разобрать OpenAPI-файл: {exc}')
        if not isinstance(data, dict) or 'openapi' not in data:
            raise forms.ValidationError('Файл не похож на OpenAPI 3.x: отсутствует поле openapi.')
        return uploaded

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('name'):
            payload = cleaned.get('report_payload') or {}
            run_id = payload.get('run_id')
            spec_path = payload.get('spec_path')
            if spec_path:
                cleaned['name'] = str(spec_path).replace('\\', '/').split('/')[-1]
            elif run_id:
                cleaned['name'] = f'Drift scan {run_id}'
            elif cleaned.get('drift_report'):
                cleaned['name'] = cleaned['drift_report'].name
        return cleaned


class ProjectScanForm(forms.Form):
    name = forms.CharField(required=False, max_length=200, label='Название проекта',
                           widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например, Shop API'}))
    project_archive = forms.FileField(label='ZIP с FastAPI-проектом',
        validators=[FileExtensionValidator(allowed_extensions=['zip'])],
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.zip'}))
    specification = forms.FileField(label='OpenAPI YAML/JSON (если нет в ZIP)', required=False,
        validators=[FileExtensionValidator(allowed_extensions=SPEC_EXTENSIONS)],
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.yaml,.yml,.json'}))
    use_llm = forms.BooleanField(label='Объяснить через LLM (передаются фрагменты находок)', required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    llm_provider = forms.ChoiceField(choices=[('ollama', 'Ollama (локально)'), ('groq', 'Groq (облако)')],
        widget=forms.Select(attrs={'class': 'form-select'}), label='Провайдер LLM')
    llm_model = forms.CharField(required=False, max_length=120, label='Модель (если пусто, стандартная)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'qwen2.5-coder:7b / llama-3.3-70b-versatile'}))

    def clean_project_archive(self):
        from .services.project_analysis import MAX_ZIP_COMPRESSED, inspect_archive, UploadError
        file = self.cleaned_data['project_archive']
        if file.size > MAX_ZIP_COMPRESSED:
            raise forms.ValidationError('ZIP больше 30 МБ.')
        try:
            inspect_archive(file)
        except UploadError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return file

    def clean_specification(self):
        file = self.cleaned_data.get('specification')
        if not file:
            return file
        if file.size > MAX_SIZE:
            raise forms.ValidationError('OpenAPI-файл больше 10 МБ.')
        try:
            text = file.read().decode('utf-8')
            payload = json.loads(text) if file.name.lower().endswith('.json') else yaml.safe_load(text)
        except Exception as exc:
            raise forms.ValidationError(f'Некорректный файл OpenAPI: {exc}') from exc
        finally:
            file.seek(0)
        if not isinstance(payload, dict) or not str(payload.get('openapi', '')).startswith('3.'):
            raise forms.ValidationError('Нужна спецификация OpenAPI 3.x.')
        return file
