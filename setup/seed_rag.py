from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from langchain_ollama import OllamaEmbeddings
import os
import re
import uuid
import yaml
from dotenv import load_dotenv

load_dotenv(override=True)

client = QdrantClient(url=os.getenv("QDRANT_URL"))
embeddings = OllamaEmbeddings(model=os.getenv("OLLAMA_EMBED_MODEL"))

RUNBOOKS_DIR = Path(__file__).resolve().parent / "runbooks"

_REMEDIATION_HEADERS = {
    "remediation", "remediation by cause", "resolution", "fix", "solution",
    "steps to fix", "solutions detail", "solutions list",
}
_ACTIONS_HEADERS = {"follow-up actions", "follow-up", "next steps", "post-fix actions", "after fix", "further steps"}
_CAUSES_HEADERS  = {"common causes", "causes", "root causes", "possible causes", "initial steps overview"}

_INTEGRATION_PATTERNS = {"jenkins", "ci-cd", "ci_cd", "db-", "database", "connection-pool", "locks", "artifacts"}


def _clean_text(text: str) -> str:
    text = re.sub(r"```\w*\s*\n?", " | ", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\n{2,}", " | ", text)
    text = re.sub(r"\n", " ", text)
    text = re.sub(r"\s*\|\s*", " | ", text)
    text = re.sub(r"(\|\s*){2,}", "| ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip(" |")


def _parse_frontmatter(md_text: str) -> tuple[dict, str]:
    if not md_text.startswith("---"):
        return {}, md_text
    try:
        end = md_text.index("---", 3)
        meta = yaml.safe_load(md_text[3:end].strip()) or {}
        return meta, md_text[end + 3:].lstrip()
    except (ValueError, yaml.YAMLError):
        return {}, md_text


def _infer_type_and_agent(filename: str) -> tuple[str, str]:
    name = filename.lower()
    if any(pat in name for pat in _INTEGRATION_PATTERNS):
        return ("ci-cd" if "jenkins" in name or "ci-cd" in name else "database", "Integration")
    if name.startswith("web_"):
        return ("web", "Platform")
    return ("kubernetes", "Platform")


def _extract_section(md_text: str, headers: set[str]) -> str:
    """Extract the full text of the first H1/H2 section whose title matches headers.
    Captures all content including H3 subsections until the next H1/H2."""
    in_section = False
    buffer: list[str] = []

    for line in md_text.splitlines():
        stripped = line.strip()
        if re.match(r'^#{1,2}(?!#)\s', stripped):
            if in_section:
                break
            in_section = stripped.lstrip("#").strip().lower() in headers
            continue
        if in_section and stripped != "---":
            buffer.append(line)

    return _clean_text("\n".join(buffer))


def seed() -> None:
    if not RUNBOOKS_DIR.exists():
        raise FileNotFoundError(f"Runbooks directory not found: {RUNBOOKS_DIR}")

    files = sorted(RUNBOOKS_DIR.glob("*.md"))
    if not files:
        print("No markdown runbook found.")
        return

    print(f"Seeding RAG documents from runbooks ({len(files)} files)...")
    total = 0

    for file_path in files:
        raw = file_path.read_text(encoding="utf-8", errors="ignore")
        meta, content = _parse_frontmatter(raw)

        inferred_type, inferred_agent = _infer_type_and_agent(file_path.stem)
        incident_type = meta.get("type", "") or inferred_type
        routing_agent = meta.get("agent", "") or inferred_agent
        incident_name = file_path.stem.replace("-", " ").replace("_", " ")

        causes      = _extract_section(content, _CAUSES_HEADERS)
        remediation = _extract_section(content, _REMEDIATION_HEADERS)
        actions     = _extract_section(content, _ACTIONS_HEADERS)

        if not remediation:
            print(f"  [SKIP] {file_path.name} — no remediation section found")
            continue

        # 1 point per runbook — full causes + full remediation in the embedding
        # This avoids duplicate near-identical points and gives the LLM complete context
        embedding_text = (
            f"Incident: {incident_name}. "
            f"Type: {incident_type}. "
            f"Causes: {causes[:300]}. "
            f"Remediation: {remediation[:400]}"
        )
        vector = embeddings.embed_query(embedding_text)

        payload = {
            "incident":    incident_name,
            "type":        incident_type,
            "agent":       routing_agent,
            "cause":       causes,
            "remediation": remediation,
            "actions":     actions,
        }

        point = PointStruct(id=str(uuid.uuid4()), vector=vector, payload=payload)
        client.upsert(collection_name="documents", points=[point])
        total += 1
        print(f"  [{incident_type:>10} | {routing_agent}]  {file_path.name}")

    print(f"\nRAG ready — {total} indexed points")


if __name__ == "__main__":
    seed()
