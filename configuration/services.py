from configuration.models import AuditLog


class AuditoriaService:
    """Servicio (sin tabla): punto único para registrar eventos de auditoría."""

    @staticmethod
    def register_event(
        official, action, entity, previous_value="", new_value="", record_id=None, origin_ip=None
    ):
        """Crea un AuditLog. `official` puede ser None (eventos del sistema)."""
        return AuditLog.register_event(
            official=official,
            action=action,
            entity=entity,
            previous_value=previous_value,
            new_value=new_value,
            record_id=record_id,
            origin_ip=origin_ip,
        )

    @staticmethod
    def register_change(official, action, instance, previous_value="", new_value="", origin_ip=None):
        """Atajo: registra un evento tomando tabla e id desde la instancia afectada."""
        return AuditLog.register_event(
            official=official,
            action=action,
            entity=instance._meta.db_table,
            previous_value=previous_value,
            new_value=new_value,
            record_id=instance.pk,
            origin_ip=origin_ip,
        )