from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import streamlit as st


def count_csv_rows(csv_path: Path) -> int:
    if not csv_path.exists():
        return 0
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        return max(sum(1 for _ in f) - 1, 0)


def build_input_csv(text_input: str, uploaded_file_bytes: bytes | None, target_path: Path) -> None:
    if uploaded_file_bytes:
        target_path.write_bytes(uploaded_file_bytes)
        return

    rows = [line.strip() for line in text_input.splitlines() if line.strip()]
    if not rows:
        raise ValueError("Добавьте хотя бы один сайт в список.")

    with target_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["website"])
        for website in rows:
            writer.writerow([website])


def run_scraper_with_options(
    input_csv: Path,
    output_csv: Path,
    contact_forms_csv: Path,
    disable_browser_fallback: bool,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "scrape_emails.py",
        "--input",
        str(input_csv),
        "--output",
        str(output_csv),
        "--contact-forms-output",
        str(contact_forms_csv),
    ]
    if disable_browser_fallback:
        command.append("--disable-browser-fallback")
    return subprocess.run(command, capture_output=True, text=True, check=False)


st.set_page_config(page_title="Email Scraper", page_icon="📧", layout="centered")
st.title("📧 Сборщик имейлов по сайтам")
st.write("Загрузите CSV или вставьте список сайтов (по одному на строку), затем запустите сбор.")

disable_browser_fallback = st.checkbox(
    "Отключить browser fallback (для облака безопаснее и дешевле)",
    value=True,
)

uploaded = st.file_uploader("CSV файл со столбцом website/url/domain/site", type=["csv"])
text_input = st.text_area(
    "Или вставьте сайты списком",
    placeholder="example.com\nhttps://site.com/blog/post\nnews-site.net",
    height=180,
)

run_clicked = st.button("🚀 Погнали собирать", type="primary")

if run_clicked:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        input_csv = temp_path / "input_websites.csv"
        output_csv = temp_path / "emails_output.csv"
        contact_forms_csv = temp_path / "contact_forms_output.csv"

        try:
            uploaded_bytes = uploaded.getvalue() if uploaded is not None else None
            build_input_csv(text_input=text_input, uploaded_file_bytes=uploaded_bytes, target_path=input_csv)
        except ValueError as exc:
            st.error(str(exc))
            st.stop()

        st.info("🛰️ Запуск разведки по доменам... держим курс на полезные контакты.")
        with st.spinner("Сканируем сайты... иногда это занимает пару минут."):
            result = run_scraper_with_options(
                input_csv=input_csv,
                output_csv=output_csv,
                contact_forms_csv=contact_forms_csv,
                disable_browser_fallback=disable_browser_fallback,
            )

        if result.returncode != 0:
            st.error("Скрапер завершился с ошибкой.")
            if result.stderr.strip():
                st.code(result.stderr)
            if result.stdout.strip():
                st.code(result.stdout)
            st.stop()

        emails_rows = count_csv_rows(output_csv)
        forms_rows = count_csv_rows(contact_forms_csv)

        st.success("✅ Готово. Добыча завершена, можно забирать файлы.")
        col1, col2 = st.columns(2)
        col1.metric("📧 Email-строк", emails_rows)
        col2.metric("📝 Доменов с формами", forms_rows)
        if result.stdout.strip():
            st.code(result.stdout)

        st.download_button(
            label="⬇️ Скачать emails_output.csv",
            data=output_csv.read_bytes(),
            file_name="emails_output.csv",
            mime="text/csv",
        )
        st.download_button(
            label="⬇️ Скачать contact_forms_output.csv",
            data=contact_forms_csv.read_bytes(),
            file_name="contact_forms_output.csv",
            mime="text/csv",
        )
