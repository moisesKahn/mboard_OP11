import datetime
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db import models
from django.contrib.auth.models import AnonymousUser

from .models import (
    AuditLog,
    Cliente,
    Proyecto,
    Material,
    Tapacanto,
    MaterialProyecto,
)
from .middleware import get_current_user


def _get_actor_and_org():
    user = get_current_user()
    org = None
    if user and not isinstance(user, AnonymousUser):
        # Intentar extraer la organización desde el perfil del usuario si existe
        profile = getattr(user, 'usuarioperfiloptimizador', None)
        if profile and getattr(profile, 'organizacion', None):
            org = profile.organizacion
    return (user if not isinstance(user, AnonymousUser) else None, org)


def _serialize_instance(instance: models.Model) -> dict:
    # Campos a excluir del audit (demasiado grandes o con tipos no serializables)
    EXCLUDE_FIELDS = {'resultado_optimizacion', 'configuracion_corte'}
    data = {}
    for field in instance._meta.fields:
        name = field.name
        if name in EXCLUDE_FIELDS:
            continue
        try:
            # Para claves foráneas, tomar el id
            if isinstance(field, models.ForeignKey):
                data[name] = getattr(instance, f"{name}_id", None)
            else:
                val = getattr(instance, name)
                # Convertir objetos no JSON-serializables a str
                if isinstance(val, (datetime.date, datetime.datetime, datetime.time)):
                    data[name] = val.isoformat()
                elif isinstance(val, (dict, list, str, int, float, bool, type(None))):
                    data[name] = val
                else:
                    data[name] = str(val)
        except Exception:
            data[name] = None
    return data


def _log(verb: str, instance: models.Model):
    actor, org = _get_actor_and_org()
    try:
        changes = _serialize_instance(instance)
    except Exception:
        changes = None

    try:
        AuditLog.objects.create(
            actor=actor,
            organizacion=org,
            verb=verb,
            target_model=instance.__class__.__name__,
            target_id=str(getattr(instance, 'pk', '')),
            target_repr=str(instance),
            changes=changes,
        )
    except Exception:
        # Silenciar errores de auditoría para no romper la operación principal
        pass


# Registrar señales para los modelos críticos
@receiver(post_save, sender=Cliente)
def cliente_saved(sender, instance, created, **kwargs):
    _log('CREATE' if created else 'UPDATE', instance)


@receiver(post_delete, sender=Cliente)
def cliente_deleted(sender, instance, **kwargs):
    _log('DELETE', instance)


@receiver(post_save, sender=Proyecto)
def proyecto_saved(sender, instance, created, **kwargs):
    _log('CREATE' if created else 'UPDATE', instance)


@receiver(post_delete, sender=Proyecto)
def proyecto_deleted(sender, instance, **kwargs):
    _log('DELETE', instance)


@receiver(post_save, sender=Material)
def material_saved(sender, instance, created, **kwargs):
    _log('CREATE' if created else 'UPDATE', instance)


@receiver(post_delete, sender=Material)
def material_deleted(sender, instance, **kwargs):
    _log('DELETE', instance)


@receiver(post_save, sender=Tapacanto)
def tapacanto_saved(sender, instance, created, **kwargs):
    _log('CREATE' if created else 'UPDATE', instance)


@receiver(post_delete, sender=Tapacanto)
def tapacanto_deleted(sender, instance, **kwargs):
    _log('DELETE', instance)


@receiver(post_save, sender=MaterialProyecto)
def materialproyecto_saved(sender, instance, created, **kwargs):
    _log('CREATE' if created else 'UPDATE', instance)


@receiver(post_delete, sender=MaterialProyecto)
def materialproyecto_deleted(sender, instance, **kwargs):
    _log('DELETE', instance)
