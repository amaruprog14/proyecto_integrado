"""
Páginas de error propias con DEBUG=False (400, 404 y 500) y archivos subidos servidos en /media/
solo con DEBUG=True. Este módulo es además el ROOT_URLCONF de las pruebas de error: agrega a las
rutas del proyecto dos vistas que fallan a propósito y conserva sus handlers.
"""

import importlib
import json
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.exceptions import SuspiciousOperation
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import clear_url_caches, path, reverse
from PIL import Image

import config.urls
from accounts.models import Official

User = get_user_model()
PASSWORD = "Clave-Errores-123"
INTERNAL_DETAIL = "detalle-interno-que-no-debe-mostrarse"


def suspicious_view(request):
    raise SuspiciousOperation(INTERNAL_DETAIL)


def failing_view(request):
    raise RuntimeError(INTERNAL_DETAIL)


urlpatterns = [
    path("__prueba__/sospechosa/", suspicious_view),
    path("__prueba__/falla/", failing_view),
    *config.urls.urlpatterns,
]
handler400 = config.urls.handler400
handler404 = config.urls.handler404


@override_settings(DEBUG=False, ROOT_URLCONF="common.test_error_pages")
class ErrorPagesWithoutDebugTests(TestCase):
    def test_disallowed_host_returns_400_with_the_custom_page(self):
        with self.assertLogs("django.security.DisallowedHost", "ERROR"):
            response = self.client.get("/", HTTP_HOST="sitio-no-permitido.example")

        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, "400.html")
        self.assertContains(response, "No pudimos procesar la solicitud", status_code=400)
        self.assertNotContains(response, "sitio-no-permitido.example", status_code=400)
        self.assertNotContains(response, "ALLOWED_HOSTS", status_code=400)

    def test_suspicious_operation_returns_400_without_internal_details(self):
        with self.assertLogs("django.security.SuspiciousOperation", "ERROR"):
            response = self.client.get("/__prueba__/sospechosa/")

        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, "400.html")
        self.assertNotContains(response, INTERNAL_DETAIL, status_code=400)
        self.assertNotContains(response, "Traceback", status_code=400)

    def test_missing_record_returns_404_with_the_custom_page(self):
        self.client.force_login(User.objects.create_superuser("errores.404", "errores404@example.test", PASSWORD))

        response = self.client.get("/configuration/items/999999/")

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "No encontramos lo que buscas", status_code=404)

    def test_unhandled_error_returns_500_without_internal_details(self):
        self.client.raise_request_exception = False

        with self.assertLogs("django.request", "ERROR"):
            response = self.client.get("/__prueba__/falla/")

        self.assertEqual(response.status_code, 500)
        self.assertTemplateUsed(response, "500.html")
        self.assertContains(response, "No pudimos completar la operación", status_code=500)
        self.assertNotContains(response, INTERNAL_DETAIL, status_code=500)
        self.assertNotContains(response, "Traceback", status_code=500)


class MediaFilesTests(TestCase):
    """config/urls.py agrega /media/ al cargarse según DEBUG; se recarga para cada caso."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        media = override_settings(MEDIA_ROOT=directory.name)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(self.reload_urls)  # al final, con el DEBUG original de las pruebas

        user = User.objects.create_user("foto.media", "foto.media@example.test", PASSWORD)
        self.official = Official.objects.create(
            user=user, full_name="Foto Media", national_id="12.345.678-5", email="foto.media@example.test"
        )
        self.client.force_login(user)

    @staticmethod
    def reload_urls():
        importlib.reload(config.urls)
        clear_url_caches()

    def upload_photo(self):
        image = Image.new("RGB", (60, 60), "red")
        output = BytesIO()
        image.save(output, "PNG")
        response = self.client.post(
            reverse("my_profile"),
            {
                "first_name": "Foto",
                "last_name": "Media",
                "email": self.official.email,
                "phone": "",
                "photo": SimpleUploadedFile("foto.png", output.getvalue(), content_type="image/png"),
                "photo_crop": json.dumps({"x": 0, "y": 0, "width": 60, "height": 60}),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.official.refresh_from_db()
        self.assertTrue(self.official.photo.url.startswith("/media/"))
        with self.official.photo.open("rb") as stream:
            return self.official.photo.url, stream.read()

    def test_uploaded_photo_is_served_under_media_with_debug(self):
        with override_settings(DEBUG=True):
            self.reload_urls()
            url, content = self.upload_photo()

            response = self.client.get(url)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), content)

    def test_media_is_not_served_by_django_without_debug(self):
        with override_settings(DEBUG=False):
            self.reload_urls()
            url, _ = self.upload_photo()

            self.assertEqual(self.client.get(url).status_code, 404)
