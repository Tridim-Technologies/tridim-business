from rest_framework import serializers

from .models import Job, JobAssignment, JobDueDateHistory, JobNote, JobStatusHistory


class JobStatusHistorySerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.get_username", read_only=True)

    class Meta:
        model = JobStatusHistory
        fields = ("previous_status", "status", "actor", "created_at", "note")


class JobDueDateHistorySerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.get_username", read_only=True)

    class Meta:
        model = JobDueDateHistory
        fields = ("previous_due_date", "due_date", "actor", "created_at")


class JobAssignmentSerializer(serializers.ModelSerializer):
    user = serializers.CharField(source="user.get_username", read_only=True)
    assigned_by = serializers.CharField(
        source="assigned_by.get_username", read_only=True
    )
    unassigned_by = serializers.CharField(
        source="unassigned_by.get_username", read_only=True, allow_null=True
    )

    class Meta:
        model = JobAssignment
        fields = (
            "id",
            "user",
            "assigned_by",
            "assigned_at",
            "unassigned_by",
            "unassigned_at",
        )


class JobNoteSerializer(serializers.ModelSerializer):
    author = serializers.CharField(source="author.get_username", read_only=True)

    class Meta:
        model = JobNote
        fields = ("id", "author", "content", "created_at")


class JobSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    source_quotation_id = serializers.UUIDField(read_only=True)
    status_history = JobStatusHistorySerializer(many=True, read_only=True)
    due_date_history = JobDueDateHistorySerializer(many=True, read_only=True)
    assignments = JobAssignmentSerializer(many=True, read_only=True)
    notes = JobNoteSerializer(many=True, read_only=True)

    class Meta:
        model = Job
        fields = (
            "id",
            "customer",
            "customer_name",
            "source_quotation_id",
            "status",
            "due_date",
            "status_history",
            "due_date_history",
            "assignments",
            "notes",
            "created_at",
        )
        read_only_fields = fields


class JobUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Job.Status.choices, required=False)
    due_date = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(max_length=240, required=False, allow_blank=True)

    def validate(self, attrs):
        if not {"status", "due_date"}.intersection(attrs):
            raise serializers.ValidationError("Provide a job status or due date.")
        return attrs


class JobAssignmentCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)


class JobNoteCreateSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=2000, trim_whitespace=True)
