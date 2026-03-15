# 📄 RAG PDF Chatbot

A Retrieval-Augmented Generation (RAG) chatbot that can answer questions from PDF documents using Large Language Models.

The system extracts information from PDF files, converts them into embeddings, stores them in a vector database, and retrieves relevant context to generate accurate answers.

---

# 🚀 Tech Stack

Backend:

- Python
- FastAPI

AI / RAG:

- LangChain
- OpenRouter API (LLM)
- Embeddings

Vector Database:

- Milvus

Infrastructure:

- Docker
- Docker Compose

Frontend:

- React / Next.js

---

# 🐳 Chạy stack (Docker)

**Tạo thư mục data (quan trọng!)**

Linux/macOS:

```bash
mkdir -p volumes/etcd volumes/minio volumes/milvus
```

Windows (PowerShell):

```powershell
New-Item -ItemType Directory -Force -Path volumes/etcd, volumes/minio, volumes/milvus
```

**Khởi động toàn bộ stack (detached mode)**

```bash
docker compose up -d
```

**Xem log realtime** (Ctrl+C để thoát, không dừng container)

```bash
docker compose logs -f milvus
```

**Kiểm tra tất cả container đang chạy**

```bash
docker compose ps
```

---

# 🧠 System Architecture
