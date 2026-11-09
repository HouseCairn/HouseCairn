"""Web routes of tasks, occurrences and attachments, under /h/<home_id>/ (docs/adr/0010, 0031)."""

from django.urls import path

from housecairn.tasks import contractor_views, views

app_name = "tasks"

urlpatterns = [
    path("today/", views.TodayView.as_view(), name="today"),
    path("history/", views.HistoryView.as_view(), name="history"),
    path("tasks/", views.TaskListView.as_view(), name="list"),
    path("tasks/new/", views.TaskCreateView.as_view(), name="create"),
    path("tasks/<uuid:task_id>/", views.TaskDetailView.as_view(), name="detail"),
    path("tasks/<uuid:task_id>/edit/", views.TaskEditView.as_view(), name="edit"),
    path("tasks/<uuid:task_id>/delete/", views.TaskDeleteView.as_view(), name="delete"),
    path(
        "tasks/<uuid:task_id>/materials/",
        views.MaterialSaveView.as_view(),
        name="material-save",
    ),
    path(
        "tasks/<uuid:task_id>/materials/<uuid:material_id>/delete/",
        views.MaterialRemoveView.as_view(),
        name="material-remove",
    ),
    path(
        "tasks/<uuid:task_id>/attachments/new/",
        views.AttachmentAddView.as_view(),
        name="attachment-add",
    ),
    path(
        "tasks/<uuid:task_id>/occurrences/<uuid:occurrence_id>/complete/",
        views.OccurrenceCompleteView.as_view(),
        name="complete",
    ),
    path(
        "tasks/<uuid:task_id>/occurrences/<uuid:occurrence_id>/undo/",
        views.OccurrenceUndoView.as_view(),
        name="undo",
    ),
    path(
        "tasks/<uuid:task_id>/occurrences/<uuid:occurrence_id>/skip/",
        views.OccurrenceSkipView.as_view(),
        name="skip",
    ),
    path(
        "tasks/<uuid:task_id>/occurrences/<uuid:occurrence_id>/postpone/",
        views.OccurrencePostponeView.as_view(),
        name="postpone",
    ),
    path(
        "tasks/<uuid:task_id>/occurrences/<uuid:occurrence_id>/edit/",
        views.OccurrenceEditView.as_view(),
        name="occurrence-edit",
    ),
    path("contractors/", contractor_views.ContractorListView.as_view(), name="contractors"),
    path(
        "contractors/new/",
        contractor_views.ContractorCreateView.as_view(),
        name="contractor-create",
    ),
    path(
        "contractors/<uuid:contractor_id>/",
        contractor_views.ContractorDetailView.as_view(),
        name="contractor-detail",
    ),
    path(
        "contractors/<uuid:contractor_id>/edit/",
        contractor_views.ContractorEditView.as_view(),
        name="contractor-edit",
    ),
    path(
        "contractors/<uuid:contractor_id>/delete/",
        contractor_views.ContractorDeleteView.as_view(),
        name="contractor-delete",
    ),
    path(
        "contractors/<uuid:contractor_id>/contact.vcf",
        contractor_views.ContractorVcardView.as_view(),
        name="contractor-vcard",
    ),
    path("task-files/<uuid:attachment_id>/", views.AttachmentFileView.as_view(), name="attachment"),
    path(
        "task-files/<uuid:attachment_id>/thumbnail/",
        views.AttachmentThumbnailView.as_view(),
        name="attachment-thumbnail",
    ),
    path(
        "task-files/<uuid:attachment_id>/delete/",
        views.AttachmentDeleteView.as_view(),
        name="attachment-delete",
    ),
]
