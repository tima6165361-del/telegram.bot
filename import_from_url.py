import re
import sqlite3
from dataclasses import dataclass
from typing import List
import requests
from bs4 import BeautifulSoup, Tag

URL = "https://ipbotsp.ru/blog/promyshlennaya-bezopasnost/proverka-znaniy-v-oblasti-energeticheskogo-nadzora/elektrobezopasnost/testy-s-otvetami-na-iv-gruppu-po-elektrobezopasnosti-do-i-svyshe-1000-v/"
DB_PATH = "group4.db"

NORM_RE = re.compile(r"^(п\.|Приложение|гл\.|табл\.|разд\.)", re.IGNORECASE)


@dataclass
class Option:
    text: str
    is_correct: bool = False


@dataclass
class Question:
    text: str
    options: List[Option]
    rationale: str
    source_url: str


def clean_text(s: str) -> str:
    s = s.replace("\r", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_greenish(el: Tag) -> bool:
    classes = [c.lower() for c in (el.get("class") or [])]
    style = (el.get("style") or "").lower()

    class_hits = [
        "green", "success", "correct", "right",
        "bg-success", "text-success", "alert-success"
    ]
    style_hits = [
        "#dff0d8", "#d4edda", "#c3e6cb",
        "rgb(223, 240, 216)", "rgb(212, 237, 218)",
        "background: green", "background-color: green",
        "color: green"
    ]

    if any(hit in " ".join(classes) for hit in class_hits):
        return True
    if any(hit in style for hit in style_hits):
        return True

    # иногда цвет висит на вложенном span/div
    for child in el.find_all(True):
        child_classes = " ".join((child.get("class") or [])).lower()
        child_style = (child.get("style") or "").lower()
        if any(hit in child_classes for hit in class_hits):
            return True
        if any(hit in child_style for hit in style_hits):
            return True

    return False


def get_main_content(soup: BeautifulSoup) -> Tag:
    for selector in [".entry-content", ".post-content", "article", "main"]:
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            return node
    return soup.body


def parse_questions(url: str) -> List[Question]:
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    content = get_main_content(soup)

    blocks: List[Tag] = []
    for el in content.find_all(["p", "li", "div", "h2", "h3", "h4"]):
        txt = clean_text(el.get_text(" ", strip=True))
        if not txt:
            continue
        blocks.append(el)

    questions: List[Question] = []
    i = 0

    while i < len(blocks):
        txt = clean_text(blocks[i].get_text(" ", strip=True))

        if txt == "Вопрос":
            i += 1
            while i < len(blocks) and not clean_text(blocks[i].get_text(" ", strip=True)):
                i += 1
            if i >= len(blocks):
                break

            q_text = clean_text(blocks[i].get_text(" ", strip=True))
            i += 1

            opts: List[Option] = []
            rationale = ""

            while i < len(blocks):
                t = clean_text(blocks[i].get_text(" ", strip=True))

                if t == "Вопрос":
                    break

                if NORM_RE.match(t):
                    rationale = t
                    i += 1
                    break

                opts.append(
                    Option(
                        text=t,
                        is_correct=is_greenish(blocks[i])
                    )
                )
                i += 1

            questions.append(
                Question(
                    text=q_text,
                    options=opts,
                    rationale=rationale,
                    source_url=url
                )
            )
        else:
            i += 1

    return questions


def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("DROP TABLE IF EXISTS options")
    cur.execute("DROP TABLE IF EXISTS questions")

    cur.execute("""
    CREATE TABLE questions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        rationale TEXT,
        source_url TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE options(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER NOT NULL,
        pos INTEGER NOT NULL,
        text TEXT NOT NULL,
        is_correct INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(question_id) REFERENCES questions(id)
    )
    """)

    con.commit()
    con.close()


def save_to_db(items: List[Question]):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    for q in items:
        cur.execute(
            "INSERT INTO questions(text, rationale, source_url) VALUES(?,?,?)",
            (q.text, q.rationale, q.source_url),
        )
        qid = cur.lastrowid

        for pos, opt in enumerate(q.options):
            cur.execute(
                "INSERT INTO options(question_id, pos, text, is_correct) VALUES(?,?,?,?)",
                (qid, pos, opt.text, 1 if opt.is_correct else 0),
            )

    con.commit()
    con.close()


if __name__ == "__main__":
    init_db()
    qs = parse_questions(URL)
    print(f"Найдено вопросов: {len(qs)}")
    with_correct = sum(any(o.is_correct for o in q.options) for q in qs)
    print(f"С распознанным правильным: {with_correct}")
    save_to_db(qs)