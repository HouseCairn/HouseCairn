"""Web routes of the budget, under /h/<home_id>/ (docs/adr/0010, 0051)."""

from django.urls import path

from housecairn.budget import views

app_name = "budget"

urlpatterns = [
    path("budget/", views.OverviewView.as_view(), name="overview"),
    path("budget/rooms/", views.RoomsView.as_view(), name="rooms"),
    path("budget/projects/", views.ProjectsView.as_view(), name="projects"),
    path("budget/tasks/", views.TasksView.as_view(), name="tasks"),
]
