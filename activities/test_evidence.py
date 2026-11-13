from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from accounts.models import Official
from analytics.services import CalculadorDesempenoService
from configuration.models import Period

from .models import Evidence, EvidenceBatch, EvidenceValidation, SocialAttention
from .test_case_follow_up import CaseFixture


class EvidenceTests(CaseFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.create_fixture()
        cls.staff.user_permissions.add(Permission.objects.get(
            content_type__app_label="activities", codename="add_evidence",
        ))
        for username, delegation in (("verificador", cls.delegation), ("lector-foraneo", cls.other_delegation)):
            user = User.objects.create_user(username)
            Official.objects.create(user=user, full_name=username, delegation=delegation,
                                    national_id=username, email=f"{username}@example.test")
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label="activities",
                codename__in=("view_activity", "view_evidence", "add_evidencevalidation")))

    def setUp(self):
        super().setUp()
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.evidence_root = Path(temp.name)
        settings = self.settings(EVIDENCE_ROOT=self.evidence_root)
        settings.enable()
        self.addCleanup(settings.disable)
        entry = reverse("attention_entry")
        self.assertRedirects(self.client.post(entry, self.attention_data()), entry)
        self.attention = SocialAttention.objects.get()
        self.activity = self.attention.activity
        self.detail = reverse("activity_detail", args=[self.activity.pk])
        self.upload = reverse("activity_evidence_upload", args=[self.activity.pk])

    @staticmethod
    def photo(index=1):
        stream = BytesIO()
        Image.new("RGB", (20, 20)).save(stream, "PNG")
        return SimpleUploadedFile(f"foto-{index}.png", stream.getvalue(), "image/png")

    def upload_images(self, images, stage=EvidenceBatch.Stage.INITIAL):
        return self.client.post(self.upload, dict(images=images, stage=stage, description="Se revisó el poste."))

    def test_multiple_stages_share_the_activity_history_and_approve_once(self):
        self.assertRedirects(self.upload_images([self.photo(index) for index in range(5)]),
                             self.detail + "#activity-evidence-title")
        self.upload_images([self.photo()], EvidenceBatch.Stage.COMPLETED)
        self.assertEqual(EvidenceBatch.objects.count(), 2)
        self.assertEqual(Evidence.objects.count(), 6)
        self.assertContains(self.client.get(self.detail), "5 imágenes adjuntas")
        self.assertContains(self.client.get(self.detail), "Trabajo terminado")
        case_url = reverse("attention_case_detail", args=[self.attention.case_id])
        self.assertContains(self.client.get(case_url), f'{self.detail}#activity-evidence-title')

        image = Evidence.objects.first()
        url = reverse("activity_evidence_image", args=[self.activity.pk, image.pk])
        response = self.client.get(url)
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))
        period = Period.objects.get()
        progress = CalculadorDesempenoService.calculate_current_progress
        self.assertEqual(progress(self.official, self.activity.item, period), 0)

        self.client.force_login(User.objects.get(username="verificador"))
        for batch in EvidenceBatch.objects.all():
            review = reverse("activity_evidence_review", args=[self.activity.pk, batch.pk])
            self.client.post(review, {"status": "APPROVED"})
            self.client.post(review, {"status": "REJECTED", "observation": "Otra decisión"})
        self.assertEqual(EvidenceValidation.objects.filter(status="APPROVED").count(), 6)
        self.assertEqual(progress(self.official, self.activity.item, period), 1)

        self.client.force_login(User.objects.get(username="lector-foraneo"))
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(review, {"status": "APPROVED"}).status_code, 404)

    def test_invalid_upload_is_atomic_and_closed_period_refuses_writes(self):
        for images in ([self.photo(), SimpleUploadedFile("invalido.png", b"texto")], [],
                       [self.photo(index) for index in range(11)]):
            self.assertRedirects(self.upload_images(images), self.detail + "#activity-evidence-title")
            self.assertFalse(EvidenceBatch.objects.exists())
            self.assertFalse(list(self.evidence_root.iterdir()))
        Period.objects.update(status=Period.Status.CLOSED)
        self.assertNotContains(self.client.get(self.detail), "Guardar evidencia")
        self.upload_images([self.photo()])
        self.assertFalse(EvidenceBatch.objects.exists())

    def test_author_cannot_review_and_rejection_requires_reason(self):
        self.upload_images([self.photo()])
        batch = EvidenceBatch.objects.get()
        review = reverse("activity_evidence_review", args=[self.activity.pk, batch.pk])
        self.staff.user_permissions.add(Permission.objects.get(
            content_type__app_label="activities", codename="add_evidencevalidation",
        ))
        self.assertEqual(self.client.post(review, {"status": "APPROVED"}).status_code, 403)
        self.client.force_login(User.objects.get(username="verificador"))
        result = self.client.post(review, {"status": "CORRECTION_REQUESTED"}, follow=True)
        self.assertContains(result, "Indica el motivo")
        self.assertFalse(EvidenceValidation.objects.exists())
        self.client.post(review, {"status": "CORRECTION_REQUESTED", "observation": "Falta claridad."})
        self.assertEqual(EvidenceValidation.objects.get().observation, "Falta claridad.")
