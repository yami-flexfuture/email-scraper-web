from __future__ import annotations

import base64
import csv
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

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


def build_scraper_command(
    input_csv: Path,
    output_csv: Path,
    contact_forms_csv: Path,
    disable_browser_fallback: bool,
) -> list[str]:
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
    return command


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
DIARY_NOTES = [
    "Запись №1 — 17.09.1956\nСегодня я поймал себя на мысли, что время странно: раньше день тянулся бесконечно, а теперь неделя улетает мгновенно. Если я почти не замечаю жизнь, проживаю ли я ее по-настоящему?",
    "Запись №2 — 04.02.1963\nМы смотрим друг на друга, но часто не видим. Каждый человек — как отдельный мир, и мы редко заходим даже в свой собственный.",
    "Запись №3 — 28.11.1978\nЯ все время откладываю жизнь “на потом”. Но это “потом” никогда не наступает. Что, если жить нужно прямо внутри текущих дел?",
    "Запись №4 — 13.07.1985\nНаблюдая за дождем, понял: мне всегда нужен повод остановиться. А дождь просто идет. Иногда лучше просто чувствовать, а не объяснять себе чувства.",
    "Запись №5 — 22.05.1973\nРеальность глубже слов. Мы называем вещи — и будто все понятно, но за названиями всегда остается то, что можно только почувствовать.",
    "Запись №6 — 09.03.1991\nТихий страх редко останавливает напрямую, но корректирует траекторию. Многое в жизни строится не из желания, а из избегания.",
    "Запись №7 — 26.10.1969\nМир не спешит, даже когда спешим мы. Усталость часто не от дел, а от попытки идти против естественного ритма.",
    "Запись №8 — 14.01.2002\nМы держимся за образ себя, как за что-то фиксированное. Но если честно, я меняюсь каждый день — иногда незаметно, иногда резко.",
    "Запись №9 — 03.06.1980\nСамые важные вещи почти не имеют формы: внимание, состояние, внутренний тон. Их не видно, но они определяют весь день.",
    "Запись №10 — 21.08.2005\nЖизнь не обязана быть полностью понятной, чтобы быть настоящей. Возможно, достаточно не понимать ее до конца и не проходить мимо.",
]


def render_background_music(track_path: Path) -> None:
    if not track_path.exists():
        return
    audio_b64 = base64.b64encode(track_path.read_bytes()).decode("ascii")
    components.html(
        f"""
        <div style="
            border: 3px solid #7ea7ff;
            border-radius: 12px;
            background: linear-gradient(135deg, #121c3a 0%, #1a2a57 100%);
            padding: 8px 10px;
            margin: 8px 0 10px 0;
            box-shadow: 3px 3px 0 #0a0f22;
            font-family: sans-serif;
            font-weight: 700;
            color: #ecf1ff;
        ">
            <audio id="bg-track" controls autoplay loop style="width: 100%; margin-top: 6px;">
                <source src="data:audio/mp3;base64,{audio_b64}" type="audio/mpeg">
            </audio>
        </div>
        <script>
            const el = document.getElementById("bg-track");
            if (el) {{
                el.volume = 0.35;
                el.play().catch(() => {{}});
            }}
        </script>
        """,
        height=120,
    )


def ensure_session_state() -> None:
    defaults = {
        "running": False,
        "proc": None,
        "run_started_at": 0.0,
        "tmp_dir": "",
        "input_csv_path": "",
        "output_csv_path": "",
        "contact_forms_csv_path": "",
        "result_code": None,
        "result_stdout": "",
        "result_stderr": "",
        "result_emails_bytes": None,
        "result_forms_bytes": None,
        "result_emails_rows": 0,
        "result_forms_rows": 0,
        "fact_slot": -1,
        "fact_payload": "",
        "fact_is_diary": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def cleanup_tmp_dir() -> None:
    tmp_dir = st.session_state.get("tmp_dir") or ""
    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    st.session_state["tmp_dir"] = ""
    st.session_state["input_csv_path"] = ""
    st.session_state["output_csv_path"] = ""
    st.session_state["contact_forms_csv_path"] = ""


def start_scrape_run(
    text_input: str,
    uploaded_file_bytes: bytes | None,
    disable_browser_fallback: bool,
) -> None:
    tmp_dir = tempfile.mkdtemp(prefix="email_scraper_run_")
    tmp_path = Path(tmp_dir)
    input_csv = tmp_path / "input_websites.csv"
    output_csv = tmp_path / "emails_output.csv"
    contact_forms_csv = tmp_path / "contact_forms_output.csv"
    build_input_csv(text_input=text_input, uploaded_file_bytes=uploaded_file_bytes, target_path=input_csv)
    command = build_scraper_command(
        input_csv=input_csv,
        output_csv=output_csv,
        contact_forms_csv=contact_forms_csv,
        disable_browser_fallback=disable_browser_fallback,
    )
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    st.session_state["proc"] = proc
    st.session_state["running"] = True
    st.session_state["run_started_at"] = time.time()
    st.session_state["tmp_dir"] = str(tmp_path)
    st.session_state["input_csv_path"] = str(input_csv)
    st.session_state["output_csv_path"] = str(output_csv)
    st.session_state["contact_forms_csv_path"] = str(contact_forms_csv)
    st.session_state["result_code"] = None
    st.session_state["result_stdout"] = ""
    st.session_state["result_stderr"] = ""
    st.session_state["result_emails_bytes"] = None
    st.session_state["result_forms_bytes"] = None
    st.session_state["result_emails_rows"] = 0
    st.session_state["result_forms_rows"] = 0
    st.session_state["fact_slot"] = -1
    st.session_state["fact_payload"] = ""
    st.session_state["fact_is_diary"] = False


def finalize_process_result(stopped_by_user: bool = False) -> None:
    proc = st.session_state.get("proc")
    if proc is None:
        st.session_state["running"] = False
        return
    if stopped_by_user and proc.poll() is None:
        proc.terminate()
    stdout, stderr = proc.communicate()
    st.session_state["result_code"] = proc.returncode
    st.session_state["result_stdout"] = stdout or ""
    st.session_state["result_stderr"] = stderr or ""
    output_csv = Path(st.session_state.get("output_csv_path") or "")
    forms_csv = Path(st.session_state.get("contact_forms_csv_path") or "")
    if output_csv.exists():
        st.session_state["result_emails_bytes"] = output_csv.read_bytes()
        st.session_state["result_emails_rows"] = count_csv_rows(output_csv)
    if forms_csv.exists():
        st.session_state["result_forms_bytes"] = forms_csv.read_bytes()
        st.session_state["result_forms_rows"] = count_csv_rows(forms_csv)
    st.session_state["running"] = False
    st.session_state["proc"] = None
    if stopped_by_user:
        st.session_state["result_code"] = 130
        if not st.session_state["result_stderr"]:
            st.session_state["result_stderr"] = "Сбор остановлен пользователем."
    cleanup_tmp_dir()


def apply_cartoon_theme(running_mode: bool) -> None:
    app_bg = (
        "radial-gradient(circle at 20% 20%, #1b2746 0%, #101930 35%, #090f1e 100%)"
        if running_mode
        else "linear-gradient(180deg, #7ec8e8 0%, #bde7f7 55%, #dff4ff 100%)"
    )
    container_bg = "rgba(14, 20, 40, 0.92)" if running_mode else "rgba(255, 252, 236, 0.96)"
    container_border = "#7ea7ff" if running_mode else "#1f1f1f"
    container_shadow = "#0a0f22" if running_mode else "#1f1f1f"
    base_text = "#ecf1ff" if running_mode else "#1b1b1b"
    input_bg = "#111b36" if running_mode else "#f4f7ff"
    input_border = "#7ea7ff" if running_mode else "#222"
    placeholder = "#9bb0df" if running_mode else "#5a6270"
    secondary_btn_bg = "#2a3e73" if running_mode else "#f0e3b1"
    secondary_btn_color = "#eef4ff" if running_mode else "#171717"
    metric_bg = "#101a35" if running_mode else "#fff9e2"
    metric_text = "#eef4ff" if running_mode else "#121212"

    st.markdown(
        f"""
        <style>
        .stApp {{
            background: {app_bg};
        }}
        .block-container {{
            background: {container_bg};
            border: 4px solid {container_border};
            border-radius: 22px;
            box-shadow: 7px 7px 0 {container_shadow};
            padding-top: 1.3rem;
            padding-bottom: 1.3rem;
            padding-left: 1.4rem;
            padding-right: 1.4rem;
            margin-top: 1.2rem;
            margin-bottom: 1.2rem;
        }}
        h1, h2, h3, p, label {{
            color: {base_text} !important;
        }}
        div[data-testid="stFileUploader"] > section,
        div[data-testid="stTextArea"] textarea {{
            border: 3px solid {input_border} !important;
            border-radius: 14px !important;
            background: {input_bg} !important;
            color: {base_text} !important;
            -webkit-text-fill-color: {base_text} !important;
            caret-color: {base_text} !important;
            font-weight: 700 !important;
        }}
        div[data-testid="stFileUploader"] button {{
            background: #ffde59 !important;
            color: #121212 !important;
            border: 3px solid {container_border} !important;
            border-radius: 12px !important;
            font-weight: 800 !important;
            box-shadow: 2px 3px 0 {container_shadow} !important;
        }}
        div[data-testid="stTextArea"] textarea::placeholder {{
            color: {placeholder} !important;
            -webkit-text-fill-color: {placeholder} !important;
            opacity: 1 !important;
        }}
        div[data-testid="stCheckbox"] label {{
            font-weight: 700 !important;
        }}
        div[data-testid="stButton"] button,
        div[data-testid="stDownloadButton"] button {{
            border: 3px solid {container_border} !important;
            border-radius: 14px !important;
            font-weight: 800 !important;
            box-shadow: 3px 4px 0 {container_shadow} !important;
        }}
        div[data-testid="stButton"] button[kind="primary"] {{
            background: #ff595e !important;
            color: #fff7ec !important;
        }}
        div[data-testid="stButton"] button[kind="secondary"] {{
            background: {secondary_btn_bg} !important;
            color: {secondary_btn_color} !important;
        }}
        div[data-testid="stDownloadButton"] button {{
            background: #ffde59 !important;
            color: #121212 !important;
        }}
        div[data-testid="stMetric"] {{
            border: 3px solid {container_border};
            border-radius: 14px;
            background: {metric_bg};
            padding: 8px 10px;
        }}
        div[data-testid="stMetric"] * {{
            color: {metric_text} !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="Email Scraper", page_icon="📧", layout="centered")
ensure_session_state()
apply_cartoon_theme(bool(st.session_state.get("running")))
st.title("📧 Сборщик имейлов по сайтам")
if st.session_state["running"]:
    st.write("Космический режим активирован: идет сбор и трансляция фактов.")
else:
    st.write("Загрузите CSV или вставьте список сайтов (по одному на строку), затем запустите сбор.")

if not st.session_state["running"]:
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
        try:
            uploaded_bytes = uploaded.getvalue() if uploaded is not None else None
            start_scrape_run(
                text_input=text_input,
                uploaded_file_bytes=uploaded_bytes,
                disable_browser_fallback=disable_browser_fallback,
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

if st.session_state["running"]:
    st.markdown("### 🛰️ Идет сбор имейлов")
    st.info("Форма скрыта до завершения — сейчас показываем факты и состояние процесса.")
    if st.button("⏹ Стоп сбор", type="secondary"):
        finalize_process_result(stopped_by_user=True)
        st.rerun()

    elapsed = max(time.time() - float(st.session_state.get("run_started_at") or 0.0), 0.0)
    current_slot = int(elapsed // FACT_ROTATE_SECONDS)
    if current_slot != int(st.session_state.get("fact_slot", -1)):
        st.session_state["fact_slot"] = current_slot
        # Факты показываем чаще, записи реже.
        if random.random() < 0.72:
            st.session_state["fact_payload"] = random.choice(PROVOCATIVE_TRUE_FACTS)
            st.session_state["fact_is_diary"] = False
        else:
            st.session_state["fact_payload"] = random.choice(DIARY_NOTES)
            st.session_state["fact_is_diary"] = True

    fact_text = str(st.session_state.get("fact_payload") or PROVOCATIVE_TRUE_FACTS[0])
    is_diary = bool(st.session_state.get("fact_is_diary"))
    card_title = "📝 Пока идет сбор... запись из архива" if is_diary else "⚡ Пока идет сбор... факт"
    card_bg = "#f4e3aa" if is_diary else "#ffe999"
    st.markdown(
        f"""
        <div style="
            border: 4px solid #202020;
            border-radius: 16px;
            background: {card_bg};
            padding: 24px 18px;
            margin: 14px 0 14px 0;
            box-shadow: 5px 5px 0 #202020;
        ">
            <div style="font-size: 1.4rem; font-weight: 900; color: #1a1a1a;">{card_title}</div>
            <div style="margin-top: 12px; font-size: 1.28rem; line-height: 1.35; font-weight: 800; color: #111;">{fact_text}</div>
            <div style="margin-top: 10px; font-size: 0.96rem; color: #2f2f2f;">
                Прошло: {elapsed:.1f} сек
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    music_track = Path(__file__).resolve().parent / "assets" / "background_track.mp3"
    render_background_music(music_track)

    proc = st.session_state.get("proc")
    if proc is not None and proc.poll() is not None:
        finalize_process_result(stopped_by_user=False)
        st.rerun()
    else:
        time.sleep(1.0)
        st.rerun()

if not st.session_state["running"] and st.session_state.get("result_code") is not None:
    result_code = int(st.session_state["result_code"])
    if result_code == 0:
        st.success("✅ Готово. Добыча завершена, можно забирать файлы.")
    elif result_code == 130:
        st.warning("⏹ Сбор остановлен пользователем.")
    else:
        st.error("Скрапер завершился с ошибкой.")

    col1, col2 = st.columns(2)
    col1.metric("📧 Email-строк", int(st.session_state.get("result_emails_rows") or 0))
    col2.metric("📝 Доменов с формами", int(st.session_state.get("result_forms_rows") or 0))

    result_stderr = str(st.session_state.get("result_stderr") or "").strip()
    result_stdout = str(st.session_state.get("result_stdout") or "").strip()
    if result_code != 0 and result_stderr:
        st.code(result_stderr)
    if result_stdout:
        st.code(result_stdout)

    emails_bytes = st.session_state.get("result_emails_bytes")
    forms_bytes = st.session_state.get("result_forms_bytes")
    if emails_bytes:
        st.download_button(
            label="⬇️ Скачать emails_output.csv",
            data=emails_bytes,
            file_name="emails_output.csv",
            mime="text/csv",
        )
    if forms_bytes:
        st.download_button(
            label="⬇️ Скачать contact_forms_output.csv",
            data=forms_bytes,
            file_name="contact_forms_output.csv",
            mime="text/csv",
        )
