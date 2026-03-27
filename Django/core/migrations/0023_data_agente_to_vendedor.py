from django.db import migrations


def agente_to_vendedor(apps, schema_editor):
    UsuarioPerfilOptimizador = apps.get_model('core', 'UsuarioPerfilOptimizador')
    UsuarioPerfilOptimizador.objects.filter(rol='agente').update(rol='vendedor')


def vendedor_to_agente(apps, schema_editor):
    UsuarioPerfilOptimizador = apps.get_model('core', 'UsuarioPerfilOptimizador')
    UsuarioPerfilOptimizador.objects.filter(rol='vendedor').update(rol='agente')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_rename_agente_to_vendedor'),
    ]

    operations = [
        migrations.RunPython(agente_to_vendedor, vendedor_to_agente),
    ]
