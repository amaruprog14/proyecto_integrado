from concurrent.futures import ThreadPoolExecutor
from threading import Event
from datetime import date
from django.test import TransactionTestCase
from django.db import transaction, close_old_connections
from django.core.exceptions import ValidationError
from configuration.models import Period, PeriodMutex
from configuration.period_services import lock_period_registry, lock_open_period


class PeriodConcurrencyTests(TransactionTestCase):
    def test_registration_waits_for_close_and_rechecks_status(self):
        today = date(2026, 11, 2)
        period = Period.objects.create(start_date=today, end_date=today)
        PeriodMutex.objects.get_or_create(pk=1)
        locked, release, registering = Event(), Event(), Event()

        def close():
            close_old_connections()
            try:
                with transaction.atomic():
                    lock_period_registry()
                    Period.objects.get(pk=period.pk).close_period()
                    locked.set()
                    if not release.wait(10):
                        raise RuntimeError("No se liberó el cierre de prueba")
            finally:
                close_old_connections()

        def register():
            close_old_connections()
            try:
                with transaction.atomic():
                    registering.set()
                    lock_period_registry()
                    lock_open_period(today)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            closing = pool.submit(close)
            self.assertTrue(locked.wait(10))
            registration = pool.submit(register)
            try:
                self.assertTrue(registering.wait(10))
                self.assertFalse(registration.done())
            finally:
                release.set()
            closing.result(timeout=10)
            with self.assertRaises(ValidationError):
                registration.result(timeout=10)
