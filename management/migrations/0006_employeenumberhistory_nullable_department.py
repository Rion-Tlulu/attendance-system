from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("management", "0005_employeenumberoperation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="employeenumberhistory",
            name="department",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="number_histories", to="management.department"),
        ),
    ]
