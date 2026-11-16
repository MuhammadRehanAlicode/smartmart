import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='source',
            field=models.CharField(db_index=True, default='online', max_length=10),
        ),
        migrations.AddField(
            model_name='order',
            name='client_created_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='OfflineOrderSync',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('client_order_id', models.UUIDField(unique=True)),
                ('outcome', models.CharField(choices=[('confirmed', 'Confirmed'), ('rejected', 'Rejected')], max_length=10)),
                ('reason_code', models.CharField(blank=True, max_length=40)),
                ('reason', models.CharField(blank=True, max_length=500)),
                ('details', models.JSONField(blank=True, default=dict)),
                ('client_created_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('order', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='offline_sync', to='orders.order')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
    ]
