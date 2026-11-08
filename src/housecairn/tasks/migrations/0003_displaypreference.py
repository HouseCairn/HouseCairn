import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0002_attachment'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DisplayPreference',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='created at')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='updated at')),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, null=True, verbose_name='deleted at')),
                ('today_group', models.CharField(choices=[('urgency', 'Urgency'), ('room', 'Room'), ('person', 'Person'), ('calendar', 'Calendar')], default='urgency', max_length=10, verbose_name='group by')),
                ('horizon_days', models.PositiveSmallIntegerField(choices=[(7, '1 week'), (14, '2 weeks'), (30, '1 month'), (60, '2 months'), (90, '3 months')], default=7, verbose_name='look ahead')),
                ('show_overdue', models.BooleanField(default=True, verbose_name='overdue')),
                ('show_upcoming', models.BooleanField(default=True, verbose_name='coming up')),
                ('show_season', models.BooleanField(default=True, verbose_name='in season')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='display_preference', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'display preference',
                'verbose_name_plural': 'display preferences',
            },
        ),
    ]
