from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("attendance", "0002_worksession_incomplete_notified_version")]

    operations = [
        migrations.AddField(
            model_name="worksession", name="moved_to",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="moved_from_sessions", to="attendance.worksession"),
        ),
    ]
