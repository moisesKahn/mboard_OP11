from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from core.auth_utils import jwt_encode
from core.models import AuditLog
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie

def forgotPassword(request):
    return render(request, "authentication/forgotPassword.html")

@ensure_csrf_cookie
def signin(request):
    if request.method == 'POST':
        # Normalizar el usuario (espacios accidentales). No modificar la contraseña.
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        user = authenticate(request, username=username, password=password)
        # Fallback: permitir login por email si se ingresó un correo
        if user is None and '@' in username:
            try:
                from django.contrib.auth.models import User
                candidate = User.objects.filter(email__iexact=username.strip()).first()
                if candidate:
                    user = authenticate(request, username=candidate.username, password=password)
            except Exception:
                pass
        
        if user is not None:
            login(request, user)
            # Emitir JWT para consumo por front si lo requiere
            try:
                perfil = getattr(user, 'usuarioperfiloptimizador', None)
                claims = {
                    'user_id': user.id,
                    'username': user.username,
                    'organization_id': getattr(getattr(perfil, 'organizacion', None), 'id', None),
                    'organization_is_general': bool(getattr(getattr(perfil, 'organizacion', None), 'is_general', False)),
                    'role': getattr(perfil, 'rol', None),
                }
                request.session['jwt_token'] = jwt_encode(claims)
            except Exception:
                pass
            # Auditoría LOGIN
            try:
                AuditLog.objects.create(
                    actor=user,
                    organizacion=getattr(getattr(user, 'usuarioperfiloptimizador', None), 'organizacion', None),
                    verb='LOGIN',
                    target_model='User',
                    target_id=str(user.id),
                    target_repr=user.username,
                )
                # Actualizar último acceso
                if perfil:
                    perfil.fecha_ultimo_acceso = timezone.now()
                    perfil.save(update_fields=['fecha_ultimo_acceso'])
            except Exception:
                pass
            # Redirigir a flujo de cambio de contraseña si flag está activo
            try:
                if perfil and perfil.must_change_password:
                    return redirect('password_change')
            except Exception:
                pass
            # Redirigir a 'next' si existe y es seguro
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            # Si el usuario es operador, dirigir a su panel
            try:
                if getattr(perfil, 'rol', None) == 'operador':
                    return redirect('operador_home')
            except Exception:
                pass
            # Redirección específica para rol autoservicio:
            # Los usuarios autoservicio ahora van a proyectos como cualquier usuario normal
            # try:
            #     if getattr(perfil, 'rol', None) == 'autoservicio':
            #         return redirect('optimizador_autoservicio_home_clone')
            # except Exception:
            #     pass
            return redirect('proyectos')  # Redirige a la página de proyectos por defecto
        else:
            messages.error(request, 'Usuario o contraseña incorrectos.')
    
    return render(request, "authentication/signin.html")

def signup(request):
    return render(request, "authentication/signup.html")


@login_required
def password_change_view(request):
    """Cambio de contraseña obligado u opcional para usuarios autenticados."""
    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        if not new_password or not confirm_password:
            messages.error(request, 'Ingresa y confirma la nueva contraseña.')
        elif new_password != confirm_password:
            messages.error(request, 'Las contraseñas no coinciden.')
        else:
            # Establecer nueva contraseña y limpiar flag must_change_password
            user = request.user
            user.set_password(new_password)
            user.save()
            try:
                perfil = getattr(user, 'usuarioperfiloptimizador', None)
                if perfil and perfil.must_change_password:
                    perfil.must_change_password = False
                    perfil.save(update_fields=['must_change_password'])
            except Exception:
                pass
            messages.success(request, 'Contraseña actualizada. Vuelve a iniciar sesión.')
            return redirect('signin')
    return render(request, 'authentication/password_change.html')


def signout(request):
    """Cierra sesión limpiando completamente la sesión y redirige a signin."""
    try:
        logout(request)  # Limpia la sesión y rota la clave
    except Exception:
        try:
            request.session.flush()
        except Exception:
            pass
    messages.success(request, 'Sesión cerrada correctamente.')
    return redirect('signin')
