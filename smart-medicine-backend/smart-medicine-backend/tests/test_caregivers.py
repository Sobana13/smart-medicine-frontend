from tests.conftest import MED, register

LINK = {"name": "Asha", "relationship": "Daughter", "email": "care@example.com", "whatsappNumber": "+919811111111",
        "consent": True, "recipientOptIn": True, "notifyMissed": True}


def _setup(client, app):
    register(client)
    care = app.test_client()
    register(care, email="care@example.com", name="Asha Care", role="caregiver")
    patient_id = client.get("/api/auth/me").get_json()["user"]["id"]
    return care, patient_id


def test_link_requires_patient_consent(client):
    register(client)
    res = client.post("/api/caregivers", json={**LINK, "consent": False})
    assert res.status_code == 400 and "consent" in res.get_json()["details"]


def test_linked_caregiver_can_view_but_not_edit(client, app):
    care, patient_id = _setup(client, app)
    assert client.post("/api/caregivers", json=LINK).status_code == 201
    client.post("/api/medicines", json=MED)
    assert care.get(f"/api/medicines?patientId={patient_id}").status_code == 200
    assert care.get(f"/api/schedule?patientId={patient_id}").status_code == 200
    assert care.get("/api/caregivers").get_json()[0]["patientName"] == "Pat Patient"
    assert care.post("/api/medicines", json=MED).status_code == 403


def test_unlinked_caregiver_is_blocked(client, app):
    care, patient_id = _setup(client, app)
    assert care.get(f"/api/schedule?patientId={patient_id}").status_code == 403
    assert care.get("/api/schedule").status_code == 400  # patientId is required


def test_withdrawing_consent_removes_access(client, app):
    care, patient_id = _setup(client, app)
    link_id = client.post("/api/caregivers", json=LINK).get_json()["id"]
    client.put(f"/api/caregivers/{link_id}", json={**LINK, "consent": False})
    assert care.get(f"/api/schedule?patientId={patient_id}").status_code == 403
