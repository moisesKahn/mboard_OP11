"""Vistas para el rol Enchapador.

El enchapador gestiona el proceso de tapacanto/enchapado de piezas ya cortadas.
Ve proyectos en estado 'enchapado_pendiente' y marca el proceso como completado.
"""
import json as _json

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse, HttpRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from core.auth_utils import get_auth_context
from core.models import AuditLog, Proyecto


def _require_enchapador_or_admin(ctx):
    """True si el usuario puede acceder a las vistas de enchapador."""
    role = ctx.get('role')
    return bool(
        role in ('enchapador', 'org_admin', 'super_admin')
        or ctx.get('organization_is_general')
        or ctx.get('is_support')
    )


# ---------------------------------------------------------------------------
# HOME — proyectos pendientes de enchapado
# ---------------------------------------------------------------------------

@login_required
def enchapador_home(request: HttpRequest):
    """Listado de proyectos en estado 'enchapado_pendiente' para el enchapador."""
    ctx = get_auth_context(request)
    if not _require_enchapador_or_admin(ctx):
        return redirect('index')

    search = request.GET.get('search') or ''

    qs = Proyecto.objects.select_related('cliente')
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        qs = qs.filter(organizacion_id=ctx.get('organization_id'))

    # Enchapador: solo ve proyectos enchapado_pendiente asignados a él
    # (se reutiliza el campo operador para la asignación)
    if ctx.get('role') == 'enchapador':
        qs = qs.filter(estado='enchapado_pendiente', operador=request.user)
    else:
        qs = qs.filter(estado='enchapado_pendiente')

    if search:
        qs = qs.filter(
            Q(codigo__icontains=search) |
            Q(nombre__icontains=search) |
            Q(cliente__nombre__icontains=search)
        )

    proyectos = qs.order_by('-fecha_modificacion')[:200]
    return render(request, 'enchapador/list.html', {
        'title': 'Enchapador',
        'subTitle': 'Proyectos pendientes de enchapado',
        'proyectos': proyectos,
        'search': search,
    })


# ---------------------------------------------------------------------------
# HISTORIAL
# ---------------------------------------------------------------------------

@login_required
def enchapador_historial(request: HttpRequest):
    """Historial de proyectos completados para el enchapador."""
    ctx = get_auth_context(request)
    if not _require_enchapador_or_admin(ctx):
        return redirect('index')

    search = request.GET.get('search') or ''
    estado = request.GET.get('estado') or ''

    qs = Proyecto.objects.select_related('cliente')
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        qs = qs.filter(organizacion_id=ctx.get('organization_id'))

    if ctx.get('role') == 'enchapador':
        qs = qs.filter(operador=request.user)

    if estado:
        qs = qs.filter(estado=estado)
    else:
        qs = qs.filter(estado='completado')

    if search:
        qs = qs.filter(
            Q(codigo__icontains=search) |
            Q(nombre__icontains=search) |
            Q(cliente__nombre__icontains=search)
        )

    proyectos = qs.order_by('-fecha_modificacion')[:200]
    return render(request, 'enchapador/historial.html', {
        'title': 'Enchapador',
        'subTitle': 'Historial de enchapado',
        'proyectos': proyectos,
        'search': search,
        'estado': estado,
    })


# ---------------------------------------------------------------------------
# DETALLE DEL PROYECTO
# ---------------------------------------------------------------------------

@login_required
@ensure_csrf_cookie
def enchapador_proyecto(request: HttpRequest, proyecto_id: int):
    """Vista de detalle del proyecto para enchapado.

    Agrupa las piezas por tipo de material (no por tablero físico) y muestra
    la información de tapacanto por pieza.
    """
    ctx = get_auth_context(request)
    if not _require_enchapador_or_admin(ctx):
        return redirect('index')

    base_qs = Proyecto.objects.select_related('cliente')
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))

    proyecto = get_object_or_404(base_qs, id=proyecto_id)

    if ctx.get('role') == 'enchapador' and proyecto.operador_id != request.user.id:
        return redirect('enchapador_home')

    return render(request, 'enchapador/detalle.html', {
        'title': f'Enchapado - {proyecto.codigo}',
        'subTitle': proyecto.nombre,
        'proyecto': proyecto,
    })


# ---------------------------------------------------------------------------
# API — completar enchapado
# ---------------------------------------------------------------------------

@csrf_exempt
@login_required
@require_http_methods(["POST"])
def enchapador_completar_api(request: HttpRequest, proyecto_id: int):
    """POST /api/enchapador/proyectos/<id>/completar-enchapado
    Marca el proyecto como 'completado' cuando todo el enchapado está terminado.
    """
    ctx = get_auth_context(request)
    base_qs = Proyecto.objects
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))

    p = get_object_or_404(base_qs, id=proyecto_id)

    if ctx.get('role') == 'enchapador' and p.operador_id != request.user.id:
        return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)

    p.estado = 'completado'
    p.save(update_fields=['estado'])

    try:
        AuditLog.objects.create(
            actor=request.user,
            organizacion=p.organizacion,
            verb='UPDATE',
            target_model='Proyecto',
            target_id=str(p.id),
            target_repr=p.codigo,
            changes={'estado': 'completado', 'via': 'enchapado'},
        )
    except Exception:
        pass

    return JsonResponse({'success': True})
