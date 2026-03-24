from django import template

register = template.Library()

@register.filter
def user_initials(user):
    """Devuelve 2 letras: inicial del nombre y del apellido; si no hay, del username.
    Siempre en mayúsculas. Si falta alguna, duplica la disponible (p.ej. 'AA').
    """
    try:
        first = (getattr(user, 'first_name', '') or '').strip()
        last = (getattr(user, 'last_name', '') or '').strip()
        if first and last:
            return (first[0] + last[0]).upper()
        if first:
            # Si solo hay nombre, usar primeras dos letras cuando existan
            if len(first) >= 2:
                return (first[:2]).upper()
            return (first[0]*2).upper()
        if last:
            if len(last) >= 2:
                return (last[:2]).upper()
            return (last[0]*2).upper()
        username = (getattr(user, 'username', '') or '').strip()
        if username:
            if len(username) >= 2:
                return (username[0] + username[-1]).upper()
            return (username[0]*2).upper()
    except Exception:
        pass
    return 'US'


@register.filter
def estado_badge(estado: str) -> str:
    """Devuelve la clase Bootstrap de badge según el estado del proyecto.
    Uso: <span class="badge {{ proyecto.estado|estado_badge }}">{{ proyecto.get_estado_display }}</span>
    """
    try:
        e = (estado or '').strip().lower()
        mapping = {
            'borrador': 'bg-secondary',
            'en_proceso': 'bg-warning text-dark',
            'optimizado': 'bg-info text-dark',
            'aprobado': 'bg-primary',
            'asignado': 'bg-info text-dark',
            'produccion': 'bg-primary',
            'enchapado_pendiente': 'bg-orange text-white',
            'completado': 'bg-success',
            'pausado': 'bg-danger',
            'cancelado': 'bg-danger',
        }
        return mapping.get(e, 'bg-light text-dark')
    except Exception:
        return 'bg-light text-dark'
