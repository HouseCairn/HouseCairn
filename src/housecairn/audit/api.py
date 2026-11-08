"""Serializer of audit entries, shared by the home and instance endpoints."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from housecairn.audit.models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer[AuditEvent]):
    label = serializers.SerializerMethodField(  # type: ignore[assignment]
        help_text="The entry as a sentence, in the API language."
    )
    actor_email = serializers.EmailField(source="actor.email", read_only=True, default=None)
    target_email = serializers.EmailField(source="target_user.email", read_only=True, default=None)

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "created_at",
            "scope",
            "action",
            "label",
            "actor_email",
            "target_email",
            "detail",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_label(self, entry: AuditEvent) -> str:
        return entry.label
