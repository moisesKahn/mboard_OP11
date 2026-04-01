from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponseForbidden
from django.db.models import Q
from django.db import transaction
from django.utils import timezone
from core.models import UsuarioPerfilOptimizador, AuditLog
from core.forms import UsuarioForm, UsuarioPerfilForm
from core.auth_utils import get_auth_context, is_support, is_org_admin

def _audit(request, verb: str, target_user: User):
    """Registrar auditoría para acciones sobre usuarios"""
    try:
        ctx = get_auth_context(request)
        actor = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None
        organizacion = None
        if ctx.get('organization_id'):
            from core.models import Organizacion
            organizacion = Organizacion.objects.filter(id=ctx['organization_id']).first()
        AuditLog.objects.create(
            actor=actor,
            organizacion=organizacion,
            verb=verb,
            target_model='auth.User',
            target_id=str(target_user.id),
            target_repr=target_user.username,
            changes=None,
            created_at=timezone.now()
        )
    except Exception:
        # No romper el flujo por auditoría
        pass

@login_required
def addUser(request):
    """Agregar nuevo usuario"""
    ctx = get_auth_context(request)
    # Permitir creación a Soporte (super_admin / organización general) y a org_admin.
    if not (is_support(ctx) or is_org_admin(ctx)):
        return HttpResponseForbidden('Solo Soporte o Administrador de Organización puede crear usuarios')
    if request.method == 'POST':
        user_form = UsuarioForm(request.POST)
        perfil_form = UsuarioPerfilForm(request.POST)

        # Ajustes de permisos para org_admin: forzar organización y limitar roles
        if is_org_admin(ctx) and not is_support(ctx):
            try:
                # Limitar los roles que puede asignar (sin super_admin ni org_admin)
                allowed_roles = ['vendedor', 'supervisor', 'operador', 'enchapador']
                perfil_form.fields['rol'].choices = [c for c in UsuarioPerfilOptimizador.ROLES if c[0] in allowed_roles]
                # Forzar organización y deshabilitar campo
                if 'organizacion' in perfil_form.fields:
                    perfil_form.fields['organizacion'].disabled = True
            except Exception:
                pass
        
        if user_form.is_valid() and perfil_form.is_valid():
            try:
                with transaction.atomic():
                    # Crear usuario
                    user = user_form.save(commit=False)
                    # Contraseña obligatoria en creación (validada en el formulario)
                    pwd = user_form.cleaned_data.get('password')
                    user.set_password(pwd)
                    user.save()
                    
                    # Crear perfil
                    perfil = perfil_form.save(commit=False)
                    perfil.user = user
                    # Forzar organización si org_admin
                    if is_org_admin(ctx) and not is_support(ctx):
                        perfil.organizacion_id = ctx.get('organization_id')
                        # Evitar elevación de rol por manipulación del POST
                        if perfil.rol not in ['vendedor', 'supervisor', 'operador', 'enchapador']:
                            perfil.rol = 'vendedor'
                    try:
                        # Si el modelo tiene must_change_password, marcarlo
                        if hasattr(perfil, 'must_change_password'):
                            perfil.must_change_password = True
                    except Exception:
                        pass
                    perfil.save()
                    _audit(request, 'CREATE_USER', user)
                    
                    messages.success(request, 'Usuario creado con contraseña definida.')
                    return redirect('usersList')
            except Exception as e:
                messages.error(request, f'Error al crear usuario: {str(e)}')
        else:
            messages.error(request, 'Por favor corrige los errores del formulario.')
    else:
        user_form = UsuarioForm()
        perfil_form = UsuarioPerfilForm()
        if is_org_admin(ctx) and not is_support(ctx):
            try:
                allowed_roles = ['vendedor', 'supervisor', 'operador', 'enchapador']
                perfil_form.fields['rol'].choices = [c for c in UsuarioPerfilOptimizador.ROLES if c[0] in allowed_roles]
                if 'organizacion' in perfil_form.fields:
                    perfil_form.fields['organizacion'].initial = ctx.get('organization_id')
                    perfil_form.fields['organizacion'].disabled = True
            except Exception:
                pass
    
    context = {
        "title": "Agregar Usuario",
        "subTitle": "Nuevo Usuario",
        "user_form": user_form,
        "perfil_form": perfil_form
    }
    return render(request, "users/addUser.html", context)

@login_required
def usersGrid(request):
    """Vista de usuarios en formato grid"""
    ctx = get_auth_context(request)
    # Filtros de búsqueda
    search = request.GET.get('search', '')
    rol_filter = request.GET.get('rol', '')
    
    # Query base con perfiles
    usuarios = User.objects.select_related('usuarioperfiloptimizador').filter(is_active=True)
    # Scope por organización si no es soporte/organización general
    try:
        if not is_support(ctx) and not ctx.get('organization_is_general'):
            org_id = ctx.get('organization_id')
            if org_id:
                usuarios = usuarios.filter(usuarioperfiloptimizador__organizacion_id=org_id)
            else:
                usuarios = usuarios.none()
    except Exception:
        pass
    
    # Aplicar filtros
    if search:
        usuarios = usuarios.filter(
            Q(username__icontains=search) | 
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search)
        )
    
    if rol_filter:
        usuarios = usuarios.filter(usuarioperfiloptimizador__rol=rol_filter)
    
    # Obtener roles únicos
    roles = UsuarioPerfilOptimizador.ROLES
    
    context = {
        "title": "Usuarios Grid",
        "subTitle": "Usuarios Grid",
        "usuarios": usuarios,
        "roles": roles,
        "search": search,
        "rol_filter": rol_filter
    }
    return render(request, "users/usersGrid.html", context)

@login_required
def usersList(request):
    """Lista de usuarios"""
    ctx = get_auth_context(request)
    # Filtros de búsqueda y paginación
    search = request.GET.get('search', '')
    rol_filter = request.GET.get('rol', '')
    org_filter = request.GET.get('org', '')
    page_size = 20
    try:
        page = max(1, int(request.GET.get('page', '1')))
    except ValueError:
        page = 1

    # Query base con perfiles
    usuarios_qs = User.objects.select_related('usuarioperfiloptimizador').filter(is_active=True)
    # Scope por organización si no es soporte/organización general
    try:
        if not is_support(ctx) and not ctx.get('organization_is_general'):
            org_id = ctx.get('organization_id')
            if org_id:
                usuarios_qs = usuarios_qs.filter(usuarioperfiloptimizador__organizacion_id=org_id)
            else:
                usuarios_qs = usuarios_qs.none()
    except Exception:
        pass
    
    # Aplicar filtros
    if search:
        usuarios_qs = usuarios_qs.filter(
            Q(username__icontains=search) | 
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search)
        )
    
    if rol_filter:
        usuarios_qs = usuarios_qs.filter(usuarioperfiloptimizador__rol=rol_filter)

    if org_filter:
        usuarios_qs = usuarios_qs.filter(usuarioperfiloptimizador__organizacion_id=org_filter)

    # Orden por fecha de creación descendente como default
    usuarios_qs = usuarios_qs.order_by('-date_joined')

    # Paginación
    total = usuarios_qs.count()
    start = (page - 1) * page_size
    end = start + page_size
    usuarios = usuarios_qs[start:end]
    total_pages = (total + page_size - 1) // page_size
    
    # Obtener roles y organizaciones para los filtros
    roles = UsuarioPerfilOptimizador.ROLES
    from core.models import Organizacion
    organizaciones = Organizacion.objects.filter(activo=True).order_by('nombre')

    context = {
        "title": "Lista de Usuarios",
        "subTitle": "Usuarios",
        "usuarios": usuarios,
        "roles": roles,
        "organizaciones": organizaciones,
        "search": search,
        "rol_filter": rol_filter,
        "org_filter": org_filter,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }
    return render(request, "users/usersList.html", context)

@login_required
def editUser(request, user_id):
    """Editar usuario existente"""
    ctx = get_auth_context(request)
    # Soporte puede editar cualquier usuario. org_admin solo usuarios de su organización (no super_admin / organización general)
    user = get_object_or_404(User, pk=user_id)
    if not is_support(ctx):
        if not is_org_admin(ctx):
            return HttpResponseForbidden('Solo Soporte o Administrador de Organización puede editar usuarios')
        # Validar que el usuario objetivo pertenece a la misma organización y no es super_admin
        try:
            target_perfil = user.usuarioperfiloptimizador
            # Bloquear edición de super_admin o usuarios fuera de la organización
            if target_perfil.rol == 'super_admin' or target_perfil.organizacion_id != ctx.get('organization_id'):
                return HttpResponseForbidden('No autorizado para editar este usuario')
        except UsuarioPerfilOptimizador.DoesNotExist:
            # Si no tiene perfil aún y somos org_admin, no permitir (solo soporte puede crear/adjuntar perfil global)
            return HttpResponseForbidden('No autorizado para editar este usuario')
    
    # Obtener o crear perfil
    try:
        perfil = user.usuarioperfiloptimizador
    except UsuarioPerfilOptimizador.DoesNotExist:
        perfil = UsuarioPerfilOptimizador(user=user)
    
    if request.method == 'POST':
        user_form = UsuarioForm(request.POST, instance=user)
        perfil_form = UsuarioPerfilForm(request.POST, instance=perfil)
        # Ajustes de permisos para org_admin
        if is_org_admin(ctx) and not is_support(ctx):
            try:
                allowed_roles = ['vendedor', 'supervisor', 'operador', 'enchapador']
                perfil_form.fields['rol'].choices = [c for c in UsuarioPerfilOptimizador.ROLES if c[0] in allowed_roles]
                # Deshabilitar organización para evitar cambios
                if 'organizacion' in perfil_form.fields:
                    perfil_form.fields['organizacion'].disabled = True
            except Exception:
                pass
        
        if user_form.is_valid() and perfil_form.is_valid():
            try:
                with transaction.atomic():
                    # Actualizar usuario
                    user = user_form.save(commit=False)
                    pwd = user_form.cleaned_data.get('password')
                    if pwd:
                        user.set_password(pwd)
                    user.save()
                    
                    # Actualizar perfil
                    perfil = perfil_form.save(commit=False)
                    perfil.user = user
                    if is_org_admin(ctx) and not is_support(ctx):
                        # Forzar organización y evitar elevación de rol
                        perfil.organizacion_id = ctx.get('organization_id')
                        if perfil.rol not in ['vendedor', 'supervisor', 'operador', 'enchapador']:
                            perfil.rol = 'vendedor'
                    perfil.save()
                    _audit(request, 'UPDATE_USER', user)
                    
                    messages.success(request, 'Usuario actualizado exitosamente.')
                    return redirect('usersList')
            except Exception as e:
                messages.error(request, f'Error al actualizar usuario: {str(e)}')
        else:
            messages.error(request, 'Por favor corrige los errores del formulario.')
    else:
        user_form = UsuarioForm(instance=user)
        perfil_form = UsuarioPerfilForm(instance=perfil)
        if is_org_admin(ctx) and not is_support(ctx):
            try:
                allowed_roles = ['vendedor', 'supervisor', 'operador', 'enchapador']
                perfil_form.fields['rol'].choices = [c for c in UsuarioPerfilOptimizador.ROLES if c[0] in allowed_roles]
                if 'organizacion' in perfil_form.fields:
                    perfil_form.fields['organizacion'].disabled = True
            except Exception:
                pass
    
    context = {
        "title": "Editar Usuario",
        "subTitle": "Modificar Usuario",
        "user_form": user_form,
        "perfil_form": perfil_form,
        "user": user
    }
    return render(request, "users/editUser.html", context)

@login_required
def viewProfile(request):
    """Ver perfil: permite ver el propio y (si autorizado) el de otros por ?user_id=.
    Muestra resumen de actividad: proyectos, clientes y últimas auditorías.
    """
    from core.models import Proyecto, Cliente, AuditLog
    target_user = request.user
    target_id = request.GET.get('user_id')
    if target_id and str(target_id).isdigit():
        # Permitir ver a otros usuarios solo a super_admin o admin de la misma organización
        try:
            other = User.objects.get(id=int(target_id))
            viewer_perfil = getattr(request.user, 'usuarioperfiloptimizador', None)
            other_perfil = getattr(other, 'usuarioperfiloptimizador', None)
            autorizado = False
            if viewer_perfil:
                if viewer_perfil.rol == 'super_admin':
                    autorizado = True
                elif viewer_perfil.rol == 'org_admin' and other_perfil and viewer_perfil.organizacion_id == getattr(other_perfil, 'organizacion_id', None):
                    autorizado = True
            if autorizado:
                target_user = other
        except User.DoesNotExist:
            pass

    # Determinar si el viewer puede editar el perfil objetivo (se usa en la plantilla para enlazar al edit correcto)
    can_edit_target = False
    try:
        viewer_perfil = getattr(request.user, 'usuarioperfiloptimizador', None)
        other_perfil = getattr(target_user, 'usuarioperfiloptimizador', None)
        if viewer_perfil:
            if viewer_perfil.rol == 'super_admin':
                can_edit_target = True
            elif viewer_perfil.rol == 'org_admin' and other_perfil and viewer_perfil.organizacion_id == getattr(other_perfil, 'organizacion_id', None):
                can_edit_target = True
    except Exception:
        can_edit_target = False

    # Perfil
    try:
        perfil = target_user.usuarioperfiloptimizador
    except UsuarioPerfilOptimizador.DoesNotExist:
        perfil = None

    # Resumen de datos
    try:
        proyectos_qs = Proyecto.objects.filter(usuario=target_user)
        total_proyectos = proyectos_qs.count()
        optimizados = proyectos_qs.filter(estado__in=['optimizado','aprobado','produccion','completado']).count()
        ultimos_proyectos = proyectos_qs.select_related('cliente').order_by('-fecha_creacion')[:5]
    except Exception:
        total_proyectos = 0; optimizados = 0; ultimos_proyectos = []
    try:
        clientes_creados = Cliente.objects.filter(created_by=target_user)
        total_clientes = clientes_creados.count()
        ultimos_clientes = clientes_creados.order_by('-fecha_creacion')[:5]
    except Exception:
        total_clientes = 0; ultimos_clientes = []
    try:
        auditoria = AuditLog.objects.filter(actor=target_user).order_by('-created_at')[:10]
    except Exception:
        auditoria = []

    context = {
        "title": "Perfil de Usuario",
        "subTitle": "Resumen",
        "user": target_user,
        "perfil": perfil,
        "total_proyectos": total_proyectos,
        "optimizados": optimizados,
        "ultimos_proyectos": ultimos_proyectos,
        "total_clientes": total_clientes,
        "ultimos_clientes": ultimos_clientes,
        "auditoria": auditoria,
        "viendo_otro": target_user != request.user,
        "can_edit_target": can_edit_target,
    }
    return render(request, "users/viewProfile.html", context)


@login_required
def edit_own_profile(request):
    """Permite a cualquier usuario editar su propio perfil (datos básicos y perfil extendido)."""
    user = request.user
    try:
        perfil = user.usuarioperfiloptimizador
    except UsuarioPerfilOptimizador.DoesNotExist:
        perfil = UsuarioPerfilOptimizador(user=user)

    if request.method == 'POST':
        # Limitar campos: el propio usuario no puede cambiar su rol ni su organización
        user_form = UsuarioForm(request.POST, instance=user)
        perfil_form = UsuarioPerfilForm(request.POST, instance=perfil)
        # Forzar valores del perfil que no puede cambiar
        if 'rol' in perfil_form.fields:
            perfil_form.fields['rol'].disabled = True
        if 'organizacion' in perfil_form.fields:
            perfil_form.fields['organizacion'].disabled = True
        if user_form.is_valid() and perfil_form.is_valid():
            try:
                with transaction.atomic():
                    user = user_form.save(commit=False)
                    # Permitir cambio de contraseña si se entrega (en este formulario no hay password por defecto)
                    if user_form.cleaned_data.get('password'):
                        user.set_password(user_form.cleaned_data['password'])
                    user.save()
                    perfil = perfil_form.save(commit=False)
                    perfil.user = user
                    perfil.save()
                    messages.success(request, 'Perfil actualizado.')
                    return redirect('viewProfile')
            except Exception as e:
                messages.error(request, f'Error al actualizar perfil: {str(e)}')
        else:
            messages.error(request, 'Por favor corrige los errores del formulario.')
    else:
        user_form = UsuarioForm(instance=user)
        perfil_form = UsuarioPerfilForm(instance=perfil)
        # Deshabilitar campos que no se pueden autoeditar
        perfil_form.fields['rol'].disabled = True
        perfil_form.fields['organizacion'].disabled = True

    context = {
        "title": "Editar Mi Perfil",
        "subTitle": "Mi Perfil",
        "user_form": user_form,
        "perfil_form": perfil_form,
        "user": user
    }
    return render(request, "users/editUser.html", context)

# APIs para manejo AJAX
@login_required
def delete_user(request, user_id):
    """Desactivar usuario vía AJAX"""
    if request.method == 'POST':
        try:
            ctx = get_auth_context(request)
            user = get_object_or_404(User, pk=user_id)
            # Permisos: soporte puede eliminar cualquiera; org_admin solo dentro de su organización y sin eliminar super_admin
            if not is_support(ctx):
                if not is_org_admin(ctx):
                    return JsonResponse({'success': False, 'message': 'Solo Soporte o Admin de Organización puede eliminar usuarios.'}, status=403)
                try:
                    target_perfil = user.usuarioperfiloptimizador
                    if target_perfil.rol == 'super_admin' or target_perfil.organizacion_id != ctx.get('organization_id'):
                        return JsonResponse({'success': False, 'message': 'No autorizado para eliminar este usuario.'}, status=403)
                except UsuarioPerfilOptimizador.DoesNotExist:
                    return JsonResponse({'success': False, 'message': 'No autorizado para eliminar este usuario.'}, status=403)
            
            # No permitir eliminar al usuario actual
            if user == request.user:
                return JsonResponse({
                    'success': False,
                    'message': 'No puedes eliminar tu propio usuario.'
                })
            
            user.is_active = False
            user.save()
            _audit(request, 'DELETE_USER', user)
            
            return JsonResponse({
                'success': True,
                'message': 'Usuario eliminado exitosamente.'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error al eliminar usuario: {str(e)}'
            })
    return JsonResponse({'success': False, 'message': 'Método no permitido'})


@login_required
def support_users_report(request):
    """Reporte solo para Soporte: username, rol, organización, último acceso y acción forzar cambio de contraseña"""
    ctx = get_auth_context(request)
    if not is_support(ctx):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Forbidden')
    usuarios = User.objects.select_related('usuarioperfiloptimizador__organizacion').all()
    data = []
    for u in usuarios:
        try:
            perfil = u.usuarioperfiloptimizador
            data.append({
                'id': u.id,
                'username': u.username,
                'rol': perfil.rol,
                'organizacion': perfil.organizacion.nombre if perfil.organizacion else None,
                'ultimo_acceso': perfil.fecha_ultimo_acceso,
                'must_change_password': perfil.must_change_password,
            })
        except UsuarioPerfilOptimizador.DoesNotExist:
            data.append({'id': u.id, 'username': u.username, 'rol': None, 'organizacion': None, 'ultimo_acceso': None, 'must_change_password': False})
    return render(request, 'users/support_report.html', {'title': 'Reporte de Usuarios (Soporte)', 'usuarios': data})


@login_required
def force_password_change(request, user_id):
    """Acción de Soporte para marcar must_change_password en un usuario"""
    ctx = get_auth_context(request)
    if not is_support(ctx):
        return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)
    user = get_object_or_404(User, id=user_id)
    try:
        perfil = user.usuarioperfiloptimizador
        perfil.must_change_password = True
        perfil.save(update_fields=['must_change_password'])
        return JsonResponse({'success': True})
    except UsuarioPerfilOptimizador.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Perfil no encontrado'}, status=404)


@login_required
def bulk_delete_other_users(request):
    """Soporte: desactivar todos los usuarios excepto el actual"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Método no permitido'}, status=405)
    ctx = get_auth_context(request)
    if not is_support(ctx):
        return JsonResponse({'success': False, 'message': 'Forbidden'}, status=403)
    current = request.user
    try:
        with transaction.atomic():
            qs = User.objects.filter(is_active=True).exclude(id=current.id)
            count = qs.count()
            for u in qs:
                u.is_active = False
                u.save(update_fields=['is_active'])
                _audit(request, 'DELETE_USER', u)
        return JsonResponse({'success': True, 'deleted': count})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
