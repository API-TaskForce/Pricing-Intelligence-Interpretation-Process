from fastapi.testclient import TestClient

from harvey_api.app import app, container


client = TestClient(app)


def test_reject_non_yaml_files():
    files = {"file": ("not_yaml.txt", "This is not yaml", "text/plain")}
    response = client.post("/upload", files=files)
    assert response.status_code == 400
    assert response.json() == {
        "detail": "Invalid Content-Type: text/plain. Only application/yaml is supported."
    }


def test_upload_yaml_file():
    filename = "test.yaml"
    files = {"file": (filename, "foo: bar\nbar: baz\n", "application/yaml")}
    response = client.post("/upload", files=files)
    assert response.status_code == 201
    response_body = response.json()
    assert response_body["filename"] == filename
    assert response_body["relative_path"] == "/static/" + filename


def test_delete_yaml_file():
    filename = "test.yaml"
    files = {"file": (filename, "foo: bar\nbar: baz\n", "application/yaml")}
    client.post("/upload", files=files)

    response = client.delete(f"/datasheet/{filename}")
    assert response.status_code == 204


def test_delete_non_existent_file():
    filename = "non_existent_file"
    response = client.delete(f"/datasheet/{filename}")
    assert response.status_code == 404
    response_body = response.json()
    assert response_body["detail"] == f"File {filename} not found."


async def mock_handle_question(*args, **kwargs):
    return {"answer": "Test answer", "plan": {}, "result": {}}


def test_chat_with_datasheet(monkeypatch):
    monkeypatch.setattr(container.agent, "handle_question", mock_handle_question)

    data = {
        "question": "How many calls can I make in 5 days?",
        "datasheet_yaml": "plans:\n  - name: pro\n",
    }
    response = client.post("/chat", json=data)
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Test answer"
    assert body["plan"] == {}
    assert body["result"] == {}


def test_chat_no_question():
    response = client.post("/chat", json={"question": "   "})
    assert response.status_code == 400
