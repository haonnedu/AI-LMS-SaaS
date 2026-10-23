"""Integration helper: accept the current user agreement + privacy notice (decision 0009).

``POST /v1/auth/bootstrap`` answers 409 ``agreement_required`` until the caller has accepted the
current versions, so every integration test that bootstraps a person calls ``accept_agreements``
first (it also provisions the account, exactly like bootstrap).
"""

from app.api import agreements as agreements_api


def mount_agreements(app) -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    if not any(route.path in paths for route in agreements_api.router.routes):
        app.include_router(agreements_api.router)


async def accept_agreements(client, headers: dict) -> dict:
    status = await client.get("/v1/auth/agreements", headers=headers)
    assert status.status_code == 200, status.text
    required = status.json()["required"]
    response = await client.post(
        "/v1/auth/agreements",
        headers=headers,
        json={
            "userAgreementVersion": required["userAgreement"],
            "privacyVersion": required["privacy"],
            "accepted": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["upToDate"] is True
    return response.json()
