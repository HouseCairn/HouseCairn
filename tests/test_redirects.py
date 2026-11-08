"""The shared rule for `next` addresses (housecairn.core.redirects)."""

import pytest
from django.test import RequestFactory

from housecairn.core.redirects import has_safe_shape, is_safe_redirect

REFUSED = [
    "",
    None,
    "//\r",
    "//\n",
    "//\t",
    "/\t/evil.example",
    "/\\\r",
    "\\\\/\n",
    "\\/\x00",
    "\\evil.example",
    "\\\\evil.example",
    "/\\evil.example",
    "//evil.example",
    "//testserver/homes/",
    " /homes/",
    "/homes/ ",
    "/homes/\u00a0",
    "/homes/\u200b",
    "/homes/\u202e",
    "\uff0f\uff0fevil.example",
    "/\uff3cevil.example",
]
ACCEPTED = ["/", "/homes/", "/h/1/tasks/?room=2&page=1", "/today/#top", "/caf%C3%A9/"]


@pytest.mark.parametrize("url", REFUSED)
def test_refused_shapes(url: str | None) -> None:
    assert not has_safe_shape(url)
    assert not is_safe_redirect(url, RequestFactory().get("/"))


@pytest.mark.parametrize("url", ACCEPTED)
def test_paths_of_this_site_are_kept(url: str) -> None:
    assert has_safe_shape(url)
    assert is_safe_redirect(url, RequestFactory().get("/"))


def test_another_host_or_a_bad_address_is_refused() -> None:
    request = RequestFactory().get("/")
    assert not is_safe_redirect("https://evil.example/", request)
    assert not is_safe_redirect("javascript:alert(1)", request)
    assert not is_safe_redirect("http://[", request)
    assert is_safe_redirect("http://testserver/homes/", request)


def test_plain_http_is_refused_on_a_secure_request() -> None:
    request = RequestFactory().get("/", secure=True)
    assert not is_safe_redirect("http://testserver/homes/", request)
    assert is_safe_redirect("https://testserver/homes/", request)
