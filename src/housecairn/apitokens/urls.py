"""Web routes of API tokens, mounted at /me/tokens/."""

from django.urls import path

from housecairn.apitokens import views

app_name = "api-tokens"

urlpatterns = [
    path("", views.TokenListView.as_view(), name="list"),
    path("new/", views.TokenCreateView.as_view(), name="new"),
    path("<uuid:token_id>/revoke/", views.TokenRevokeView.as_view(), name="revoke"),
]
