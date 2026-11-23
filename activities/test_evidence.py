from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections
from django.test import Client, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import Official
from agenda.alerts import notify_evidence_reviewers
from agenda.models import Alert
from analytics.services import CalculadorDesempenoService
from configuration.models import AuditLog, Period

from .models import Evidence, EvidenceBatch, EvidenceBatchAnnulment, EvidenceValidation, SocialAttention
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
        self.attention.recipient.phone = "912345678"
        self.attention.recipient.save(update_fields=["phone"])
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

    def evidence_url(self, action, batch):
        return reverse(f"activity_evidence_{action}", args=[self.activity.pk, batch.pk])

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

    def test_upload_and_review_record_metadata_and_audit(self):
        before_upload = timezone.now()
        photo = self.photo()
        self.assertRedirects(self.upload_images([photo]), self.detail + "#activity-evidence-title")
        batch = EvidenceBatch.objects.get(activity=self.activity)
        image = batch.images.get()
        self.assertEqual((batch.author, batch.stage), (self.official, EvidenceBatch.Stage.INITIAL))
        self.assertLessEqual(before_upload, image.upload_date)
        self.assertLessEqual(image.upload_date, timezone.now())
        size = (self.evidence_root / image.file_url).stat().st_size
        self.assertGreater(size, 0)
        self.assertEqual((image.original_name, image.file_format, image.size_kb),
                         ("foto-1.png", "png", (size + 1023) // 1024))

        reviewer = User.objects.get(username="verificador")
        self.client.force_login(reviewer)
        before_review = timezone.now()
        response = self.client.post(self.evidence_url("review", batch),
                                    {"status": "APPROVED", "observation": "Foto verificada."})
        self.assertRedirects(response, self.detail + "#activity-evidence-title")
        decision = image.validations.get()
        entry = AuditLog.objects.get(affected_record_id=batch.pk, action="Evidencia revisada")
        self.assertEqual((decision.verifier, decision.status), (reviewer.official, "APPROVED"))
        self.assertEqual((entry.official, entry.actor_username), (reviewer.official, reviewer.username))
        self.assertEqual((entry.previous_value, entry.new_value), ("PENDING", "APPROVED · Foto verificada."))
        for stamp in (decision.validated_at, entry.date):
            self.assertLessEqual(before_review, stamp)
            self.assertLessEqual(stamp, timezone.now())

    def test_rejected_and_corrected_uploads_count_only_after_approval(self):
        reviewer = User.objects.get(username="verificador")
        period = Period.objects.get()
        progress = CalculadorDesempenoService.calculate_current_progress
        for index, status in enumerate(("REJECTED", "CORRECTION_REQUESTED", "APPROVED"), start=1):
            self.client.force_login(self.staff)
            self.assertRedirects(self.upload_images([self.photo(index)]), self.detail + "#activity-evidence-title")
            batch = EvidenceBatch.objects.get(images__original_name=f"foto-{index}.png")
            self.client.force_login(reviewer)
            review = self.evidence_url("review", batch)
            self.assertContains(self.client.get(self.detail), review)
            self.assertRedirects(self.client.post(review, {"status": status, "observation": "Revisión de la foto."}),
                                 self.detail + "#activity-evidence-title")
            self.assertEqual(batch.images.get().validations.get().status, status)
            self.assertEqual(progress(self.official, self.activity.item, period), int(status == "APPROVED"))
        self.client.post(review, {"status": "APPROVED"})
        self.assertEqual(EvidenceValidation.objects.count(), 3)
        self.assertEqual(progress(self.official, self.activity.item, period), 1)

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

    def test_annulment_keeps_review_and_photos_and_updates_progress_once(self):
        self.upload_images([self.photo(1), self.photo(2)])
        self.upload_images([self.photo(3)], EvidenceBatch.Stage.COMPLETED)
        first, second = EvidenceBatch.objects.all()
        reviewer = User.objects.get(username="verificador")
        reviewer.user_permissions.add(Permission.objects.get(
            content_type__app_label="activities", codename="change_evidencevalidation",
        ))
        self.client.force_login(reviewer)
        period = Period.objects.get()
        progress = CalculadorDesempenoService.calculate_current_progress
        self.assertEqual(progress(self.official, self.activity.item, period), 0)
        for batch in (first, second):
            self.client.post(self.evidence_url("review", batch), {"status": "APPROVED", "observation": "Respaldo aprobado."})
        self.assertEqual(progress(self.official, self.activity.item, period), 1)
        self.assertContains(self.client.get(self.detail), "Anular aprobación", count=2)

        reason = "La imagen correspondía a otra gestión."
        annul_first = self.evidence_url("annul", first)
        self.assertRedirects(self.client.post(annul_first, {"reason": reason}), self.detail + "#activity-evidence-title")
        self.assertEqual(progress(self.official, self.activity.item, period), 1)
        self.assertRedirects(self.client.post(self.evidence_url("annul", second), {"reason": reason}),
                             self.detail + "#activity-evidence-title")
        self.assertEqual(progress(self.official, self.activity.item, period), 0)
        self.assertEqual(EvidenceValidation.objects.filter(status="APPROVED", deleted_at__isnull=False).count(), 3)
        self.assertEqual(Evidence.objects.filter(deleted_at__isnull=True).count(), 3)
        self.assertEqual(len(list(self.evidence_root.iterdir())), 3)
        self.assertEqual(EvidenceBatchAnnulment.objects.get(batch=first).actor, reviewer.official)
        audit = AuditLog.objects.filter(action="Aprobación de evidencia anulada", affected_record_id=first.pk).get()
        self.assertEqual(audit.previous_value, "Aprobada")
        self.assertIn(reason, audit.new_value)
        page = self.client.get(self.detail)
        self.assertContains(page, "Aprobación anulada", count=2)
        self.assertContains(page, "Aprobada por verificador", count=2)
        self.assertContains(page, "Anulada por verificador", count=2)
        self.assertContains(page, reason, count=2)
        self.assertNotContains(page, "Anular aprobación")
        self.assertNotContains(page, "Revisar evidencia")

        duplicate = self.client.post(annul_first, {"reason": "Otro motivo."}, follow=True)
        self.assertContains(duplicate, "ya fue anulada")
        self.assertEqual(EvidenceBatchAnnulment.objects.get(batch=first).reason, reason)
        self.client.post(self.evidence_url("review", first), {"status": "APPROVED"})
        self.assertEqual(progress(self.official, self.activity.item, period), 0)

        self.client.force_login(self.staff)
        self.upload_images([self.photo(4)])
        self.client.force_login(reviewer)
        replacement = EvidenceBatch.objects.exclude(pk__in=[first.pk, second.pk]).get()
        self.client.post(self.evidence_url("review", replacement), {"status": "APPROVED"})
        self.assertEqual(progress(self.official, self.activity.item, period), 1)

    def test_annulment_requires_an_approved_batch_permission_reason_and_open_period(self):
        self.upload_images([self.photo()])
        batch = EvidenceBatch.objects.get()
        reviewer = User.objects.get(username="verificador")
        foreign = User.objects.get(username="lector-foraneo")
        change = Permission.objects.get(content_type__app_label="activities", codename="change_evidencevalidation")
        url = self.evidence_url("annul", batch)
        reason = {"reason": "El archivo no corresponde."}
        self.client.force_login(reviewer)
        self.assertEqual(self.client.post(url, reason).status_code, 403)
        reviewer.user_permissions.add(change)
        self.assertContains(self.client.post(url, reason, follow=True), "no tiene una aprobación vigente")
        self.client.post(self.evidence_url("review", batch), {"status": "APPROVED"})
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertContains(self.client.post(url, {"reason": "   "}, follow=True), "Indica el motivo de la anulación.")
        foreign.user_permissions.add(change)
        self.client.force_login(foreign)
        self.assertEqual(self.client.post(url, reason).status_code, 404)
        self.staff.user_permissions.add(change)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(url, reason).status_code, 403)
        self.client.force_login(reviewer)
        Period.objects.get().close_period()
        self.assertNotContains(self.client.get(self.detail), "Anular aprobación")
        self.assertContains(self.client.post(url, reason, follow=True), "período abierto")
        self.assertFalse(EvidenceBatchAnnulment.objects.exists())
        self.assertTrue(EvidenceValidation.objects.filter(status="APPROVED", deleted_at__isnull=True).exists())

    def test_upload_notifies_only_scoped_reviewers_and_review_resolves_alert(self):
        self.upload_images([self.photo()])
        batch = EvidenceBatch.objects.get()
        notify_evidence_reviewers(batch)
        alert = Alert.objects.get(evidence_batch=batch)
        reviewer = User.objects.get(username="verificador")
        self.assertEqual(alert.official, reviewer.official)
        self.assertEqual(alert.reference_link, self.detail + f"#evidence-batch-{batch.pk}")
        inbox = reverse("alert_list")
        seen = reverse("alert_seen", args=[alert.pk])
        self.assertEqual(self.client.post(seen).status_code, 404)

        self.client.force_login(reviewer)
        self.assertContains(self.client.get(inbox), alert.reason)
        self.assertEqual(self.client.get(seen).status_code, 405)
        self.assertRedirects(self.client.post(seen), inbox)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Alert.Status.SEEN)
        self.assertNotContains(self.client.get(inbox), alert.reason)
        self.assertContains(self.client.get(inbox, {"estado": "todas"}), alert.reason)

        review = reverse("activity_evidence_review", args=[self.activity.pk, batch.pk])
        self.client.post(review, {"status": "APPROVED"})
        alert.refresh_from_db()
        self.assertIsNotNone(alert.resolved_at)
        self.assertContains(self.client.get(inbox, {"estado": "todas"}), "Resuelta")
        reviewer.user_permissions.clear()
        self.assertNotContains(self.client.get(inbox, {"estado": "todas"}), alert.reason)


@skipUnlessDBFeature("has_select_for_update")
class EvidenceConcurrentReviewTests(CaseFixture, TransactionTestCase):
    def setUp(self):
        self.create_fixture()
        super().setUp()

    def test_two_reviewers_leave_one_decision_and_one_audit_record(self):
        self.client.post(reverse("attention_entry"), self.attention_data())
        activity = SocialAttention.objects.get().activity
        batch = EvidenceBatch.objects.create(activity=activity, author=self.official, stage="INITIAL")
        for index in range(2):
            Evidence.objects.create(activity=activity, batch=batch, original_name=f"foto-{index}.png", file_url=f"qa-{index}.png")
        clients = []
        for username in ("revision-uno", "revision-dos"):
            user = User.objects.create_user(username)
            Official.objects.create(user=user, full_name=username, national_id=username, delegation=self.delegation,
                                    email=f"{username}@example.invalid")
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label="activities",
                codename__in=("view_activity", "view_evidence", "add_evidencevalidation")))
            client = Client()
            client.force_login(user)
            clients.append(client)
        barrier = Barrier(2)
        url = reverse("activity_evidence_review", args=[activity.pk, batch.pk])

        def review(client, status):
            try:
                barrier.wait(timeout=10)
                return client.post(url, {"status": status, "observation": "Revisión de prueba."}, follow=True)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(review, clients, ("APPROVED", "REJECTED")))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 200])
        self.assertEqual(sum("ya no está pendiente de revisión" in r.content.decode() for r in responses), 1)
        decisions = EvidenceValidation.objects.filter(evidence__batch=batch)
        self.assertEqual(set(decisions.values_list("evidence_id", flat=True)), set(batch.images.values_list("pk", flat=True)))
        self.assertEqual(decisions.count(), 2)
        self.assertEqual(decisions.values("status", "verifier_id").order_by().distinct().count(), 1)
        audit = AuditLog.objects.get(action="Evidencia revisada", affected_record_id=batch.pk)
        winner = decisions.first()
        self.assertEqual(audit.official_id, winner.verifier_id)
        self.assertIn(winner.status, audit.new_value)
