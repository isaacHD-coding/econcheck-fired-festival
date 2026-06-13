from pathlib import Path
import py_compile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectInitializationTests(unittest.TestCase):
    def test_required_project_directories_exist(self) -> None:
        for dirname in ["app", "harness", "workers", "tests", "runs"]:
            with self.subTest(dirname=dirname):
                self.assertTrue((ROOT / dirname).is_dir())

    def test_required_project_docs_exist(self) -> None:
        for filename in ["AGENT.md", "HARNESS.md", "TECHNICAL_SPEC.md", "ROADMAP.md"]:
            with self.subTest(filename=filename):
                self.assertTrue((ROOT / filename).is_file())

    def test_streamlit_entrypoints_exist_and_compile(self) -> None:
        for filename in ["app/chat.py", "app/observability.py"]:
            with self.subTest(filename=filename):
                path = ROOT / filename
                self.assertTrue(path.is_file())
                py_compile.compile(str(path), doraise=True)

    def test_app_harness_and_workers_are_importable_packages(self) -> None:
        for filename in ["app/__init__.py", "harness/__init__.py", "workers/__init__.py"]:
            with self.subTest(filename=filename):
                self.assertTrue((ROOT / filename).is_file())

    def test_observability_import_resolves_to_app_package(self) -> None:
        from app.observability import load_run_view

        self.assertTrue(callable(load_run_view))

    def test_project_declares_minimal_milestone_zero_dependencies(self) -> None:
        pyproject_path = ROOT / "pyproject.toml"
        self.assertTrue(pyproject_path.is_file())

        pyproject = tomllib.loads(pyproject_path.read_text())
        dependencies = pyproject["project"]["dependencies"]
        optional_dependencies = pyproject["project"]["optional-dependencies"]["dev"]

        self.assertIn("streamlit", dependencies)
        self.assertIn("pytest", optional_dependencies)

    def test_runs_directory_is_trackable_but_run_outputs_are_ignored(self) -> None:
        self.assertTrue((ROOT / "runs" / ".gitkeep").is_file())


if __name__ == "__main__":
    unittest.main()
