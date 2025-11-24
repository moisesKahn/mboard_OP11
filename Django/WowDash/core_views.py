from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q, Count
from django.db.models.functions import TruncMonth, TruncWeek
from core.models import Cliente, Proyecto, Organizacion
from core.auth_utils import get_auth_context
from core.models import UsuarioPerfilOptimizador
from core.forms import ClienteForm, ProyectoForm

@login_required
def organizacion_detalle(request, organizacion_id):
    """Perfil/detalle de una organización: datos generales, usuarios por rol,
    métricas de proyectos/optimizaciones y últimos proyectos."""
    org = get_object_or_404(Organizacion, id=organizacion_id)

    # Usuarios asociados y conteo por rol
    usuarios = UsuarioPerfilOptimizador.objects.filter(organizacion=org)
    conteo_roles = usuarios.values('rol').annotate(cantidad=Count('id'))
    rol_map = {item['rol']: item['cantidad'] for item in conteo_roles}

    # Métricas de proyectos (optimizaciones)
    proyectos_org = Proyecto.objects.filter(cliente__organizacion=org)
    total_proyectos = proyectos_org.count()
    ultimos_proyectos = proyectos_org.select_related('cliente').order_by('-fecha_creacion')[:10]

    # Series temporales por mes (último año) y por semana (últimas 12 semanas)
    from django.utils import timezone
    from datetime import timedelta
    ahora = timezone.now()
    inicio_mes = (ahora - timedelta(days=365)).replace(day=1)
    inicio_semana = ahora - timedelta(weeks=12)

    serie_mes_qs = (
        proyectos_org.filter(fecha_creacion__gte=inicio_mes)
        .annotate(periodo=TruncMonth('fecha_creacion'))
        .values('periodo')
        .annotate(total=Count('id'))
        .order_by('periodo')
    )
    series_mensual = [
        { 'mes': item['periodo'].strftime('%Y-%m'), 'total': item['total'] }
        for item in serie_mes_qs
    ]

    serie_semana_qs = (
        proyectos_org.filter(fecha_creacion__gte=inicio_semana)
        .annotate(periodo=TruncWeek('fecha_creacion'))
        .values('periodo')
        .annotate(total=Count('id'))
        .order_by('periodo')
    )
    series_semanal = [
        { 'semana': item['periodo'].strftime('%Y-%m-%d'), 'total': item['total'] }
        for item in serie_semana_qs
    ]

    context = {
        'title': f"Organización: {org.nombre}",
        'subTitle': 'Perfil de Organización',
        'organizacion': org,
        'usuarios': usuarios.select_related('user'),
        'conteo_roles': rol_map,
        'total_proyectos': total_proyectos,
        'ultimos_proyectos': ultimos_proyectos,
        'series_mensual': series_mensual,
        'series_semanal': series_semanal,
    }
    return render(request, 'organizaciones/organizacion_detalle.html', context)
def clientes_list(request):
    """Lista de clientes"""
    ctx = get_auth_context(request)
    # Filtros de búsqueda
    search = request.GET.get('search', '')
    try:
        page_size = max(1, min(100, int(request.GET.get('page_size', '10'))))
    except ValueError:
        page_size = 10
    try:
        page = max(1, int(request.GET.get('page', '1')))
    except ValueError:
        page = 1
    
    # Query base
    clientes = Cliente.objects.filter(activo=True)
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        clientes = clientes.filter(organizacion_id=ctx.get('organization_id'))
    
    # Aplicar filtros
    if search:
        clientes = clientes.filter(
            Q(rut__icontains=search) | 
            Q(nombre__icontains=search) |
            Q(organizacion__nombre__icontains=search) |
            Q(email__icontains=search)
        )
    
    # Orden y paginación
    clientes = clientes.order_by('-fecha_creacion') if hasattr(Cliente, 'fecha_creacion') else clientes.order_by('-id')
    total = clientes.count()
    start = (page - 1) * page_size
    end = start + page_size
    clientes = clientes[start:end]
    total_pages = (total + page_size - 1) // page_size

    context = {
        "title": "Lista de Clientes",
        "subTitle": "Clientes",
        "clientes": clientes,
        "search": search,
        "page": page,
        "page_size": page_size,
        "page_sizes": [10, 20, 30, 50, 100],
        "total": total,
        "total_pages": total_pages,
    }
    return render(request, 'clientes/clientes_list.html', context)

@login_required
def add_cliente(request):
    """Agregar nuevo cliente"""
    ctx = get_auth_context(request)
    if request.method == 'POST':
        form = ClienteForm(request.POST)
        if form.is_valid():
            cliente = form.save(commit=False)
            # Forzar organización y creador
            if not (ctx.get('organization_is_general') or ctx.get('is_support')):
                cliente.organizacion_id = ctx.get('organization_id')
            cliente.created_by = request.user
            cliente.save()
            messages.success(request, 'Cliente agregado exitosamente.')
            return redirect('clientes_lista')
        else:
            messages.error(request, 'Por favor corrige los errores del formulario.')
    else:
        form = ClienteForm()
    
    context = {
        "title": "Agregar Cliente",
        "subTitle": "Nuevo Cliente",
        "form": form
    }
    return render(request, 'clientes/add_cliente.html', context)

@login_required
def edit_cliente(request, cliente_id):
    """Editar cliente existente"""
    ctx = get_auth_context(request)
    base_qs = Cliente.objects
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
    cliente = get_object_or_404(base_qs, pk=cliente_id)
    
    if request.method == 'POST':
        form = ClienteForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cliente actualizado exitosamente.')
            return redirect('clientes_lista')
        else:
            messages.error(request, 'Por favor corrige los errores del formulario.')
    else:
        form = ClienteForm(instance=cliente)
    
    context = {
        "title": "Editar Cliente",
        "subTitle": "Modificar Cliente",
        "form": form,
        "cliente": cliente
    }
    return render(request, 'clientes/edit_cliente.html', context)

@login_required
def delete_cliente(request, cliente_id):
    """Eliminar (desactivar) cliente vía AJAX"""
    if request.method == 'POST':
        try:
            ctx = get_auth_context(request)
            base_qs = Cliente.objects
            if not (ctx.get('organization_is_general') or ctx.get('is_support')):
                base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
            cliente = get_object_or_404(base_qs, pk=cliente_id)
            # Permisos: solo ADMIN_ORG (org_admin) o Soporte (super_admin)
            role = ctx.get('role')
            if not (ctx.get('organization_is_general') or ctx.get('is_support') or role == 'org_admin'):
                return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)
            cliente.activo = False
            cliente.save()
            return JsonResponse({
                'success': True,
                'message': 'Cliente eliminado exitosamente.'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error al eliminar cliente: {str(e)}'
            })
    return JsonResponse({'success': False, 'message': 'Método no permitido'})

@login_required
def buscar_clientes_ajax(request):
    """Buscar clientes vía AJAX para el optimizador"""
    query = request.GET.get('q', '').strip()
    
    if len(query) < 3:
        return JsonResponse({'clientes': []})
    
    # Buscar clientes activos que coincidan con la query
    ctx = get_auth_context(request)
    clientes_qs = Cliente.objects.filter(activo=True)
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        clientes_qs = clientes_qs.filter(organizacion_id=ctx.get('organization_id'))
    clientes = clientes_qs.filter(
        Q(nombre__icontains=query) |
        Q(rut__icontains=query) |
        Q(organizacion__nombre__icontains=query)
    ).order_by('nombre')[:10]  # Limitar a 10 resultados
    
    # Formatear datos para JSON
    clientes_data = []
    for cliente in clientes:
        clientes_data.append({
            'id': cliente.id,
            'nombre': cliente.nombre,
            'rut': cliente.rut,
            'organizacion': cliente.organizacion.nombre if cliente.organizacion else '',
            'email': cliente.email or '',
            'telefono': cliente.telefono or '',
        })
    
    return JsonResponse({'clientes': clientes_data})

@login_required
def proyectos_list(request):
    """Lista de proyectos (página principal de proyectos)"""
    ctx = get_auth_context(request)
    # Filtros de búsqueda
    search = request.GET.get('search', '')
    estado_filter = request.GET.get('estado', '')
    cliente_filter = request.GET.get('cliente', '')
    # Paginación
    try:
        page_size = max(1, min(100, int(request.GET.get('page_size', '10'))))
    except ValueError:
        page_size = 10
    try:
        page = max(1, int(request.GET.get('page', '1')))
    except ValueError:
        page = 1
    
    # Verificar si el usuario es autoservicio
    es_autoservicio = False
    try:
        perfil = getattr(request.user, 'usuarioperfiloptimizador', None)
        es_autoservicio = getattr(perfil, 'rol', None) == 'autoservicio'
    except Exception:
        pass
    
    # Query base con relaciones
    proyectos = Proyecto.objects.select_related('cliente', 'creado_por').all()
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        # Scope por organización del proyecto
        proyectos = proyectos.filter(organizacion_id=ctx.get('organization_id'))
    
    # Si es autoservicio: siempre mostrar resultados vacíos a menos que haya búsqueda
    # El buscador siempre consulta la base de datos
    if es_autoservicio:
        if not search:
            proyectos = proyectos.none()
        else:
            # Aplicar filtros de búsqueda
            proyectos = proyectos.filter(
                Q(codigo__icontains=search) | 
                Q(nombre__icontains=search) |
                Q(cliente__nombre__icontains=search) |
                Q(cliente__rut__icontains=search)
            )
    elif search:
        # Para usuarios no autoservicio, aplicar búsqueda normal
        proyectos = proyectos.filter(
            Q(codigo__icontains=search) | 
            Q(nombre__icontains=search) |
            Q(cliente__nombre__icontains=search) |
            Q(cliente__rut__icontains=search)
        )
    
    if estado_filter:
        proyectos = proyectos.filter(estado=estado_filter)
    
    if cliente_filter:
        proyectos = proyectos.filter(cliente_id=cliente_filter)
    
    # Ordenar y paginar
    proyectos = proyectos.order_by('-fecha_creacion') if hasattr(Proyecto, 'fecha_creacion') else proyectos.order_by('-id')
    total = proyectos.count()
    start = (page - 1) * page_size
    end = start + page_size
    proyectos = proyectos[start:end]
    total_pages = (total + page_size - 1) // page_size

    # Obtener listas para filtros
    estados = Proyecto.ESTADOS
    clientes = Cliente.objects.filter(activo=True).order_by('nombre')
    # Preparar operadores por organización (solo usuarios con rol 'operador')
    from core.models import UsuarioPerfilOptimizador
    org_ids = set([p.organizacion_id for p in proyectos if getattr(p, 'organizacion_id', None)])
    operadores_qs = UsuarioPerfilOptimizador.objects.filter(rol='operador', organizacion_id__in=org_ids).select_related('user')
    operadores_by_org = {}
    for op in operadores_qs:
        if not op.organizacion_id:
            continue
        operadores_by_org.setdefault(op.organizacion_id, []).append({
            'id': op.user.id,
            'name': op.user.get_full_name() or op.user.username,
        })
    # Adjuntar lista de operadores disponibles a cada proyecto para uso en plantilla
    for p in proyectos:
        setattr(p, 'available_operadores', operadores_by_org.get(getattr(p, 'organizacion_id', None), []))
    
    context = {
        "title": "Lista de Proyectos",
        "subTitle": "Proyectos",
        "proyectos": proyectos,
        "estados": estados,
        "clientes": clientes,
        "operadores_by_org": operadores_by_org,
        "search": search,
        "estado_filter": estado_filter,
        "cliente_filter": cliente_filter,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }
    return render(request, 'invoice/list.html', context)  # Usar el template existente

@login_required
def add_proyecto(request):
    """Agregar nuevo proyecto"""
    ctx = get_auth_context(request)
    if request.method == 'POST':
        form = ProyectoForm(request.POST)
        if form.is_valid():
            proyecto = form.save(commit=False)
            proyecto.creado_por = request.user
            # Forzar organización según usuario
            if not (ctx.get('organization_is_general') or ctx.get('is_support')):
                proyecto.organizacion_id = ctx.get('organization_id')
            
            # Auto-generar código si no se proporciona
            if not proyecto.codigo:
                last_project = Proyecto.objects.order_by('-id').first()
                next_number = 1 if not last_project else last_project.id + 1
                proyecto.codigo = f"PROJ-{next_number:03d}"
            
            proyecto.save()
            messages.success(request, 'Proyecto creado exitosamente.')
            return redirect('proyectos')
        else:
            messages.error(request, 'Por favor corrige los errores del formulario.')
    else:
        form = ProyectoForm()
    
    context = {
        "title": "Agregar Proyecto",
        "subTitle": "Nuevo Proyecto",
        "form": form
    }
    return render(request, 'proyectos/add_proyecto.html', context)

@login_required
def edit_proyecto(request, proyecto_id):
    """Editar proyecto existente"""
    ctx = get_auth_context(request)
    base_qs = Proyecto.objects
    if not (ctx.get('organization_is_general') or ctx.get('is_support')):
        base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
    proyecto = get_object_or_404(base_qs, pk=proyecto_id)
    
    if request.method == 'POST':
        form = ProyectoForm(request.POST, instance=proyecto)
        if form.is_valid():
            form.save()
            messages.success(request, 'Proyecto actualizado exitosamente.')
            return redirect('proyectos')
        else:
            messages.error(request, 'Por favor corrige los errores del formulario.')
    else:
        form = ProyectoForm(instance=proyecto)
    
    context = {
        "title": "Editar Proyecto",
        "subTitle": "Modificar Proyecto",
        "form": form,
        "proyecto": proyecto
    }
    return render(request, 'proyectos/edit_proyecto.html', context)

@login_required
def update_project_status(request):
    """Actualizar estado del proyecto vía AJAX"""
    if request.method == 'POST':
        try:
            proyecto_id = request.POST.get('proyecto_id')
            nuevo_estado = request.POST.get('estado')
            
            ctx = get_auth_context(request)
            base_qs = Proyecto.objects
            if not (ctx.get('organization_is_general') or ctx.get('is_support')):
                base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
            proyecto = get_object_or_404(base_qs, pk=proyecto_id)
            proyecto.estado = nuevo_estado
            proyecto.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Estado actualizado exitosamente.'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error al actualizar estado: {str(e)}'
            })
    return JsonResponse({'success': False, 'message': 'Método no permitido'})


@login_required
def asignar_operador(request):
    """Asignar un operador a un proyecto vía AJAX. Valida alcance por organización."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Método no permitido'})
    try:
        proyecto_id = request.POST.get('proyecto_id')
        operador_id = request.POST.get('operador_id') or None
        ctx = get_auth_context(request)
        base_qs = Proyecto.objects
        if not (ctx.get('organization_is_general') or ctx.get('is_support')):
            base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
        proyecto = get_object_or_404(base_qs, pk=proyecto_id)

        # Validar operador
        operador_obj = None
        if operador_id:
            from django.contrib.auth.models import User
            operador_obj = get_object_or_404(User, pk=operador_id)
            # Verificar que el operador pertenezca a la misma organización (salvo organización general)
            try:
                perfil = operador_obj.usuarioperfiloptimizador
                if perfil.rol != 'operador':
                    return JsonResponse({'success': False, 'message': 'El usuario seleccionado no es un operador.'})
                if not (ctx.get('organization_is_general') or ctx.get('is_support')) and perfil.organizacion_id != proyecto.organizacion_id:
                    return JsonResponse({'success': False, 'message': 'No puedes asignar operadores de otra organización.'})
            except Exception:
                return JsonResponse({'success': False, 'message': 'El usuario no tiene perfil válido.'})

        proyecto.operador = operador_obj
        proyecto.save(update_fields=['operador'])
        return JsonResponse({'success': True, 'message': 'Operador asignado correctamente.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error asignando operador: {str(e)}'})

@login_required
def delete_proyecto(request, proyecto_id):
    """Eliminar proyecto vía AJAX"""
    if request.method == 'POST':
        try:
            ctx = get_auth_context(request)
            base_qs = Proyecto.objects
            if not (ctx.get('organization_is_general') or ctx.get('is_support')):
                base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
            proyecto = get_object_or_404(base_qs, pk=proyecto_id)
            proyecto.delete()
            return JsonResponse({
                'success': True,
                'message': 'Proyecto eliminado exitosamente.'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error al eliminar proyecto: {str(e)}'
            })
    return JsonResponse({'success': False, 'message': 'Método no permitido'})

@login_required
def duplicate_proyecto(request, proyecto_id):
    """Cargar proyecto en modo copia para duplicarlo en el optimizador"""
    if request.method == 'POST':
        try:
            ctx = get_auth_context(request)
            base_qs = Proyecto.objects
            if not (ctx.get('organization_is_general') or ctx.get('is_support')):
                base_qs = base_qs.filter(organizacion_id=ctx.get('organization_id'))
            proyecto_original = get_object_or_404(base_qs.select_related('cliente'), pk=proyecto_id)
            
            # Construir URL de redirección según el rol del usuario
            from django.urls import reverse
            try:
                perfil = getattr(request.user, 'usuarioperfiloptimizador', None)
                es_autoservicio = getattr(perfil, 'rol', None) == 'autoservicio'
            except Exception:
                es_autoservicio = False
            
            # Autoservicio va al optimizador autoservicio con el proyecto original en modo copia
            if es_autoservicio:
                redirect_url = reverse('optimizador_autoservicio_home_clone')
                # Guardar el ID del proyecto ORIGINAL para cargarlo en modo copia
                request.session['autoservicio_proyecto_copiado'] = proyecto_original.id
            else:
                # Para otros roles, crear copia física del proyecto
                nuevo_proyecto = Proyecto()
                nuevo_proyecto.nombre = f"{proyecto_original.nombre} (Copia)"
                nuevo_proyecto.cliente = proyecto_original.cliente
                nuevo_proyecto.creado_por = request.user
                nuevo_proyecto.organizacion = proyecto_original.organizacion
                nuevo_proyecto.estado = 'nuevo'
                
                # Auto-generar código
                last_project = Proyecto.objects.order_by('-id').first()
                next_number = 1 if not last_project else last_project.id + 1
                nuevo_proyecto.codigo = f"PROJ-{next_number:03d}"
                
                # Copiar configuración y resultados si existen
                if proyecto_original.configuracion:
                    nuevo_proyecto.configuracion = proyecto_original.configuracion
                if proyecto_original.resultado_optimizacion:
                    nuevo_proyecto.resultado_optimizacion = proyecto_original.resultado_optimizacion
                
                nuevo_proyecto.save()
                redirect_url = reverse('optimizador_abrir', args=[nuevo_proyecto.id])
            
            return JsonResponse({
                'success': True,
                'message': 'Cargando proyecto en el optimizador...',
                'redirect_url': redirect_url
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error al cargar proyecto: {str(e)}'
            })
    return JsonResponse({'success': False, 'message': 'Método no permitido'})

# ============= VISTAS DE ORGANIZACIONES =============

@login_required
def organizaciones_list(request):
    """Vista para listar organizaciones"""
    search = request.GET.get('search', '')
    try:
        page_size = max(1, min(100, int(request.GET.get('page_size', '10'))))
    except ValueError:
        page_size = 10
    try:
        page = max(1, int(request.GET.get('page', '1')))
    except ValueError:
        page = 1
    
    # Query base
    organizaciones = Organizacion.objects.filter(activo=True)
    
    # Aplicar filtros
    if search:
        organizaciones = organizaciones.filter(
            Q(codigo__icontains=search) | 
            Q(nombre__icontains=search) |
            Q(email__icontains=search)
        )
    
    # Orden y paginación
    organizaciones = organizaciones.order_by('-fecha_creacion') if hasattr(Organizacion, 'fecha_creacion') else organizaciones.order_by('-id')
    total = organizaciones.count()
    start = (page - 1) * page_size
    end = start + page_size
    organizaciones = organizaciones[start:end]
    total_pages = (total + page_size - 1) // page_size

    context = {
        "title": "Lista de Organizaciones",
        "subTitle": "Organizaciones",
        "organizaciones": organizaciones,
        "search": search,
        "page": page,
        "page_size": page_size,
        "page_sizes": [10, 20, 30, 50, 100],
        "total": total,
        "total_pages": total_pages,
    }
    return render(request, 'organizaciones/organizaciones_list.html', context)

@login_required
def add_organizacion(request):
    """Vista para agregar nueva organización"""
    if request.method == 'POST':
        # Crear datos del formulario manualmente
        data = {
            'codigo': request.POST.get('codigo'),
            'nombre': request.POST.get('nombre'),
            'direccion': request.POST.get('direccion'),
            'telefono': request.POST.get('telefono'),
            'email': request.POST.get('email'),
            'activo': request.POST.get('activo') == 'on'
        }
        
        try:
            organizacion = Organizacion.objects.create(**data)
            messages.success(request, f'Organización {organizacion.nombre} creada exitosamente.')
            return redirect('organizaciones_lista')
        except Exception as e:
            messages.error(request, f'Error al crear organización: {str(e)}')
    
    context = {
        "title": "Agregar Organización",
        "subTitle": "Nueva Organización",
    }
    return render(request, 'organizaciones/add_organizacion.html', context)

@login_required
def edit_organizacion(request, organizacion_id):
    """Vista para editar organización"""
    organizacion = get_object_or_404(Organizacion, id=organizacion_id)
    
    if request.method == 'POST':
        try:
            organizacion.codigo = request.POST.get('codigo')
            organizacion.nombre = request.POST.get('nombre')
            organizacion.direccion = request.POST.get('direccion')
            organizacion.telefono = request.POST.get('telefono')
            organizacion.email = request.POST.get('email')
            organizacion.activo = request.POST.get('activo') == 'on'
            organizacion.save()
            
            messages.success(request, f'Organización {organizacion.nombre} actualizada exitosamente.')
            return redirect('organizaciones_lista')
        except Exception as e:
            messages.error(request, f'Error al actualizar organización: {str(e)}')
    
    context = {
        "title": "Editar Organización",
        "subTitle": "Modificar Organización",
        "organizacion": organizacion,
    }
    return render(request, 'organizaciones/edit_organizacion.html', context)

@login_required
def delete_organizacion(request, organizacion_id):
    """Vista para eliminar organización"""
    if request.method == 'POST':
        try:
            organizacion = get_object_or_404(Organizacion, id=organizacion_id)
            nombre = organizacion.nombre
            organizacion.delete()
            return JsonResponse({
                'success': True,
                'message': f'Organización {nombre} eliminada exitosamente.'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error al eliminar organización: {str(e)}'
            })
    return JsonResponse({'success': False, 'message': 'Método no permitido'})