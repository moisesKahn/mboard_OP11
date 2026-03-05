import re
from django.contrib.auth import authenticate
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.db.models import Count
from core.models import UsuarioPerfilOptimizador, Cliente, Proyecto, AuditLog, OptimizationRun
from core.auth_utils import jwt_encode, get_auth_context


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
        resd = _json.loads(res) if isinstance(res, str) else res
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
                'cortes': t.get('cortes') or [],
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
    if estado not in ('pendiente','en_corte','cortada','descartada'):
        return JsonResponse({'success': False, 'message': 'Estado inválido'}, status=400)

    res = p.resultado_optimizacion
    if not res:
        return JsonResponse({'success': False, 'message': 'Proyecto sin resultado'}, status=404)
    try:
        resd = _json.loads(res) if isinstance(res, str) else res
    except Exception:
        return JsonResponse({'success': False, 'message': 'Resultado inválido'}, status=500)

    materiales = resd.get('materiales') if isinstance(resd.get('materiales'), list) else [resd]
    updated = False
    # Intentar formato nuevo: m{m}t{t}p{i}
    mti = re.match(r'^m(\d+)t(\d+)p(\d+)$', pieza_id or '')
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
        # no-op

    if not updated:
        return JsonResponse({'success': False, 'message': 'Pieza no encontrada'}, status=404)

    # Persistir
    if 'materiales' in resd:
        p.resultado_optimizacion = _json.dumps(resd, ensure_ascii=False)
    else:
        p.resultado_optimizacion = _json.dumps(materiales[0], ensure_ascii=False)
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
        resd = _json.loads(res) if isinstance(res, str) else res
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
    # Persistir
    if 'materiales' in resd:
        p.resultado_optimizacion = _json.dumps(resd, ensure_ascii=False)
    else:
        p.resultado_optimizacion = _json.dumps(materiales[0], ensure_ascii=False)
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
        resd = _json.loads(res) if isinstance(res, str) else res
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
    # Ok: completar
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
            changes={'estado': 'completado'},
        )
    except Exception:
        pass
    return JsonResponse({'success': True})


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
        resd = _json.loads(res) if isinstance(res, str) else res
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

    # Persistir
    if 'materiales' in resd:
        p.resultado_optimizacion = _json.dumps(resd, ensure_ascii=False)
    else:
        p.resultado_optimizacion = _json.dumps(materiales[0], ensure_ascii=False)

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

