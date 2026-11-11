from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("management", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ExportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("output_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("target_month", models.DateField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("manifest", models.JSONField(default=list)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
