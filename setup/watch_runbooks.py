import sys
import time
import logging
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from setup.seed_rag import ingest_single

RUNBOOKS_DIR = Path(__file__).resolve().parent / "runbooks"

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)


class RunbookHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not isinstance(event, FileCreatedEvent):
            return
        path = Path(event.src_path)
        if path.suffix != ".md":
            return

        log.info(f"New runbook detected: {path.name}")
        # Small delay to let the file finish writing (Windows)
        time.sleep(0.5)
        try:
            indexed = ingest_single(path)
            if indexed:
                log.info(f"[OK] {path.name} formatted, vectorized and stored in Qdrant")
            else:
                log.warning(f"[SKIP] {path.name} ignored (no remediation section)")
        except Exception as e:
            log.error(f"[ERROR] {path.name}: {e}")


def watch():
    if not RUNBOOKS_DIR.exists():
        log.error(f"Directory not found: {RUNBOOKS_DIR}")
        sys.exit(1)

    log.info(f"Watching {RUNBOOKS_DIR}")
    log.info("Waiting for new runbooks (.md)")

    handler = RunbookHandler()
    observer = Observer()
    observer.schedule(handler, str(RUNBOOKS_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Stopping watcher.")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    watch()
