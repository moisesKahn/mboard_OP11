import json as _json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse, HttpRequest, StreamingHttpResponse
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

    qs = Proyecto.objects.select_related('cliente').defer(
        'resultado_optimizacion', 'configuracion', 'descripcion'
    )
    # Scope por organización (excepto soporte)
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        qs = qs.filter(organizacion_id=ctx.get('organization_id'))
    # Scope por rol operador: solo asignados a sí mismo
    if ctx.get('role') == 'operador':
        qs = qs.filter(operador=request.user)
    # Excluir estados que pertenecen al historial (completado y pendiente_enchapado)
    ESTADOS_HISTORIAL = ('completado', 'pendiente_enchapado')
    if estado:
        qs = qs.filter(estado=estado)
    else:
        qs = qs.exclude(estado__in=ESTADOS_HISTORIAL)
    if search:
        search_q = (
            Q(codigo__icontains=search)
            | Q(nombre__icontains=search)
            | Q(cliente__nombre__icontains=search)
        )
        try:
            search_q |= Q(public_id=int(search))
        except (ValueError, TypeError):
            pass
        qs = qs.filter(search_q)

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
        search_q = (
            Q(codigo__icontains=search)
            | Q(nombre__icontains=search)
            | Q(cliente__nombre__icontains=search)
        )
        try:
            search_q |= Q(public_id=int(search))
        except (ValueError, TypeError):
            pass
        qs = qs.filter(search_q)

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
    Muestra el tablero con piezas y guía el operador cortando de forma secuencial.
    Si el proyecto está en un estado pre-inicio (aprobado/produccion/optimizado),
    lo marca como 'asignado' para que el operador vea el modal de verificación de materiales.
    """
    ctx = get_auth_context(request)
    base_qs = Proyecto.objects.select_related('cliente')
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
    proyecto = get_object_or_404(base_qs, id=proyecto_id)

    # Autorización adicional: si es operador, debe estar asignado
    if ctx.get('role') == 'operador' and proyecto.operador_id != request.user.id:
        return redirect('operador_home')

    # Si el proyecto está en un estado "listo para producción" pero aún no iniciado,
    # transicionarlo a 'asignado' para que el operador vea el modal de materiales.
    ESTADOS_PRE_INICIO = ('aprobado', 'produccion', 'optimizado')
    if proyecto.estado in ESTADOS_PRE_INICIO:
        proyecto.estado = 'asignado'
        proyecto.save(update_fields=['estado'])

    context = {
        'title': f'Corte Guiado - {proyecto.codigo}',
        'subTitle': proyecto.nombre,
        'proyecto': proyecto,
        'resultado_optimizacion_json': _json.dumps(proyecto.resultado_optimizacion) if proyecto.resultado_optimizacion else 'null',
    }
    return render(request, 'operador/corte_guiado.html', context)


@login_required
def operador_proyectos_sse(request: HttpRequest):
    """SSE /operador/proyectos/eventos/
    Emite un evento 'cambio' cada vez que el conjunto de proyectos activos
    del operador cambia (nuevo proyecto, cambio de estado, etc.).
    El cliente reconecta automáticamente si se cae la conexión.
    """
    import time

    ctx = get_auth_context(request)
    ESTADOS_HISTORIAL = ('completado', 'pendiente_enchapado', 'cancelado')

    def _get_firma():
        """Devuelve una firma liviana del estado actual: lista de (id, estado)."""
        qs = Proyecto.objects.only('id', 'estado', 'nombre')
        if not (ctx.get('organization_is_general') or ctx.get('is_support')):
            qs = qs.filter(organizacion_id=ctx.get('organization_id'))
        if ctx.get('role') == 'operador':
            qs = qs.filter(operador=request.user)
        qs = qs.exclude(estado__in=ESTADOS_HISTORIAL)
        return frozenset((p.id, p.estado) for p in qs)

    def _event_stream():
        # Inicializar con el estado actual para NO disparar un cambio falso al conectar
        firma_anterior = _get_firma()
        INTERVALO = 8   # segundos entre chequeos
        HEARTBEAT  = 25 # segundos entre keep-alive
        ultimo_hb  = time.time()
        yield 'retry: 5000\n\n'   # reconectar tras 5 s si se corta
        while True:
            try:
                firma = _get_firma()
                if firma != firma_anterior:
                    # Proyectos añadidos al conjunto visible del operador
                    nuevos = firma - firma_anterior
                    payload = _json.dumps({
                        'total': len(firma),
                        'nuevos': len(nuevos),
                    })
                    yield f'event: cambio\ndata: {payload}\n\n'
                    firma_anterior = firma
                # Heartbeat para mantener la conexión viva
                if time.time() - ultimo_hb >= HEARTBEAT:
                    yield ': keep-alive\n\n'
                    ultimo_hb = time.time()
            except Exception:
                pass
            time.sleep(INTERVALO)

    resp = StreamingHttpResponse(_event_stream(), content_type='text/event-stream')
    resp['Cache-Control'] = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'   # Nginx: deshabilitar buffering
    return resp
