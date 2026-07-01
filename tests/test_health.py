def test_health_check(client):
    """
    ARRANGE: test client is ready
    ACT: hit the health endpoint
    ASSERT: returns 200 with status ok
    """
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}