from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("configuration", "0004_periodmutex_attentiontype_activity_item"),
    ]

    operations = [
        migrations.AlterField(
            model_name="item",
            name="code",
            field=models.CharField(
                blank=True, help_text="Si se deja vacío se genera automáticamente.",
                max_length=25, unique=True, verbose_name="Código",
            ),
        ),
    ]
