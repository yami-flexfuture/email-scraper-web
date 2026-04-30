from __future__ import annotations

import csv
import random
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


def render_mini_games() -> None:
    st.markdown("### 🎮 Мини-игры пока идет парсинг")
    game = st.selectbox(
        "Выбери режим",
        ["Гоночки", "Танчики", "Аэрохоккей"],
        index=0,
    )

    if game == "Гоночки":
        col1, col2 = st.columns(2)
        with col1:
            st.session_state.setdefault("race_player", 0)
            if st.button("Газ в пол!"):
                st.session_state["race_player"] += random.randint(7, 16)
        with col2:
            st.session_state.setdefault("race_bot", 0)
            st.session_state["race_bot"] += random.randint(5, 13)
            if st.button("Новая гонка"):
                st.session_state["race_player"] = 0
                st.session_state["race_bot"] = 0
        st.progress(min(st.session_state["race_player"], 100), text="Ты")
        st.progress(min(st.session_state["race_bot"], 100), text="Бот")
        if st.session_state["race_player"] >= 100 or st.session_state["race_bot"] >= 100:
            if st.session_state["race_player"] > st.session_state["race_bot"]:
                st.success("🏁 Ты победил в гоночках!")
            elif st.session_state["race_player"] < st.session_state["race_bot"]:
                st.warning("💨 Бот оказался быстрее. Реванш?")
            else:
                st.info("🤝 Ничья. Фотофиниш.")

    elif game == "Танчики":
        st.session_state.setdefault("tank_hp_you", 100)
        st.session_state.setdefault("tank_hp_bot", 100)
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("💣 Выстрел"):
                st.session_state["tank_hp_bot"] = max(
                    0, st.session_state["tank_hp_bot"] - random.randint(8, 20)
                )
                st.session_state["tank_hp_you"] = max(
                    0, st.session_state["tank_hp_you"] - random.randint(5, 15)
                )
        with c2:
            if st.button("🛡 Ремонт"):
                st.session_state["tank_hp_you"] = min(
                    100, st.session_state["tank_hp_you"] + random.randint(6, 14)
                )
        with c3:
            if st.button("🔄 Новая битва"):
                st.session_state["tank_hp_you"] = 100
                st.session_state["tank_hp_bot"] = 100
        st.progress(st.session_state["tank_hp_you"], text="Твой танк")
        st.progress(st.session_state["tank_hp_bot"], text="Танк бота")
        if st.session_state["tank_hp_bot"] == 0:
            st.success("🔥 Противник уничтожен!")
        elif st.session_state["tank_hp_you"] == 0:
            st.error("💥 Твой танк подбит.")

    else:
        st.session_state.setdefault("hockey_you", 0)
        st.session_state.setdefault("hockey_bot", 0)
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🏒 Удар по шайбе"):
                event = random.choice(["goal_you", "goal_bot", "save", "post"])
                if event == "goal_you":
                    st.session_state["hockey_you"] += 1
                    st.success("ГОООЛ! Ты забил.")
                elif event == "goal_bot":
                    st.session_state["hockey_bot"] += 1
                    st.warning("Бот поймал тебя на контратаке.")
                elif event == "save":
                    st.info("Вратарь тащит.")
                else:
                    st.info("Штанга!")
        with col2:
            st.metric("Ты", st.session_state["hockey_you"])
        with col3:
            st.metric("Бот", st.session_state["hockey_bot"])
        if st.button("🔄 Новый матч"):
            st.session_state["hockey_you"] = 0
            st.session_state["hockey_bot"] = 0


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
st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #88d6ff 0%, #e8f8ff 40%, #f9fdff 100%);
    }
    .cartoon-card {
        background: #fff7dc;
        border: 4px solid #111;
        border-radius: 22px;
        padding: 16px 18px;
        box-shadow: 6px 6px 0 #111;
        margin-bottom: 14px;
    }
    .cartoon-title {
        font-size: 2.1rem;
        font-weight: 900;
        color: #111;
        margin: 0;
        line-height: 1.1;
    }
    .cartoon-subtitle {
        font-size: 1rem;
        color: #222;
        margin-top: 8px;
    }
    .badge-row {
        margin-top: 10px;
    }
    .badge {
        display: inline-block;
        background: #ffde59;
        color: #111;
        border: 3px solid #111;
        border-radius: 999px;
        padding: 4px 10px;
        margin-right: 8px;
        margin-bottom: 6px;
        font-size: 0.82rem;
        font-weight: 700;
    }
    </style>
    <div class="cartoon-card">
        <p class="cartoon-title">🎬 Email Scraper: Arcade Lobby Edition</p>
        <p class="cartoon-subtitle">
            Закидывай сайты — мы ищем рабочие имейлы и контактные формы.
            А сверху можно отвлечься на мини-аркаду.
        </p>
        <div class="badge-row">
            <span class="badge">Top-3 email на домен</span>
            <span class="badge">Contact forms отдельно</span>
            <span class="badge">CSV in / CSV out</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.container():
    with st.expander("🎮 Открыть мини-игры"):
        render_mini_games()

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
