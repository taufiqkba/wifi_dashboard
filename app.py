import concurrent.futures
import io
import sqlite3
import time  # Untuk jeda retry
import zipfile
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import urllib3

# --- MATIKAN WARNING SSL ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- KONFIGURASI HALAMAN ---
st.set_page_config(
    layout="wide", page_title="Wifi.id Usage Dashboard v6.0", page_icon="💎"
)

# --- DATABASE SETUP (SQLITE) ---
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
    "POLDA Jawa Tengah 1": {"vo_id": "13329"},
    "Lainnya": {"vo_id": "15557"},
}

# --- CREDENTIALS ---
USERS = {"admin": "admin123", "team_jateng": "jateng2026", "user_lapangan": "lapangan1"}


# --- 1. FUNGSI FETCH DATA (DENGAN RETRY LOGIC) ---
def fetch_usage_data(session_id, vo_id, loc_id, start_date, end_date, max_retries=3):
    url = "https://venue.wifi.id/vdash/dashboard/plinechart?"
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

    # RETRY LOOP
    for attempt in range(max_retries):
        try:
            response = requests.post(
                url, headers=headers, data=payload, verify=False, timeout=30
            )
            if response.status_code != 200:
                time.sleep(1)  # Jeda dulu sebelum retry
                continue  # Coba lagi

            try:
                data = response.json()
            except ValueError:
                return None

            if not data:
                return pd.DataFrame()

            df = pd.DataFrame(data)
            if "PERIODE" in df.columns:
                df["date"] = pd.to_datetime(
                    df["PERIODE"], format="%Y%m%d", errors="coerce"
                )
                if "USAGES" in df.columns:
                    df["usage_bytes"] = pd.to_numeric(
                        df["USAGES"], errors="coerce"
                    ).fillna(0)
                    df["total_usage_gb"] = df["usage_bytes"] / (1024**3)
                else:
                    df["total_usage_gb"] = 0
                if "TRAFIK" in df.columns:
                    df["connected_user"] = (
                        pd.to_numeric(df["TRAFIK"], errors="coerce")
                        .fillna(0)
                        .astype(int)
                    )
                else:
                    df["connected_user"] = 0

                df = df.sort_values("date")
                return df[["date", "connected_user", "total_usage_gb"]]
            else:
                return pd.DataFrame()

        except Exception:
            time.sleep(1)  # Jeda jika koneksi error
            continue  # Coba lagi

    return None  # Nyerah setelah 3x percobaan


# --- 2. FUNGSI CHART (CATEGORY AXIS) ---
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


# --- 3. HELPER: BULK PROCESSOR ---
def process_single_location(row_data, phpsess, vo_id, s_date, e_date):
    loc_id = row_data["LOC_ID"]
    loc_name = row_data["SITE_NAME"]

    # Fungsi fetch sudah punya auto-retry didalamnya
    df = fetch_usage_data(phpsess, vo_id, loc_id, s_date, e_date)

    if df is None or df.empty:
        return None

    title_html = f"<b>{loc_name} ({loc_id})</b><br><span style='font-size: 16px; color: gray;'>{s_date.strftime('%d/%m/%Y')} - {e_date.strftime('%d/%m/%Y')}</span>"

    # Generate Chart
    fig = create_chart(df, title_html)

    # Render Image (Bagian Paling Berat di CPU)
    img_bytes = fig.to_image(format="png", width=1400, height=700, scale=2)

    # MEMORY CLEANUP: Hapus object figure setelah jadi bytes
    del fig

    clean_name = "".join([c if c.isalnum() else "_" for c in loc_name])
    filename = f"{clean_name}_{loc_id}.png"
    return (filename, img_bytes)


# --- 4. SECURITY ---
def login_page():
    st.header("🔐 Login Dashboard")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
        if submit:
            if username in USERS and USERS[username] == password:
                st.session_state["authenticated"] = True
                st.session_state["user"] = username
                st.success("Login berhasil!")
                st.rerun()
            else:
                st.error("Username atau Password salah.")


def check_authentication():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if not st.session_state["authenticated"]:
        login_page()
        return False
    return True


# --- MAIN APP ---
if check_authentication():
    with st.sidebar:
        st.write(f"👤 Login sebagai: **{st.session_state['user']}**")
        if st.button("Logout"):
            st.session_state["authenticated"] = False
            st.rerun()
        st.title("🎛️ Control Panel")

    selected_project = st.sidebar.selectbox(
        "📂 Pilih Proyek Aktif", list(PROJECT_CONFIG.keys())
    )
    current_vo_id = PROJECT_CONFIG[selected_project]["vo_id"]
    st.sidebar.markdown("---")

    st.sidebar.subheader(f"🔑 Session ID: {selected_project}")
    default_val = st.session_state["project_sessions"].get(selected_project, "")
    new_sess = st.sidebar.text_input(
        "PHPSESSID", value=default_val, type="password", key=f"sess_{selected_project}"
    )
    st.session_state["project_sessions"][selected_project] = new_sess
    st.sidebar.markdown("---")

    st.sidebar.subheader(f"💾 Database Lokasi")
    active_df = load_from_db(selected_project)

    if not active_df.empty:
        st.sidebar.success(f"✅ {len(active_df)} Lokasi Tersimpan!")
        with st.sidebar.expander("⚠️ Atur Ulang Data"):
            if st.button(f"Hapus Data {selected_project}", type="primary"):
                delete_project_data(selected_project)
                st.rerun()
    else:
        st.sidebar.warning("Data lokasi belum ada. Upload Excel.")
        uploaded_file = st.sidebar.file_uploader(
            f"Upload Excel {selected_project}",
            type=["xlsx"],
            key=f"file_{selected_project}",
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
                    st.sidebar.success("Disimpan ke Database!")
                    st.rerun()
                else:
                    st.sidebar.error("❌ Gagal mendeteksi kolom LOC ID atau Nama.")
            except Exception as e:
                st.sidebar.error(f"Error membaca file: {e}")

    active_sess = st.session_state["project_sessions"].get(selected_project)

    if active_df is not None and not active_df.empty:
        col_d1, col_d2 = st.columns([1, 3])
        with col_d1:
            st.markdown(f"**Periode Laporan**")
            d_range = st.date_input(
                "Rentang Tanggal", value=(datetime(2026, 1, 1), datetime(2026, 1, 31))
            )

        tab1, tab2 = st.tabs(["📊 Live Preview", "📦 Bulk Download (Stabil)"])

        with tab1:
            if not active_sess:
                st.warning("⚠️ Masukkan PHPSESSID.")
            else:
                select_options = active_df.apply(
                    lambda x: f"{x['SITE_NAME']} | {x['LOC_ID']}", axis=1
                )
                selected_option = st.selectbox("Pilih Lokasi:", select_options)
                sel_idx = select_options[select_options == selected_option].index[0]
                sel_row = active_df.iloc[sel_idx]

                if len(d_range) == 2:
                    s_date, e_date = d_range
                    if st.button("🔍 Cek Chart"):
                        with st.spinner(f"Fetching..."):
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
                                "Avg Usage", f"{df_res['total_usage_gb'].mean():.2f} GB"
                            )
                            m3.metric("Max User", f"{df_res['connected_user'].max()}")
                            m4.metric("Days", len(df_res))
                            title_html = f"<b>{sel_row['SITE_NAME']} ({sel_row['LOC_ID']})</b><br><span style='font-size: 16px; color: gray;'>{s_date.strftime('%d/%m/%Y')} - {e_date.strftime('%d/%m/%Y')}</span>"
                            st.plotly_chart(
                                create_chart(df_res, title_html), width="stretch"
                            )
                        else:
                            st.error("Data kosong.")

        with tab2:
            st.header(f"🚀 Download Manager: {selected_project}")

            # FITUR BARU: PILIHAN KECEPATAN
            st.info(
                "💡 **Tips:** Pilih 'Safe Mode' jika koneksi tidak stabil atau server spesifikasi rendah."
            )
            speed_mode = st.radio(
                "Pilih Mode Download:",
                (
                    "Safe Mode (Stabil, 3 Concurrent)",
                    "Turbo Mode (Cepat, 8 Concurrent)",
                ),
                index=0,
            )

            # Tentukan max_workers berdasarkan pilihan
            workers = 3 if "Safe" in speed_mode else 8

            if len(d_range) == 2:
                s_date, e_date = d_range
                if st.button(f"Mulai Download ({len(active_df)} Lokasi)"):
                    if not active_sess:
                        st.error("Session ID kosong!")
                        st.stop()

                    zip_buffer = io.BytesIO()
                    progress_text = st.empty()
                    my_bar = st.progress(0)

                    # LOGIC UTAMA: CONCURRENT DOWNLOAD
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=workers
                    ) as executor:
                        future_to_loc = {
                            executor.submit(
                                process_single_location,
                                row,
                                active_sess,
                                current_vo_id,
                                s_date,
                                e_date,
                            ): row
                            for index, row in active_df.iterrows()
                        }
                        completed_count = 0
                        total_items = len(active_df)

                        with zipfile.ZipFile(
                            zip_buffer, "a", zipfile.ZIP_DEFLATED, False
                        ) as zf:
                            for future in concurrent.futures.as_completed(
                                future_to_loc
                            ):
                                completed_count += 1
                                pct = completed_count / total_items
                                my_bar.progress(pct)
                                progress_text.text(
                                    f"Processing {completed_count}/{total_items}..."
                                )
                                try:
                                    res = future.result()
                                    if res:
                                        fname, img_data = res
                                        zf.writestr(fname, img_data)
                                except Exception:
                                    pass

                    progress_text.success("✅ Download Selesai!")
                    st.download_button(
                        "💾 Simpan ZIP File",
                        zip_buffer.getvalue(),
                        f"Chart_{selected_project}.zip",
                        "application/zip",
                    )
    else:
        st.info("👈 Masukkan Session di sidebar. Menu Upload akan muncul otomatis.")
