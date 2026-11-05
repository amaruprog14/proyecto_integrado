import accounts.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0008_groupprofile')]
    operations = [migrations.AddField(
        model_name='official', name='photo',
        field=models.ImageField(blank=True, upload_to=accounts.models.profile_photo_path,
                                verbose_name='Foto de perfil'),
    )]
