"""
Генерация Markdown-отчета по результатам benchmark.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from tests.eval.rag.report_models import EvaluationReport

TEMPLATE_DIR = Path(__file__).parent / "templates"

OUTPUT_FILE = Path(__file__).resolve().parents[3] / "docs" / "chunking_report.md"

TEMPLATE_NAME = "chunking_report.md.j2"


def get_environment() -> Environment:
    """Создать Jinja2 environment для Markdown-шаблонов."""

    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_report(
    report: EvaluationReport,
) -> str:
    """Отрендерить Markdown-отчет из EvaluationReport."""

    environment = get_environment()

    template = environment.get_template(
        TEMPLATE_NAME,
    )

    return template.render(
        report=report,
    )


def save_report(
    report: EvaluationReport,
    output: Path = OUTPUT_FILE,
) -> Path:
    """Отрендерить и сохранить Markdown-отчет."""

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    markdown = render_report(report)

    output.write_text(
        markdown,
        encoding="utf-8",
    )

    print(f"✓ Report: {output}")

    return output
