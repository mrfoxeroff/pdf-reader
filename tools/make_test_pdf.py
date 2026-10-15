"""Generate a large test PDF (used for manual and automated testing)."""
import random
import sys

import pymupdf as fitz

FONT = r"C:\Windows\Fonts\arial.ttf"
WORDS = ("документ страница поиск текст быстрый просмотр масштаб закладка комментарий "
         "выделение Acrobat reader пример проверка таблица глава раздел данные анализ").split()


def main(path, pages=600):
    random.seed(1)
    doc = fitz.open()
    toc = []
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_font(fontname="arial", fontfile=FONT)
        if i % 10 == 0:
            toc.append([1, f"Глава {i // 10 + 1}", i + 1])
        if i % 10 == 5:
            toc.append([2, f"Раздел {i // 10 + 1}.1", i + 1])
        page.insert_text((60, 70), f"Глава {i // 10 + 1}. Страница {i + 1}", fontname="arial", fontsize=18)
        body = []
        for _ in range(28):
            body.append(" ".join(random.choice(WORDS) for _ in range(random.randint(7, 11))))
        if i == 42:
            body[5] = "Уникальная фраза для проверки поиска: ЁЛКА и елка."
        page.insert_textbox(fitz.Rect(60, 95, 535, 800), "\n".join(body), fontname="arial", fontsize=11)
        page.draw_rect(fitz.Rect(60, 780, 535, 800), color=(0.2, 0.4, 0.8), fill=(0.9, 0.93, 1))
        if i < pages - 1:
            page.insert_text((66, 794), f"→ Перейти на страницу {min(pages, i + 11)}", fontname="arial",
                             fontsize=10, color=(0, 0, 0.7))
    for i in range(pages - 1):
        doc[i].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(60, 780, 300, 800),
                            "page": min(pages - 1, i + 10), "to": fitz.Point(0, 0)})
    doc[3].set_rotation(90)
    doc.set_toc(toc)
    doc.set_metadata({"title": "Тестовый документ", "author": "PDF Reader"})
    doc.save(path, garbage=3, deflate=True)
    print("saved", path, len(doc))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 600)
