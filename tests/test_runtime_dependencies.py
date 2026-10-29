from pathlib import Path


def test_azure_runtime_dependencies_are_installed_for_cloud_runtime() -> None:
    project_root = Path(__file__).resolve().parents[1]
    pyproject = (project_root / "pyproject.toml").read_text()
    dockerfile = (project_root / "Dockerfile").read_text()

    assert "azure-eventhub>=5.12.0" in pyproject
    assert "azure-identity>=1.17.0" in pyproject
    assert "azure-ai-projects>=2.8.0" in pyproject
    assert "pip install --no-cache-dir -e ." in dockerfile
