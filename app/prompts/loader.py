import json
from importlib import resources


def _read_prompt_file(filename: str) -> str:
    return (
        resources
        .files(__package__)
        .joinpath(filename)
        .read_text(encoding="utf-8")
        .strip()
    )


def load_service_facts() -> str:
    return _read_prompt_file("service_facts.txt")


def load_system_prompt_template() -> str:
    return _read_prompt_file("system_prompt.txt")


def load_classifier_system_prompt() -> str:
    return _read_prompt_file("classifier_system_prompt.txt")


def load_classifier_few_shots() -> list:
    return json.loads(_read_prompt_file("classifier_few_shots.json"))
