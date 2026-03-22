
def test_complaint_generation_removed(client):
    response = client.post("/complaint-generation", json={})
    assert response.status_code == 404
