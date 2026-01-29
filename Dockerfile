# Gunakan image Python yang ringan
FROM python:3.9-slim

# Install dependencies sistem (dibutuhkan oleh Kaleido/Plotly)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Set folder kerja
WORKDIR /app

# Copy requirements dan install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy semua file aplikasi
COPY . .

# Buat folder .streamlit untuk config (opsional)
RUN mkdir -p .streamlit

# Expose port default Streamlit
EXPOSE 8501

# Perintah untuk menjalankan aplikasi
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
