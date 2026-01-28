import concurrent.futures
import io
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
    layout="wide", page_title="Wifi.id Usage Dashboard v3.1", page_icon="🚀"
)

# --- INISIALISASI SESSION STATE ---
if "project_sessions" not in st.session_state:
    st.session_state["project_sessions"] = {}
if "project_data" not in st.session_state:
    st.session_state["project_data"] = {}

# --- CONFIG PROYEK ---
PROJECT_CONFIG = {
    "Kecamatan Berdaya": {"vo_id": "15557"},
    "Pendidikan": {"vo_id": "13231"},
    "Pelayanan Publik": {"vo_id": "12945"},
    "WMS Polda Jateng": {"vo_id": "15557"},
    "Lainnya": {"vo_id": "15557"},
}


# --- 1. FUNGSI FETCH DATA ---
def fetch_usage_data(session_id, vo_id, loc_id, start_date, end_date):
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

    try:
        response = requests.post(
            url, headers=headers, data=payload, verify=False, timeout=30
        )

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

            if "USAGES" in df.columns:
                df["usage_bytes"] = pd.to_numeric(df["USAGES"], errors="coerce").fillna(
                    0
                )
                df["total_usage_gb"] = df["usage_bytes"] / (1024**3)
            else:
                df["total_usage_gb"] = 0

            if "TRAFIK" in df.columns:
                df["connected_user"] = (
                    pd.to_numeric(df["TRAFIK"], errors="coerce").fillna(0).astype(int)
                )
            else:
                df["connected_user"] = 0

            df = df.sort_values("date")
            return df[["date", "connected_user", "total_usage_gb"]]
        else:
            return pd.DataFrame()

    except Exception:
        return None


# --- 2. FUNGSI CHART (MAJOR VISUAL UPDATE) ---
def create_chart(df, title_text):
    fig = go.Figure()

    # Line 1: Connected User (Biru - Smooth Solid)
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["connected_user"],
            name="Connected User",
            mode="lines+markers",
            line=dict(color="#2980b9", width=3, shape="spline"),  # Spline = Smooth
            yaxis="y",
        )
    )

    # Line 2: Total Usage (Merah - Smooth Solid - NO DOTS)
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["total_usage_gb"],
            name="Total Usage (GB)",
            mode="lines+markers",
            # Hapus dash='dot' agar garisnya solid penuh
            line=dict(color="#c0392b", width=3, shape="spline"),
            yaxis="y2",
        )
    )

    # --- LAYOUT ADJUSTMENT ---
    fig.update_layout(
        title=dict(
            text=title_text,
            font=dict(size=22),
            y=0.95,  # Posisi title agak ke atas
            x=0.01,
            xanchor="left",
            yanchor="top",
        ),
        # Atur Margin agar Title tidak menumpuk dengan Legend
        # Top margin diperbesar (t=140)
        margin=dict(l=50, r=50, t=150, b=50),
        # Legend ditaruh di atas plot area, tapi di bawah Title
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,  # Sedikit di atas area grafik
            xanchor="left",
            x=0,
        ),
        # X-Axis: Tampilkan SEMUA Tanggal
        xaxis=dict(
            showgrid=False,
            tickmode="array",  # Mode manual
            tickvals=df["date"],  # Gunakan semua tanggal dari data
            tickformat="%d %b",  # Format: 01 Jan
            tickangle=-45,  # Miringkan agar tidak tabrakan
        ),
        # Y-Axis Kiri (User)
        yaxis=dict(
            title=dict(text="Connected User", font=dict(color="#2980b9")),
            tickfont=dict(color="#2980b9"),
        ),
        # Y-Axis Kanan (Usage)
        yaxis2=dict(
            title=dict(text="Total Usage (GB)", font=dict(color="#c0392b")),
            tickfont=dict(color="#c0392b"),
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

    df = fetch_usage_data(phpsess, vo_id, loc_id, s_date, e_date)

    if df is None or df.empty:
        return None

    # Format Judul dengan <br><br> agar ada jarak enter
    # Baris 1: Nama Lokasi & ID
    # Baris 2: Tanggal (Ukuran font lebih kecil)
    title_html = (
        f"<b>{loc_name} ({loc_id})</b><br>"
        f"<span style='font-size: 16px; color: gray;'>{s_date.strftime('%d/%m/%Y')} - {e_date.strftime('%d/%m/%Y')}</span>"
    )

    fig = create_chart(df, title_html)

    # Export High Res
    img_bytes = fig.to_image(format="png", width=1400, height=700, scale=2)

    clean_name = "".join([c if c.isalnum() else "_" for c in loc_name])
    filename = f"{clean_name}_{loc_id}.png"
    return (filename, img_bytes)


# --- 4. SECURITY ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    def password_entered():
        if st.session_state["password"] == "admin123":
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.error("Password salah")

    if not st.session_state["password_correct"]:
        st.text_input(
            "Password", type="password", on_change=password_entered, key="password"
        )
        return False
    return True


# --- MAIN APP ---
if check_password():
    st.sidebar.title("🎛️ Control Panel")

    # A. PROYEK
    selected_project = st.sidebar.selectbox(
        "📂 Pilih Proyek Aktif", list(PROJECT_CONFIG.keys())
    )
    current_vo_id = PROJECT_CONFIG[selected_project]["vo_id"]

    st.sidebar.markdown("---")

    # B. SESSION
    st.sidebar.subheader(f"🔑 Session ID: {selected_project}")
    default_val = st.session_state["project_sessions"].get(selected_project, "")
    new_sess = st.sidebar.text_input(
        "PHPSESSID", value=default_val, type="password", key=f"sess_{selected_project}"
    )
    st.session_state["project_sessions"][selected_project] = new_sess

    st.sidebar.markdown("---")

    # C. UPLOAD
    st.sidebar.subheader(f"📤 Upload Data: {selected_project}")
    uploaded_file = st.sidebar.file_uploader(
        f"File Excel {selected_project}", type=["xlsx"], key=f"file_{selected_project}"
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
                st.session_state["project_data"][selected_project] = df_clean
                st.sidebar.success(f"✅ {len(df_clean)} Lokasi dimuat!")
            else:
                st.sidebar.error("❌ Gagal mendeteksi kolom LOC ID atau Nama.")

        except Exception as e:
            st.sidebar.error(f"Error membaca file: {e}")

    # --- CONTENT ---
    active_df = st.session_state["project_data"].get(selected_project)
    active_sess = st.session_state["project_sessions"].get(selected_project)

    if active_df is not None and not active_df.empty:
        col_d1, col_d2 = st.columns([1, 3])
        with col_d1:
            st.markdown(f"**Periode Laporan**")
            d_range = st.date_input(
                "Rentang Tanggal", value=(datetime(2026, 1, 1), datetime(2026, 1, 31))
            )

        tab1, tab2 = st.tabs(["📊 Live Preview", "📦 Bulk Download (Turbo)"])

        # TAB 1
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

                            # TITLE CANTIK DENGAN SPACING
                            title_html = (
                                f"<b>{sel_row['SITE_NAME']} ({sel_row['LOC_ID']})</b><br>"
                                f"<span style='font-size: 16px; color: gray;'>{s_date.strftime('%d/%m/%Y')} - {e_date.strftime('%d/%m/%Y')}</span>"
                            )

                            st.plotly_chart(
                                create_chart(df_res, title_html),
                                use_container_width=True,
                            )
                        else:
                            st.error("Data kosong.")

        # TAB 2
        with tab2:
            st.header(f"🚀 Turbo Download: {selected_project}")

            if len(d_range) == 2:
                s_date, e_date = d_range

                if st.button("Start Bulk Download"):
                    if not active_sess:
                        st.error("Session ID kosong!")
                        st.stop()

                    zip_buffer = io.BytesIO()
                    progress_text = st.empty()
                    my_bar = st.progress(0)

                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=10
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
                                    f"Downloading {completed_count}/{total_items}..."
                                )

                                try:
                                    res = future.result()
                                    if res:
                                        fname, img_data = res
                                        zf.writestr(fname, img_data)
                                except Exception:
                                    pass

                    progress_text.success("✅ Selesai!")
                    st.download_button(
                        "💾 Download ZIP",
                        zip_buffer.getvalue(),
                        f"Chart_{selected_project}.zip",
                        "application/zip",
                    )
    else:
        st.info("👈 Masukkan Session & Upload Excel dulu.")
