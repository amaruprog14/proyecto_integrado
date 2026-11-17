from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import Delegation, Official, Role
from accounts.views import recovery_token_generator
from activities.models import EvidenceBatch, EvidenceValidation
from analytics.models import ScoreAdjustment
from analytics.queries import TEAM_PERFORMANCE, VIEW_PERFORMANCE
from analytics.services import q2
from analytics.test_performance_calculator import CalculatorFixture
from configuration.models import AuditLog, Period


TODAY = date(2026, 8, 26)
PASSWORD = "Clave-API-2026"
TOKEN = reverse("sgr_api:token")
REFRESH = reverse("sgr_api:token_refresh")
PERIODS = reverse("sgr_api:periods")
PERSONAL = reverse("sgr_api:personal_performance")


def permission(name):
    app, codename = name.split(".")
    return Permission.objects.get(content_type__app_label=app, codename=codename)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PerformanceAPITests(CalculatorFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other = Delegation.objects.create(delegation_name="Sur", address="Calle 2", commune="La Serena")
        cls.worker = cls.account("funcionario-api", "Gestor social", Role.Scope.OWN, VIEW_PERFORMANCE)
        cls.delegate = cls.account("delegada-api", "Gestor social", Role.Scope.DELEGATION,
                                   VIEW_PERFORMANCE, TEAM_PERFORMANCE)
        cls.global_user = cls.account("coordinadora-api", None, Role.Scope.ALL, VIEW_PERFORMANCE, TEAM_PERFORMANCE)
        cls.verifier.user = User.objects.create_user("verificador-api", password=PASSWORD)
        cls.verifier.save(update_fields=["user"])
        cls.verifier.user.user_permissions.add(*[permission(f"activities.{name}") for name in
                                                 ("view_activity", "view_evidence", "add_evidencevalidation")])

    @classmethod
    def account(cls, username, position, scope, *permissions):
        official = cls.official(username, position)
        official.user = User.objects.create_user(username, email=official.email, password=PASSWORD)
        official.save(update_fields=["user"])
        role = Role.objects.create(role_name=f"Rol {username}", scope=scope)
        role.permissions.add(*(permission(name) for name in permissions))
        official.roles.add(role)
        return official

    def setUp(self):
        self.api = APIClient()
        localdate = patch("sgr_api.views.timezone.localdate", return_value=TODAY)
        localdate.start()
        self.addCleanup(localdate.stop)

    def obtain(self, official, identifier=None):
        response = self.api.post(TOKEN, {"username": identifier or official.user.username, "password": PASSWORD},
                                 format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response.json()

    def authorize(self, official):
        tokens = self.obtain(official)
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        return tokens

    def team_url(self, delegation=None):
        return reverse("sgr_api:delegation_performance", args=[(delegation or self.delegation).pk])

    def test_issue_refresh_invalid_password_and_expired_token(self):
        self.assertEqual(self.api.get(PERSONAL).status_code, 401)
        self.api.credentials(HTTP_AUTHORIZATION="Bearer invalido")
        self.assertEqual(self.api.get(PERSONAL).status_code, 401)
        self.api.credentials()
        self.assertEqual(self.api.post(TOKEN, {"username": self.worker.user.username, "password": "incorrecta"},
                                       format="json").status_code, 401)
        tokens = self.obtain(self.worker, self.worker.email)
        response = self.api.post(REFRESH, {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(response.status_code, 200)
        refreshed = AccessToken(response.json()["access"])
        self.assertEqual(refreshed["exp"] - refreshed["iat"], 300)
        refreshed.set_exp(lifetime=timedelta(seconds=-1))
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {refreshed}")
        self.assertEqual(self.api.get(PERSONAL).status_code, 401)

    def test_token_endpoint_respects_sgr_lockout(self):
        with self.settings(LOGIN_MAX_FAILED_ATTEMPTS=2):
            for identifier in (self.worker.user.username, self.worker.email):
                self.assertEqual(self.api.post(TOKEN, {"username": identifier, "password": "incorrecta"},
                                               format="json").status_code, 401)
            self.assertEqual(self.api.post(TOKEN, {"username": self.worker.user.username, "password": PASSWORD},
                                           format="json").status_code, 401)

    def assert_old_tokens_rejected_and_new_password_works(self, tokens, password):
        self.assertEqual(self.api.get(PERIODS).status_code, 401)
        self.api.credentials()
        self.assertEqual(self.api.post(REFRESH, {"refresh": tokens["refresh"]}, format="json").status_code, 401)
        fresh = self.api.post(TOKEN, {"username": self.worker.user.username, "password": password}, format="json")
        self.assertEqual(fresh.status_code, 200)
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {fresh.json()['access']}")
        self.assertEqual(self.api.get(PERIODS).status_code, 200)
        self.api.credentials()
        self.assertEqual(self.api.post(REFRESH, {"refresh": fresh.json()["refresh"]}, format="json").status_code, 200)

    def test_web_password_change_revokes_both_tokens(self):
        tokens = self.authorize(self.worker)
        self.client.force_login(self.worker.user)
        password = "Renovada-API-2026"
        response = self.client.post(reverse("password_change"), {
            "old_password": PASSWORD, "new_password1": password, "new_password2": password,
        })
        self.assertEqual(response.status_code, 302)
        self.assert_old_tokens_rejected_and_new_password_works(tokens, password)

    def test_password_recovery_revokes_both_tokens(self):
        tokens = self.authorize(self.worker)
        link = reverse("recovery_confirm", kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(self.worker.user.pk)),
            "token": recovery_token_generator.make_token(self.worker.user),
        })
        response = self.client.get(link, follow=True)
        self.assertTrue(response.context["validlink"])
        password = "Recuperada-API-2026"
        response = self.client.post(response.request["PATH_INFO"], {
            "new_password1": password, "new_password2": password,
        })
        self.assertEqual(response.status_code, 302)
        self.assert_old_tokens_rejected_and_new_password_works(tokens, password)

    def test_failed_password_change_keeps_existing_tokens_valid(self):
        tokens = self.authorize(self.worker)
        self.client.force_login(self.worker.user)
        response = self.client.post(reverse("password_change"), {
            "old_password": PASSWORD, "new_password1": "Renovada-API-2026", "new_password2": "Diferente-API-2026",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.api.get(PERIODS).status_code, 200)
        self.api.credentials()
        self.assertEqual(self.api.post(REFRESH, {"refresh": tokens["refresh"]}, format="json").status_code, 200)

    def test_legacy_tokens_without_password_claim_are_rejected(self):
        tokens = self.authorize(self.worker)
        access, refresh = AccessToken(tokens["access"]), RefreshToken(tokens["refresh"])
        del access[api_settings.REVOKE_TOKEN_CLAIM]
        del refresh[api_settings.REVOKE_TOKEN_CLAIM]
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(self.api.get(PERIODS).status_code, 401)
        self.api.credentials()
        self.assertEqual(self.api.post(REFRESH, {"refresh": str(refresh)}, format="json").status_code, 401)

    def test_role_removal_and_suspension_take_effect_after_token_issuance(self):
        tokens = self.authorize(self.worker)
        self.assertEqual(self.api.get(PERSONAL).status_code, 200)
        self.worker.roles.clear()
        self.assertEqual(self.api.get(PERSONAL).status_code, 403)
        self.assertTrue(AuditLog.objects.filter(action="Acceso denegado", official=self.worker).exists())
        Official.objects.filter(pk=self.worker.pk).update(status=Official.Status.SUSPENDED)
        self.assertEqual(self.api.get(PERSONAL).status_code, 403)
        self.assertEqual(self.api.post(REFRESH, {"refresh": tokens["refresh"]}, format="json").status_code, 401)
        self.assertEqual(self.api.post(TOKEN, {"username": self.worker.user.username, "password": PASSWORD},
                                       format="json").status_code, 401)

    def test_period_discovery_validation_and_no_results(self):
        self.authorize(self.worker)
        self.assertEqual(self.api.post(PERSONAL, {}, format="json").status_code, 405)
        archived = Period.objects.create(start_date=date(2026, 10, 1), end_date=date(2026, 12, 31),
                                         deleted_at=timezone.now())
        self.assertEqual(self.api.get(PERIODS).json(), [{
            "id": self.period.pk, "inicio": "2026-07-01", "fin": "2026-09-30",
            "estado": Period.Status.OPEN, "congelado_en": None,
        }])
        self.assertEqual(self.api.get(PERSONAL).json()["periodo"]["id"], self.period.pk)
        for invalid in ("", "0", "1.0", "-1", "x", "9223372036854775808"):
            with self.subTest(periodo=invalid):
                self.assertEqual(self.api.get(PERSONAL, {"periodo": invalid}).status_code, 400)
        self.assertEqual(self.api.get(PERSONAL, {"periodo": archived.pk}).status_code, 404)
        self.assertEqual(self.api.get(PERSONAL, {"periodo": archived.pk + 1}).status_code, 404)
        plan = self.plans["Gestor social"]
        plan.versions.update(published_at=None)
        response = self.api.get(PERSONAL)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["total_ponderado"])
        self.assertTrue(response.json()["aviso"])
        Period.objects.filter(pk=self.period.pk).update(deleted_at=timezone.now())
        self.assertEqual(self.api.get(PERIODS).json(), [])
        self.assertEqual(self.api.get(PERSONAL).status_code, 404)

    def test_delegation_authorization_and_resource_audit(self):
        self.authorize(self.worker)
        self.assertEqual(self.api.get(self.team_url()).status_code, 403)
        self.authorize(self.delegate)
        self.assertEqual(self.api.get(self.team_url()).status_code, 200)
        self.assertEqual(self.api.get(self.team_url(self.other)).status_code, 404)
        self.assertTrue(AuditLog.objects.filter(official=self.delegate, action="Acceso denegado",
                                                affected_record_id=self.other.pk).exists())
        self.authorize(self.global_user)
        response = self.api.get(self.team_url(self.other))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["promedio_ponderado"])
        self.assertNotIn("funcionario-api", response.content.decode())

    def test_web_approval_changes_the_personal_and_team_json(self):
        [activity] = self.record(self.worker, "Visita terreno", 1, status=None)
        batch = EvidenceBatch.objects.create(activity=activity, author=self.worker,
                                             stage=EvidenceBatch.Stage.COMPLETED, description="Respaldo de prueba")
        activity.evidences.update(batch=batch)
        self.authorize(self.worker)
        self.client.force_login(self.worker.user)
        for progress in (0, 1):
            panel = self.client.get(reverse("my_performance")).context["result"]
            response = self.api.get(PERSONAL)
            item = next(row for row in response.json()["items"] if row["nombre"] == "Visita terreno")
            self.assertEqual(self.rows(panel)["Visita terreno"].progress, progress)
            self.assertEqual(item["avance"], f"{progress}.00")
            self.assertEqual(response.json()["total_ponderado"], str(q2(panel.total)))
            self.assertIn("no-store", response["Cache-Control"])
            if progress == 0:
                self.client.force_login(self.verifier.user)
                review = reverse("activity_evidence_review", args=[activity.pk, batch.pk])
                self.client.post(review, {"status": EvidenceValidation.Status.APPROVED})
                self.assertTrue(EvidenceValidation.objects.filter(evidence__batch=batch, status="APPROVED").exists())
                self.client.force_login(self.worker.user)

        self.authorize(self.delegate)
        self.client.force_login(self.delegate.user)
        web = self.client.get(reverse("delegation_performance")).context
        team = self.api.get(self.team_url()).json()
        self.assertEqual(team["actividades_computadas"], web["total_activities"])
        self.assertEqual(team["promedio_ponderado"], str(q2(web["average"])))

    def test_closed_results_and_historical_delegation_remain_frozen(self):
        [activity] = self.record(self.worker, "Visita terreno", 1)
        Period.objects.filter(pk=self.period.pk).update(status=Period.Status.CLOSED)
        self.authorize(self.delegate)
        missing = self.api.get(self.team_url()).json()
        self.assertIsNone(missing["promedio_ponderado"])
        self.assertIn("congelados", missing["aviso"])
        Period.objects.filter(pk=self.period.pk).update(status=Period.Status.OPEN)
        self.period.close_period()
        before = self.api.get(self.team_url()).json()
        self.assertEqual(before["actividades_computadas"], 1)
        self.assertIsNotNone(before["periodo"]["congelado_en"])
        Official.objects.filter(pk=self.worker.pk).update(delegation=self.other)
        activity.deleted_at = timezone.now()
        activity.save(update_fields=["deleted_at"])
        self.assertEqual(self.api.get(self.team_url()).json(), before)
        self.authorize(self.worker)
        personal = self.api.get(PERSONAL).json()
        self.assertEqual(personal["fecha_corte"], "2026-09-30")
        self.assertEqual(next(row for row in personal["items"] if row["nombre"] == "Visita terreno")["avance"], "1.00")

    def adjustment(self, kind, points, day=date(2026, 8, 1)):
        return ScoreAdjustment.objects.create(
            official=self.worker, period=self.period, occurred_on=day, kind=kind,
            channel=ScoreAdjustment.Channel.EMAIL, reason="Motivo ficticio", written_support="Correo ficticio",
            recorded_by=self.verifier.user, reviewed_by=self.verifier.user,
            reviewed_at=timezone.make_aware(datetime.combine(day + timedelta(days=1), time(10))),
            status=ScoreAdjustment.Status.APPROVED, points=Decimal(points))

    def assert_reconciles(self, data):
        base, adjustments = Decimal(data["total_base"]), Decimal(data["ajustes_computables"])
        self.assertEqual(Decimal(data["total_ponderado"]), min(base + adjustments, Decimal(data["tope_resultado_final"])))
        self.assertEqual(adjustments, sum((Decimal(row["puntos_computables"]) for row in data["ajustes"]), Decimal(0)))
        self.assertEqual(base, sum((Decimal(row["resultado_ponderado"]) for row in data["items"]), Decimal(0)))

    def test_total_reconciles_with_base_and_score_adjustments(self):
        self.authorize(self.worker)
        data = self.api.get(PERSONAL).json()
        self.assertEqual((data["total_ponderado"], data["total_base"], data["ajustes_computables"], data["ajustes"]),
                         ("0.00", "0.00", "0.00", []))
        self.assertEqual(data["tope_resultado_final"], "150.00")
        self.assert_reconciles(data)

        # Una felicitación aprobada: el total es 10 aunque los ítems sumen 0, y ahora se explica.
        self.adjustment(ScoreAdjustment.Kind.CONGRATULATION, "10")
        data = self.api.get(PERSONAL).json()
        self.assertEqual((data["total_ponderado"], data["total_base"], data["ajustes_computables"]), ("10.00", "0.00", "10.00"))
        self.assertEqual(data["ajustes"], [{"tipo": "Felicitación", "fecha": "2026-08-01", "puntos_autorizados": "10.00",
                                            "puntos_computables": "10.00", "excluido_por_limite": False}])
        self.assert_reconciles(data)

        # Más de tres felicitaciones: la cuarta queda informada pero excluida por el límite.
        for _ in range(3):
            self.adjustment(ScoreAdjustment.Kind.CONGRATULATION, "10")
        data = self.api.get(PERSONAL).json()
        self.assertEqual(data["ajustes_computables"], "30.00")
        self.assertEqual([row["excluido_por_limite"] for row in data["ajustes"]], [False, False, False, True])
        self.assertEqual((data["ajustes"][-1]["puntos_autorizados"], data["ajustes"][-1]["puntos_computables"]), ("10.00", "0.00"))
        self.assert_reconciles(data)

        # Un reclamo descuenta: base + ajustes negativos, sin cambiar los campos existentes.
        self.record(self.worker, "Visita terreno", 12)
        self.adjustment(ScoreAdjustment.Kind.COMPLAINT, "-20")
        data = self.api.get(PERSONAL).json()
        self.assertEqual((data["total_base"], data["ajustes_computables"], data["total_ponderado"]), ("20.00", "10.00", "30.00"))
        self.assertEqual(data["ajustes"][-1]["tipo"], "Reclamo")
        self.assert_reconciles(data)
        live = data

        # Período congelado: los mismos valores salen del resumen guardado al cierre.
        self.period.close_period()
        ScoreAdjustment.objects.filter(official=self.worker).update(points=Decimal("1"))
        frozen = self.api.get(PERSONAL).json()
        for key in ("total_ponderado", "total_base", "ajustes_computables", "ajustes", "tope_resultado_final"):
            self.assertEqual(frozen[key], live[key], key)
        self.assert_reconciles(frozen)

    def test_final_score_cap_comes_from_the_plan_version(self):
        self.plans["Gestor social"].versions.update(max_final_score=Decimal("15"))
        self.record(self.worker, "Visita terreno", 12)  # 20 puntos base
        self.authorize(self.worker)
        data = self.api.get(PERSONAL).json()
        self.assertEqual((data["total_base"], data["tope_resultado_final"], data["total_ponderado"]), ("20.00", "15.00", "15.00"))
        self.assert_reconciles(data)

    @override_settings(DEBUG=False, SGR_API_DOCS_ENABLED=False)
    def test_documentation_requires_an_enabled_environment_and_web_session(self):
        schema = reverse("sgr_api:schema")
        self.assertEqual(self.client.get(schema).status_code, 404)
        with self.settings(SGR_API_DOCS_ENABLED=True):
            self.assertEqual(self.client.get(schema).status_code, 403)
            self.client.force_login(self.worker.user)
            for page in ("swagger", "redoc"):
                self.assertContains(self.client.get(reverse(f"sgr_api:{page}")), "drf_spectacular_sidecar")
            document = self.client.get(schema, HTTP_ACCEPT="application/vnd.oai.openapi+json").json()
            paths = document["paths"]
            self.assertEqual(paths[PERSONAL]["get"]["security"], [{"jwtAuth": []}])
            self.assertFalse(paths[TOKEN]["post"].get("security"))
            self.assertEqual(self.client.get(PERSONAL).status_code, 401)
