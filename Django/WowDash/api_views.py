import re
import json as _json
import subprocess
import tempfile
import os
from reportlab.lib.pagesizes import mm as _rl_mm
from reportlab.pdfgen import canvas as _rl_canvas
from django.contrib.auth import authenticate
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.db.models import Count
from core.models import UsuarioPerfilOptimizador, Cliente, Proyecto, AuditLog, OptimizationRun, NotificacionEnchapador
from core.auth_utils import jwt_encode, get_auth_context


def _parse_resultado(res):
    """
    Normaliza el campo resultado_optimizacion independientemente de cómo fue guardado.
    - Si es dict (JSONField entregado ya parseado por Django) → lo devuelve tal cual.
    - Si es string JSON simple → hace un json.loads.
    - Si está doblemente serializado (string dentro de JSON) → hace dos json.loads.
    Siempre retorna un dict.
    """
    if res is None:
        return None
    if isinstance(res, dict):
        return res
    try:
        parsed = _json.loads(res)
        if isinstance(parsed, str):
            # Doblemente serializado: el JSON contenía un string JSON
            return _json.loads(parsed)
        return parsed
    except Exception:
        return None


def _claims_for_user(user: User):
    perfil = None
    org_id = None
    org_general = False
    role = None
    try:
        perfil = user.usuarioperfiloptimizador
        if perfil and perfil.organizacion:
            org_id = perfil.organizacion.id
            org_general = bool(perfil.organizacion.is_general)
        role = perfil.rol
    except UsuarioPerfilOptimizador.DoesNotExist:
        pass
    return {
        'user_id': user.id,
        'username': user.username,
        'organization_id': org_id,
        'organization_is_general': org_general,
        'role': role,
    }


@csrf_exempt
def auth_login(request: HttpRequest):
    # Si se accede por GET desde el navegador, redirigir a la página de login HTML
    if request.method != 'POST':
        from django.shortcuts import redirect
        return redirect('signin')
    try:
        import json
        data = json.loads(request.body or '{}')
        username = data.get('username')
        password = data.get('password')
        if not username or not password:
            return JsonResponse({'success': False, 'message': 'Credenciales requeridas'}, status=400)
        user = authenticate(request, username=username, password=password)
        if not user:
            return JsonResponse({'success': False, 'message': 'Usuario o contraseña inválidos'}, status=401)
        claims = _claims_for_user(user)
        token = jwt_encode(claims)
        # Auditoría LOGIN
        try:
            AuditLog.objects.create(
                actor=user,
                organizacion=getattr(user.usuarioperfiloptimizador, 'organizacion', None),
                verb='LOGIN',
                target_model='User',
                target_id=str(user.id),
                target_repr=user.username,
                changes=None,
            )
        except Exception:
            pass
        return JsonResponse({'success': True, 'token': token, 'claims': claims})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


def _scope_queryset_by_org(qs, ctx):
    # Soporte/Org General ve todo
    if ctx.get('organization_is_general') or ctx.get('is_support'):
        return qs
    org_id = ctx.get('organization_id')
    if hasattr(qs.model, 'organizacion_id'):
        return qs.filter(organizacion_id=org_id)
    if qs.model is Cliente:
        return qs.filter(organizacion_id=org_id)
    if qs.model is Proyecto:
        # Proyecto tiene FK organizacion
        return qs.filter(organizacion_id=org_id)
    return qs


@login_required
def users_list_api(request: HttpRequest):
    ctx = get_auth_context(request)
    qs = User.objects.all().select_related('usuarioperfiloptimizador')
    # Scope: por organización (usuarios de su org) salvo soporte
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        org_id = ctx.get('organization_id')
        qs = qs.filter(usuarioperfiloptimizador__organizacion_id=org_id)
    data = []
    for u in qs[:200]:
        role = None
        org = None
        try:
            role = u.usuarioperfiloptimizador.rol
            org = u.usuarioperfiloptimizador.organizacion.nombre if u.usuarioperfiloptimizador.organizacion else None
        except Exception:
            pass
        data.append({'id': u.id, 'username': u.username, 'role': role, 'organizacion': org})
    return JsonResponse({'users': data})


@login_required
def user_resumen_api(request: HttpRequest, user_id: int):
    ctx = get_auth_context(request)
    user = get_object_or_404(User, id=user_id)
    # Autorización: mismo scope de organización o soporte
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        try:
            user_org_id = user.usuarioperfiloptimizador.organizacion_id
        except Exception:
            user_org_id = None
        if user_org_id != ctx.get('organization_id'):
            return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)

    # Conteos
    proyectos_creados = Proyecto.objects.filter(creado_por=user).count()
    clientes_creados = Cliente.objects.filter(created_by=user).count()
    # Últimas 50 acciones de auditoría
    logs = AuditLog.objects.filter(actor=user).order_by('-created_at')[:50]
    acciones = [
        {
            'verb': l.verb,
            'target': f"{l.target_model}({l.target_id})",
            'at': l.created_at.strftime('%Y-%m-%d %H:%M'),
        }
        for l in logs
    ]
    perfil = None
    role = None
    org = None
    try:
        perfil = user.usuarioperfiloptimizador
        role = perfil.rol
        org = perfil.organizacion.nombre if perfil.organizacion else None
    except Exception:
        pass
    return JsonResponse({
        'success': True,
        'user': {
            'id': user.id,
            'username': user.username,
            'role': role,
            'organizacion': org,
            'proyectos_creados': proyectos_creados,
            'clientes_creados': clientes_creados,
            'acciones': acciones,
        }
    })


@login_required
def analytics_optimizations(request: HttpRequest):
    """GET /api/analytics/optimizations?start=YYYY-MM-DD&end=YYYY-MM-DD
    Retorna lista de eventos por día: [{title, start, allDay:true}]
    """
    import datetime as dt
    from django.db.models.functions import TruncDate
    from django.db.models import Count
    ctx = get_auth_context(request)
    start = request.GET.get('start')
    end = request.GET.get('end')
    try:
        start_d = dt.datetime.strptime(start, '%Y-%m-%d').date() if start else None
        end_d = dt.datetime.strptime(end, '%Y-%m-%d').date() if end else None
    except Exception:
        return JsonResponse({'success': False, 'message': 'Formato de fecha inválido'}, status=400)
    qs = OptimizationRun.objects.all()
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        qs = qs.filter(organizacion_id=ctx.get('organization_id'))
    if start_d:
        qs = qs.filter(run_at__date__gte=start_d)
    if end_d:
        qs = qs.filter(run_at__date__lte=end_d)
    agg = qs.annotate(day=TruncDate('run_at')).values('day').annotate(count=Count('id')).order_by('day')
    events = [
        {
            'title': f"{row['count']} optimizaciones",
            'start': row['day'].isoformat(),
            'allDay': True,
        } for row in agg
    ]
    return JsonResponse({'success': True, 'events': events})


# =====================
# Operador APIs
# =====================
from django.views.decorators.http import require_http_methods
import json as _json


def _is_operator_or_admin(ctx):
    role = ctx.get('role')
    return bool(role in ('operador', 'org_admin', 'super_admin') or ctx.get('organization_is_general') or ctx.get('is_support'))


@login_required
@require_http_methods(["GET"])
def operador_proyectos_api(request: HttpRequest):
    """GET /api/operador/proyectos: lista proyectos visibles para el operador/admin.
    Filtros: estado, search
    """
    ctx = get_auth_context(request)
    if not _is_operator_or_admin(ctx):
        return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)
    estado = request.GET.get('estado') or ''
    search = request.GET.get('search') or ''

    qs = Proyecto.objects.select_related('cliente')
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        qs = qs.filter(organizacion_id=ctx.get('organization_id'))
    if ctx.get('role') == 'operador':
        qs = qs.filter(operador=request.user)
    if estado:
        qs = qs.filter(estado=estado)
    if search:
        from django.db.models import Q
        qs = qs.filter(Q(codigo__icontains=search) | Q(nombre__icontains=search) | Q(cliente__nombre__icontains=search))
    data = [
        {
            'id': p.id,
            'public_id': p.public_id,
            'codigo': p.codigo,
            'nombre': p.nombre,
            'cliente': getattr(p.cliente, 'nombre', None),
            'estado': p.estado,
            'creado': p.fecha_creacion.strftime('%Y-%m-%d %H:%M'),
        } for p in qs.order_by('-fecha_creacion')[:300]
    ]
    return JsonResponse({'success': True, 'proyectos': data})


@login_required
@require_http_methods(["GET"])
def operador_proyecto_detalle_api(request: HttpRequest, proyecto_id: int):
    """GET /api/operador/proyectos/<id>: retorna diseño optimizado normalizado para UI Operador."""
    ctx = get_auth_context(request)
    base_qs = Proyecto.objects.select_related('cliente')
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
    p = get_object_or_404(base_qs, id=proyecto_id)
    if ctx.get('role') == 'operador' and p.operador_id != request.user.id:
        return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)

    # Parsear resultado
    res = p.resultado_optimizacion
    if not res:
        return JsonResponse({'success': False, 'message': 'Proyecto sin resultado'}, status=404)
    try:
        resd = _parse_resultado(res)
    except Exception:
        resd = res if isinstance(res, dict) else None
    if not isinstance(resd, (dict,)):
        return JsonResponse({'success': False, 'message': 'Resultado inválido'}, status=500)

    # Soporte: resultado puede ser un único material (raíz) o materiales[]
    materiales = resd.get('materiales') if isinstance(resd.get('materiales'), list) else [resd]
    # Normalizar TODOS los materiales (para selector en UI)
    normalized_materiales = []
    for m_idx, mat in enumerate(materiales, start=1):
        try:
            kerf = (mat.get('config') or {}).get('kerf', mat.get('desperdicio_sierra'))
        except Exception:
            kerf = None
        try:
            margen_x = (mat.get('margenes') or {}).get('margen_x', (mat.get('config') or {}).get('margen_x'))
            margen_y = (mat.get('margenes') or {}).get('margen_y', (mat.get('config') or {}).get('margen_y'))
        except Exception:
            margen_x = margen_y = None
        material_nombre = (mat.get('material') or {}).get('nombre') or None
        tableros = mat.get('tableros') or []
        normalized_tableros_m = []
        for t_idx, t in enumerate(tableros, start=1):
            piezas = []
            for i, pi in enumerate(t.get('piezas') or [], start=1):
                # PID único incluyendo índice de material
                pieza_id = f"m{m_idx}t{t_idx}p{i}"
                pieza = {
                    'pieza_id': pieza_id,
                    'tablero_num': t_idx,
                    'nombre': pi.get('nombre') or pi.get('id_unico') or f"P{i}",
                    'x': pi.get('x'), 'y': pi.get('y'),
                    'ancho': pi.get('ancho'), 'largo': pi.get('largo'),
                    'rotada': bool(pi.get('rotada')),
                    'estado': pi.get('estado') or 'pendiente',
                    'tapacantos': pi.get('tapacantos') or {},
                }
                piezas.append(pieza)
            normalized_tableros_m.append({
                'num': t_idx,
                'ancho_mm': t.get('ancho') or mat.get('tablero_ancho_original') or mat.get('tablero_ancho_efectivo'),
                'largo_mm': t.get('largo') or mat.get('tablero_largo_original') or mat.get('tablero_largo_efectivo'),
                'piezas': piezas,
                'eficiencia': t.get('eficiencia_tablero'),
            })
        normalized_materiales.append({
            'indice': m_idx,
            'nombre': material_nombre,
            'meta': {
                'material': material_nombre,
                'kerf': kerf,
                'margen_x': margen_x,
                'margen_y': margen_y,
            },
            'tableros': normalized_tableros_m,
        })

    # Mantener compatibilidad: exponer también el PRIMER material al nivel raíz
    first = normalized_materiales[0] if normalized_materiales else {'meta': {}, 'tableros': []}
    return JsonResponse({
        'success': True,
        'proyecto': {
            'id': p.id,
            'public_id': p.public_id,
            'codigo': p.codigo,
            'nombre': p.nombre,
            'cliente': getattr(p.cliente, 'nombre', None),
            'estado': p.estado,
        },
        'tableros': first.get('tableros', []),  # legacy
        'meta': first.get('meta', {}),          # legacy
        'materiales': normalized_materiales,    # nuevo para selector
    })


@csrf_exempt
@login_required
@require_http_methods(["PATCH"])
def operador_pieza_estado_api(request: HttpRequest, proyecto_id: int, pieza_id: str):
    """PATCH /api/operador/proyectos/<id>/piezas/<pieza_id>
    Body: { estado: 'pendiente'|'en_corte'|'cortada'|'descartada' }
    Persiste el estado dentro del JSON de resultado.
    Usa select_for_update() para evitar race conditions cuando múltiples piezas
    se guardan en paralelo (ej: Promise.all en el frontend).
    """
    from django.db import transaction

    ctx = get_auth_context(request)

    # Validar permisos y payload ANTES de abrir la transacción
    base_qs = Proyecto.objects
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
    # Verificar existencia sin lock primero
    if not base_qs.filter(id=proyecto_id).exists():
        from django.http import Http404
        raise Http404

    try:
        payload = _json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'success': False, 'message': 'Payload inválido'}, status=400)
    estado = (payload.get('estado') or '').strip()
    if estado not in ('pendiente','en_corte','cortada','descartada'):
        return JsonResponse({'success': False, 'message': 'Estado inválido'}, status=400)

    # Parsear pieza_id antes de la transacción
    mti = re.match(r'^m(\d+)t(\d+)p(\d+)$', pieza_id or '')

    with transaction.atomic():
        # select_for_update: bloquea la fila hasta que la transacción termine.
        # Esto serializa los PATCHes concurrentes y evita que un request
        # sobreescriba los cambios de otro que llegó al mismo tiempo.
        p = base_qs.select_for_update().get(id=proyecto_id)

        if ctx.get('role') == 'operador' and p.operador_id != request.user.id:
            return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)

        res = p.resultado_optimizacion
        if not res:
            return JsonResponse({'success': False, 'message': 'Proyecto sin resultado'}, status=404)
        # IMPORTANTE: hacer deepcopy para que Django detecte el campo como modificado.
        # El JSONField de Django entrega el mismo objeto dict en memoria; si se modifica
        # in-place y se re-asigna el mismo objeto, Django no genera el UPDATE SQL.
        import copy
        resd = copy.deepcopy(_parse_resultado(res))
        if resd is None:
            return JsonResponse({'success': False, 'message': 'Resultado inválido'}, status=500)

        materiales = resd.get('materiales') if isinstance(resd.get('materiales'), list) else [resd]
        updated = False

        if mti:
            target_m = int(mti.group(1))
            target_t = int(mti.group(2))
            target_p = int(mti.group(3))
            for m_idx, mat in enumerate(materiales, start=1):
                if m_idx != target_m:
                    continue
                tableros = mat.get('tableros') or []
                for t_idx, t in enumerate(tableros, start=1):
                    if t_idx != target_t:
                        continue
                    piezas = t.get('piezas') or []
                    for i, pi in enumerate(piezas, start=1):
                        if i == target_p:
                            pi['estado'] = estado
                            updated = True
                            break
                    break
                break
        else:
            # Compatibilidad: formato antiguo t{t}p{i} (sin material)
            for mat in materiales:
                tableros = mat.get('tableros') or []
                for t_idx, t in enumerate(tableros, start=1):
                    piezas = t.get('piezas') or []
                    for i, pi in enumerate(piezas, start=1):
                        pid = f"t{t_idx}p{i}"
                        if pid == pieza_id:
                            pi['estado'] = estado
                            updated = True
                            break
                if updated:
                    break

        if not updated:
            return JsonResponse({'success': False, 'message': 'Pieza no encontrada'}, status=404)

        # Garantizar que TODAS las piezas tengan la clave 'estado' antes de persistir
        for mat in materiales:
            for tab in (mat.get('tableros') or []):
                for pi in (tab.get('piezas') or []):
                    if 'estado' not in pi:
                        pi['estado'] = 'pendiente'

        # Persistir dentro de la transacción (atómica con el select_for_update).
        # IMPORTANTE: resultado_optimizacion es un JSONField — se debe asignar el DICT,
        # no un string. Si se asigna json.dumps(...), Django re-serializa el string
        # produciéndose doble codificación y el estado no se guarda correctamente.
        if 'materiales' in resd:
            p.resultado_optimizacion = resd
        else:
            p.resultado_optimizacion = materiales[0]
        p.save(update_fields=['resultado_optimizacion'])

    # Auditoría
    try:
        AuditLog.objects.create(
            actor=request.user,
            organizacion=p.organizacion,
            verb='EDIT',
            target_model='Proyecto',
            target_id=str(p.id),
            target_repr=p.codigo,
            changes={'pieza_id': pieza_id, 'estado': estado},
        )
    except Exception:
        pass

    return JsonResponse({'success': True})


@csrf_exempt
@login_required
@require_http_methods(["PATCH"])
def operador_piezas_batch_api(request: HttpRequest, proyecto_id: int):
    """PATCH /api/operador/proyectos/<id>/piezas-batch
    Body: { piezas: [ {pieza_id: 'm1t1p3', estado: 'cortada'}, ... ] }
    Aplica múltiples cambios de estado en UNA SOLA transacción/lock,
    reduciendo el número de round-trips a la BD cuando se cortan varias
    piezas de golpe (ej: siguiente corte marca 3 piezas a la vez).
    """
    from django.db import transaction

    ctx = get_auth_context(request)
    base_qs = Proyecto.objects
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
    if not base_qs.filter(id=proyecto_id).exists():
        from django.http import Http404
        raise Http404

    try:
        payload = _json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'success': False, 'message': 'Payload inválido'}, status=400)

    piezas_payload = payload.get('piezas') or []
    if not isinstance(piezas_payload, list) or not piezas_payload:
        return JsonResponse({'success': False, 'message': 'Se requiere lista de piezas'}, status=400)

    ESTADOS_VALIDOS = {'pendiente', 'en_corte', 'cortada', 'descartada'}
    cambios = {}  # pieza_id → estado (ya validados)
    for item in piezas_payload:
        if not isinstance(item, dict):
            continue
        pid = (item.get('pieza_id') or '').strip()
        est = (item.get('estado') or '').strip()
        if pid and est in ESTADOS_VALIDOS:
            cambios[pid] = est

    if not cambios:
        return JsonResponse({'success': False, 'message': 'Sin cambios válidos'}, status=400)

    with transaction.atomic():
        p = base_qs.select_for_update().get(id=proyecto_id)
        if ctx.get('role') == 'operador' and p.operador_id != request.user.id:
            return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)

        res = p.resultado_optimizacion
        if not res:
            return JsonResponse({'success': False, 'message': 'Proyecto sin resultado'}, status=404)

        import copy
        resd = copy.deepcopy(_parse_resultado(res))
        if resd is None:
            return JsonResponse({'success': False, 'message': 'Resultado inválido'}, status=500)

        materiales = resd.get('materiales') if isinstance(resd.get('materiales'), list) else [resd]
        pending = dict(cambios)  # copia para marcar los encontrados
        updated = 0

        for m_idx, mat in enumerate(materiales, start=1):
            for t_idx, t in enumerate(mat.get('tableros') or [], start=1):
                for p_idx, pi in enumerate(t.get('piezas') or [], start=1):
                    pid = f'm{m_idx}t{t_idx}p{p_idx}'
                    if pid in pending:
                        pi['estado'] = pending.pop(pid)
                        updated += 1
                    # Compatibilidad con formato antiguo t{t}p{i}
                    pid_legacy = f't{t_idx}p{p_idx}'
                    if pid_legacy in pending:
                        pi['estado'] = pending.pop(pid_legacy)
                        updated += 1
                    if 'estado' not in pi:
                        pi['estado'] = 'pendiente'

        if updated == 0:
            return JsonResponse({'success': False, 'message': 'Ninguna pieza encontrada'}, status=404)

        if 'materiales' in resd:
            p.resultado_optimizacion = resd
        else:
            p.resultado_optimizacion = materiales[0]
        p.save(update_fields=['resultado_optimizacion'])

    try:
        AuditLog.objects.create(
            actor=request.user,
            organizacion=p.organizacion,
            verb='EDIT',
            target_model='Proyecto',
            target_id=str(p.id),
            target_repr=p.codigo,
            changes={'batch_piezas': list(cambios.keys()), 'count': updated},
        )
    except Exception:
        pass

    return JsonResponse({'success': True, 'updated': updated})


@csrf_exempt
@login_required
@require_http_methods(["PATCH"])
def operador_proyecto_estado_api(request: HttpRequest, proyecto_id: int):
    """PATCH /api/operador/proyectos/<id>/estado
    Body: { estado: 'en_proceso'|'completado'|... }
    Actualiza el estado del proyecto con validación de scope.
    """
    ctx = get_auth_context(request)
    base_qs = Proyecto.objects
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
    p = get_object_or_404(base_qs, id=proyecto_id)
    if ctx.get('role') == 'operador' and p.operador_id != request.user.id:
        return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)
    try:
        payload = _json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'success': False, 'message': 'Payload inválido'}, status=400)
    estado = (payload.get('estado') or '').strip()
    # Validar contra choices
    valid_estados = {choice[0] for choice in Proyecto.ESTADOS}
    if estado not in valid_estados:
        return JsonResponse({'success': False, 'message': 'Estado inválido'}, status=400)
    p.estado = estado
    p.save(update_fields=['estado'])
    try:
        AuditLog.objects.create(
            actor=request.user,
            organizacion=p.organizacion,
            verb='UPDATE',
            target_model='Proyecto',
            target_id=str(p.id),
            target_repr=p.codigo,
            changes={'estado': estado},
        )
    except Exception:
        pass
    return JsonResponse({'success': True})


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def operador_proyecto_marcar_todas_cortadas_api(request: HttpRequest, proyecto_id: int):
    """POST /api/operador/proyectos/<id>/piezas/marcar-todas
    Body: { estado: 'cortada' }  (por ahora solo soporta 'cortada')
    Marca TODAS las piezas del resultado como 'cortada' y persiste el JSON.
    """
    ctx = get_auth_context(request)
    base_qs = Proyecto.objects
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
    p = get_object_or_404(base_qs, id=proyecto_id)
    if ctx.get('role') == 'operador' and p.operador_id != request.user.id:
        return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)
    try:
        payload = _json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        payload = {}
    estado = (payload.get('estado') or 'cortada').strip()
    if estado != 'cortada':
        return JsonResponse({'success': False, 'message': 'Solo se permite marcar como cortada.'}, status=400)
    res = p.resultado_optimizacion
    if not res:
        return JsonResponse({'success': False, 'message': 'Proyecto sin resultado'}, status=404)
    try:
        import copy
        resd = copy.deepcopy(_parse_resultado(res))
    except Exception:
        return JsonResponse({'success': False, 'message': 'Resultado inválido'}, status=500)
    materiales = resd.get('materiales') if isinstance(resd.get('materiales'), list) else [resd]
    count = 0
    for mat in materiales:
        for t in (mat.get('tableros') or []):
            for pi in (t.get('piezas') or []):
                if pi.get('estado') != 'cortada':
                    pi['estado'] = 'cortada'
                    count += 1
    # Persistir — asignar dict directamente al JSONField (no json.dumps)
    if 'materiales' in resd:
        p.resultado_optimizacion = resd
    else:
        p.resultado_optimizacion = materiales[0]
    p.save(update_fields=['resultado_optimizacion'])
    try:
        AuditLog.objects.create(
            actor=request.user,
            organizacion=p.organizacion,
            verb='EDIT',
            target_model='Proyecto',
            target_id=str(p.id),
            target_repr=p.codigo,
            changes={'bulk_piezas': 'cortada', 'count': count},
        )
    except Exception:
        pass
    return JsonResponse({'success': True, 'updated': count})


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def operador_proyecto_completar_api(request: HttpRequest, proyecto_id: int):
    """POST /api/operador/proyectos/<id>/completar
    Valida que todas las piezas estén 'cortada' y marca el proyecto como 'completado'.
    """
    ctx = get_auth_context(request)
    base_qs = Proyecto.objects
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
    p = get_object_or_404(base_qs, id=proyecto_id)
    if ctx.get('role') == 'operador' and p.operador_id != request.user.id:
        return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)
    res = p.resultado_optimizacion
    if not res:
        return JsonResponse({'success': False, 'message': 'Proyecto sin resultado'}, status=404)
    try:
        resd = _parse_resultado(res)
    except Exception:
        return JsonResponse({'success': False, 'message': 'Resultado inválido'}, status=500)
    materiales = resd.get('materiales') if isinstance(resd.get('materiales'), list) else [resd]
    missing = 0
    total = 0
    for mat in materiales:
        for t in (mat.get('tableros') or []):
            for pi in (t.get('piezas') or []):
                total += 1
                if pi.get('estado') != 'cortada':
                    missing += 1
    if missing > 0:
        return JsonResponse({'success': False, 'message': f'Faltan {missing} pieza(s) por cortar de {total}.'}, status=400)

    # Verificar si alguna pieza tiene tapacanto para determinar el estado destino
    tiene_tapacanto = False
    for mat in materiales:
        tap = mat.get('tapacanto') or {}
        tap_nombre = (tap.get('nombre') or '').strip()
        if tap_nombre:
            tiene_tapacanto = True
            break
        # También revisar a nivel de pieza
        if not tiene_tapacanto:
            for t in (mat.get('tableros') or []):
                for pi in (t.get('piezas') or []):
                    tc = pi.get('tapacantos') or {}
                    if any(tc.values()):
                        tiene_tapacanto = True
                        break
                if tiene_tapacanto:
                    break
        if tiene_tapacanto:
            break

    # Si hay tapacanto pendiente → enchapado_pendiente, si no → completado directamente
    nuevo_estado = 'enchapado_pendiente' if tiene_tapacanto else 'completado'
    p.estado = nuevo_estado
    p.save(update_fields=['estado'])
    try:
        AuditLog.objects.create(
            actor=request.user,
            organizacion=p.organizacion,
            verb='UPDATE',
            target_model='Proyecto',
            target_id=str(p.id),
            target_repr=p.codigo,
            changes={'estado': nuevo_estado},
        )
    except Exception:
        pass
    # Notificar a todos los enchapadores de la organización si hay enchapado pendiente
    if nuevo_estado == 'enchapado_pendiente':
        try:
            from django.contrib.auth.models import User as _User
            from core.models import UsuarioPerfilOptimizador as _UP
            enchapadores = _User.objects.filter(
                usuarioperfiloptimizador__rol='enchapador',
                usuarioperfiloptimizador__organizacion_id=p.organizacion_id,
            )
            for enc in enchapadores:
                NotificacionEnchapador.objects.create(
                    destinatario=enc,
                    proyecto_nombre=p.nombre or '',
                    proyecto_id=p.id,
                )
        except Exception:
            pass
    return JsonResponse({'success': True, 'estado': nuevo_estado, 'enchapado_pendiente': nuevo_estado == 'enchapado_pendiente'})


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def operador_tablero_completado_api(request: HttpRequest, proyecto_id: int):
    """POST /api/operador/proyectos/<id>/tablero-completado
    Body: { mat_idx: int, tab_idx: int }
    Marca todas las piezas del tablero indicado como 'cortada', persiste el JSON
    y cambia el estado del proyecto a 'en_proceso' si no estaba ya completado.
    Devuelve también si TODOS los tableros del proyecto ya están completos.
    """
    ctx = get_auth_context(request)
    base_qs = Proyecto.objects
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
    p = get_object_or_404(base_qs, id=proyecto_id)
    if ctx.get('role') == 'operador' and p.operador_id != request.user.id:
        return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)

    try:
        payload = _json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        payload = {}

    mat_idx = payload.get('mat_idx')
    tab_idx = payload.get('tab_idx')
    if mat_idx is None or tab_idx is None:
        return JsonResponse({'success': False, 'message': 'Se requieren mat_idx y tab_idx.'}, status=400)

    res = p.resultado_optimizacion
    if not res:
        return JsonResponse({'success': False, 'message': 'Proyecto sin resultado.'}, status=404)
    try:
        import copy
        resd = copy.deepcopy(_parse_resultado(res))
    except Exception:
        return JsonResponse({'success': False, 'message': 'Resultado inválido.'}, status=500)

    materiales = resd.get('materiales') if isinstance(resd.get('materiales'), list) else [resd]

    try:
        tablero = materiales[int(mat_idx)]['tableros'][int(tab_idx)]
    except (IndexError, KeyError, TypeError):
        return JsonResponse({'success': False, 'message': 'Tablero no encontrado.'}, status=404)

    # Marcar todas las piezas de este tablero como cortada
    count = 0
    for pi in (tablero.get('piezas') or []):
        if pi.get('estado') != 'cortada':
            pi['estado'] = 'cortada'
            count += 1

    # Persistir — asignar dict directamente al JSONField (no json.dumps)
    if 'materiales' in resd:
        p.resultado_optimizacion = resd
    else:
        p.resultado_optimizacion = materiales[0]

    # Actualizar estado del proyecto a en_proceso si corresponde
    campos_a_guardar = ['resultado_optimizacion']
    if p.estado not in ('completado', 'en_proceso', 'produccion'):
        p.estado = 'en_proceso'
        campos_a_guardar.append('estado')

    p.save(update_fields=campos_a_guardar)

    # Verificar si TODOS los tableros de todos los materiales están completamente cortados
    todos_cortados = True
    total_tableros = 0
    tableros_completos = 0
    for mat in materiales:
        for t in (mat.get('tableros') or []):
            total_tableros += 1
            piezas = t.get('piezas') or []
            if piezas and all(pi.get('estado') == 'cortada' for pi in piezas):
                tableros_completos += 1
            else:
                todos_cortados = False

    try:
        AuditLog.objects.create(
            actor=request.user,
            organizacion=p.organizacion,
            verb='EDIT',
            target_model='Proyecto',
            target_id=str(p.id),
            target_repr=p.codigo,
            changes={'tablero_completado': f'mat={mat_idx},tab={tab_idx}', 'piezas_marcadas': count},
        )
    except Exception:
        pass

    return JsonResponse({
        'success': True,
        'updated': count,
        'todos_tableros_completos': todos_cortados,
        'tableros_completos': tableros_completos,
        'total_tableros': total_tableros,
    })


# ── Impresoras CUPS ────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def impresoras_list_api(request: HttpRequest):
    """GET /api/impresoras  →  lista de impresoras CUPS disponibles."""
    try:
        result = subprocess.run(
            ['lpstat', '-p'],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
        printers = []
        for line in lines:
            # formato: "la impresora NOMBRE está ..."
            parts = line.split()
            if len(parts) >= 3:
                printers.append(parts[2])
        # impresora por defecto
        default_result = subprocess.run(
            ['lpstat', '-d'],
            capture_output=True, text=True, timeout=5
        )
        default_name = ''
        for line in default_result.stdout.splitlines():
            if ':' in line:
                default_name = line.split(':', 1)[-1].strip()
                break
        return JsonResponse({'success': True, 'impresoras': printers, 'default': default_name})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e), 'impresoras': [], 'default': ''}, status=500)


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def imprimir_etiqueta_pieza_api(request: HttpRequest, proyecto_id: int, pieza_id: str):
    """POST /api/operador/proyectos/<id>/piezas/<pieza_id>/imprimir-etiqueta
    Body JSON: { impresora: str (opcional), copias: int (opcional, default 1) }
    Genera un PDF de etiqueta con reportlab y lo envía a la impresora CUPS.
    """
    ctx = get_auth_context(request)
    base_qs = Proyecto.objects
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))

    # Traer campos necesarios incluyendo cliente y public_id
    row = base_qs.filter(id=proyecto_id).select_related('cliente').values(
        'id', 'resultado_optimizacion', 'public_id', 'cliente__nombre'
    ).first()
    if not row:
        from django.http import Http404
        raise Http404

    try:
        payload = _json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        payload = {}

    impresora = (payload.get('impresora') or '').strip() or None
    copias = max(1, min(10, int(payload.get('copias') or 1)))

    # Buscar pieza en el resultado
    res = row['resultado_optimizacion']
    if not res:
        return JsonResponse({'success': False, 'message': 'Proyecto sin resultado'}, status=404)
    try:
        resd = _parse_resultado(res)
    except Exception:
        return JsonResponse({'success': False, 'message': 'Resultado inválido'}, status=500)

    materiales = resd.get('materiales') if isinstance(resd.get('materiales'), list) else [resd]
    pieza_data = None
    material_nombre = '—'

    # pieza_id tiene formato m{m}t{t}p{i} (generado dinámicamente, no está en el JSON)
    mti = re.match(r'^m(\d+)t(\d+)p(\d+)$', pieza_id or '')
    if mti:
        target_m = int(mti.group(1))
        target_t = int(mti.group(2))
        target_p = int(mti.group(3))
        for m_idx, mat in enumerate(materiales, start=1):
            if m_idx != target_m:
                continue
            mat_nombre = mat.get('material') or mat.get('nombre') or (mat.get('meta') or {}).get('material') or '—'
            for t_idx, tablero in enumerate(mat.get('tableros') or [], start=1):
                if t_idx != target_t:
                    continue
                piezas = tablero.get('piezas') or []
                for i, pi in enumerate(piezas, start=1):
                    if i == target_p:
                        pieza_data = pi
                        material_nombre = mat_nombre
                        break
                break
            break
    else:
        # Compatibilidad: formato antiguo t{t}p{i}
        for mat in materiales:
            mat_nombre = mat.get('material') or mat.get('nombre') or '—'
            for t_idx, tablero in enumerate(mat.get('tableros') or [], start=1):
                for i, pi in enumerate(tablero.get('piezas') or [], start=1):
                    pid = f"t{t_idx}p{i}"
                    if pid == pieza_id:
                        pieza_data = pi
                        material_nombre = mat_nombre
                        break
                if pieza_data:
                    break
            if pieza_data:
                break

    if not pieza_data:
        return JsonResponse({'success': False, 'message': 'Pieza no encontrada'}, status=404)

    pw_mm = int(pieza_data.get('ancho') or 0)
    ph_mm = int(pieza_data.get('largo') or 0)
    nombre  = str(pieza_data.get('nombre') or pieza_id)
    tc      = pieza_data.get('tapacantos') or {}
    veta    = pieza_data.get('veta') or ''

    # Datos del proyecto para el header de la etiqueta
    folio_id   = str(row.get('public_id') or proyecto_id)
    cliente_n  = str(row.get('cliente__nombre') or '').strip()

    # ── Nombre del material ────────────────────────────────────────────────────
    if isinstance(material_nombre, dict):
        material_nombre = material_nombre.get('nombre') or material_nombre.get('codigo') or '—'

    # ── Contar cuántas piezas con el mismo nombre hay en todos los tableros ────
    # Para mostrar pieza N (idx/total)
    if mti:
        target_m2 = int(mti.group(1)); target_t2 = int(mti.group(2)); target_p2 = int(mti.group(3))
        mismo_nombre = [p for mat in materiales for t in (mat.get('tableros') or [])
                        for p in (t.get('piezas') or []) if str(p.get('nombre') or '') == nombre]
        pieza_idx_global = 0
        cnt = 0
        for mat2 in materiales:
            for t_i, tab2 in enumerate(mat2.get('tableros') or [], 1):
                for p_i, pp in enumerate(tab2.get('piezas') or [], 1):
                    if str(pp.get('nombre') or '') == nombre:
                        cnt += 1
                        if mat2 is materiales[target_m2-1] and t_i == target_t2 and p_i == target_p2:
                            pieza_idx_global = cnt
        pieza_count_str = f'({pieza_idx_global}/{cnt})' if cnt > 1 else ''
    else:
        pieza_count_str = ''

    # ── Generar ZPL (nativo Zebra — sin PDF, sin ReportLab) ───────────────────
    # Etiqueta 70 × 50 mm a 300 dpi → 827 × 591 dots
    DPI = 300
    def mm2d(v): return int(v * DPI / 25.4)
    def _z(s, mx=28): return str(s)[:mx].replace('^', '').replace('~', '')

    LW = mm2d(70); LH = mm2d(50)
    M  = mm2d(2)   # margen lateral

    # ── Header: 2 líneas ~10mm ────────────────────────────────────────────────
    HDR_H = mm2d(10)

    # Nombre pieza + contador
    nombre_label = _z(nombre + (' ' + pieza_count_str if pieza_count_str else ''), 30)

    # ── Zona dibujo pieza: ~25mm de alto ──────────────────────────────────────
    DA_TOP = HDR_H + mm2d(1)
    DA_W   = LW - 2 * M
    DA_H   = mm2d(25)
    scale  = min(DA_W / max(pw_mm, 1), DA_H / max(ph_mm, 1)) * 0.75
    rw = int(pw_mm * scale); rh = int(ph_mm * scale)
    rx = M + (DA_W - rw) // 2
    ry = DA_TOP + (DA_H - rh) // 2

    # Tapacantos en texto ASCII (las Zebra no soportan Unicode en fuentes internas)
    tc_parts = []
    if tc.get('arriba'):    tc_parts.append('Arr')
    if tc.get('derecha'):   tc_parts.append('Der')
    if tc.get('abajo'):     tc_parts.append('Aba')
    if tc.get('izquierda'): tc_parts.append('Izq')
    tc_str = ' '.join(tc_parts) if tc_parts else '-'

    veta_str = {'horizontal': 'H', 'vertical': 'V'}.get(veta, '')

    zpl_lines = [
        '^XA',
        '^LH0,0',
        f'^PW{LW}',
        f'^LL{LH}',
        '^MNY',         # media type: non-continuous (etiquetas con gap)
        '^MTT',         # media tracking: transmissive
        f'^LL{LH}',     # repetir LL despues de MN para que tome efecto
        '^CI28',        # codificación UTF-8
        # ── Línea 1: nombre pieza + contador ──────────────────────────────────
        f'^FO{M},{M}^CF0,32^FD{nombre_label}^FS',
        # ── Línea 2: material ─────────────────────────────────────────────────
        f'^FO{M},{mm2d(5.5)}^CF0,24^FD{_z(material_nombre, 28)}^FS',
        # ── Separador horizontal ──────────────────────────────────────────────
        f'^FO0,{HDR_H}^GB{LW},2,2^FS',
        # ── Rectángulo pieza (fondo blanco + borde) ──────────────────────────
        f'^FO{rx},{ry}^GB{rw},{rh},2,W^FS',
        f'^FO{rx},{ry}^GB{rw},{rh},2^FS',
    ]

    # Tapacantos: marcas internas
    TC_OFF = max(3, int(min(rw, rh) * 0.07))
    BORDER = 3
    if tc.get('arriba'):
        zpl_lines.append(f'^FO{rx},{ry + TC_OFF}^GB{rw},{BORDER},{BORDER}^FS')
    if tc.get('abajo'):
        zpl_lines.append(f'^FO{rx},{ry + rh - TC_OFF - BORDER}^GB{rw},{BORDER},{BORDER}^FS')
    if tc.get('izquierda'):
        zpl_lines.append(f'^FO{rx + TC_OFF},{ry}^GB{BORDER},{rh},{BORDER}^FS')
    if tc.get('derecha'):
        zpl_lines.append(f'^FO{rx + rw - TC_OFF - BORDER},{ry}^GB{BORDER},{rh},{BORDER}^FS')

    # ── Cotas: ancho arriba del rect, largo a la derecha ─────────────────────
    cota_size = 22
    zpl_lines.append(f'^FO{rx},{ry - mm2d(4)}^CF0,{cota_size}^FD{pw_mm}mm^FS')
    cota_largo_y = ry + max(4, (rh - cota_size) // 2)
    zpl_lines.append(f'^FO{rx + rw + mm2d(1)},{cota_largo_y}^CF0,{cota_size}^FD{ph_mm}mm^FS')

    # ── Pie: Tc + Veta en una línea ──────────────────────────────────────────
    PIE_Y = LH - mm2d(5)
    pie_text = f'Tc:{tc_str}'
    if veta_str:
        pie_text += f'  V:{veta_str}'
    zpl_lines.append(f'^FO{M},{PIE_Y}^CF0,22^FD{_z(pie_text, 30)}^FS')

    zpl_lines += [
        '^JUS',         # guardar configuración (PW, LL) en NVRAM de la impresora
        f'^PQ{copias}',
        '^XZ',
    ]

    zpl = '\n'.join(zpl_lines)

    # Devolver el ZPL como texto — el navegador lo envía a Zebra Browser Print local
    from django.http import HttpResponse
    return HttpResponse(zpl, content_type='text/plain; charset=utf-8')


# ---------------------------------------------------------------------------
# RESUMEN DE PROYECTO — popup de previsualización
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["GET"])
def proyecto_resumen_api(request, proyecto_id: int):
    """GET /api/proyectos/<id>/resumen
    Devuelve un resumen calculado del proyecto: materiales, tableros, piezas,
    cortes, metros de tapacanto y porcentaje de avance.

    Estructura real de resultado_optimizacion:
      { materiales: [ { material: {nombre, codigo}, tapacanto: {nombre, codigo},
                        tableros: [ { piezas: [ {nombre, ancho, largo,
                                                  indiceUnidad, totalUnidades,
                                                  estado?, tapacantos:{arriba,abajo,izq,der} } ] } ] } ],
        total_piezas, total_tableros, ... }
    """
    import json as _json
    from core.auth_utils import get_auth_context
    ctx = get_auth_context(request)
    qs = Proyecto.objects.select_related('cliente', 'operador')
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        qs = qs.filter(organizacion_id=ctx.get('organization_id'))
    p = get_object_or_404(qs, id=proyecto_id)

    # resultado_optimizacion puede ser dict o string JSON
    raw = p.resultado_optimizacion or {}
    if isinstance(raw, str):
        try:
            resultado = _json.loads(raw)
        except Exception:
            resultado = {}
    else:
        resultado = raw

    materiales_raw = resultado.get('materiales') or []

    total_piezas_global = 0
    total_piezas_cortadas = 0
    total_tableros = 0
    total_cortes = 0
    metros_tapacanto = 0.0
    tiene_tapacanto = False
    materiales_resumen = []

    for mat in materiales_raw:
        # material es un dict {nombre, codigo, ...}
        mat_info = mat.get('material') or {}
        mat_nombre = mat_info.get('nombre') or mat_info.get('codigo') or mat.get('nombre') or '—'

        # tapacanto es un dict {nombre, codigo}
        tap_info = mat.get('tapacanto') or {}
        tap_nombre = (tap_info.get('nombre') or tap_info.get('codigo') or '').strip()

        tableros = mat.get('tableros') or []
        mat_tableros = len(tableros)

        # Conteo de piezas: cada (nombre, indiceUnidad) es una pieza distinta.
        # totalUnidades indica cuántas unidades del tipo hay (no útil para contar).
        piezas_vistas: set = set()    # set de (nombre, indiceUnidad)
        piezas_cortadas_vistas: set = set()
        mat_tc_metros = 0.0
        mat_cortes = 0

        for t in tableros:
            piezas = t.get('piezas') or []
            piezas_activas = []
            for pi in piezas:
                estado_pi = (pi.get('estado') or 'pendiente').strip()
                if estado_pi == 'descartada':
                    continue
                piezas_activas.append(pi)

                clave = (pi.get('nombre') or '', int(pi.get('indiceUnidad') or 0))
                piezas_vistas.add(clave)
                if estado_pi == 'cortada':
                    piezas_cortadas_vistas.add(clave)

                # Metros de tapacanto por pieza (dimensiones en mm → metros)
                tc = pi.get('tapacantos') or {}
                ancho_m = float(pi.get('ancho') or 0) / 1000
                largo_m = float(pi.get('largo') or 0) / 1000
                if tc.get('arriba'):    mat_tc_metros += ancho_m
                if tc.get('abajo'):     mat_tc_metros += ancho_m
                if tc.get('izquierda'): mat_tc_metros += largo_m
                if tc.get('derecha'):   mat_tc_metros += largo_m
                if any(tc.get(k) for k in ('arriba', 'abajo', 'izquierda', 'derecha')):
                    tiene_tapacanto = True

            # Cortes guillotina: filas + columnas únicas de corte en este tablero
            if piezas_activas:
                xs = set(round(pi.get('x', 0)) for pi in piezas_activas)
                ys = set(round(pi.get('y', 0)) for pi in piezas_activas)
                mat_cortes += max(0, len(xs) - 1) + max(0, len(ys) - 1)

        if tap_nombre:
            tiene_tapacanto = True

        # Totales de piezas para este material
        mat_total_piezas = len(piezas_vistas)
        mat_cortadas = len(piezas_cortadas_vistas)

        total_piezas_global += mat_total_piezas
        total_piezas_cortadas += mat_cortadas
        total_tableros += mat_tableros
        total_cortes += mat_cortes
        metros_tapacanto += mat_tc_metros

        materiales_resumen.append({
            'nombre': mat_nombre,
            'tableros': mat_tableros,
            'piezas': mat_total_piezas,
            'tapacanto': tap_nombre,
            'tiene_tapacanto': bool(tap_nombre) or mat_tc_metros > 0,
        })

    pct_avance = 0
    if total_piezas_global > 0:
        pct_avance = round(total_piezas_cortadas * 100 / total_piezas_global, 1)

    # Si el proyecto no ha entrado a producción las piezas no tienen estado → 0%
    estado_sin_avance = p.estado in ('borrador', 'optimizado', 'aprobado', 'asignado', 'enchapado_pendiente')
    if estado_sin_avance:
        pct_avance = 0
        total_piezas_cortadas = 0

    # Usar totales del header JSON si el parseo de piezas da cero (proyecto nuevo)
    if total_piezas_global == 0 and resultado.get('total_piezas'):
        total_piezas_global = int(resultado['total_piezas'])
    if total_tableros == 0 and resultado.get('total_tableros'):
        total_tableros = int(resultado['total_tableros'])

    # Si no hay detalle por material pero sí hay totales globales, crear entry genérico
    if not materiales_resumen and (total_piezas_global > 0 or total_tableros > 0):
        materiales_resumen = [{
            'nombre': '—',
            'tableros': total_tableros,
            'piezas': total_piezas_global,
            'tapacanto': '',
            'tiene_tapacanto': tiene_tapacanto,
        }]

    return JsonResponse({
        'id': p.id,
        'codigo': p.public_id or p.codigo,
        'nombre': p.nombre,
        'cliente': p.cliente.nombre if p.cliente else '—',
        'estado': p.estado,
        'estado_display': p.get_estado_display(),
        'operador': (p.operador.get_full_name() or p.operador.username) if p.operador else None,
        'total_materiales': len(materiales_resumen),
        'total_tableros': total_tableros,
        'total_piezas': total_piezas_global,
        'total_piezas_cortadas': total_piezas_cortadas,
        'total_cortes': total_cortes,
        'metros_tapacanto': round(metros_tapacanto, 2),
        'tiene_tapacanto': tiene_tapacanto,
        'pct_avance': pct_avance,
        'materiales': materiales_resumen,
    })


# ---------------------------------------------------------------------------
# RESUMEN BATCH — precarga múltiples proyectos en una sola petición
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(["GET"])
def proyectos_resumen_batch_api(request):
    """GET /api/proyectos/resumen-batch?ids=1,2,3
    Devuelve los resúmenes de varios proyectos en una sola llamada.
    Usado para precargar datos al cargar la página.
    """
    import json as _json
    from core.auth_utils import get_auth_context
    ctx = get_auth_context(request)

    ids_raw = request.GET.get('ids', '')
    try:
        ids = [int(x) for x in ids_raw.split(',') if x.strip().isdigit()]
    except Exception:
        ids = []

    if not ids:
        return JsonResponse({'resumenes': {}})

    qs = Proyecto.objects.select_related('cliente', 'operador').filter(id__in=ids).defer(
        'configuracion', 'descripcion'
    )
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        qs = qs.filter(organizacion_id=ctx.get('organization_id'))

    def _calcular(p):
        raw = p.resultado_optimizacion or {}
        if isinstance(raw, str):
            try:
                resultado = _json.loads(raw)
            except Exception:
                resultado = {}
        else:
            resultado = raw

        materiales_raw = resultado.get('materiales') or []
        total_piezas_global = 0
        total_piezas_cortadas = 0
        total_tableros = 0
        total_cortes = 0
        metros_tapacanto = 0.0
        tiene_tapacanto = False
        materiales_resumen = []

        for mat in materiales_raw:
            mat_info = mat.get('material') or {}
            mat_nombre = mat_info.get('nombre') or mat_info.get('codigo') or mat.get('nombre') or '—'
            tap_info = mat.get('tapacanto') or {}
            tap_nombre = (tap_info.get('nombre') or tap_info.get('codigo') or '').strip()
            tableros = mat.get('tableros') or []
            mat_tableros = len(tableros)
            piezas_vistas = set()
            piezas_cortadas_vistas = set()
            mat_tc_metros = 0.0
            mat_cortes = 0

            for t in tableros:
                piezas_activas = []
                for pi in (t.get('piezas') or []):
                    if (pi.get('estado') or '').strip() == 'descartada':
                        continue
                    piezas_activas.append(pi)
                    clave = (pi.get('nombre') or '', int(pi.get('indiceUnidad') or 0))
                    piezas_vistas.add(clave)
                    if (pi.get('estado') or '').strip() == 'cortada':
                        piezas_cortadas_vistas.add(clave)
                    tc = pi.get('tapacantos') or {}
                    ancho_m = float(pi.get('ancho') or 0) / 1000
                    largo_m = float(pi.get('largo') or 0) / 1000
                    if tc.get('arriba'):    mat_tc_metros += ancho_m
                    if tc.get('abajo'):     mat_tc_metros += ancho_m
                    if tc.get('izquierda'): mat_tc_metros += largo_m
                    if tc.get('derecha'):   mat_tc_metros += largo_m
                    if any(tc.get(k) for k in ('arriba', 'abajo', 'izquierda', 'derecha')):
                        tiene_tapacanto = True
                if piezas_activas:
                    xs = set(round(pi.get('x', 0)) for pi in piezas_activas)
                    ys = set(round(pi.get('y', 0)) for pi in piezas_activas)
                    mat_cortes += max(0, len(xs) - 1) + max(0, len(ys) - 1)

            if tap_nombre:
                tiene_tapacanto = True

            mat_total_piezas = len(piezas_vistas)
            mat_cortadas = len(piezas_cortadas_vistas)
            total_piezas_global += mat_total_piezas
            total_piezas_cortadas += mat_cortadas
            total_tableros += mat_tableros
            total_cortes += mat_cortes
            metros_tapacanto += mat_tc_metros
            materiales_resumen.append({
                'nombre': mat_nombre,
                'tableros': mat_tableros,
                'piezas': mat_total_piezas,
                'tapacanto': tap_nombre,
            })

        pct_avance = 0
        if total_piezas_global > 0:
            pct_avance = round(total_piezas_cortadas * 100 / total_piezas_global, 1)
        if p.estado in ('borrador', 'optimizado', 'aprobado', 'asignado', 'enchapado_pendiente'):
            pct_avance = 0
            total_piezas_cortadas = 0
        if total_piezas_global == 0 and resultado.get('total_piezas'):
            total_piezas_global = int(resultado['total_piezas'])
        if total_tableros == 0 and resultado.get('total_tableros'):
            total_tableros = int(resultado['total_tableros'])

        # Si no hay detalle por material pero sí hay totales globales, crear entry genérico
        if not materiales_resumen and (total_piezas_global > 0 or total_tableros > 0):
            materiales_resumen = [{
                'nombre': '—',
                'tableros': total_tableros,
                'piezas': total_piezas_global,
                'tapacanto': '',
            }]

        return {
            'id': p.id,
            'codigo': p.public_id or p.codigo,
            'cliente': p.cliente.nombre if p.cliente else '—',
            'estado': p.estado,
            'estado_display': p.get_estado_display(),
            'total_tableros': total_tableros,
            'total_piezas': total_piezas_global,
            'total_piezas_cortadas': total_piezas_cortadas,
            'total_cortes': total_cortes,
            'metros_tapacanto': round(metros_tapacanto, 2),
            'tiene_tapacanto': tiene_tapacanto,
            'pct_avance': pct_avance,
            'materiales': materiales_resumen,
        }

    resumenes = {}
    for p in qs:
        try:
            resumenes[str(p.id)] = _calcular(p)
        except Exception:
            resumenes[str(p.id)] = None

    return JsonResponse({'resumenes': resumenes})
