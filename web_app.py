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


def render_cartoon_header() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(180deg, #79d8ff 0%, #cfeefe 55%, #eef9ff 100%);
        }
        .sp-card {
            background: #fff7d9;
            border: 4px solid #1f1f1f;
            border-radius: 26px;
            box-shadow: 7px 8px 0 #1f1f1f;
            padding: 16px 18px;
            margin-bottom: 14px;
        }
        .sp-title {
            margin: 0;
            color: #171717;
            font-size: 1.95rem;
            font-weight: 900;
            line-height: 1.1;
        }
        .sp-subtitle {
            margin: 8px 0 10px 0;
            color: #292929;
            font-size: 1rem;
            font-weight: 600;
        }
        .sp-badge {
            display: inline-block;
            margin-right: 8px;
            margin-bottom: 7px;
            padding: 4px 10px;
            border-radius: 999px;
            border: 3px solid #222;
            background: #ffde5a;
            color: #111;
            font-size: 0.82rem;
            font-weight: 800;
        }
        .sp-characters {
            width: 100%;
            margin: 4px 0 8px 0;
            border-radius: 14px;
            border: 3px solid #222;
            background: #f7fbff;
            padding: 8px 4px;
            text-align: center;
        }
        .sp-footnote {
            color: #2f2f2f;
            font-size: 0.86rem;
            font-weight: 600;
            margin-top: 8px;
        }
        </style>
        <div class="sp-card">
          <p class="sp-title">🧤 Email Scraper: Snow Town Style</p>
          <p class="sp-subtitle">
            Мультяшный бумажный вайб: яркие цвета, толстые контуры и веселая атмосфера.
          </p>
          <div class="sp-characters">
            <svg width="520" height="115" viewBox="0 0 520 115" xmlns="http://www.w3.org/2000/svg" aria-label="cartoon kids">
              <rect x="0" y="0" width="520" height="115" fill="#f7fbff"/>
              <!-- kid 1 -->
              <circle cx="75" cy="38" r="24" fill="#ffe0bd" stroke="#111" stroke-width="3"/>
              <rect x="52" y="62" width="46" height="34" rx="8" fill="#ff5f5f" stroke="#111" stroke-width="3"/>
              <circle cx="66" cy="38" r="3" fill="#111"/><circle cx="84" cy="38" r="3" fill="#111"/>
              <rect x="54" y="20" width="42" height="12" rx="6" fill="#3d8cff" stroke="#111" stroke-width="3"/>
              <!-- kid 2 -->
              <circle cx="190" cy="38" r="24" fill="#ffe0bd" stroke="#111" stroke-width="3"/>
              <rect x="167" y="62" width="46" height="34" rx="8" fill="#57c8ff" stroke="#111" stroke-width="3"/>
              <circle cx="181" cy="38" r="3" fill="#111"/><circle cx="199" cy="38" r="3" fill="#111"/>
              <rect x="170" y="16" width="40" height="15" rx="7" fill="#ffcc33" stroke="#111" stroke-width="3"/>
              <!-- kid 3 -->
              <circle cx="305" cy="38" r="24" fill="#ffe0bd" stroke="#111" stroke-width="3"/>
              <rect x="282" y="62" width="46" height="34" rx="8" fill="#7bc96f" stroke="#111" stroke-width="3"/>
              <circle cx="296" cy="38" r="3" fill="#111"/><circle cx="314" cy="38" r="3" fill="#111"/>
              <rect x="286" y="18" width="38" height="13" rx="6" fill="#ff8f3c" stroke="#111" stroke-width="3"/>
              <!-- kid 4 -->
              <circle cx="420" cy="38" r="24" fill="#ffe0bd" stroke="#111" stroke-width="3"/>
              <rect x="397" y="62" width="46" height="34" rx="8" fill="#b49cff" stroke="#111" stroke-width="3"/>
              <circle cx="411" cy="38" r="3" fill="#111"/><circle cx="429" cy="38" r="3" fill="#111"/>
              <rect x="400" y="17" width="40" height="14" rx="7" fill="#ff5fb8" stroke="#111" stroke-width="3"/>
            </svg>
          </div>
          <span class="sp-badge">Top-3 email на домен</span>
          <span class="sp-badge">Contact forms отдельно</span>
          <span class="sp-badge">CSV in / CSV out</span>
          <p class="sp-footnote">Персонажи оригинальные, в стилистике cutout/cartoon.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="Email Scraper", page_icon="📧", layout="centered")
render_cartoon_header()
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
