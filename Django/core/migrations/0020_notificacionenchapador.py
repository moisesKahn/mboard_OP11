from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_notificacionoperador'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificacionEnchapador',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('proyecto_nombre', models.CharField(blank=True, default='', max_length=200)),
                ('proyecto_id', models.IntegerField(blank=True, null=True)),
                ('leida', models.BooleanField(default=False, verbose_name='Leída')),
                ('fecha', models.DateTimeField(auto_now_add=True)),
                ('destinatario', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notificaciones_enchapador',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Enchapador destinatario',
                )),
            ],
            options={
                'verbose_name': 'Notificación de enchapador',
                'verbose_name_plural': 'Notificaciones de enchapador',
                'ordering': ['-fecha'],
            },
        ),
    ]
