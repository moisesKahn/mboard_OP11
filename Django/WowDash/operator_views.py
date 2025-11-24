from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse, HttpRequest
from django.db.models import Q
from core.models import Proyecto
from core.auth_utils import get_auth_context


def _require_operator_or_admin(ctx):
    """Devuelve True si el usuario es operador, admin de org o super_admin/soporte."""
    role = ctx.get('role')
    return bool(role in ('operador', 'org_admin', 'super_admin') or ctx.get('organization_is_general') or ctx.get('is_support'))


@login_required
def operador_home(request: HttpRequest):
    """Listado para el rol Operador.
    - Operador: ve solo proyectos asignados (proyecto.operador == request.user)
    - Org admin / super_admin: ven proyectos de su organización (o todos si soporte)
    Filtros básicos: estado, search (cliente/nombre/código)
    """
    ctx = get_auth_context(request)
    if not _require_operator_or_admin(ctx):
        return redirect('index')

    estado = request.GET.get('estado') or ''
    search = request.GET.get('search') or ''

    qs = Proyecto.objects.select_related('cliente')
    # Scope por organización (excepto soporte)
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        qs = qs.filter(organizacion_id=ctx.get('organization_id'))
    # Scope por rol operador: solo asignados a sí mismo
    if ctx.get('role') == 'operador':
        qs = qs.filter(operador=request.user)
    # Filtros
    if estado:
        qs = qs.filter(estado=estado)
    if search:
        qs = qs.filter(Q(codigo__icontains=search) | Q(nombre__icontains=search) | Q(cliente__nombre__icontains=search))

    proyectos = qs.order_by('-fecha_creacion')[:200]
    context = {
        'title': 'Operador',
        'subTitle': 'Proyectos asignados',
        'proyectos': proyectos,
        'estado': estado,
        'search': search,
    }
    return render(request, 'operador/list.html', context)


@login_required
def operador_historial(request: HttpRequest):
    """Historial para el rol Operador.
    - Operador: ve solo proyectos asignados a él en estados cerrados (completado/cancelado) o finalizados.
    - Org admin / super_admin: ven historial de su organización (o todos si soporte).
    Filtros: estado opcional y búsqueda.
    """
    ctx = get_auth_context(request)
    if not _require_operator_or_admin(ctx):
        return redirect('index')

    # Estados considerados "historial" por defecto
    estados_hist = {'completado', 'cancelado'}
    estado = request.GET.get('estado') or ''
    search = request.GET.get('search') or ''

    qs = Proyecto.objects.select_related('cliente')
    # Scope por organización (excepto soporte)
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        qs = qs.filter(organizacion_id=ctx.get('organization_id'))
    # Scope por rol operador: solo asignados a sí mismo
    if ctx.get('role') == 'operador':
        qs = qs.filter(operador=request.user)

    # Filtro por estados de historial (por defecto)
    if estado:
        qs = qs.filter(estado=estado)
    else:
        qs = qs.filter(estado__in=list(estados_hist))

    if search:
        qs = qs.filter(Q(codigo__icontains=search) | Q(nombre__icontains=search) | Q(cliente__nombre__icontains=search))

    proyectos = qs.order_by('-fecha_modificacion', '-fecha_creacion')[:200]
    context = {
        'title': 'Operador',
        'subTitle': 'Historial de proyectos',
        'proyectos': proyectos,
        'estado': estado,
        'search': search,
        'estados_hist': sorted(list(estados_hist)),
    }
    return render(request, 'operador/historial.html', context)


@login_required
@ensure_csrf_cookie
def operador_proyecto(request: HttpRequest, proyecto_id: int):
    """Detalle de un proyecto para operación/corte."""
    ctx = get_auth_context(request)
    base_qs = Proyecto.objects.select_related('cliente')
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
    proyecto = get_object_or_404(base_qs, id=proyecto_id)

    # Autorización adicional: si es operador, debe estar asignado
    if ctx.get('role') == 'operador' and proyecto.operador_id != request.user.id:
        return redirect('operador_home')

    context = {
        'title': f'Operar proyecto {proyecto.codigo}',
        'subTitle': proyecto.nombre,
        'proyecto': proyecto,
    }
    # Usar versión full-screen para maximizar área de visualización
    return render(request, 'operador/detalle_full.html', context)


@login_required
@ensure_csrf_cookie
def operador_corte_guiado(request: HttpRequest, proyecto_id: int):
    """Vista de corte guiado paso a paso para operadores.
    Muestra el tablero con piezas y guía el operador cortando de forma secuencial."""
    ctx = get_auth_context(request)
    base_qs = Proyecto.objects.select_related('cliente')
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
    proyecto = get_object_or_404(base_qs, id=proyecto_id)

    # Autorización adicional: si es operador, debe estar asignado
    if ctx.get('role') == 'operador' and proyecto.operador_id != request.user.id:
        return redirect('operador_home')

    context = {
        'title': f'Corte Guiado - {proyecto.codigo}',
        'subTitle': proyecto.nombre,
        'proyecto': proyecto,
    }
    return render(request, 'operador/corte_guiado.html', context)
