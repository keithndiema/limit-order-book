FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake r-base-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[analysis]" && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build -j
CMD ["lob", "demo"]
