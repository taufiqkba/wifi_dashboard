import concurrent.futures
import io
import sqlite3
import time
import zipfile
from datetime import datetime

import pandas as pd
import plotly.express as px  # Tambahan untuk Bar Chart Summary
import plotly.graph_objects as go
import requests
import streamlit as st
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- MATIKAN WARNING SSL ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- KONFIGURASI HALAMAN ---
st.set_page_config(
    layout="wide", page_title="Wifi.id Usage Dashboard v7.0", page_icon="🏆"
)

# --- DATABASE SETUP ---
DB_NAME = "wifi_locations.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT,
            loc_id TEXT,
            site_name TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_to_db(df, project_name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM locations WHERE project_name = ?", (project_name,))
    data_tuples = [
        (project_name, row["LOC_ID"], row["SITE_NAME"]) for _, row in df.iterrows()
    ]
    c.executemany(
        "INSERT INTO locations (project_name, loc_id, site_name) VALUES (?, ?, ?)",
        data_tuples,
    )
    conn.commit()
    conn.close()


def load_from_db(project_name):
    conn = sqlite3.connect(DB_NAME)
    query = "SELECT loc_id, site_name FROM locations WHERE project_name = ?"
    df = pd.read_sql_query(query, conn, params=(project_name,))
    conn.close()
    if not df.empty:
        df.columns = ["LOC_ID", "SITE_NAME"]
    return df


def delete_project_data(project_name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM locations WHERE project_name = ?", (project_name,))
    conn.commit()
    conn.close()


init_db()

# --- INISIALISASI SESSION STATE ---
if "project_sessions" not in st.session_state:
    st.session_state["project_sessions"] = {}

# --- CONFIG PROYEK ---
PROJECT_CONFIG = {
    "Kecamatan Berdaya": {"vo_id": "15557"},
    "Pendidikan": {"vo_id": "13231"},
    "Pelayanan Publik": {"vo_id": "12945"},
    "WMS POLDA Jawa Tengah": {"vo_id": "13329"},
    "Lainnya": {"vo_id": "15557"},
}

# --- CREDENTIALS (SECURE) ---
# Mengambil data user & password dari Streamlit Secrets
# Jika dijalankan lokal, dia baca .streamlit/secrets.toml
# Jika di Cloud, dia baca dari menu Settings -> Secrets
try:
    USERS = st.secrets["users"]
except FileNotFoundError:
    st.error("Settingan Password belum ada! Mohon konfigurasi Secrets terlebih dahulu.")
    st.stop()


# --- 1. FUNGSI FETCH DATA ---
# --- SETUP SESSION GLOBAL (Supaya koneksi tidak putus-nyambung) ---
def get_session():
    if "request_session" not in st.session_state:
        session = requests.Session()
        retries = Retry(
            total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504]
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))
        st.session_state["request_session"] = session
    return st.session_state["request_session"]


# --- 1. FUNGSI FETCH DATA (OPTIMIZED + CACHING) ---
# @st.cache_data membuat data tersimpan di RAM server selama 1 jam (ttl=3600)
# Jadi kalau diklik ulang, tidak perlu fetch ke wifi.id lagi.
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_usage_data(session_id, vo_id, loc_id, start_date, end_date):
    url = "https://venue.wifi.id/vdash/dashboard/plinechart?"

    # Gunakan Session yang persisten
    s = get_session()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": f"PHPSESSID={session_id}",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    s_date_clean = start_date.strftime("%Y%m%d")
    e_date_clean = end_date.strftime("%Y%m%d")

    payload = {
        "optionsRadios": "3",
        "startdate": s_date_clean,
        "enddate": e_date_clean,
        "rr": "3",
        "vo": vo_id,
        "level": "l2",
        "locid": loc_id,
        "namasite": "JATENG",
        "ap": "",
        "kota": "",
        "ssid": "",
        "sitename": "",
    }

    try:
        # Timeout dinaikkan ke 60 detik karena server USA ke Indo pasti delay
        response = s.post(url, headers=headers, data=payload, verify=False, timeout=60)

        if response.status_code != 200:
            return None

        try:
            data = response.json()
        except ValueError:
            return None

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        if "PERIODE" in df.columns:
            df["date"] = pd.to_datetime(df["PERIODE"], format="%Y%m%d", errors="coerce")

            # Optimasi tipe data biar hemat RAM server
            if "USAGES" in df.columns:
                df["usage_bytes"] = pd.to_numeric(df["USAGES"], errors="coerce").fillna(
                    0
                )
                df["total_usage_gb"] = df["usage_bytes"] / (1024**3)
            else:
                df["total_usage_gb"] = 0.0

            if "TRAFIK" in df.columns:
                df["connected_user"] = (
                    pd.to_numeric(df["TRAFIK"], errors="coerce").fillna(0).astype(int)
                )
            else:
                df["connected_user"] = 0

            df = df.sort_values("date")
            # Return hanya kolom penting biar cache enteng
            return df[["date", "connected_user", "total_usage_gb"]]
        else:
            return pd.DataFrame()

    except Exception:
        return None


# --- 2. FUNGSI CHART ---
def create_chart(df, title_text):
    df["date_str"] = df["date"].dt.strftime("%d %b")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["date_str"],
            y=df["connected_user"],
            name="Connected User",
            mode="lines+markers",
            line=dict(color="#2980b9", width=5, shape="spline"),
            marker=dict(size=8),
            yaxis="y",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["date_str"],
            y=df["total_usage_gb"],
            name="Total Usage (GB)",
            mode="lines+markers",
            line=dict(color="#c0392b", width=5, shape="spline"),
            marker=dict(size=8),
            yaxis="y2",
        )
    )
    fig.update_layout(
        title=dict(
            text=title_text,
            font=dict(size=22, color="black"),
            y=0.95,
            x=0.01,
            xanchor="left",
            yanchor="top",
        ),
        margin=dict(l=50, r=50, t=150, b=50),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            font=dict(size=14),
        ),
        xaxis=dict(
            type="category", showgrid=False, tickangle=-45, tickfont=dict(size=12)
        ),
        yaxis=dict(
            title=dict(text="Connected User", font=dict(color="#2980b9", size=14)),
            tickfont=dict(color="#2980b9", size=12),
        ),
        yaxis2=dict(
            title=dict(text="Total Usage (GB)", font=dict(color="#c0392b", size=14)),
            tickfont=dict(color="#c0392b", size=12),
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        template="plotly_white",
        hovermode="x unified",
    )
    return fig


# --- 3. HELPER: BULK PROCESSOR & SUMMARY ---
def process_single_location(row_data, phpsess, vo_id, s_date, e_date):
    loc_id = row_data["LOC_ID"]
    loc_name = row_data["SITE_NAME"]

    df = fetch_usage_data(phpsess, vo_id, loc_id, s_date, e_date)

    # CASE ERROR: Jika data None (Gagal Fetch)
    if df is None:
        return {
            "status": "error",
            "name": loc_name,
            "id": loc_id,
            "reason": "Connection Failed",
        }

    # CASE EMPTY: Jika data Kosong (Zonk)
    if df.empty:
        return {
            "status": "empty",
            "name": loc_name,
            "id": loc_id,
            "reason": "No Data Available",
        }

    # SUKSES FETCH
    total_usage = df["total_usage_gb"].sum()

    # Buat Chart
    title_html = f"<b>{loc_name} ({loc_id})</b><br><span style='font-size: 16px; color: gray;'>{s_date.strftime('%d/%m/%Y')} - {e_date.strftime('%d/%m/%Y')}</span>"
    fig = create_chart(df, title_html)
    img_bytes = fig.to_image(format="png", width=1400, height=700, scale=2)
    del fig

    clean_name = "".join([c if c.isalnum() else "_" for c in loc_name])
    filename = f"{clean_name}_{loc_id}.png"

    return {
        "status": "success",
        "filename": filename,
        "img_data": img_bytes,
        "loc_id": loc_id,
        "site_name": loc_name,
        "total_usage": total_usage,
    }


# --- 4. SECURITY ---
def check_authentication():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if not st.session_state["authenticated"]:
        st.header("🔐 Login Dashboard")
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                if username in USERS and USERS[username] == password:
                    st.session_state["authenticated"] = True
                    st.session_state["user"] = username
                    st.rerun()
                else:
                    st.error("Login Gagal")
        return False
    return True


# --- MAIN APP ---
if check_authentication():
    with st.sidebar:
        st.write(f"👤 User: **{st.session_state['user']}**")
        if st.button("Logout"):
            st.session_state["authenticated"] = False
            st.rerun()
        st.title("🎛️ Control Panel")

    selected_project = st.sidebar.selectbox("📂 Proyek", list(PROJECT_CONFIG.keys()))
    current_vo_id = PROJECT_CONFIG[selected_project]["vo_id"]

    # Session Input
    default_val = st.session_state["project_sessions"].get(selected_project, "")
    new_sess = st.sidebar.text_input(
        f"Session ID ({selected_project})", value=default_val, type="password"
    )
    st.session_state["project_sessions"][selected_project] = new_sess

    # Database Logic
    st.sidebar.markdown("---")
    st.sidebar.subheader("💾 Database")
    active_df = load_from_db(selected_project)

    if not active_df.empty:
        st.sidebar.success(f"✅ {len(active_df)} Lokasi Ready")
        with st.sidebar.expander("⚠️ Atur Data"):
            if st.button(f"Hapus DB {selected_project}", type="primary"):
                delete_project_data(selected_project)
                st.rerun()
    else:
        st.sidebar.warning("Data kosong. Upload Excel.")
        uploaded_file = st.sidebar.file_uploader(
            f"Upload {selected_project}", type=["xlsx"], key=f"file_{selected_project}"
        )
        if uploaded_file:
            try:
                df_temp = pd.read_excel(uploaded_file)
                df_temp.columns = [
                    c.strip().upper().replace(" ", "_") for c in df_temp.columns
                ]
                col_loc_id = None
                col_site_name = None
                for col in df_temp.columns:
                    if "LOC" in col:
                        col_loc_id = col
                    elif any(x in col for x in ["KEC", "NAM", "LOK", "GED", "SITE"]):
                        col_site_name = col

                if not col_site_name and len(df_temp.columns) > 1:
                    col_site_name = (
                        df_temp.columns[1]
                        if df_temp.columns[0] == col_loc_id
                        else df_temp.columns[0]
                    )

                if col_loc_id and col_site_name:
                    df_clean = df_temp[[col_loc_id, col_site_name]].copy()
                    df_clean.columns = ["LOC_ID", "SITE_NAME"]
                    save_to_db(df_clean, selected_project)
                    st.sidebar.success("Disimpan!")
                    st.rerun()
                else:
                    st.sidebar.error("Format Excel salah.")
            except Exception as e:
                st.sidebar.error(f"Error: {e}")

    # --- CONTENT AREA ---
    active_sess = st.session_state["project_sessions"].get(selected_project)

    if active_df is not None and not active_df.empty:
        st.markdown(f"### 📊 Dashboard: {selected_project}")
        d_range = st.date_input(
            "Periode Laporan", value=(datetime(2026, 1, 1), datetime(2026, 1, 31))
        )

        # TAB MENU
        tab1, tab2, tab3 = st.tabs(
            [
                "🔍 Cek Single Location",
                "📥 Bulk Download (Manager)",
                "📈 Global Summary (Rekap)",
            ]
        )

        # === TAB 1: SINGLE CHECK ===
        with tab1:
            if not active_sess:
                st.warning("⚠️ Masukkan Session ID di Sidebar.")
            else:
                col_sel1, col_sel2 = st.columns([3, 1])
                with col_sel1:
                    select_options = active_df.apply(
                        lambda x: f"{x['SITE_NAME']} | {x['LOC_ID']}", axis=1
                    )
                    selected_option = st.selectbox("Pilih Lokasi:", select_options)

                sel_idx = select_options[select_options == selected_option].index[0]
                sel_row = active_df.iloc[sel_idx]

                if len(d_range) == 2:
                    s_date, e_date = d_range
                    if st.button("Tampilkan Grafik", key="btn_single"):
                        with st.spinner("Fetching data..."):
                            df_res = fetch_usage_data(
                                active_sess,
                                current_vo_id,
                                sel_row["LOC_ID"],
                                s_date,
                                e_date,
                            )

                        if df_res is not None and not df_res.empty:
                            m1, m2, m3, m4 = st.columns(4)
                            m1.metric(
                                "Total Usage",
                                f"{df_res['total_usage_gb'].sum():.2f} GB",
                            )
                            m2.metric(
                                "Rata-rata/Hari",
                                f"{df_res['total_usage_gb'].mean():.2f} GB",
                            )
                            m3.metric("Max User", f"{df_res['connected_user'].max()}")
                            m4.metric("Data Point", f"{len(df_res)} Hari")

                            title_html = f"<b>{sel_row['SITE_NAME']} ({sel_row['LOC_ID']})</b><br><span style='font-size: 16px; color: gray;'>{s_date.strftime('%d/%m/%Y')} - {e_date.strftime('%d/%m/%Y')}</span>"
                            st.plotly_chart(
                                create_chart(df_res, title_html), width="stretch"
                            )
                        else:
                            st.error("Data kosong atau session invalid.")

        # === TAB 2: BULK DOWNLOAD + ERROR LOGGING ===
        with tab2:
            st.info(
                "Fitur ini akan mendownload semua chart dan membuat **Laporan Error** jika ada data yang gagal."
            )

            mode = st.radio(
                "Kecepatan Download:",
                ["Safe Mode (Stabil)", "Turbo Mode (Cepat)"],
                horizontal=True,
            )
            workers = 3 if "Safe" in mode else 8

            if len(d_range) == 2 and st.button(
                f"Mulai Download ({len(active_df)} Lokasi)", key="btn_bulk"
            ):
                if not active_sess:
                    st.error("Session ID Kosong!")
                    st.stop()

                s_date, e_date = d_range
                zip_buffer = io.BytesIO()
                prog_bar = st.progress(0)
                status_text = st.empty()

                # List untuk menampung error log
                error_logs = []
                success_count = 0

                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=workers
                ) as executor:
                    futures = {
                        executor.submit(
                            process_single_location,
                            row,
                            active_sess,
                            current_vo_id,
                            s_date,
                            e_date,
                        ): row
                        for _, row in active_df.iterrows()
                    }

                    total = len(active_df)
                    with zipfile.ZipFile(
                        zip_buffer, "a", zipfile.ZIP_DEFLATED, False
                    ) as zf:
                        for i, future in enumerate(
                            concurrent.futures.as_completed(futures)
                        ):
                            res = future.result()
                            prog_bar.progress((i + 1) / total)
                            status_text.text(f"Processing {i + 1}/{total}...")

                            if res["status"] == "success":
                                zf.writestr(res["filename"], res["img_data"])
                                success_count += 1
                            else:
                                # Catat Error
                                error_logs.append(
                                    f"[{res['status'].upper()}] {res['name']} ({res['id']}): {res['reason']}"
                                )

                        # Tulis File Log Error ke dalam ZIP
                        if error_logs:
                            log_content = (
                                f"LAPORAN ERROR DOWNLOAD\nProject: {selected_project}\nTanggal: {datetime.now()}\n\n"
                                + "\n".join(error_logs)
                            )
                            zf.writestr("00_LAPORAN_ERROR_LOG.txt", log_content)

                status_text.success(
                    f"✅ Selesai! Berhasil: {success_count}, Gagal/Kosong: {len(error_logs)}"
                )
                if error_logs:
                    st.warning(
                        f"⚠️ Ada {len(error_logs)} lokasi yang gagal/kosong. Cek file '00_LAPORAN_ERROR_LOG.txt' di dalam ZIP."
                    )

                st.download_button(
                    "💾 Download ZIP Hasil",
                    zip_buffer.getvalue(),
                    f"Report_{selected_project}.zip",
                    "application/zip",
                )

        # === TAB 3: GLOBAL SUMMARY (NEW FEATURE!) ===
        with tab3:
            st.markdown("### 📈 Rekapitulasi Data (Top Usage)")
            st.caption(
                "Fitur ini akan menarik data sekilas dari seluruh lokasi untuk membuat peringkat penggunaan."
            )

            if st.button("Generate Summary Report"):
                if not active_sess:
                    st.error("Session ID Kosong!")
                    st.stop()

                s_date, e_date = d_range
                summary_data = []
                prog_bar = st.progress(0)

                # Gunakan Turbo Mode untuk fetch data (Tanpa generate gambar biar cepat)
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    futures = {
                        executor.submit(
                            fetch_usage_data,
                            active_sess,
                            current_vo_id,
                            row["LOC_ID"],
                            s_date,
                            e_date,
                        ): row
                        for _, row in active_df.iterrows()
                    }

                    for i, future in enumerate(
                        concurrent.futures.as_completed(futures)
                    ):
                        row = futures[future]
                        df_res = future.result()
                        prog_bar.progress((i + 1) / len(active_df))

                        if df_res is not None and not df_res.empty:
                            total_gb = df_res["total_usage_gb"].sum()
                            avg_gb = df_res["total_usage_gb"].mean()
                            summary_data.append(
                                {
                                    "Kecamatan/Lokasi": row["SITE_NAME"],
                                    "LOC ID": row["LOC_ID"],
                                    "Total Usage (GB)": round(total_gb, 2),
                                    "Rata-rata (GB)": round(avg_gb, 2),
                                }
                            )

                if summary_data:
                    df_summary = pd.DataFrame(summary_data).sort_values(
                        "Total Usage (GB)", ascending=False
                    )

                    # Tampilkan Metric Global
                    col1, col2 = st.columns(2)
                    col1.metric(
                        "Total Usage Project",
                        f"{df_summary['Total Usage (GB)'].sum():,.2f} GB",
                    )
                    col2.metric(
                        "Lokasi Aktif", f"{len(df_summary)} / {len(active_df)} Titik"
                    )

                    st.markdown("---")

                    # Tampilkan Bar Chart Top 10
                    st.subheader("🏆 Top 10 Lokasi dengan Usage Tertinggi")
                    df_top10 = df_summary.head(10)
                    fig_bar = px.bar(
                        df_top10,
                        x="Total Usage (GB)",
                        y="Kecamatan/Lokasi",
                        orientation="h",
                        text="Total Usage (GB)",
                        color="Total Usage (GB)",
                        color_continuous_scale="Blues",
                    )
                    fig_bar.update_layout(
                        yaxis=dict(autorange="reversed")
                    )  # Urutan 1 di atas
                    st.plotly_chart(fig_bar, use_container_width=True)

                    # Tampilkan Data Table
                    st.subheader("📋 Data Lengkap")
                    st.dataframe(df_summary, use_container_width=True)
                else:
                    st.error("Gagal mengambil data rekap. Pastikan Session ID Valid.")
