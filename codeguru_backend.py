"""
CodeGuru Backend - single-file Python 3.10+ backend

WHAT THIS FILE PROVIDES
-----------------------
1. FastAPI backend for the existing CodeGuru frontend
2. Three Ollama local models:
      - qwen3:8b
      - llama3.1:8b
      - gemma3:4b
3. Separate UUID session ID for every "New Chat"
4. Persistent chat history in SQLite
5. Recent chat list
6. Delete a single chat / clear all chats
7. File upload per chat session
8. RAG over uploaded files
9. PDF text extraction + OCR fallback for scanned PDFs
10. Image OCR
11. TXT / MD / JSON / CSV / source-code / DOCX / PPTX / XLSX support
12. Feature buttons matching the screenshot:
      - Debug
      - Explain
      - Quiz
      - Notes
      - Image
      - Video
13. CORS for React / HTML / JS frontend
14. Model health check
15. Groq cloud chat support alongside local Ollama, selectable per chat

PYTHON
------
Python 3.10 recommended.

OLLAMA
------
Install Ollama, start it, then run:

    ollama pull qwen3:8b
    ollama pull llama3.1:8b
    ollama pull gemma3:4b
    ollama pull nomic-embed-text

The embedding model is separate from the three chat models.

RECOMMENDED INSTALL
-------------------
Create a Python 3.10 virtual environment first:

    py -3.10 -m venv .venv
    .venv\\Scripts\\activate

Then install:

    pip install fastapi uvicorn python-multipart
    pip install langchain langchain-core langchain-text-splitters
    pip install langchain-ollama langchain-chroma chromadb
    pip install pypdf pymupdf pillow pytesseract
    pip install python-docx python-pptx openpyxl
    pip install groq

GROQ (OPTIONAL)
---------------
For cloud chat, create a Groq API key and set it on the FastAPI host:

    $env:GROQ_API_KEY = "gsk_your_key_here"       # PowerShell, current terminal

The dashboard can also send a key for the current browser session. Keys are
never saved in the CodeGuru database. For a deployed app, use GROQ_API_KEY on
the backend instead of sharing a key with browser users.

OCR EXTRA REQUIREMENT ON WINDOWS
---------------------------------
pytesseract is only the Python wrapper. You also need the Tesseract
OCR program installed on Windows.

After installing Tesseract, set:
    TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe

If Tesseract is already in PATH, no environment variable is needed.

RUN
---
    python codeguru_backend.py

or:

    uvicorn codeguru_backend:app --host 0.0.0.0 --port 8000 --reload

API
---
GET    /api/health
GET    /api/models
POST   /api/chat/new
POST   /api/chat
GET    /api/chats
GET    /api/chats/{session_id}
DELETE /api/chats/{session_id}
DELETE /api/chats
POST   /api/upload/{session_id}
GET    /api/files/{session_id}

CHAT REQUEST EXAMPLE
--------------------
{
    "session_id": "uuid-from-/api/chat/new",
    "message": "Explain this PDF",
    "model": "qwen3:8b",
    "feature": "chat"
}

feature can be:
    chat, debug, explain, quiz, notes, image, video

IMPORTANT FRONTEND FLOW
-----------------------
1. User clicks New Chat
2. Frontend calls POST /api/chat/new
3. Backend returns a NEW session_id
4. Frontend stores that session_id for the active chat
5. Every message uses that same session_id
6. Uploaded files are also attached to that session_id
7. RAG only searches documents belonging to that session
8. When user clicks New Chat again, a new UUID is created
9. Previous history remains isolated and available in Recent Chats

This gives every chat its own:
    session_id
    message history
    uploaded documents
    RAG context
    selected model
"""

from __future__ import annotations

import csv
import io
import json
import mimetypes
import os
import re
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# LangChain / Ollama
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# File readers
from pypdf import PdfReader
import pymupdf as fitz
from PIL import Image

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None


# ============================================================
# CONFIG
# ============================================================

APP_NAME = "CodeGuru"
HOST = os.getenv("CODEGURU_HOST", "0.0.0.0")
PORT = int(os.getenv("CODEGURU_PORT", "8000"))
PROJECT_DIR = Path(__file__).resolve().parent

# This remains server-only: do not return it from any API response.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_API_TOKEN = os.getenv("OLLAMA_API_TOKEN", "").strip()
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120"))

# Keep runtime files outside the frontend project. VS Code Live Server watches
# the project directory and would otherwise reload the dashboard whenever a
# chat updates SQLite or a user uploads a file.
# Vercel functions have a read-only deployment filesystem. Its only writable
# location is /tmp, so keep transient serverless data there at import time.
if os.getenv("VERCEL"):
    DEFAULT_DATA_DIR = Path("/tmp") / "codeguru"
else:
    DEFAULT_DATA_DIR = (
        Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        / "CodeGuru"
    )
DATA_DIR = Path(os.getenv("CODEGURU_DATA_DIR", str(DEFAULT_DATA_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.getenv("CODEGURU_DB", str(DATA_DIR / "codeguru_history.db")))
CHROMA_PATH = Path(os.getenv("CODEGURU_CHROMA", str(DATA_DIR / "codeguru_chroma")))
UPLOAD_DIR = Path(os.getenv("CODEGURU_UPLOADS", str(DATA_DIR / "codeguru_uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CHROMA_PATH.mkdir(parents=True, exist_ok=True)

TESSERACT_CMD = os.getenv("TESSERACT_CMD")
if TESSERACT_CMD and pytesseract is not None:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


# These are the three LOCAL Ollama models used by CodeGuru.
# Users only need to download the ones their PC can handle.
LOCAL_MODELS: Dict[str, Dict[str, str]] = {
    "qwen3:8b": {
        "label": "Qwen3 8B",
        "description": "Best overall choice for CodeGuru: coding, reasoning and explanations.",
    },
    "llama3.1:8b": {
        "label": "Llama 3.1 8B",
        "description": "Balanced general chat and coding model.",
    },
    "gemma3:4b": {
        "label": "Gemma 3 4B",
        "description": "Low-end PC option with lower memory requirements.",
    },
}

GROQ_MODELS: Dict[str, Dict[str, str]] = {
    "openai/gpt-oss-20b": {
        "label": "GPT-OSS 20B",
        "description": "Fast Groq model for everyday coding and explanations.",
    },
    "qwen/qwen3.8-27b": {
        "label": "Qwen3.8 27B",
        "description": "Groq preview model for stronger reasoning and code.",
    },
}

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

EMBEDDING_MODEL = os.getenv("CODEGURU_EMBEDDING_MODEL", "nomic-embed-text")

# RAG settings
CHUNK_SIZE = 900
CHUNK_OVERLAP = 150
TOP_K = 5

# Keep recent conversation context small enough for local models.
HISTORY_LIMIT = 12

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".css",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".java",
    ".xml",
    ".sql",
    ".docx",
    ".pptx",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tiff",
}


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="CodeGuru API",
    version="1.0.0",
    description="Local AI + RAG backend for CodeGuru",
)

# Serve the existing static frontend from the same Vercel deployment. Only the
# public assets directory is mounted; individual root-level files are allowlisted
# below to avoid exposing Python code or local data files.
app.mount(
    "/assets",
    StaticFiles(directory=str(PROJECT_DIR / "assets")),
    name="assets",
)

# In production set ALLOWED_ORIGINS to the exact Vercel site origin(s). The
# legacy variable is retained for existing deployments during migration.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        os.getenv(
            "CODEGURU_ALLOWED_ORIGINS",
            "http://localhost:5500,http://127.0.0.1:5500,"
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:3000,http://127.0.0.1:3000",
        ),
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# SQLITE DATABASE
# ============================================================

def db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            model TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'ollama',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            feature TEXT NOT NULL DEFAULT 'chat',
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(session_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            file_type TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(session_id)
        )
        """
    )

    # Upgrade databases created before provider support was added.
    session_columns = {
        row["name"]
        for row in cur.execute("PRAGMA table_info(sessions)").fetchall()
    }
    if "provider" not in session_columns:
        cur.execute(
            "ALTER TABLE sessions ADD COLUMN provider TEXT NOT NULL DEFAULT 'ollama'"
        )

    conn.commit()
    conn.close()


init_db()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# PYDANTIC SCHEMAS
# ============================================================

class NewChatRequest(BaseModel):
    model: str = Field(default="qwen3:8b", min_length=1, max_length=128)
    provider: str = Field(default="ollama", max_length=32)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=36, max_length=36)
    message: str = Field(min_length=1, max_length=20_000)
    model: Optional[str] = Field(default=None, min_length=1, max_length=128)
    provider: Optional[str] = Field(default=None, max_length=32)
    api_key: Optional[str] = Field(default=None, max_length=512)
    feature: str = "chat"


# ============================================================
# MODEL / EMBEDDING CACHE
# ============================================================

_chat_models: Dict[str, ChatOllama] = {}
_embedding_model: Optional[OllamaEmbeddings] = None


def validate_provider(provider: str) -> str:
    normalized = (provider or "ollama").lower().strip()
    if normalized not in {"ollama", "groq"}:
        raise HTTPException(
            status_code=400,
            detail="Provider must be either 'ollama' or 'groq'.",
        )
    return normalized


def validate_model(model_name: str, provider: str) -> str:
    provider = validate_provider(provider)
    model_name = model_name.strip()
    # Permit names returned by /api/tags but reject values that could be used
    # as malformed upstream payloads or log injection.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model_name):
        raise HTTPException(status_code=400, detail="Invalid model name.")
    if provider == "ollama":
        return model_name
    available_models = (
        GROQ_MODELS
    )

    if model_name not in available_models:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Unsupported {provider} model",
                "available_models": list(available_models.keys()),
            },
        )
    return model_name


def ollama_headers() -> Dict[str, str]:
    """Return server-only tunnel headers without exposing them to clients."""
    headers = {"ngrok-skip-browser-warning": "1"}
    if OLLAMA_API_TOKEN:
        headers["Authorization"] = f"Bearer {OLLAMA_API_TOKEN}"
    return headers


def local_ollama_error() -> HTTPException:
    return HTTPException(status_code=503, detail="Local Ollama is offline. Choose another configured model and try again.")


async def ollama_model_names() -> List[str]:
    """Fetch model names from Ollama's tags API using the tunnel credentials."""
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags", headers=ollama_headers())
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise local_ollama_error() from exc
    return [item["name"] for item in payload.get("models", []) if isinstance(item.get("name"), str)]


async def stream_ollama_chat(model: str, prompt: str) -> AsyncIterator[str]:
    """Proxy Ollama NDJSON incrementally, yielding only generated text tokens."""
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": True}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(OLLAMA_TIMEOUT)) as client:
            async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/chat", headers=ollama_headers(), json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    if event.get("error"):
                        raise RuntimeError(str(event["error"]))
                    token = event.get("message", {}).get("content", "")
                    if isinstance(token, str) and token:
                        yield token
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        # A response may already have started, so this cannot be converted to a
        # JSON 503 at that point. Connection failures are preflighted below.
        raise local_ollama_error() from exc


def get_chat_model(model_name: str) -> ChatOllama:
    model_name = validate_model(model_name, "ollama")

    if model_name not in _chat_models:
        _chat_models[model_name] = ChatOllama(
            model=model_name,
            base_url=OLLAMA_BASE_URL,
            temperature=0.2,
        )

    return _chat_models[model_name]


def get_groq_response(
    model_name: str,
    prompt: str,
    request_api_key: Optional[str] = None,
) -> str:
    model_name = validate_model(model_name, "groq")
    api_key = (request_api_key or GROQ_API_KEY).strip()

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "Groq API key is missing. Set GROQ_API_KEY on the backend "
                "or enter your own Groq key in CodeGuru API Mode."
            ),
        )

    try:
        from groq import Groq
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Groq support is not installed. Run: "
                "python -m pip install -r requirements.txt"
            ),
        ) from exc

    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        response_text = completion.choices[0].message.content
        if not response_text:
            raise RuntimeError("Groq returned an empty response.")
        return response_text
    except HTTPException:
        raise
    except Exception as exc:
        error_text = str(exc)
        if "api_key" in error_text.lower() or "authentication" in error_text.lower():
            message = "Groq rejected the API key. Check GROQ_API_KEY and try again."
        elif "model" in error_text.lower() and "not" in error_text.lower():
            message = f"Groq model '{model_name}' is not available for this account."
        else:
            message = f"Groq request failed: {error_text}"
        raise HTTPException(status_code=503, detail=message) from exc


def get_embedding_model() -> OllamaEmbeddings:
    global _embedding_model

    if _embedding_model is None:
        _embedding_model = OllamaEmbeddings(
            model=EMBEDDING_MODEL,
            base_url=OLLAMA_BASE_URL,
            # Embeddings go through the same tunnel as chat, so they need the
            # same server-only headers and a timeout that ends before Vercel's.
            client_kwargs={
                "headers": ollama_headers(),
                "timeout": OLLAMA_TIMEOUT,
            },
        )

    return _embedding_model


def get_vector_store() -> Chroma:
    return Chroma(
        collection_name="codeguru_documents",
        embedding_function=get_embedding_model(),
        persist_directory=str(CHROMA_PATH),
    )


# ============================================================
# DATABASE HELPERS
# ============================================================

def session_exists(session_id: str) -> bool:
    conn = db_connection()
    row = conn.execute(
        "SELECT session_id FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    return row is not None


def session_has_files(session_id: str) -> bool:
    conn = db_connection()
    row = conn.execute(
        "SELECT 1 FROM files WHERE session_id = ? LIMIT 1",
        (session_id,),
    ).fetchone()
    conn.close()
    return row is not None


def create_session(model: str, provider: str = "ollama") -> Dict[str, Any]:
    provider = validate_provider(provider)
    model = validate_model(model, provider)

    session_id = str(uuid.uuid4())
    timestamp = now_iso()

    conn = db_connection()
    conn.execute(
        """
        INSERT INTO sessions
        (session_id, title, model, provider, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            "New chat",
            model,
            provider,
            timestamp,
            timestamp,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "session_id": session_id,
        "title": "New chat",
        "model": model,
        "provider": provider,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    conn = db_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()

    return dict(row) if row else None


def update_session(
    session_id: str,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    title: Optional[str] = None,
) -> None:
    current = get_session(session_id)
    if current is None:
        return

    new_model = model or current["model"]
    new_provider = provider or current.get("provider", "ollama")
    new_title = title or current["title"]

    conn = db_connection()
    conn.execute(
        """
        UPDATE sessions
        SET model = ?, provider = ?, title = ?, updated_at = ?
        WHERE session_id = ?
        """,
        (
            new_model,
            new_provider,
            new_title,
            now_iso(),
            session_id,
        ),
    )
    conn.commit()
    conn.close()


def save_message(
    session_id: str,
    role: str,
    content: str,
    feature: str = "chat",
) -> None:
    conn = db_connection()
    conn.execute(
        """
        INSERT INTO messages
        (session_id, role, content, feature, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            session_id,
            role,
            content,
            feature,
            now_iso(),
        ),
    )
    conn.commit()
    conn.close()


def get_messages(
    session_id: str,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    conn = db_connection()

    if limit:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content, feature, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        rows = list(reversed(rows))
    else:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content, feature, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        ).fetchall()

    conn.close()
    return [dict(row) for row in rows]


def make_title(message: str) -> str:
    clean = re.sub(r"\s+", " ", message).strip()
    if len(clean) <= 42:
        return clean
    return clean[:42].rstrip() + "..."


# ============================================================
# FILE EXTRACTION
# ============================================================

def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def ocr_image(path: Path) -> str:
    if pytesseract is None:
        raise RuntimeError(
            "pytesseract is not installed. Install it with: pip install pytesseract"
        )

    image = Image.open(path)
    text = pytesseract.image_to_string(image)
    return clean_text(text)


def extract_pdf(path: Path) -> str:
    # First try normal PDF text extraction.
    extracted_pages: List[str] = []

    try:
        reader = PdfReader(str(path))
        for page in reader.pages:
            text = page.extract_text() or ""
            extracted_pages.append(text.strip())
    except Exception:
        extracted_pages = []

    normal_text = "\n\n".join(
        page for page in extracted_pages if page
    ).strip()

    # If text extraction found enough text, use it.
    if len(normal_text) >= 50:
        return clean_text(normal_text)

    # OCR fallback for scanned/image-only PDFs.
    if pytesseract is None:
        return clean_text(normal_text)

    ocr_pages: List[str] = []

    try:
        document = fitz.open(str(path))

        for page in document:
            pix = page.get_pixmap(
                matrix=fitz.Matrix(2, 2),
                alpha=False,
            )

            image_bytes = pix.tobytes("png")
            image = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(image)

            if text.strip():
                ocr_pages.append(text.strip())

        document.close()

    except Exception:
        return clean_text(normal_text)

    return clean_text(
        "\n\n".join(ocr_pages)
        if ocr_pages
        else normal_text
    )


def extract_docx(path: Path) -> str:
    if DocxDocument is None:
        raise RuntimeError("python-docx is not installed.")

    document = DocxDocument(str(path))
    parts: List[str] = []

    for paragraph in document.paragraphs:
        if paragraph.text.strip():
            parts.append(paragraph.text)

    for table in document.tables:
        for row in table.rows:
            parts.append(
                " | ".join(cell.text.strip() for cell in row.cells)
            )

    return clean_text("\n".join(parts))


def extract_pptx(path: Path) -> str:
    if Presentation is None:
        raise RuntimeError("python-pptx is not installed.")

    presentation = Presentation(str(path))
    parts: List[str] = []

    for slide_number, slide in enumerate(
        presentation.slides,
        start=1,
    ):
        parts.append(f"[Slide {slide_number}]")

        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                parts.append(shape.text)

    return clean_text("\n".join(parts))


def extract_xlsx(path: Path) -> str:
    if load_workbook is None:
        raise RuntimeError("openpyxl is not installed.")

    workbook = load_workbook(
        filename=str(path),
        read_only=True,
        data_only=True,
    )

    parts: List[str] = []

    for worksheet in workbook.worksheets:
        parts.append(f"[Sheet: {worksheet.title}]")

        for row in worksheet.iter_rows(values_only=True):
            values = [
                str(value)
                for value in row
                if value is not None
            ]

            if values:
                parts.append(" | ".join(values))

    return clean_text("\n".join(parts))


def extract_csv(path: Path) -> str:
    with path.open(
        "r",
        encoding="utf-8",
        errors="ignore",
        newline="",
    ) as handle:
        reader = csv.reader(handle)
        return clean_text(
            "\n".join(
                " | ".join(row)
                for row in reader
            )
        )


def extract_file(path: Path) -> str:
    extension = path.suffix.lower()

    if extension == ".pdf":
        return extract_pdf(path)

    if extension in {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".tiff",
    }:
        return ocr_image(path)

    if extension == ".docx":
        return extract_docx(path)

    if extension == ".pptx":
        return extract_pptx(path)

    if extension == ".xlsx":
        return extract_xlsx(path)

    if extension == ".csv":
        return extract_csv(path)

    if extension == ".json":
        raw = path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
        try:
            data = json.loads(raw)
            return clean_text(
                json.dumps(
                    data,
                    indent=2,
                    ensure_ascii=False,
                )
            )
        except Exception:
            return clean_text(raw)

    # Source code, markdown, txt, html, css, etc.
    return clean_text(
        path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
    )


# ============================================================
# RAG
# ============================================================

def make_chunks(
    text: str,
    filename: str,
    session_id: str,
) -> List[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=[
            "\n\n",
            "\n",
            " ",
            "",
        ],
    )

    chunks = splitter.split_text(text)

    documents: List[Document] = []

    for index, chunk in enumerate(chunks):
        if not chunk.strip():
            continue

        documents.append(
            Document(
                page_content=chunk,
                metadata={
                    "session_id": session_id,
                    "filename": filename,
                    "chunk_index": index,
                },
            )
        )

    return documents


def add_to_rag(
    session_id: str,
    filename: str,
    text: str,
) -> int:
    documents = make_chunks(
        text=text,
        filename=filename,
        session_id=session_id,
    )

    if not documents:
        return 0

    vector_store = get_vector_store()

    ids = [
        f"{session_id}_{uuid.uuid4()}"
        for _ in documents
    ]

    vector_store.add_documents(
        documents=documents,
        ids=ids,
    )

    return len(documents)


def search_rag(
    session_id: str,
    question: str,
    top_k: int = TOP_K,
) -> List[Document]:
    vector_store = get_vector_store()

    try:
        return vector_store.similarity_search(
            question,
            k=top_k,
            filter={
                "session_id": session_id,
            },
        )
    except Exception:
        return []


def format_rag_context(
    documents: List[Document],
) -> str:
    if not documents:
        return ""

    parts: List[str] = []

    for index, document in enumerate(documents, start=1):
        filename = document.metadata.get(
            "filename",
            "unknown",
        )

        parts.append(
            f"[Document {index} - {filename}]\n"
            f"{document.page_content}"
        )

    return "\n\n".join(parts)


# ============================================================
# PROMPTS / FEATURES
# ============================================================

FEATURE_INSTRUCTIONS = {
    "chat": """
Answer the user's question clearly and accurately.
If uploaded-document context is provided, use it when relevant.
Do not invent information that is not supported by the context.
""",
    "debug": """
Act as a senior programming mentor.
Analyze the supplied code/problem, identify the error,
explain why it happens, provide corrected code, and explain
the fix step-by-step.
""",
    "explain": """
Teach the topic like a patient computer-science instructor.
Start with a simple explanation, then go deeper, and include
a practical example where useful.
""",
    "quiz": """
Create a useful quiz based on the user's topic and any
uploaded documents. Include questions first and then provide
answers/explanations clearly.
""",
    "notes": """
Turn the relevant information into clean study notes.
Use headings, bullet points, key definitions, examples,
important formulas/complexities when applicable, and a short
quick-revision section.
""",
    "image": """
The frontend's Image feature should use this response as an
image-generation prompt/specification. Do not pretend that
this text response itself is an image. Describe the requested
visual clearly, including layout, labels and educational details.
""",
    "video": """
Create a complete educational video script/storyboard for the
requested topic. Include narration, scene-by-scene visuals,
code/diagrams to show, and approximate timing. This backend
returns the script; actual MP4 rendering can be connected later
using a video renderer such as Manim/FFmpeg.
""",
}


def build_system_prompt(feature: str) -> str:
    feature = feature.lower().strip()

    instruction = FEATURE_INSTRUCTIONS.get(
        feature,
        FEATURE_INSTRUCTIONS["chat"],
    )

    return f"""
You are CodeGuru, an AI coding and learning assistant.

{instruction}

Rules:
- Be precise.
- Prefer readable explanations.
- Use clean, natural sentences for normal conversation. Use simple headings,
  bullets, or code blocks only when they make a technical answer clearer.
- When writing code, use correct syntax.
- If you do not know something, say so.
- When document context is provided, distinguish the document's
  information from general knowledge.
- Never claim to have read a file if no file context was supplied.
"""


def convert_history_to_messages(
    messages: List[Dict[str, Any]],
) -> List[Any]:
    converted: List[Any] = []

    for message in messages:
        if message["role"] == "user":
            converted.append(
                HumanMessage(
                    content=message["content"],
                )
            )

        elif message["role"] == "assistant":
            converted.append(
                AIMessage(
                    content=message["content"],
                )
            )

    return converted


def build_prompt(
    system_prompt: str,
    history: List[Dict[str, Any]],
    question: str,
    rag_context: str,
) -> str:
    history_text = ""

    for message in history:
        role = message["role"].upper()
        content = message["content"]

        history_text += (
            f"\n{role}:\n{content}\n"
        )

    if rag_context:
        context_section = f"""
UPLOADED FILE CONTEXT:
----------------------
{rag_context}
----------------------

Use the uploaded context when it is relevant to the user's
question. If the answer cannot be found in the uploaded
documents, say that clearly rather than inventing a citation.
"""
    else:
        context_section = """
No uploaded-document context is available for this request.
"""

    return f"""
{system_prompt}

CONVERSATION HISTORY:
{history_text}

{context_section}

CURRENT USER REQUEST:
{question}

CODEGURU RESPONSE:
"""


# ============================================================
# API ROUTES - GENERAL
# ============================================================

FIREBASE_CONFIG_ENVIRONMENT_NAMES: Dict[str, tuple[str, str]] = {
    "apiKey": ("FIREBASE_API_KEY", "VITE_FIREBASE_API_KEY"),
    "authDomain": ("FIREBASE_AUTH_DOMAIN", "VITE_FIREBASE_AUTH_DOMAIN"),
    "projectId": ("FIREBASE_PROJECT_ID", "VITE_FIREBASE_PROJECT_ID"),
    "storageBucket": ("FIREBASE_STORAGE_BUCKET", "VITE_FIREBASE_STORAGE_BUCKET"),
    "messagingSenderId": (
        "FIREBASE_MESSAGING_SENDER_ID",
        "VITE_FIREBASE_MESSAGING_SENDER_ID",
    ),
    "appId": ("FIREBASE_APP_ID", "VITE_FIREBASE_APP_ID"),
    "measurementId": ("FIREBASE_MEASUREMENT_ID", "VITE_FIREBASE_MEASUREMENT_ID"),
}


@app.get("/api/firebase-config", include_in_schema=False)
def firebase_web_config() -> JSONResponse:
    """Return the public Firebase web configuration from runtime environment.

    The Firebase Web API key identifies the Firebase project and is necessarily
    visible to a browser client. Keep authorization in Firebase Auth, Security
    Rules and App Check; never return private service-account credentials here.
    Both FIREBASE_* and existing VITE_FIREBASE_* Vercel variable names work.
    """
    config = {
        field: next(
            (os.getenv(name, "").strip() for name in names if os.getenv(name, "").strip()),
            "",
        )
        for field, names in FIREBASE_CONFIG_ENVIRONMENT_NAMES.items()
    }
    missing = [field for field, value in config.items() if not value]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=(
                "Firebase is not configured on this deployment. Add these Vercel "
                "environment variables and redeploy: "
                + ", ".join(FIREBASE_CONFIG_ENVIRONMENT_NAMES[field][0] for field in missing)
            ),
        )

    return JSONResponse(config, headers={"Cache-Control": "no-store"})

@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": APP_NAME,
        "embedding_model": EMBEDDING_MODEL,
        "groq_models": list(GROQ_MODELS.keys()),
        "groq_configured": bool(GROQ_API_KEY),
    }


@app.get("/api/ollama/health")
async def ollama_health() -> Dict[str, Any]:
    """Report tunnel reachability without revealing its URL or credentials."""
    try:
        model_names = await ollama_model_names()
    except HTTPException:
        return {"reachable": False, "status": "offline"}
    return {"reachable": True, "status": "ok", "model_count": len(model_names)}


@app.get("/api/ollama/models")
async def ollama_models() -> Dict[str, Any]:
    """Return models currently exposed by the private Ollama tunnel."""
    return {"models": await ollama_model_names()}


@app.get("/api/models")
async def models(provider: str = "ollama") -> Dict[str, Any]:
    provider = validate_provider(provider)

    if provider == "groq":
        return {
            "provider": "groq",
            "configured": bool(GROQ_API_KEY),
            "models": [
                {"id": model_id, "installed": True, **details}
                for model_id, details in GROQ_MODELS.items()
            ],
        }

    try:
        installed = await ollama_model_names()
    except HTTPException:
        # Keep existing local choices visible when the tunnel is unavailable.
        installed = []

    return {
        "provider": "ollama",
        "models": [
            {
                "id": model_id,
                "label": model_id,
                "description": "Available from the configured Ollama instance.",
                "installed": True,
            }
            for model_id in installed
        ],
        "embedding_model": EMBEDDING_MODEL,
    }


# ============================================================
# API ROUTES - CHAT SESSIONS
# ============================================================

@app.post("/api/chat/new")
def new_chat(request: NewChatRequest) -> Dict[str, Any]:
    """
    Create a completely separate chat session.

    Every click on "New chat" should call this endpoint.
    """
    return create_session(request.model, request.provider)


@app.get("/api/chats")
def recent_chats() -> Dict[str, Any]:
    """
    Used by the left sidebar "Recent Chats".
    """
    conn = db_connection()

    rows = conn.execute(
        """
        SELECT
            s.session_id,
            s.title,
            s.model,
            s.provider,
            s.created_at,
            s.updated_at,
            (
                SELECT content
                FROM messages m
                WHERE m.session_id = s.session_id
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_message
        FROM sessions s
        ORDER BY s.updated_at DESC
        """
    ).fetchall()

    conn.close()

    return {
        "chats": [dict(row) for row in rows],
    }


@app.get("/api/chats/{session_id}")
def chat_history(session_id: str) -> Dict[str, Any]:
    session = get_session(session_id)

    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Chat session not found.",
        )

    return {
        "session": session,
        "messages": get_messages(session_id),
    }


@app.delete("/api/chats/{session_id}")
def delete_chat(session_id: str) -> Dict[str, Any]:
    if not session_exists(session_id):
        raise HTTPException(
            status_code=404,
            detail="Chat session not found.",
        )

    # Delete RAG vectors belonging to this session.
    try:
        vector_store = get_vector_store()
        existing = vector_store.get(
            where={"session_id": session_id}
        )

        ids = existing.get("ids", [])

        if ids:
            vector_store.delete(ids=ids)
    except Exception:
        pass

    conn = db_connection()

    conn.execute(
        "DELETE FROM messages WHERE session_id = ?",
        (session_id,),
    )

    conn.execute(
        "DELETE FROM files WHERE session_id = ?",
        (session_id,),
    )

    conn.execute(
        "DELETE FROM sessions WHERE session_id = ?",
        (session_id,),
    )

    conn.commit()
    conn.close()

    # Delete physical uploaded files.
    session_dir = UPLOAD_DIR / session_id

    if session_dir.exists():
        for item in session_dir.iterdir():
            if item.is_file():
                try:
                    item.unlink()
                except Exception:
                    pass

        try:
            session_dir.rmdir()
        except Exception:
            pass

    return {
        "success": True,
        "session_id": session_id,
    }


@app.delete("/api/chats")
def clear_all_chats() -> Dict[str, Any]:
    """
    Used by the sidebar "Clear" button.
    """
    conn = db_connection()

    session_rows = conn.execute(
        "SELECT session_id FROM sessions"
    ).fetchall()

    session_ids = [
        row["session_id"]
        for row in session_rows
    ]

    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM files")
    conn.execute("DELETE FROM sessions")

    conn.commit()
    conn.close()

    # Delete all RAG vectors.
    try:
        vector_store = get_vector_store()

        all_data = vector_store.get()
        ids = all_data.get("ids", [])

        if ids:
            vector_store.delete(ids=ids)
    except Exception:
        pass

    # Delete uploads.
    for session_id in session_ids:
        session_dir = UPLOAD_DIR / session_id

        if session_dir.exists():
            for item in session_dir.iterdir():
                if item.is_file():
                    try:
                        item.unlink()
                    except Exception:
                        pass

            try:
                session_dir.rmdir()
            except Exception:
                pass

    return {
        "success": True,
        "deleted_sessions": len(session_ids),
    }


# ============================================================
# API ROUTES - FILE UPLOAD / RAG
# ============================================================

@app.post("/api/upload/{session_id}")
async def upload_file(
    session_id: str,
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    if not session_exists(session_id):
        raise HTTPException(
            status_code=404,
            detail="Chat session not found. Create a chat first.",
        )

    original_name = Path(file.filename or "uploaded_file")
    extension = original_name.suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Unsupported file type.",
                "supported_extensions": sorted(
                    ALLOWED_EXTENSIONS
                ),
            },
        )

    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    safe_name = re.sub(
        r"[^a-zA-Z0-9._-]",
        "_",
        original_name.name,
    )

    stored_name = (
        f"{uuid.uuid4().hex}_{safe_name}"
    )

    stored_path = session_dir / stored_name

    try:
        content = await file.read()

        # Basic safety limit: 25 MB.
        if len(content) > 25 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail="File is too large. Maximum size is 25 MB.",
            )

        stored_path.write_bytes(content)

        extracted_text = extract_file(stored_path)

        if not extracted_text.strip():
            raise HTTPException(
                status_code=400,
                detail=(
                    "No readable text was found in this file. "
                    "For images/scanned PDFs, make sure Tesseract OCR "
                    "is installed."
                ),
            )

        try:
            chunk_count = add_to_rag(
                session_id=session_id,
                filename=original_name.name,
                text=extracted_text,
            )
        except Exception as exc:
            # Indexing needs the Ollama embedding model. Keep the server-only
            # Ollama URL out of the message that is returned to the browser.
            reason = str(exc).replace(OLLAMA_BASE_URL, "[Ollama URL]")
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Could not index this file with the '{EMBEDDING_MODEL}' "
                    "embedding model. Check that OLLAMA_BASE_URL points to a "
                    "running Ollama server that has this model installed "
                    f"(ollama pull {EMBEDDING_MODEL}). Details: {reason}"
                ),
            ) from exc

        conn = db_connection()

        conn.execute(
            """
            INSERT INTO files
            (session_id, filename, stored_path, file_type, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                original_name.name,
                str(stored_path),
                file.content_type or mimetypes.guess_type(
                    original_name.name
                )[0],
                now_iso(),
            ),
        )

        conn.commit()
        conn.close()

        return {
            "success": True,
            "session_id": session_id,
            "filename": original_name.name,
            "chunks_created": chunk_count,
            "characters_extracted": len(extracted_text),
            "rag_ready": True,
        }

    except HTTPException:
        try:
            stored_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    except Exception as exc:
        try:
            stored_path.unlink(missing_ok=True)
        except Exception:
            pass

        raise HTTPException(
            status_code=500,
            detail=f"Could not process file: {exc}",
        )


@app.get("/api/files/{session_id}")
def list_files(session_id: str) -> Dict[str, Any]:
    if not session_exists(session_id):
        raise HTTPException(
            status_code=404,
            detail="Chat session not found.",
        )

    conn = db_connection()

    rows = conn.execute(
        """
        SELECT id, filename, file_type, created_at
        FROM files
        WHERE session_id = ?
        ORDER BY id ASC
        """,
        (session_id,),
    ).fetchall()

    conn.close()

    return {
        "session_id": session_id,
        "files": [dict(row) for row in rows],
    }


# ============================================================
# API ROUTES - CHAT
# ============================================================

@app.post("/api/chat")
async def chat(request: ChatRequest) -> Any:
    """
    Main endpoint used by the CodeGuru message box.

    Important:
    The RAG search is filtered by session_id, so a new chat
    cannot accidentally retrieve documents from another chat.
    """

    if not session_exists(request.session_id):
        raise HTTPException(
            status_code=404,
            detail="Chat session not found. Call /api/chat/new first.",
        )

    feature = request.feature.lower().strip()

    if feature not in FEATURE_INSTRUCTIONS:
        feature = "chat"

    session = get_session(request.session_id)

    provider_name = validate_provider(
        request.provider or session.get("provider", "ollama")
    )
    model_name = request.model or session["model"]
    model_name = validate_model(model_name, provider_name)

    # Store the selected model for this particular chat.
    update_session(
        request.session_id,
        model=model_name,
        provider=provider_name,
    )

    # Retrieve recent history BEFORE saving current message.
    history = get_messages(
        request.session_id,
        limit=HISTORY_LIMIT,
    )

    # Search only this session's uploaded documents.
    # Groq can answer ordinary chats without Ollama. Ollama embeddings are
    # needed only after a file has been uploaded for this session's RAG store.
    rag_documents: List[Document] = []
    if session_has_files(request.session_id):
        rag_documents = search_rag(
            request.session_id,
            request.message,
            top_k=TOP_K,
        )

    rag_context = format_rag_context(
        rag_documents
    )

    system_prompt = build_system_prompt(feature)

    prompt = build_prompt(
        system_prompt=system_prompt,
        history=history,
        question=request.message,
        rag_context=rag_context,
    )

    try:
        if provider_name == "groq":
            response_text = get_groq_response(
                model_name,
                prompt,
                request.api_key,
            )
        else:
            # Fail before starting the HTTP stream so a disconnected tunnel is
            # returned as a clear JSON 503 rather than a partial response.
            available_models = await ollama_model_names()
            if model_name not in available_models:
                raise HTTPException(
                    status_code=400,
                    detail=f"Ollama model '{model_name}' is not available.",
                )

            async def token_stream() -> AsyncIterator[str]:
                tokens: List[str] = []
                try:
                    async for token in stream_ollama_chat(model_name, prompt):
                        tokens.append(token)
                        yield token
                finally:
                    # Persist only completed text; this preserves the existing
                    # history behavior while allowing the browser to render it.
                    response_text = "".join(tokens)
                    if response_text:
                        save_message(request.session_id, "user", request.message, feature)
                        save_message(request.session_id, "assistant", response_text, feature)
                        if session["title"] == "New chat":
                            update_session(request.session_id, title=make_title(request.message))
                        else:
                            update_session(request.session_id)

            return StreamingResponse(
                token_stream(),
                media_type="text/plain; charset=utf-8",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        error_text = str(exc)

        if isinstance(exc, (httpx.HTTPError, TimeoutError)):
            message = "Local Ollama is offline. Choose another configured model and try again."
        elif "not found" in error_text.lower():
            message = (
                f"Ollama model '{model_name}' was not found. "
                f"Run: ollama pull {model_name}"
            )
        else:
            message = f"Ollama error: {error_text}"

        raise HTTPException(
            status_code=503,
            detail=message,
        )

    # Groq remains non-streaming and retains the existing API-key integration.
    save_message(
        request.session_id,
        "user",
        request.message,
        feature,
    )

    save_message(
        request.session_id,
        "assistant",
        response_text,
        feature,
    )

    # Rename "New chat" after first user message.
    if session["title"] == "New chat":
        update_session(
            request.session_id,
            title=make_title(request.message),
        )
    else:
        update_session(request.session_id)

    return {
        "success": True,
        "session_id": request.session_id,
        "provider": provider_name,
        "model": model_name,
        "feature": feature,
        "response": response_text,
        "rag_used": bool(rag_documents),
        "sources": [
            {
                "filename": doc.metadata.get(
                    "filename",
                    "unknown",
                ),
                "chunk_index": doc.metadata.get(
                    "chunk_index"
                ),
            }
            for doc in rag_documents
        ],
    }


# ============================================================
# FRONTEND ROUTES
# ============================================================

FRONTEND_ROUTES = {
    "index": "index.html",
    "index.html": "index.html",
    "login": "login.html",
    "login.html": "login.html",
    "dashboard": "dashboard.html",
    "dashboard.html": "dashboard.html",
    "style.css": "style.css",
    "theme.js": "theme.js",
    "features-data.js": "features-data.js",
    "firebase-config.js": "firebase-config.js",
    "auth.js": "auth.js",
    "api-config.js": "api-config.js",
    "api.js": "api.js",
    "chat.js": "chat.js",
}


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(PROJECT_DIR / "index.html")


@app.get("/{filename}", include_in_schema=False)
def frontend_file(filename: str) -> FileResponse:
    frontend_file_name = FRONTEND_ROUTES.get(filename)
    if not frontend_file_name:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(PROJECT_DIR / frontend_file_name)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "codeguru_backend:app",
        host=HOST,
        port=PORT,
        reload=True,
    )
