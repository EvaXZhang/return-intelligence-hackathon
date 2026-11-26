def test_streamlit_apptest_constructs_two_areas(tmp_path,monkeypatch):
    from pathlib import Path
    monkeypatch.setenv('AI_BACKEND','simulated');monkeypatch.setenv('AWS_INTEGRATION_ENABLED','false');monkeypatch.setenv('DEPLOYMENT_ENABLED','false');monkeypatch.setenv('DB_PATH',str(tmp_path/'data'/'ui.db'));monkeypatch.setenv('ARTIFACT_DIR',str(tmp_path/'artifacts'));monkeypatch.setenv('UPLOAD_DIR',str(tmp_path/'uploads'));monkeypatch.setenv('LOG_PATH',str(tmp_path/'logs'/'app.log'))
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(Path(__file__).parents[1]/'app.py',default_timeout=10).run();assert not app.exception;assert any('Customer Portal' in x.value for x in app.header);assert any('LOCAL SYNTHETIC DEMO' in x.value for x in app.info)
    app.sidebar.radio[0].set_value('Staff Dashboard').run();assert not app.exception;assert any('Staff Dashboard' in x.value for x in app.header)
