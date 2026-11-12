"""The banner of a demonstration instance, on every page (docs/adr/0071)."""

from django.http import HttpRequest

from housecairn.demo import mode


def demo(request: HttpRequest) -> dict[str, object]:
    if not mode.is_on():
        return {"demo_mode": False}
    return {
        "demo_mode": True,
        "demo_accounts": [
            {"role": "admin", "email": mode.ADMIN_EMAIL},
            {"role": "user", "email": mode.USER_EMAIL},
        ],
        "demo_password": mode.PASSWORD,
        "demo_reset_time": f"{mode.RESET_HOUR:02d}:00",
        "demo_reset_zone": mode.RESET_TIME_ZONE,
    }
