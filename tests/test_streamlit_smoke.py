import importlib.util
import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_streamlit_entrypoints_compile() -> None:
    for filename in ["app.py", "pages/2_Observability.py"]:
        path = ROOT / filename
        assert path.is_file()
        py_compile.compile(str(path), doraise=True)


def test_streamlit_pages_import_without_running_main() -> None:
    app_module = load_module(ROOT / "app.py", "econcheck_streamlit_app")
    observability_module = load_module(
        ROOT / "pages" / "2_Observability.py",
        "econcheck_streamlit_observability_page",
    )

    assert callable(app_module.main)
    assert callable(observability_module.main)


def test_fixture_data_supports_chat_page_view_model() -> None:
    from harness.observability import load_run_artifacts, run_question
    from harness.observability.view_models import answer_text, chart_specs, progress_stages

    run_id = run_question("What has happened to CPI inflation over the last five years?")
    run = load_run_artifacts(run_id)

    assert all(stage["status"] == "complete" for stage in progress_stages(run))
    assert "CPI inflation" in answer_text(run)
    assert chart_specs(run)


def test_streamlit_helpers_avoid_deprecated_container_width_parameter() -> None:
    helper_source = (ROOT / "harness" / "observability" / "streamlit_ui.py").read_text()

    assert "use_container_width" not in helper_source
