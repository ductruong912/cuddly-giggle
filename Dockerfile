# App image: FastAPI + PaddleOCR-VL detection/layout. Recognition runs in the separate
# llama container (docker-compose.yml). Older driver? rebuild with cu118:
#   --build-arg CUDA_TAG=11.8.0-cudnn8-runtime-ubuntu22.04
#   --build-arg PADDLE_INDEX=https://www.paddlepaddle.org.cn/packages/stable/cu118/
ARG CUDA_TAG=12.6.3-cudnn-runtime-ubuntu22.04
FROM nvidia/cuda:${CUDA_TAG}

ARG PADDLE_INDEX=https://www.paddlepaddle.org.cn/packages/stable/cu126/
ARG PADDLE_PKG=paddlepaddle-gpu==3.3.0

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates curl \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-dev python3.11-venv \
        libreoffice-writer libreoffice-calc \
        libgl1 libglib2.0-0 libgomp1 \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pin the CUDA build of PaddlePaddle first; requirements.txt then resolves it as satisfied.
RUN python3.11 -m pip install --no-cache-dir ${PADDLE_PKG} -i ${PADDLE_INDEX}
COPY requirements.txt .
RUN python3.11 -m pip install --no-cache-dir -r requirements.txt

COPY . .

ENV HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000
CMD ["python3.11", "main.py"]
