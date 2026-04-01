import datetime
from typing import Optional, Dict, Any
import base64
import json
import hmac
import hashlib
from django.conf import settings
from django.utils import timezone


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _b64url_decode(data: str) -> bytes:
    padding = '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def jwt_encode(payload: Dict[str, Any], exp_minutes: int = 120) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = datetime.datetime.utcnow()
    payload = {
        **payload,
        'iat': int(now.timestamp()),
        'exp': int((now + datetime.timedelta(minutes=exp_minutes)).timestamp()),
        'iss': 'WowDash',
    }
    header_b64 = _b64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
    signing_input = f"{header_b64}.{payload_b64}".encode('ascii')
    sig = hmac.new(settings.SECRET_KEY.encode('utf-8'), signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(sig)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def jwt_decode(token: str) -> Optional[Dict[str, Any]]:
    try:
        header_b64, payload_b64, signature_b64 = token.split('.')
        signing_input = f"{header_b64}.{payload_b64}".encode('ascii')
        expected_sig = hmac.new(settings.SECRET_KEY.encode('utf-8'), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_sig, _b64url_decode(signature_b64)):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode('utf-8'))
        # Validaciones mínimas
        if payload.get('iss') != 'WowDash':
            return None
        exp = payload.get('exp')
        if exp is not None and int(exp) < int(datetime.datetime.utcnow().timestamp()):
            return None
        return payload
    except Exception:
        return None


def get_bearer_token_from_request(request) -> Optional[str]:
    auth_header = request.META.get('HTTP_AUTHORIZATION') or request.headers.get('Authorization')
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == 'bearer':
        return parts[1]
    return None


def get_token_claims(request) -> Optional[Dict[str, Any]]:
    token = get_bearer_token_from_request(request)
    if not token:
        return None
    return jwt_decode(token)


def get_auth_context(request) -> Dict[str, Any]:
    """Obtiene contexto de autenticación unificado desde JWT o sesión.
    Retorna: {
      'user_id', 'username', 'organization_id', 'organization_is_general', 'role',
      'is_support', 'organization' (obj o None), 'perfil' (obj o None)
    }
    """
    from core.models import UsuarioPerfilOptimizador, Organizacion
    claims = get_token_claims(request)
    if claims:
        org_id = claims.get('organization_id')
        org = None
        try:
            if org_id:
                org = Organizacion.objects.filter(id=org_id).first()
        except Exception:
            org = None
        is_general = bool(claims.get('organization_is_general') or (org.is_general if org else False))
        return {
            'user_id': claims.get('user_id'),
            'username': claims.get('username'),
            'organization_id': org.id if org else None,
            'organization_is_general': is_general,
            'role': claims.get('role'),
            'is_support': is_general,
            'organization': org,
            'perfil': None,
        }
    # Fallback sesión
    user = getattr(request, 'user', None)
    perfil = None
    org = None
    role = None
    is_general = False
    if user and user.is_authenticated:
        try:
            perfil = user.usuarioperfiloptimizador
            org = perfil.organizacion
            role = perfil.rol
            is_general = bool(org.is_general) if org else False
        except Exception:
            perfil = None

    # Si el super_admin tiene un rol activo en sesión, usarlo
    if role == 'super_admin' and hasattr(request, 'session'):
        rol_activo = request.session.get('superadmin_rol_activo')
        if rol_activo:
            role = rol_activo

    return {
        'user_id': getattr(user, 'id', None),
        'username': getattr(user, 'username', None),
        'organization_id': getattr(org, 'id', None),
        'organization_is_general': is_general,
        'role': role,
        'is_support': bool(perfil and perfil.rol == 'super_admin'),
        'organization': org,
        'perfil': perfil,
    }


def is_support(ctx: Dict[str, Any]) -> bool:
    return bool(ctx.get('organization_is_general') or ctx.get('is_support') or ctx.get('role') == 'super_admin')


def is_org_admin(ctx: Dict[str, Any]) -> bool:
    return ctx.get('role') == 'org_admin'


def is_agent(ctx: Dict[str, Any]) -> bool:
    return ctx.get('role') == 'vendedor'


def is_subordinador(ctx: Dict[str, Any]) -> bool:
    return ctx.get('role') == 'subordinador'




def is_subordinado(ctx: Dict[str, Any]) -> bool:
    """Subordinado: nivel global, gestiona organizaciones y usuarios."""
    return ctx.get('role') in ('subordinado', 'subordinador')  # backward compat


def is_supervisor(ctx: Dict[str, Any]) -> bool:
    """Supervisor: asigna operadores y cambia estados dentro de una organización."""
    return ctx.get('role') == 'supervisor'


def can_approve_projects(ctx: Dict[str, Any]) -> bool:
    """Roles que pueden asignar operadores y cambiar estado de proyectos."""
    return ctx.get('role') in ('super_admin', 'org_admin', 'subordinado',
                               'subordinador', 'supervisor')


def can_delete_projects(ctx: Dict[str, Any]) -> bool:
    """Roles que pueden eliminar proyectos."""
    return ctx.get('role') in ('super_admin', 'org_admin', 'subordinado',
                               'subordinador', 'supervisor')
