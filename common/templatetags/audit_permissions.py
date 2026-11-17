from django import template

from configuration.audit_views import can_view_audit

register = template.Library()
register.filter("can_view_audit", can_view_audit)
