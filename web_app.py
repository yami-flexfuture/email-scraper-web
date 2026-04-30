from __future__ import annotations

import base64
import csv
import html
import random
import re
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
DIARY_EXTRA_SECONDS = 2.0
PROVOCATIVE_TRUE_FACTS = [
    "1) В Древнем Риме использовали мочу как средство для стирки и чистки зубов",
    "2) У людей есть “второй мозг” в кишечнике\nОн содержит сотни миллионов нейронов и может работать независимо от головы.",
    "3) Государство тайно давало людям ЛСД без их согласия\nВ программе Project MKUltra сотрудников, солдат и обычных людей накачивали психоактивными веществами, чтобы изучить контроль сознания.",
    "4)  Учёный пересадил голову обезьяне (частично успешно)\nRobert J. White в 1970-х пересадил голову одной обезьяны на тело другой. Она была в сознании и могла видеть/слышать, но была парализована.",
    "5) Есть болезнь, при которой ты буквально не можешь перестать есть себя\nРедкое расстройство — тяжёлые формы Lesch-Nyhan syndrome могут вызывать неконтролируемое самоповреждение, вплоть до кусания собственного тела.",
    "6) В одном эксперименте младенца специально травмировали психологически\nВ опыте Little Albert experiment ребёнка научили бояться обычных предметов (например, белого кролика), создавая фобию.",
    "7) Врачи раньше лечили истерию у женщин “массажем”\nЭто считалось медицинской процедурой, а не чем-то интимным — отсюда, кстати, появление первых механических устройств.",
    "8) Есть болезнь, при которой ты уверен, что уже мёртв\nCotard's syndrome — люди искренне считают себя трупами или что у них нет органов.",
    "9) Ты смотришь в прошлое буквально всегда\nКогда ты видишь звёзды — ты видишь свет, которому тысячи или миллионы лет. Некоторые из них уже могут не существовать.",
    "10) Ты — это не “ты”, а куча химии\nЛюбое твоё чувство, решение, страх — результат работы нейронов и химических реакций. Чуть измени баланс — и “ты” уже другой.",
    "11) Мозг может игнорировать половину реальности — буквально\nСиндром пространственного игнорирования изучался, в том числе, Vilayanur S. Ramachandran\n→ пациенты после инсульта не видят левую сторону мира (едят только половину тарелки, бреют половину лица).",
    "12) Ты можешь быть уверен в ложном воспоминании — и это доказано\nИсследования Elizabeth Loftus показали, что людям можно “вживить” воспоминания (например, что они терялись в детстве в магазине).\n→ память — это реконструкция, а не запись.",
    "13) Есть момент, когда мозг “решает” за тебя раньше, чем ты это осознаёшь\nЭксперименты Benjamin Libet показали:\nсигнал готовности к действию возникает до осознанного решения.\n→ ощущение свободы выбора может быть постфактум.",
    "14) Ты не контролируешь большинство процессов, которые считаешь “собой”\nРешения, эмоции, реакции — результат бессознательных процессов (исследования когнитивной науки, включая Daniel Kahneman).\n→ сознание — это скорее “комментатор”, чем управляющий.",
    "15) . Есть предел того, что вообще можно узнать\nПринцип Heisenberg uncertainty principle:\nневозможно точно знать одновременно положение и импульс частицы.\n→ это не ограничение приборов, а фундамент реальности.",
    "16) Ты не можешь доказать, что реальность “внешняя”\nФилософский сценарий “мозг в колбе” (развивали, например, Hilary Putnam).\n→ все твои ощущения могут быть симуляцией — и это принципиально непроверяемо изнутри.",
]
DIARY_NOTES = [
    "Запись №2 — 04.02.1963\n\nСегодня я думал о людях. О том, как мы смотрим друг на друга и почти никогда не видим. Мы слышим слова, но редко слышим смысл, потому что в этот момент уже готовим свой ответ. Иногда кажется, что каждый человек — это целый мир, запертый внутри, и мы живём рядом с миллиардами миров, даже не пытаясь в них заглянуть. И, возможно, самое странное — что мы и в свой собственный мир заходим не так уж часто.",
    "Запись №3 — 28.11.1978\n\nЕсть одна привычка, которую я заметил у себя: я всё время откладываю жизнь на потом. Вот закончу дела — и тогда отдохну, вот разберусь со всем — и тогда начну жить спокойно. Но это «потом» ведёт себя подозрительно: оно всегда впереди и никогда не наступает. И тогда появляется мысль, почти детская по своей простоте — а что, если жить нужно не после всего этого, а прямо внутри этого?",
    "Запись №4 — 13.07.1985\n\nСегодня я наблюдал за дождём. Долго, без цели. И вдруг понял, что мне почти всегда нужен повод, чтобы остановиться. Как будто просто так нельзя — нужно заслужить паузу. Но дождю всё равно, заслужил я её или нет. Он просто идёт. И в этом есть какая-то честность, которой не хватает мне самому. Я слишком часто объясняю себе, почему можно или нельзя что-то чувствовать, вместо того чтобы просто чувствовать.",
    "Запись №5 — 22.05.1973\n\nИногда мне кажется, что реальность гораздо глубже, чем мы привыкли думать. Мы смотрим на вещи и называем их — стол, улица, человек — и как будто на этом всё заканчивается. Но это только слова. За ними всегда есть что-то ещё, что не помещается в объяснение. И, возможно, именно это «что-то» и есть настоящая жизнь, которую невозможно полностью описать, но можно почувствовать, если хоть немного замедлиться.",
    "Запись №6 — 09.03.1991\n\nСегодня я размышлял о страхе. Не о каком-то конкретном, а о тихом, почти незаметном, который сопровождает решения. Он не кричит, не останавливает напрямую, но слегка корректирует траекторию, уводя туда, где безопаснее, привычнее, понятнее. И если присмотреться, можно увидеть, как много в жизни построено не из желания, а из избегания. Это не трагедия, но и не совсем свобода.",
    "Запись №7 — 26.10.1969\n\nЕсть ощущение, что мир не спешит, даже когда спешим мы. Деревья не торопятся расти быстрее, чем могут, утро не наступает раньше времени, и вечер не задерживается дольше, чем положено. Только человек всё время пытается ускорить то, что по своей природе происходит само. И, возможно, усталость — это не от того, что много дел, а от того, что мы всё время идём против ритма, в котором всё остальное живёт спокойно.",
    "Запись №8 — 14.01.2002\n\nСегодня я подумал о том, как сильно мы привязываемся к представлению о себе. Мы собираем его годами — из мнений, ошибок, чужих слов — и потом начинаем его защищать, как будто это что-то твёрдое и окончательное. Но если быть честным, я меняюсь каждый день, иногда незаметно, иногда резко, и тот, кем я был вчера, уже не совсем я. Тогда возникает вопрос: если я постоянно меняюсь, то кто тот, за кого я так держусь?",
    "Запись №9 — 03.06.1980\n\nЯ всё чаще замечаю, что самые важные вещи почти не имеют формы. Их нельзя взять в руки, нельзя показать, но именно они определяют, как проходит день. Внимание, состояние, внутренний тон — это как воздух: его не видно, но без него ничего не работает. И, возможно, заботиться о жизни — это не столько управлять событиями, сколько учиться замечать то, что происходит внутри.",
    "Запись №10 — 21.08.2005\n\nСегодня пришла простая мысль, которая почему-то раньше не казалась очевидной: жизнь не обязана быть понятной, чтобы быть настоящей. Мы всё время стремимся её объяснить, разложить, назвать — но она от этого не становится яснее, только проще в наших словах. А сама по себе она остаётся чем-то большим, чем любое объяснение. И, возможно, достаточно не понимать её до конца, а просто не проходить мимо.",
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


def format_fact_or_note(text: str, is_diary: bool) -> str:
    if not is_diary:
        cleaned = re.sub(r"^\s*\d+\)\s*", "", text.strip())
        cleaned = cleaned.lstrip(". ").strip()
    else:
        cleaned = text.strip()
    escaped = html.escape(cleaned).replace("\n", "<br>")
    return escaped


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
        "next_fact_switch_at": 0.0,
        "fact_payload": "",
        "fact_is_diary": False,
        "stdout_log_path": "",
        "stderr_log_path": "",
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
    stdout_log = tmp_path / "stdout.log"
    stderr_log = tmp_path / "stderr.log"
    out_f = stdout_log.open("w", encoding="utf-8")
    err_f = stderr_log.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        command,
        stdout=out_f,
        stderr=err_f,
        text=True,
    )
    out_f.close()
    err_f.close()
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
    st.session_state["next_fact_switch_at"] = 0.0
    st.session_state["fact_payload"] = ""
    st.session_state["fact_is_diary"] = False
    st.session_state["stdout_log_path"] = str(stdout_log)
    st.session_state["stderr_log_path"] = str(stderr_log)


def finalize_process_result(stopped_by_user: bool = False) -> None:
    proc = st.session_state.get("proc")
    if proc is None:
        st.session_state["running"] = False
        return
    if stopped_by_user and proc.poll() is None:
        proc.terminate()
    proc.wait()
    stdout_log_path = st.session_state.get("stdout_log_path") or ""
    stderr_log_path = st.session_state.get("stderr_log_path") or ""
    stdout = Path(stdout_log_path).read_text(encoding="utf-8", errors="ignore") if stdout_log_path else ""
    stderr = Path(stderr_log_path).read_text(encoding="utf-8", errors="ignore") if stderr_log_path else ""
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
    st.session_state["stdout_log_path"] = ""
    st.session_state["stderr_log_path"] = ""
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
    next_switch_at = float(st.session_state.get("next_fact_switch_at") or 0.0)
    if elapsed >= next_switch_at:
        # Факты показываем чаще, записи реже.
        if random.random() < 0.72:
            st.session_state["fact_payload"] = random.choice(PROVOCATIVE_TRUE_FACTS)
            st.session_state["fact_is_diary"] = False
        else:
            st.session_state["fact_payload"] = random.choice(DIARY_NOTES)
            st.session_state["fact_is_diary"] = True
        hold_for = FACT_ROTATE_SECONDS + (DIARY_EXTRA_SECONDS if st.session_state["fact_is_diary"] else 0.0)
        st.session_state["next_fact_switch_at"] = elapsed + hold_for

    fact_text = str(st.session_state.get("fact_payload") or PROVOCATIVE_TRUE_FACTS[0])
    is_diary = bool(st.session_state.get("fact_is_diary"))
    formatted_text = format_fact_or_note(fact_text, is_diary=is_diary)
    card_title = "📝 Запись из архива" if is_diary else "⚡ Интересный факт"
    card_bg = "#dbc98a" if is_diary else "#ffe999"
    card_text_color = "#101827"
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
            <div style="margin-top: 12px; font-size: 1.28rem; line-height: 1.35; font-weight: 800; color: {card_text_color}; white-space: normal;">{formatted_text}</div>
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
