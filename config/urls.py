"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from pathlib import Path

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import path, include
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView
from activities.client_portal import home

urlpatterns = [
    path('', home, name='home'),
    path('portal/', include('activities.client_portal')),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('activities/', include('activities.urls')),
    path('agenda/', include('agenda.urls')),
    path('analytics/', include('analytics.urls')),
    path('configuration/', include('configuration.urls'))
]

# Solo se publica el directorio de fotos de funcionarios en desarrollo.
# Las fotos de clientes se sirven mediante la vista del perfil autenticado.
if settings.DEBUG:
    urlpatterns += static(
        f"{settings.MEDIA_URL}profile_photos/",
        document_root=Path(settings.MEDIA_ROOT) / "profile_photos",
    )

handler400 = 'common.views.bad_request'
handler404 = 'common.views.page_not_found'
