from __future__ import annotations

import base64
import csv
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import streamlit as st
import streamlit.components.v1 as components


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


FACT_ROTATE_SECONDS = 4.2
PROVOCATIVE_TRUE_FACTS = [
    "В Древнем Риме человеческую мочу действительно использовали в быту: как чистящее средство (из-за аммиака), в том числе при стирке.",
    "У человека есть “второй мозг” в кишечнике: энтеральная нервная система содержит сотни миллионов нейронов.",
    "В Project MKUltra (CIA) людям действительно давали психоактивные вещества, включая ЛСД, нередко без информированного согласия.",
    "В 1970 году нейрохирург Robert J. White выполнил эксперимент по трансплантации головы обезьяны: животное оставалось в сознании, но было парализовано.",
    "Тяжелые формы Lesch-Nyhan syndrome могут сопровождаться тяжелым самоповреждением, включая укусы собственных тканей.",
    "В эксперименте Little Albert ребенку формировали страх нейтральных объектов (например, белого кролика), создавая условную фобию.",
    "В конце XIX — начале XX века врачи применяли “массаж” как лечение “истерии”; с этой практикой связывают появление ранних механических устройств.",
    "При Cotard's syndrome человек может быть убежден, что он мертв или что у него “нет органов”.",
    "Когда ты смотришь на звезды, ты всегда видишь прошлое: свет многих из них шел тысячи и миллионы лет.",
    "Эмоции и решения зависят от нейрохимии мозга: изменение нейромедиаторного баланса может заметно менять состояние и поведение.",
    "Синдром пространственного игнорирования: после повреждения мозга человек может “терять” половину пространства (например, левую сторону).",
    "Исследования Elizabeth Loftus показали, что человеку можно сформировать ложные воспоминания.",
    "Эксперименты Benjamin Libet показали: мозговой сигнал готовности к действию может возникать до осознанного ощущения решения.",
    "Многие когнитивные процессы бессознательны: по работам Daniel Kahneman, “быстрое мышление” часто принимает решения раньше осознанного анализа.",
    "Принцип неопределенности Гейзенберга: нельзя одновременно точно знать и положение, и импульс частицы.",
    "Философский сценарий “мозг в колбе” ставит вопрос: можно ли строго доказать, что наш опыт обязательно связан с внешней реальностью.",
]


def run_scraper_with_live_facts(
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

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    fact_box = st.empty()
    start_ts = time.time()
    fact_idx = 0
    while process.poll() is None:
        elapsed = max(time.time() - start_ts, 0.0)
        fact = PROVOCATIVE_TRUE_FACTS[fact_idx % len(PROVOCATIVE_TRUE_FACTS)]
        fact_box.markdown(
            f"""
            <div style="
                border: 3px solid #202020;
                border-radius: 14px;
                background: #ffe999;
                padding: 10px 12px;
                margin: 10px 0 8px 0;
                box-shadow: 4px 4px 0 #202020;
            ">
                <div style="font-weight: 900; color: #1a1a1a;">⚡ Пока идет сбор... факт #{fact_idx + 1}</div>
                <div style="margin-top: 6px; font-weight: 700; color: #111;">{fact}</div>
                <div style="margin-top: 6px; font-size: 0.82rem; color: #2f2f2f;">
                    Прошло: {elapsed:.1f} сек
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        fact_idx += 1
        time.sleep(FACT_ROTATE_SECONDS)

    stdout, stderr = process.communicate()
    fact_box.empty()
    return subprocess.CompletedProcess(
        args=command,
        returncode=process.returncode,
        stdout=stdout or "",
        stderr=stderr or "",
    )


def render_background_music(track_path: Path) -> None:
    if not track_path.exists():
        return
    audio_b64 = base64.b64encode(track_path.read_bytes()).decode("ascii")
    components.html(
        f"""
        <audio id="bg-track" autoplay loop>
            <source src="data:audio/mp3;base64,{audio_b64}" type="audio/mpeg">
        </audio>
        <script>
            const el = document.getElementById("bg-track");
            if (el) {{
                el.volume = 0.35;
                el.play().catch(() => {{}});
            }}
        </script>
        """,
        height=0,
    )


def apply_cartoon_theme() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(180deg, #7ec8e8 0%, #bde7f7 55%, #dff4ff 100%);
        }
        .block-container {
            background: rgba(255, 252, 236, 0.96);
            border: 4px solid #1f1f1f;
            border-radius: 22px;
            box-shadow: 7px 7px 0 #1f1f1f;
            padding-top: 1.3rem;
            padding-bottom: 1.3rem;
            padding-left: 1.4rem;
            padding-right: 1.4rem;
            margin-top: 1.2rem;
            margin-bottom: 1.2rem;
        }
        h1, h2, h3, p, label {
            color: #1b1b1b !important;
        }
        div[data-testid="stFileUploader"] > section,
        div[data-testid="stTextArea"] textarea {
            border: 3px solid #222 !important;
            border-radius: 14px !important;
            background: #f4f7ff !important;
            color: #121212 !important;
            -webkit-text-fill-color: #121212 !important;
            caret-color: #121212 !important;
            font-weight: 700 !important;
        }
        div[data-testid="stTextArea"] textarea::placeholder {
            color: #5a6270 !important;
            -webkit-text-fill-color: #5a6270 !important;
            opacity: 1 !important;
        }
        div[data-testid="stCheckbox"] label {
            font-weight: 700 !important;
        }
        div[data-testid="stButton"] button,
        div[data-testid="stDownloadButton"] button {
            border: 3px solid #1f1f1f !important;
            border-radius: 14px !important;
            font-weight: 800 !important;
            box-shadow: 3px 4px 0 #1f1f1f !important;
        }
        div[data-testid="stButton"] button[kind="primary"] {
            background: #ff595e !important;
            color: #fff7ec !important;
        }
        div[data-testid="stDownloadButton"] button {
            background: #ffde59 !important;
            color: #121212 !important;
        }
        div[data-testid="stMetric"] {
            border: 3px solid #1f1f1f;
            border-radius: 14px;
            background: #fff9e2;
            padding: 8px 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="Email Scraper", page_icon="📧", layout="centered")
apply_cartoon_theme()
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
        music_track = Path(__file__).resolve().parent / "assets" / "background_track.mp3"

        try:
            uploaded_bytes = uploaded.getvalue() if uploaded is not None else None
            build_input_csv(text_input=text_input, uploaded_file_bytes=uploaded_bytes, target_path=input_csv)
        except ValueError as exc:
            st.error(str(exc))
            st.stop()

        render_background_music(music_track)
        st.info("🛰️ Запуск разведки по доменам... держим курс на полезные контакты.")
        with st.spinner("Сканируем сайты... иногда это занимает пару минут."):
            result = run_scraper_with_live_facts(
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
