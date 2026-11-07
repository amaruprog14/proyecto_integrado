from common.testing_seed import seed_test_data
import uuid

from django.contrib.auth.models import User, Permission
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from accounts.models import ServiceRecipient, Delegation, Official, Role, Territory
from configuration.models import AttentionType, SubattentionType
from .models import ClientRequest, ClientRequestEvent


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ClientPortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_test_data()
        cls.users = [User.objects.create_user(f"client{i}", password="Client-12345") for i in range(2)]
        cls.people = [ServiceRecipient.objects.create(user=user, full_name=f"Cliente {i}",
            national_id=rut, email=f"client{i}@example.test")
            for i, (user, rut) in enumerate(zip(cls.users, ("12345678-5", "11111111-1")))]
        cls.delegation = Delegation.objects.get(delegation_name="Sur")
        cls.territory = Territory.objects.create(territory_name="Territorio Demo", delegation=cls.delegation)
        for person in cls.people:
            person.territory = cls.territory
            person.address = "Calle Demo 123"
            person.save()
        cls.kind = AttentionType.objects.filter(is_active=True, deleted_at__isnull=True).first()
        cls.sub = SubattentionType.objects.filter(attention_type=cls.kind, is_active=True).first()

    def setUp(self):
        self.client.force_login(self.users[0])

    def payload(self, **overrides):
        return dict(attention_type=self.kind.pk, subattention_type=self.sub.pk,
                    delegation=self.delegation.pk, subject="Consulta ciudadana",
                    description="Necesito orientación sobre los servicios.",
                    submission_token=str(uuid.uuid4()), **overrides)

    def create_request(self, recipient=None):
        return ClientRequest.objects.create(recipient=recipient or self.people[0], delegation=self.delegation,
            attention_type=self.kind, subattention_type=self.sub, subject="Solicitud privada",
            description="Antecedentes privados", submission_token=uuid.uuid4())

    def test_create_owner_status_and_duplicate_protection(self):
        payload = self.payload()
        payload.update(recipient=self.people[1].pk, status="RESOLVED", response="Falsa respuesta")
        self.assertRedirects(self.client.post(reverse("client_request_create"), payload), reverse("client_requests"))
        item = ClientRequest.objects.get()
        self.assertEqual(item.recipient, self.people[0])
        self.assertEqual(item.status, "RECEIVED")
        self.assertEqual(item.response, "")
        self.client.post(reverse("client_request_create"), payload)
        self.assertEqual(ClientRequest.objects.count(), 1)
        self.assertEqual(ClientRequestEvent.objects.count(), 1)
        self.assertContains(self.client.get(reverse("client_requests")), "Recibida")

    def test_direct_url_and_filters_never_expose_another_client(self):
        own = self.create_request()
        other = self.create_request(self.people[1])
        self.assertEqual(self.client.get(reverse("client_request_detail", args=[other.pk])).status_code, 404)
        response = self.client.get(reverse("client_requests"), {"recipient": self.people[1].pk})
        self.assertEqual(list(response.context["page_obj"]), [own])
        self.assertContains(response, 'action-icon--view')
        self.assertEqual(self.client.post(reverse("staff_client_request_review", args=[own.pk]),
            {"status": "RESOLVED", "response": "No autorizado"}).status_code, 403)

    def test_profile_edits_only_own_contact_and_preserves_identity(self):
        response = self.client.get(reverse("client_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Cargo</dt>")
        self.client.post(reverse("client_profile"), {"first_name": "Clara", "last_name": "Rojas",
            "email": "new@example.test", "phone": "+56912345678", "user": self.users[1].pk,
            "full_name": "Identidad falsa", "national_id": "11.111.111-1", "status": "INACTIVE"})
        self.people[0].refresh_from_db()
        self.people[1].refresh_from_db()
        self.assertEqual(self.people[0].email, "new@example.test")
        self.assertEqual(self.people[0].user_id, self.users[0].pk)
        # Nombre editable por el propio cliente (nombres + apellidos, igual en su cuenta); el
        # nombre completo enviado directamente, el RUT, el estado y la cuenta vinculada no.
        self.assertEqual(self.people[0].full_name, "Clara Rojas")
        self.users[0].refresh_from_db()
        self.assertEqual((self.users[0].first_name, self.users[0].last_name, self.users[0].email),
                         ("Clara", "Rojas", "new@example.test"))
        self.assertNotEqual(self.people[0].national_id, "11111111-1")
        self.assertEqual(self.people[0].status, "ACTIVE")
        self.assertEqual(self.people[1].email, "client1@example.test")

    def test_form_rejects_inactive_and_mismatched_catalogs(self):
        other_type = AttentionType.objects.create(name="Otro tipo")
        payload = self.payload()
        payload["attention_type"] = other_type.pk
        response = self.client.post(reverse("client_request_create"), payload)
        self.assertIn("subattention_type", response.context["form"].errors)
        self.kind.is_active = False
        self.kind.save()
        response = self.client.post(reverse("client_request_create"), self.payload())
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(ClientRequest.objects.count(), 0)

    def test_disabled_client_anonymous_and_employee_access(self):
        self.assertRedirects(self.client.get(reverse("home")), reverse("client_requests"))
        self.client.force_login(User.objects.get(username="admin_demo"))
        self.assertEqual(self.client.get(reverse("client_requests")).status_code, 403)
        self.client.force_login(self.users[0])
        self.people[0].status = "INACTIVE"
        self.people[0].save()
        self.assertIn(self.client.get(reverse("client_requests")).status_code, (302, 403))
        self.assertIsNone(__import__('django.contrib.auth', fromlist=['authenticate']).authenticate(
            username=self.users[0].username, password="Client-12345"))
        self.client.logout()
        self.assertEqual(self.client.get(reverse("client_requests")).status_code, 302)

    def test_staff_response_and_delegation_boundary(self):
        item = self.create_request()
        user = User.objects.create_user("reviewer", password="Reviewer-123")
        official = Official.objects.create(user=user, full_name="Revisor", national_id="staff-test",
                                           email="reviewer@example.test", delegation=self.delegation)
        role = Role.objects.create(role_name="Revisión ciudadana", scope=Role.Scope.DELEGATION)
        role.permissions.add(*Permission.objects.filter(content_type__app_label="activities",
            codename__in=["view_socialattention", "change_socialattention"]))
        official.roles.add(role)
        self.client.force_login(user)
        url = reverse("staff_client_request_review", args=[item.pk])
        self.assertEqual(self.client.post(url, {"status": "RESOLVED", "response": ""}).status_code, 200)
        self.assertEqual(self.client.post(url, {"status": "RESOLVED", "response": "Tu consulta fue atendida."}).status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.status, "RESOLVED")
        self.assertEqual(item.events.count(), 1)
        self.client.force_login(self.users[0])
        self.assertContains(self.client.get(reverse("client_request_detail", args=[item.pk])), "Tu consulta fue atendida.")
        self.client.force_login(user)
        item.delegation = Delegation.objects.get(delegation_name="Norte")
        item.save()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"status": "REVIEW", "response": "Ajena"}).status_code, 404)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ClientPhotoTests(TransactionTestCase):
    def test_client_crop_and_private_photo(self):
        import json
        import tempfile
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            user = User.objects.create_user("client-photo", password="Client-12345")
            recipient = ServiceRecipient.objects.create(user=user, full_name="Cliente Foto", national_id="12345678-5")
            image = BytesIO()
            Image.new("RGB", (100, 80), "red").save(image, "PNG")
            self.client.force_login(user)
            self.assertEqual(self.client.post(reverse("client_profile"), {
                "first_name": "Cliente", "last_name": "Foto",
                "email": "photo@example.test", "phone": "", "photo_crop": json.dumps(
                    dict(x=10, y=10, width=50, height=50)),
                "photo": SimpleUploadedFile("perfil.png", image.getvalue(), content_type="image/png")
            }).status_code, 302)
            recipient.refresh_from_db()
            with recipient.photo.open("rb") as saved:
                self.assertEqual(Image.open(saved).size, (50, 50))
            response = self.client.get(reverse("client_profile_photo"))
            self.assertEqual(response.status_code, 200)
            self.assertIn("private", response["Cache-Control"])
            self.assertIn("no-store", response["Cache-Control"])
            self.assertTrue(b"".join(response.streaming_content))
            response.close()
            other = User.objects.create_user("client-other-photo", password="Client-12345")
            ServiceRecipient.objects.create(user=other, full_name="Otro Cliente", national_id="11111111-1")
            self.client.force_login(other)
            self.assertEqual(self.client.get(reverse("client_profile_photo"), {"recipient": recipient.pk}).status_code, 404)
