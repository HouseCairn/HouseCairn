"""Serializer of audit entries, shared by the home and instance endpoints."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from housecairn.accounts.names import person_name
from housecairn.audit.models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer[AuditEvent]):
    label = serializers.SerializerMethodField(  # type: ignore[assignment]
        help_text="The entry as a sentence, in the API language."
    )
    actor_name = serializers.SerializerMethodField(
        help_text="The name shown for the person who acted (display name, never the address); "
        "empty for a deleted account or the system."
    )
    target_name = serializers.SerializerMethodField(
        help_text="The name shown for the person concerned; empty if there is none."
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
            "actor_name",
            "actor_email",
            "target_name",
            "target_email",
            "detail",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_actor_name(self, entry: AuditEvent) -> str:
        return person_name(entry.actor)

    @extend_schema_field(serializers.CharField())
    def get_target_name(self, entry: AuditEvent) -> str:
        return person_name(entry.target_user)

    @extend_schema_field(serializers.CharField())
    def get_label(self, entry: AuditEvent) -> str:
        return entry.label
