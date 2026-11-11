from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("corrections", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="correctionrequest", name="is_proxy",
            field=models.BooleanField(default=False, verbose_name="代理申請"),
        ),
        migrations.AddField(
            model_name="correctionrequest", name="proxy_reason",
            field=models.CharField(blank=True, max_length=1000, verbose_name="本人申請ができない理由"),
        ),
        migrations.AddField(
            model_name="correctionrequest", name="evidence",
            field=models.CharField(blank=True, max_length=1000, verbose_name="確認資料と確認方法"),
        ),
        migrations.AddField(
            model_name="correctionrequest", name="withdrawn_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="withdrawn_corrections", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="correctionrequest", name="withdraw_reason",
            field=models.CharField(blank=True, max_length=500, verbose_name="取下げ理由"),
        ),
    ]
