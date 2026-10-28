from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_alter_official_national_id_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="delegation",
            name="delegation_name",
            field=models.CharField(max_length=100, unique=True, verbose_name="Nombre de la delegación"),
        ),
        migrations.AlterField(
            model_name="delegation",
            name="address",
            field=models.CharField(max_length=100, verbose_name="Dirección"),
        ),
        migrations.AlterField(
            model_name="delegation",
            name="commune",
            field=models.CharField(max_length=60, verbose_name="Comuna"),
        ),
    ]
