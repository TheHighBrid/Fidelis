# Fidelis Studio - Production Container for OVH Cloud & Linux VPS
FROM python:3.12-slim-bookworm

LABEL maintainer="Fidelis Development Team"
LABEL description="Fidelis Photographic Restoration Studio with Vulkan/NCNN and Local Portrait Pore Engine"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    FIDELIS_HOME=/root/.local/share/fidelis \
    PATH="/root/.local/share/fidelis/bin:/root/.local/bin:${PATH}"

# Install native dependencies: OpenCV, Vulkan loader, image codecs, build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libvulkan1 \
    vulkan-tools \
    jq \
    file \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install uv for high-speed deterministic dependency management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app

# Copy dependency specifications first for caching
COPY requirements.txt ./
RUN /root/.local/bin/uv pip install --system --no-cache -r requirements.txt \
    && /root/.local/bin/uv pip install --system --no-cache onnxruntime opencv-python-headless

# Copy repository sources
COPY . .

# Setup Fidelis runtime directories
RUN mkdir -p /root/.local/share/fidelis/runtime \
    /root/.local/share/fidelis/models/portrait \
    /root/.local/share/fidelis/bin \
    && cp bin/fidelis /root/.local/share/fidelis/bin/fidelis \
    && chmod +x /root/.local/share/fidelis/bin/fidelis scripts/*.py scripts/*.sh 2>/dev/null || true

# Download base portrait models (CodeFormer & YuNet) for container readiness
RUN curl -L -s -o /root/.local/share/fidelis/models/portrait/yunet.onnx \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
    && curl -L -C - --fail --retry 3 -o /root/.local/share/fidelis/models/portrait/codeformer.onnx \
    https://github.com/harisreedhar/Face-Upscalers-ONNX/releases/download/Models/codeformer.onnx || true

EXPOSE 8080
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8080/ || exit 1

ENTRYPOINT ["python3", "scripts/web-ui.py", "-b", "0.0.0.0", "-p", "8080"]
