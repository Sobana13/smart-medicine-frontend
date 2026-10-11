from tests.conftest import MED, register


def test_create_list_get_update_delete(client):
    register(client)
    created = client.post("/api/medicines", json=MED)
    assert created.status_code == 201
    med = created.get_json()
    assert med["times"] == ["08:00", "20:00"] and med["dosage"] == "500 mg tablet"

    assert len(client.get("/api/medicines").get_json()) == 1
    assert client.get(f"/api/medicines/{med['id']}").get_json()["name"] == "Metformin"

    changed = client.put(f"/api/medicines/{med['id']}", json={**MED, "frequency": "once", "times": ["09:00"]})
    assert changed.status_code == 200 and changed.get_json()["times"] == ["09:00"]

    assert client.delete(f"/api/medicines/{med['id']}").status_code == 200
    assert client.get(f"/api/medicines/{med['id']}").status_code == 404


def test_invalid_input_is_rejected(client):
    register(client)
    bad = {**MED, "name": "", "end": "2025-01-01", "times": ["8am"], "frequency": "sometimes"}
    res = client.post("/api/medicines", json=bad)
    assert res.status_code == 400
    assert {"name", "end", "times", "frequency"} <= set(res.get_json()["details"])


def test_frequency_must_match_number_of_times(client):
    register(client)
    res = client.post("/api/medicines", json={**MED, "frequency": "thrice"})
    assert res.status_code == 400 and "times" in res.get_json()["details"]


def test_patients_cannot_touch_each_others_medicines(client, app):
    register(client)
    med_id = client.post("/api/medicines", json=MED).get_json()["id"]
    other = app.test_client()
    register(other, email="other@example.com")
    assert other.get("/api/medicines").get_json() == []
    assert other.get(f"/api/medicines/{med_id}").status_code == 404
    assert other.put(f"/api/medicines/{med_id}", json=MED).status_code == 404
    assert other.delete(f"/api/medicines/{med_id}").status_code == 404


def test_caregiver_cannot_add_medicines(client):
    register(client, role="caregiver")
    assert client.post("/api/medicines", json=MED).status_code == 403
