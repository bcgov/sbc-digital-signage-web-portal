import io
import json

from app import create_app
from app.routes import classify_update_result


def make_client(tmp_path):
    upload_dir = tmp_path / "uploads"
    updates_root = tmp_path / "updates"
    updater_root = tmp_path / "updater"

    app = create_app(
        {
            "TESTING": True,
            "UPLOAD_FOLDER": upload_dir,
            "UPDATE_INCOMING_DIR": updates_root / "incoming",
            "UPDATE_STAGING_DIR": updates_root / "staging",
            "UPDATE_LOG_DIR": updates_root / "logs",
            "UPDATER_ROOT": updater_root,
            "UPDATER_STATE_FILE": updater_root / "state.json",
        }
    )
    return app.test_client(), app


def write_state(app, state):
    state_path = app.config["UPDATER_STATE_FILE"]
    state_path.write_text(json.dumps(state), encoding="utf-8")


def test_admin_post_success_renders_updating_notice(monkeypatch, tmp_path):
    client, app = make_client(tmp_path)
    write_state(
        app,
        {
            "active_release": "release-a",
            "last_known_good": "release-a",
            "last_successful_postdeploy_migration": None,
            "last_successful_predeploy_migration": None,
            "previous_release": None,
            "update_in_progress": False,
            "last_attempt": "attempt-0",
            "last_error": None,
        },
    )
    monkeypatch.setattr("app.routes.start_update_service", lambda: (True, "ignored"))

    response = client.post(
        "/admin",
        data={"update_zip": (io.BytesIO(b"fake zip"), "release.zip")},
        content_type="multipart/form-data",
    )

    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Updating software" in body
    assert 'data-watch-update="true"' in body
    assert 'data-initial-last-attempt="attempt-0"' in body


def test_admin_post_failure_renders_start_error(monkeypatch, tmp_path):
    client, app = make_client(tmp_path)
    write_state(
        app,
        {
            "active_release": None,
            "last_known_good": None,
            "last_successful_postdeploy_migration": None,
            "last_successful_predeploy_migration": None,
            "previous_release": None,
            "update_in_progress": False,
            "last_attempt": None,
            "last_error": None,
        },
    )
    monkeypatch.setattr("app.routes.start_update_service", lambda: (False, "boom"))

    response = client.post(
        "/admin",
        data={"update_zip": (io.BytesIO(b"fake zip"), "release.zip")},
        content_type="multipart/form-data",
    )

    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "updater could not start: boom" in body
    assert 'data-watch-update="false"' in body


def test_admin_get_in_progress_exposes_polling_bootstrap(tmp_path):
    client, app = make_client(tmp_path)
    write_state(
        app,
        {
            "active_release": "release-a",
            "last_known_good": "release-a",
            "last_successful_postdeploy_migration": None,
            "last_successful_predeploy_migration": None,
            "previous_release": "release-previous",
            "update_in_progress": True,
            "last_attempt": "attempt-9",
            "last_error": None,
        },
    )

    response = client.get("/admin")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Updating software" in body
    assert 'data-watch-update="true"' in body
    assert 'data-initial-last-attempt="attempt-9"' in body
    assert 'data-initial-active-release="release-a"' in body
    assert 'data-initial-update-in-progress="true"' in body


def test_classify_update_result_states():
    assert classify_update_result({"update_in_progress": True}) == "in_progress"
    assert classify_update_result({"update_in_progress": False, "last_attempt": None}) == "idle"
    assert (
        classify_update_result(
            {
                "update_in_progress": False,
                "last_attempt": "attempt-1",
                "last_error": None,
                "log_tail": ["[2026-05-01T00:00:00Z] Update completed successfully."],
            }
        )
        == "succeeded"
    )
    assert (
        classify_update_result(
            {
                "update_in_progress": False,
                "last_attempt": "attempt-2",
                "last_error": "failure",
            }
        )
        == "failed"
    )
    assert (
        classify_update_result(
            {
                "update_in_progress": False,
                "last_attempt": "attempt-3",
                "last_error": None,
                "log_tail": ["[2026-05-01T00:00:00Z] Extracting update package"],
            }
        )
        == "pending"
    )
