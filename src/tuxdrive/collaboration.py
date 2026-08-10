"""Local-first collaborative documents.

Collaboration metadata lives beside a shared folder in a hidden directory.  Every
operation is an immutable file, so TuxDrive's existing peer/cloud synchronizer can
replicate concurrent changes without overwriting another device's operation log.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ROOT = "ROOT"
OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"


class CollaborationError(RuntimeError):
    pass


def _safe(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")[:48]
    return label or hashlib.sha256(value.encode()).hexdigest()[:24]


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".tuxdrive-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass(frozen=True)
class TextOperation:
    operation_id: str
    actor: str
    counter: int
    kind: str
    after: str = ROOT
    value: str = ""
    target: str = ""
    timestamp: float = 0.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TextOperation":
        operation = cls(**raw)
        if operation.kind not in {"insert", "delete"}:
            raise CollaborationError("Unknown collaborative text operation")
        if operation.kind == "insert" and len(operation.value) != 1:
            raise CollaborationError("Insert operations must contain exactly one character")
        return operation


class TextCRDT:
    """A small replicated growable array with deterministic sibling ordering."""

    def __init__(self, actor: str, operations: Iterable[TextOperation] = ()) -> None:
        self.actor = _safe(actor)
        self.operations: dict[str, TextOperation] = {}
        self.merge(operations)
        self.counter = max((op.counter for op in self.operations.values() if op.actor == self.actor), default=0)

    @staticmethod
    def _sort_key(operation: TextOperation) -> tuple[int, str, str]:
        return operation.counter, operation.actor, operation.operation_id

    def merge(self, operations: Iterable[TextOperation]) -> None:
        for operation in operations:
            previous = self.operations.get(operation.operation_id)
            if previous and previous != operation:
                raise CollaborationError(f"Conflicting operation identifier: {operation.operation_id}")
            self.operations[operation.operation_id] = operation

    def _next(self, kind: str, **values: Any) -> TextOperation:
        self.counter += 1
        return TextOperation(
            operation_id=f"{self.actor}:{self.counter:020d}", actor=self.actor,
            counter=self.counter, kind=kind, timestamp=time.time(), **values,
        )

    def ordered_ids(self) -> list[str]:
        inserts = {key: op for key, op in self.operations.items() if op.kind == "insert"}
        children: dict[str, list[TextOperation]] = {}
        for operation in inserts.values():
            parent = operation.after if operation.after in inserts or operation.after == ROOT else ROOT
            children.setdefault(parent, []).append(operation)
        ordered: list[str] = []

        def visit(parent: str) -> None:
            for child in sorted(children.get(parent, ()), key=self._sort_key):
                ordered.append(child.operation_id)
                visit(child.operation_id)

        visit(ROOT)
        return ordered

    def visible_ids(self) -> list[str]:
        deleted = {op.target for op in self.operations.values() if op.kind == "delete"}
        return [operation_id for operation_id in self.ordered_ids() if operation_id not in deleted]

    @property
    def text(self) -> str:
        return "".join(self.operations[key].value for key in self.visible_ids())

    def insert(self, position: int, text: str) -> list[TextOperation]:
        visible = self.visible_ids()
        position = max(0, min(position, len(visible)))
        after = visible[position - 1] if position else ROOT
        created: list[TextOperation] = []
        for character in text:
            operation = self._next("insert", after=after, value=character)
            self.operations[operation.operation_id] = operation
            created.append(operation)
            after = operation.operation_id
        return created

    def delete(self, start: int, end: int) -> list[TextOperation]:
        visible = self.visible_ids()[max(0, start):max(0, end)]
        created = [self._next("delete", target=target) for target in visible]
        self.merge(created)
        return created

    def replace(self, value: str) -> list[TextOperation]:
        old = self.text
        prefix = 0
        while prefix < min(len(old), len(value)) and old[prefix] == value[prefix]:
            prefix += 1
        suffix = 0
        while suffix < len(old) - prefix and suffix < len(value) - prefix and old[-suffix - 1] == value[-suffix - 1]:
            suffix += 1
        created = self.delete(prefix, len(old) - suffix)
        created.extend(self.insert(prefix, value[prefix:len(value) - suffix if suffix else len(value)]))
        return created


@dataclass(frozen=True)
class ReviewEvent:
    event_id: str
    kind: str
    actor: str
    created_at: float
    body: str = ""
    anchor: int = 0
    end: int = 0
    status: str = "open"
    assignee: str = ""


class CollaborationWorkspace:
    """Immutable operation/event storage suitable for ordinary folder sync."""

    def __init__(self, folder: Path | str, document_id: str, actor: str) -> None:
        self.folder = Path(folder)
        self.document_id = _safe(document_id)
        self.actor = _safe(actor)
        self.root = self.folder / ".tuxdrive-collaboration" / self.document_id
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def load(self) -> TextCRDT:
        operations: list[TextOperation] = []
        for path in sorted((self.root / "operations").glob("*/*.json")):
            operations.append(TextOperation.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return TextCRDT(self.actor, operations)

    def persist(self, operations: Iterable[TextOperation]) -> None:
        for operation in operations:
            path = self.root / "operations" / _safe(operation.actor) / f"{operation.counter:020d}.json"
            value = asdict(operation)
            if path.exists():
                if json.loads(path.read_text(encoding="utf-8")) != value:
                    raise CollaborationError(f"Operation file was modified: {path.name}")
                continue
            _atomic_json(path, value)

    def import_checkpoint(self, source: Path | str) -> TextCRDT:
        path = Path(source)
        if path.suffix.lower() not in {".md", ".markdown", ".txt"}:
            raise CollaborationError("Only Markdown and plain text use the real-time text editor")
        crdt = self.load()
        if not crdt.operations:
            self.persist(crdt.insert(0, path.read_text(encoding="utf-8")))
        return self.load()

    def export_checkpoint(self, destination: Path | str, crdt: TextCRDT) -> None:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(crdt.text, encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        _atomic_json(self.root / "checkpoints" / f"{int(time.time() * 1000)}.json", {
            "file": destination.name, "sha256": hashlib.sha256(crdt.text.encode()).hexdigest(), "actor": self.actor,
        })

    def add_review(self, kind: str, body: str, anchor: int = 0, end: int = 0, assignee: str = "") -> ReviewEvent:
        if kind not in {"comment", "suggestion", "approval", "task", "tracked-change"}:
            raise CollaborationError("Unsupported review event")
        event = ReviewEvent(uuid.uuid4().hex, kind, self.actor, time.time(), body, anchor, end, "approved" if kind == "approval" else "open", assignee)
        _atomic_json(self.root / "reviews" / f"{event.event_id}.json", asdict(event))
        return event

    def reviews(self) -> list[ReviewEvent]:
        return [ReviewEvent(**json.loads(path.read_text(encoding="utf-8"))) for path in sorted((self.root / "reviews").glob("*.json"))]

    def write_presence(self, key: bytes, cursor: int, selection_end: int, ttl: int = 30) -> None:
        if len(key) != 32:
            raise CollaborationError("Presence encryption requires a 256-bit workspace key")
        expires = time.time() + max(5, min(ttl, 300))
        payload = json.dumps({"actor": self.actor, "cursor": cursor, "selection_end": selection_end, "expires": expires}).encode()
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, payload, self.document_id.encode())
        _atomic_json(self.root / "presence" / f"{self.actor}.json", {
            "version": 1, "nonce": base64.b64encode(nonce).decode(), "ciphertext": base64.b64encode(ciphertext).decode(), "expires": expires,
        })

    def read_presence(self, key: bytes) -> list[dict[str, Any]]:
        now = time.time()
        present: list[dict[str, Any]] = []
        for path in (self.root / "presence").glob("*.json"):
            envelope = json.loads(path.read_text(encoding="utf-8"))
            if float(envelope.get("expires", 0)) <= now:
                path.unlink(missing_ok=True)
                continue
            try:
                value = AESGCM(key).decrypt(base64.b64decode(envelope["nonce"]), base64.b64decode(envelope["ciphertext"]), self.document_id.encode())
                present.append(json.loads(value))
            except Exception as exc:
                raise CollaborationError("Presence data could not be authenticated") from exc
        return present


@dataclass
class ODFParagraph:
    text: str
    style: str = ""
    kind: str = "paragraph"


@dataclass
class ODFCell:
    sheet: str
    row: int
    column: int
    value: str
    formula: str = ""
    style: str = ""


@dataclass
class ODFDocument:
    kind: str
    entries: dict[str, bytes] = field(repr=False)
    paragraphs: list[ODFParagraph] = field(default_factory=list)
    cells: list[ODFCell] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    tracked_changes: bool = False
    warnings: list[str] = field(default_factory=list)


class ODFAdapter:
    """Structured ODT/ODS import and deterministic, recoverable snapshot export."""

    @staticmethod
    def load(path: Path | str) -> ODFDocument:
        path = Path(path)
        kind = path.suffix.lower().lstrip(".")
        if kind not in {"odt", "ods"}:
            raise CollaborationError("Structured editing supports ODT and ODS")
        with zipfile.ZipFile(path) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        if "content.xml" not in entries:
            raise CollaborationError("ODF document has no content.xml")
        root = ET.fromstring(entries["content.xml"])
        document = ODFDocument(kind, entries)
        document.comments = ["".join(node.itertext()) for node in root.findall(f".//{{{OFFICE}}}annotation")]
        document.tracked_changes = root.find(f".//{{{TEXT}}}tracked-changes") is not None
        if kind == "odt":
            for node in list(root.findall(f".//{{{TEXT}}}p")) + list(root.findall(f".//{{{TEXT}}}h")):
                document.paragraphs.append(ODFParagraph("".join(node.itertext()), node.attrib.get(f"{{{TEXT}}}style-name", ""), "heading" if node.tag.endswith("}h") else "paragraph"))
                if list(node):
                    document.warnings.append("Inline/unsupported XML is retained in a recovery copy; editing that paragraph may flatten its formatting")
        else:
            for sheet in root.findall(f".//{{{TABLE}}}table"):
                name = sheet.attrib.get(f"{{{TABLE}}}name", "Sheet")
                for row_number, row in enumerate(sheet.findall(f"{{{TABLE}}}table-row")):
                    for column, cell in enumerate(row.findall(f"{{{TABLE}}}table-cell")):
                        document.cells.append(ODFCell(name, row_number, column, "".join(cell.itertext()), cell.attrib.get(f"{{{TABLE}}}formula", ""), cell.attrib.get(f"{{{TABLE}}}style-name", "")))
            document.warnings.append("ODS real-time editing is experimental; unsupported/repeated cells are preserved in the recovery copy")
        return document

    @staticmethod
    def export(document: ODFDocument, destination: Path | str) -> None:
        root = ET.fromstring(document.entries["content.xml"])
        changed = False
        if document.kind == "odt":
            nodes = list(root.findall(f".//{{{TEXT}}}p")) + list(root.findall(f".//{{{TEXT}}}h"))
            for node, paragraph in zip(nodes, document.paragraphs):
                if "".join(node.itertext()) != paragraph.text:
                    for child in list(node):
                        node.remove(child)
                    node.text = paragraph.text
                    changed = True
        else:
            cell_map = {(cell.sheet, cell.row, cell.column): cell for cell in document.cells}
            for sheet in root.findall(f".//{{{TABLE}}}table"):
                name = sheet.attrib.get(f"{{{TABLE}}}name", "Sheet")
                for row_number, row in enumerate(sheet.findall(f"{{{TABLE}}}table-row")):
                    for column, node in enumerate(row.findall(f"{{{TABLE}}}table-cell")):
                        cell = cell_map.get((name, row_number, column))
                        if not cell:
                            continue
                        existing = "".join(node.itertext())
                        if existing != cell.value or node.attrib.get(f"{{{TABLE}}}formula", "") != cell.formula:
                            if cell.formula:
                                node.set(f"{{{TABLE}}}formula", cell.formula)
                            for child in list(node):
                                node.remove(child)
                            paragraph = ET.SubElement(node, f"{{{TEXT}}}p")
                            paragraph.text = cell.value
                            changed = True
        entries = dict(document.entries)
        if changed:
            entries["TuxDrive/original-content.xml"] = document.entries["content.xml"]
            entries["content.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        with zipfile.ZipFile(temporary, "w") as archive:
            names = sorted(entries, key=lambda name: (name != "mimetype", name))
            for name in names:
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o600 << 16
                compression = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
                archive.writestr(info, entries[name], compress_type=compression)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)


def document_capability(path: Path | str) -> dict[str, Any]:
    suffix = Path(path).suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        return {"mode": "realtime-crdt", "safe": True, "features": ["offline", "comments", "presence", "approvals"]}
    if suffix in {".odt", ".ods"}:
        return {"mode": "structured-experimental", "safe": True, "features": ["deterministic-export", "recovery-xml", "review"]}
    if suffix in {".docx", ".xlsx", ".pdf"}:
        return {"mode": "lock-version-review", "safe": True, "features": ["lease", "version-history", "approval"]}
    return {"mode": "lock-version-review", "safe": False, "features": ["lease"]}
