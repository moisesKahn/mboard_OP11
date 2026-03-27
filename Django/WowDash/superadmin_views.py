"""
Vistas para el sistema de impersonación de Super Administradores.

Flujo:
  1. Super admin hace login normal.
  2. Desde el drawer lateral elige cualquier usuario de su organización
     (excepto otros super_admin).
  3. POST /superadmin/impersonar/<user_id>/
     → guarda el ID original en sesión → hace login() con ese usuario.
  4. Barra flotante siempre visible → GET /superadmin/restaurar/
     → restaura la sesión original del super_admin.
"""
from django.contrib.auth import login, get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from core.models import UsuarioPerfilOptimizador

User = get_user_model()

SESSION_ORIGINAL_ID   = 'impersona_original_id'
SESSION_ORIGINAL_NAME = 'impersona_original_name'
SESSION_ORIGINAL_ROL  = 'impersona_original_rol'

ROL_HOME = {
    'operador':    'operador_home',
    'enchapador':  'enchapador_home',
    'vendedor':    'proyectos',
    'org_admin':   'proyectos',
    'subordinador':'proyectos',
    'supervisor':  'proyectos',
    'autoservicio':'autoservicio_home',
}


def _perfil_rol(user):
    try:
        return user.usuarioperfiloptimizador.rol
    except Exception:
        return None


def _es_superadmin(user):
    return _perfil_rol(user) == 'super_admin'


@login_required
def usuarios_impersonables(request):
    """JSON con usuarios de la org del super_admin (excluye otros super_admin)."""
    if not _es_superadmin(request.user):
        return HttpResponseForbidden('Solo disponible para Super Admin.')
    try:
        org = request.user.usuarioperfiloptimizador.organizacion
    except Exception:
        return JsonResponse({'usuarios': []})

    perfiles = (
        UsuarioPerfilOptimizador.objects
        .filter(organizacion=org, activo=True)
        .exclude(rol='super_admin')
        .exclude(user=request.user)
        .select_related('user')
        .order_by('rol', 'user__first_name', 'user__username')
    )

    ETIQUETAS = {
        'org_admin':   'Admin Org.',
        'vendedor':    'Vendedor',
        'operador':    'Operador',
        'enchapador':  'Enchapador',
        'supervisor':  'Supervisor',
        'subordinador':'Subordinador',
        'autoservicio':'Autoservicio',
    }
    ICONOS = {
        'org_admin':   'lucide:building-2',
        'vendedor':    'lucide:shopping-bag',
        'operador':    'lucide:hammer',
        'enchapador':  'lucide:layers',
        'supervisor':  'lucide:eye',
        'subordinador':'lucide:user-minus',
        'autoservicio':'lucide:monitor',
    }

    usuarios = []
    for p in perfiles:
        u = p.user
        nombre = u.get_full_name() or u.username
        partes = nombre.split()
        iniciales = ''.join(x[0].upper() for x in partes[:2]) or u.username[:2].upper()
        usuarios.append({
            'id':       u.id,
            'nombre':   nombre,
            'username': u.username,
            'iniciales':iniciales,
            'rol':      p.rol,
            'etiqueta': ETIQUETAS.get(p.rol, p.rol),
            'icono':    ICONOS.get(p.rol, 'lucide:user'),
        })

    return JsonResponse({'usuarios': usuarios})


@require_POST
@login_required
def impersonar(request, user_id):
    """Inicia sesión como otro usuario sin necesitar su contraseña."""
    original_id = request.session.get(SESSION_ORIGINAL_ID)
    if original_id:
        real_user = User.objects.filter(id=original_id).first()
        if not real_user or not _es_superadmin(real_user):
            return HttpResponseForbidden('Acceso denegado.')
    else:
        if not _es_superadmin(request.user):
            return HttpResponseForbidden('Solo disponible para Super Admin.')
        real_user = request.user

    objetivo = User.objects.filter(id=user_id).select_related('usuarioperfiloptimizador').first()
    if not objetivo:
        return HttpResponseForbidden('Usuario no encontrado.')
    if _perfil_rol(objetivo) == 'super_admin':
        return HttpResponseForbidden('No se puede impersonar a un Super Admin.')

    try:
        org_real     = real_user.usuarioperfiloptimizador.organizacion
        org_objetivo = objetivo.usuarioperfiloptimizador.organizacion
        if org_real != org_objetivo:
            return HttpResponseForbidden('El usuario no pertenece a tu organización.')
    except Exception:
        return HttpResponseForbidden('Error de organización.')

    # Guardar datos ANTES para recuperarlos luego del flush de sesión
    original_id_val   = real_user.id
    original_name_val = real_user.get_full_name() or real_user.username

    # login() puede hacer flush() de la sesión si cambia de usuario → los datos
    # guardados antes se perderían. Se vuelven a escribir justo después.
    login(request, objetivo, backend='django.contrib.auth.backends.ModelBackend')

    request.session[SESSION_ORIGINAL_ID]   = original_id_val
    request.session[SESSION_ORIGINAL_NAME] = original_name_val
    request.session[SESSION_ORIGINAL_ROL]  = 'super_admin'

    rol_objetivo = _perfil_rol(objetivo)
    return redirect(ROL_HOME.get(rol_objetivo, 'proyectos'))


@login_required
def restaurar_impersonacion(request):
    """Vuelve al super_admin original."""
    original_id = request.session.get(SESSION_ORIGINAL_ID)
    if not original_id:
        return redirect('proyectos')

    original = User.objects.filter(id=original_id).first()
    if not original:
        return redirect('proyectos')

    for key in (SESSION_ORIGINAL_ID, SESSION_ORIGINAL_NAME, SESSION_ORIGINAL_ROL):
        request.session.pop(key, None)

    login(request, original, backend='django.contrib.auth.backends.ModelBackend')
    return redirect('proyectos')
