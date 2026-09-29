from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def can_review(user):
    """Проверяет, может ли пользователь выполнять действия ревьюера."""
    return bool(
        user.is_authenticated
        and (user.is_superuser or user.groups.filter(name='reviewer').exists())
    )


def reviewer_required(view_func):
    """Разрешает доступ только группе reviewer или суперпользователю."""
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if can_review(request.user):
            return view_func(request, *args, **kwargs)
        raise PermissionDenied('Требуется роль reviewer.')

    return _wrapped
