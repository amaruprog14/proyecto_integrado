from uuid import uuid4

from django.contrib.auth.models import Permission, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Official
from activities.models import ClientRequest, SocialAttention
from activities.test_case_follow_up import CaseFixture

from .models import Comment


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class InternalCommentTests(CaseFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_fixture()
        cls.staff.user_permissions.add(Permission.objects.get(
            content_type__app_label="activities", codename="change_activity",
        ))

    def setUp(self):
        super().setUp()
        self.client.post(reverse("attention_entry"), self.attention_data())
        self.attention = SocialAttention.objects.get()

    def test_activity_comments_escape_content_require_csrf_and_preserve_author(self):
        activity = self.attention.activity
        url = reverse("activity_internal_comment", args=[activity.pk])
        detail = reverse("activity_detail", args=[activity.pk])
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        self.assertEqual(csrf_client.post(url, {"text": "Sin token"}).status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 405)
        for text in ("   ", "x" * 501):
            self.client.post(url, {"text": text})
        self.assertFalse(Comment.objects.exists())
        self.assertRedirects(self.client.post(url, {"text": "<script>Comentario</script>"}),
                             detail + "#internal-comments")
        saved = Comment.objects.get()
        self.assertEqual((saved.author, saved.activity), (self.official, activity))
        self.assertContains(self.client.get(detail), "&lt;script&gt;Comentario&lt;/script&gt;")

    def test_another_authorized_official_reads_the_activity_comment(self):
        activity = self.attention.activity
        reader = User.objects.create_user("lectora-interna")
        Official.objects.create(user=reader, full_name="Lectora ficticia", delegation=self.delegation,
                                national_id="LECTORA-TEST", email="lectora@example.test")
        reader.user_permissions.add(Permission.objects.get(content_type__app_label="activities", codename="view_activity"))
        detail = reverse("activity_detail", args=[activity.pk])
        self.assertRedirects(self.client.post(reverse("activity_internal_comment", args=[activity.pk]),
                                              {"text": "Coordinar visita de seguimiento."}), detail + "#internal-comments")
        second_session = Client()
        second_session.force_login(reader)
        response = second_session.get(detail)
        self.assertContains(response, "Coordinar visita de seguimiento.")
        self.assertEqual(response.context["internal_comments"].get().author, self.official)

    def test_case_conversation_is_staff_only_and_scoped(self):
        recipient = self.attention.recipient
        resident = User.objects.create_user("vecina-comentarios")
        recipient.user = resident
        recipient.save(update_fields=["user"])
        origin = ClientRequest.objects.create(recipient=recipient, delegation=self.delegation, attention_type=self.kind,
                                              subattention_type=self.sub, subject="Solicitud de prueba",
                                              submission_token=uuid4())
        case = origin.attention_case
        url = reverse("case_internal_comment", args=[case.pk])
        for text in ("Primera coordinación", "Respuesta interna del equipo"):
            self.assertEqual(self.client.post(url, {"text": text}).status_code, 302)
        staff_detail = self.client.get(reverse("attention_case_detail", args=[case.pk]))
        content = staff_detail.content.decode()
        self.assertLess(content.index("Primera coordinación"), content.index("Respuesta interna del equipo"))
        self.client.force_login(resident)
        self.assertNotContains(self.client.get(reverse("client_request_detail", args=[origin.pk])), "Primera coordinación")
        self.assertEqual(self.client.post(url, {"text": "Intento desde el portal"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("alert_list")).status_code, 403)

        self.official.delegation = self.other_delegation
        self.official.save(update_fields=["delegation"])
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(url, {"text": "Intento fuera del ámbito"}).status_code, 404)
        self.assertEqual(Comment.objects.filter(case=case).count(), 2)
