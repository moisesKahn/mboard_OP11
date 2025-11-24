import threading
from typing import Optional

_thread_locals = threading.local()


def get_current_request():
    return getattr(_thread_locals, 'request', None)


def get_current_user():
    req = get_current_request()
    if not req:
        return None
    try:
        return getattr(req, 'user', None)
    except Exception:
        return None


class RequestUserMiddleware:
    """Middleware minimal que guarda la request actual en una variable thread-local.

    Esto permite que señales y otros hooks accedan al usuario que originó la petición
    sin requerir modificar todas las llamadas manualmente.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Guardar la request en el hilo actual
        try:
            _thread_locals.request = request
        except Exception:
            pass

        response = self.get_response(request)

        # Intentamos limpiar la referencia para evitar fugas de memoria en servidores persistentes
        try:
            if hasattr(_thread_locals, 'request'):
                del _thread_locals.request
        except Exception:
            pass

        return response


class AutoServicioIsolationMiddleware:
    """Middleware desactivado - Los usuarios autoservicio ahora usan el flujo normal.
    Dejado como placeholder para compatibilidad con settings.py.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Middleware desactivado - permitir acceso completo
        return self.get_response(request)
