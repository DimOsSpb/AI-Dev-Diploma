import json
import re
from pathlib import Path

import frontmatter
from openai import OpenAI
from tqdm import tqdm

# -------------------------
# CONFIG
# -------------------------

SOURCE = Path("source/kubernetes/website/content/ru/docs")

OUTPUT = Path("../data/kb/kubernetes")

MODEL = "Qwen3.5-9B-Q5_K_M"


client = OpenAI(base_url="http://172.16.30.12:8080/v1", api_key="ollama")


# -------------------------
# PROMPT
# -------------------------

PROMPT = """
Ты технический писатель DevOps.

Проанализируй документацию Kubernetes.

Верни только JSON.

Формат:

{
"title":"",
"category":"",
"tags":[]
}


category только:

architecture
administration
workloads
networking
storage
security
monitoring
troubleshooting
runbooks
faq


Правила:

- title на русском языке
- tags 3-8 ключевых слов
- category выбрать по смыслу
- Kubernetes термины не переводить

Документ:
"""


# -------------------------
# HELPERS
# -------------------------


def clean_text(text):

    text = re.sub(r"\{\{.*?\}\}", "", text, flags=re.DOTALL)

    return text.strip()


def ask_llm(text):

    result = client.chat.completions.create(
        model=MODEL,
        temperature=0.1,
        timeout=600,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": PROMPT + text}],
    )

    answer = result.choices[0].message.content
    if answer:
        answer = answer.replace("```json", "").replace("```", "").strip()
    else:
        answer = ""

    try:
        return json.loads(answer)

    except json.JSONDecodeError:
        print("\nОтвет модели:")
        print(answer[:1000])
        raise


# -------------------------
# BUILD KB
# -------------------------

counter = 1


files = list(SOURCE.rglob("*.md"))


print(f"Найдено документов: {len(files)}")


for file in tqdm(files):
    try:
        doc = frontmatter.load(file)

        text = clean_text(doc.content)

        # пропускаем короткие страницы

        if len(text) < 200:
            continue

        data = ask_llm(text)

        category = data["category"]

        folder = OUTPUT / category

        folder.mkdir(parents=True, exist_ok=True)

        filename = folder / f"k8s-{counter:05}.md"

        header = f"""---
id: k8s-{counter:05}
title: {data["title"]}
product: kubernetes
category: {category}
tags:
"""

        for tag in data["tags"]:
            header += f"  - {tag}\n"

        header += """
source: kubernetes-docs
language: ru
created_at: 2026-07-24
version: "1.34"
---

"""

        filename.write_text(header + text, encoding="utf-8")

        counter += 1

    except Exception as e:
        print("\nОшибка:", file, e)


print(f"Создано документов: {counter - 1}")
