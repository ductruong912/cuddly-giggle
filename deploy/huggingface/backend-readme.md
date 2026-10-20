---
title: Cuddly Giggle
short_description: Read documents and view OCR results instantly
emoji: 📄
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 6.20.0
python_version: '3.10'
app_file: app.py
suggested_hardware: zero-a10g
---

React OCR playground with its API in the same Space. Select **ZeroGPU** hardware
when creating this Space; `suggested_hardware` alone does not allocate hardware.

The demo uses PaddleOCR-VL 1.6 with the Transformers backend, rather than the
local GGUF server. It returns OCR Markdown, JSON, and bounding boxes without
calling OpenAI or a database. Uploads are limited to 20 MiB and 3 PDF pages.
GPU availability, request duration, and daily quotas are controlled by Hugging
Face. Uploaded files use temporary Space storage. Download results from the UI.

Only upload documents you are comfortable processing in a public demo.
