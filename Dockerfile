FROM python:3.11

# 作業ディレクトリを設定
WORKDIR /app

# システムパッケージの更新とffmpegのインストール
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 依存ファイルのコピーとインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションファイルをコピー
COPY . .

# 一時動画ディレクトリを作成（オプション）
RUN mkdir -p /tmp/mij_temp_videos

# Uvicornでアプリを起動
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]