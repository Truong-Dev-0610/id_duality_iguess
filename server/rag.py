"""Knowledge Base + RAG.

Kho kiến thức riêng lưu trong SQLite. Truy xuất bằng SQLite FTS5 (BM25) trên văn bản đã
bỏ dấu -> không cần dịch vụ ngoài, không tốn chi phí, chạy được cả trên gói hosting miễn phí.
Có thể thay `search()` bằng truy xuất vector (embedding) mà không phải sửa nơi gọi.
"""
import re

from .db import now_iso
from .safety import normalize

STOPWORDS = set(
    "la va cua cho toi em minh ban co khong duoc nhung nay do da dang se thi ma mot cac nhu "
    "voi trong ra vao lai nua qua rat hay gi sao the nao viec khi neu thay bi de den tu cung".split()
)
AUDIENCES = ("all", "student", "parent", "teacher")


def chunk_text(text, target=700, overlap=120):
    """Cắt theo đoạn; đoạn dài thì cắt theo câu. Có gối đầu nhẹ để giữ ngữ cảnh."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.replace("\r", "")) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(p) > target * 1.5:
            sents = re.split(r"(?<=[.!?。])\s+", p)
        else:
            sents = [p]
        for s in sents:
            if cur and len(cur) + len(s) + 1 > target:
                chunks.append(cur.strip())
                tail = cur[-overlap:] if overlap else ""
                cur = tail.split(" ", 1)[1] if " " in tail else ""   # gối đầu theo ranh giới từ
            cur += (" " if cur else "") + s
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def _tokens(text):
    return [t for t in normalize(text).split() if len(t) > 1 and t not in STOPWORDS]


def index_document(db, doc_id):
    doc = db.execute("SELECT * FROM kb_documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        return 0
    remove_chunks(db, doc_id)
    full = f"{doc['title']}\n\n{doc['content']}"
    n = 0
    for i, ch in enumerate(chunk_text(doc["content"])):
        cur = db.execute("INSERT INTO kb_chunks(doc_id,idx,text) VALUES(?,?,?)", (doc_id, i, ch))
        # tiêu đề + tags được lập chỉ mục cùng nội dung để tăng độ liên quan
        db.execute(
            "INSERT INTO kb_fts(norm,chunk_id) VALUES(?,?)",
            (normalize(f"{doc['title']} {doc['tags']} {ch}"), cur.lastrowid),
        )
        n += 1
    db.commit()
    return n


def remove_chunks(db, doc_id):
    ids = [r["id"] for r in db.execute("SELECT id FROM kb_chunks WHERE doc_id=?", (doc_id,))]
    for cid in ids:
        db.execute("DELETE FROM kb_fts WHERE chunk_id=?", (cid,))
    db.execute("DELETE FROM kb_chunks WHERE doc_id=?", (doc_id,))


def add_document(db, title, content, audience="all", tags="", source="", created_by=None):
    if audience not in AUDIENCES:
        audience = "all"
    ts = now_iso()
    cur = db.execute(
        "INSERT INTO kb_documents(title,audience,tags,source,content,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (title.strip()[:200], audience, tags.strip()[:200], source.strip()[:300], content.strip(), created_by, ts, ts),
    )
    db.commit()
    index_document(db, cur.lastrowid)
    return cur.lastrowid


def delete_document(db, doc_id):
    remove_chunks(db, doc_id)
    db.execute("DELETE FROM kb_documents WHERE id=?", (doc_id,))
    db.commit()


def _fts_query(question):
    toks = _tokens(question)[:24]
    if not toks:
        return ""
    parts = [f'"{t}"' for t in toks]
    parts += [f'"{a} {b}"' for a, b in zip(toks, toks[1:])]  # cụm 2 từ -> chính xác hơn
    return " OR ".join(parts)


def search(db, question, role="student", k=4):
    """Trả về danh sách {doc_id,title,text,score}. Tài liệu lọc theo đối tượng (audience)."""
    q = _fts_query(question)
    if not q:
        return []
    aud = ("all", role) if role in AUDIENCES else ("all",)
    if role == "admin":
        aud = AUDIENCES
    marks = ",".join("?" * len(aud))
    rows = db.execute(
        f"""SELECT c.id AS chunk_id, d.id AS doc_id, d.title, d.source, c.text, bm25(kb_fts) AS score
            FROM kb_fts
            JOIN kb_chunks c ON c.id = kb_fts.chunk_id
            JOIN kb_documents d ON d.id = c.doc_id
            WHERE kb_fts MATCH ? AND d.is_active=1 AND d.audience IN ({marks})
            ORDER BY score LIMIT ?""",
        (q, *aud, k * 3),
    ).fetchall()
    if not rows:
        return []
    best = rows[0]["score"]
    qset = set(_tokens(question))
    need = 1 if len(qset) <= 2 else 2          # tránh khớp lẻ 1 từ ngẫu nhiên
    out, seen_docs = [], {}
    for r in rows:
        if len(qset & set(_tokens(r["text"]))) < need:
            continue
        if r["score"] > best * 0.35:     # score âm: càng âm càng liên quan
            continue
        if seen_docs.get(r["doc_id"], 0) >= 2:   # tối đa 2 đoạn/tài liệu để đa dạng nguồn
            continue
        seen_docs[r["doc_id"]] = seen_docs.get(r["doc_id"], 0) + 1
        out.append({"doc_id": r["doc_id"], "title": r["title"], "text": r["text"], "score": r["score"]})
        if len(out) >= k:
            break
    return out


def format_context(hits):
    if not hits:
        return ""
    body = "\n\n".join(f'[{i}] ({h["title"]})\n{h["text"]}' for i, h in enumerate(hits, 1))
    return f"<tai_lieu>\n{body}\n</tai_lieu>"


def parse_seed_file(text):
    """Định dạng: khối '---' đầu file chứa title/audience/tags, phần sau là nội dung."""
    meta, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = m.group(2)
    return meta, body.strip()


def seed_from_dir(db, directory):
    from pathlib import Path
    added = 0
    for f in sorted(Path(directory).glob("*.md")):
        meta, body = parse_seed_file(f.read_text(encoding="utf-8"))
        title = meta.get("title") or f.stem
        if db.execute("SELECT 1 FROM kb_documents WHERE title=?", (title,)).fetchone():
            continue
        add_document(db, title, body, meta.get("audience", "all"), meta.get("tags", ""), f"seed/{f.name}")
        added += 1
    return added
