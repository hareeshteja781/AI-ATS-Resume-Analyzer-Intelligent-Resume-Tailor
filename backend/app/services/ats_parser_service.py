from __future__ import annotations

import io
import re
from collections import OrderedDict
from datetime import datetime
from typing import Any

from docx import Document
from docx.oxml.ns import qn
from pypdf import PdfReader

from app.services.storage_service import StorageService

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

SECTION_ALIASES = OrderedDict(
    (
        ("summary", {"summary", "professional summary", "profile", "objective"}),
        ("skills", {"skills", "technical skills", "core skills", "core competencies", "key skills", "technologies", "technical competencies"}),
        ("experience", {"experience", "work experience", "professional experience", "employment", "work history", "employment history", "professional background", "relevant experience", "internships"}),
        ("projects", {"projects", "selected projects", "personal projects", "academic projects"}),
        ("education", {"education", "academic background", "qualifications"}),
        ("certifications", {"certifications", "certificates", "licenses", "training"}),
        ("achievements", {"achievements", "awards", "honors", "accomplishments"}),
    )
)

PROFILE_CONFIG = {
    "generic": {
        "description": "General compatibility checks based on common text extraction behavior.",
        "checks": (
            "text_extractability", "standard_section_headings", "reading_order",
            "contact_information", "tables", "multiple_columns", "graphics_images",
            "image_only", "headers_footers", "text_boxes", "unusual_symbols",
            "date_consistency", "keyword_organization", "section_structure",
        ),
    },
    "greenhouse": {
        "description": "Greenhouse-oriented checks for machine-readable text, sections, and ordering; not a vendor parser clone.",
        "checks": (
            "text_extractability", "standard_section_headings", "reading_order",
            "contact_information", "tables", "multiple_columns", "graphics_images",
            "image_only", "text_boxes", "unusual_symbols", "keyword_organization",
            "section_structure",
        ),
    },
    "workday": {
        "description": "Workday-oriented checks for extractable fields, conventional sections, and document structure; not a vendor parser clone.",
        "checks": (
            "text_extractability", "standard_section_headings", "reading_order",
            "contact_information", "tables", "multiple_columns", "image_only",
            "headers_footers", "text_boxes", "date_consistency", "keyword_organization",
            "section_structure",
        ),
    },
}


class ATSParserService:
    def __init__(self, storage: StorageService | None = None):
        self.storage = storage or StorageService()

    def analyze_resume(self, resume, profile: str = "generic") -> dict[str, Any]:
        source_bytes = b""
        if resume.storage_path:
            try:
                source_bytes = self.storage.get_bytes(resume.storage_path)
            except (FileNotFoundError, OSError, ValueError):
                source_bytes = b""

        if source_bytes:
            return self.analyze_bytes(source_bytes, resume.content_type, profile=profile)
        return self.analyze_text(resume.text_content or "", profile=profile, source_format="stored_text")

    def analyze_bytes(self, source_bytes: bytes, content_type: str, *, profile: str = "generic") -> dict[str, Any]:
        if content_type == "application/pdf":
            return self._analyze_pdf(source_bytes, profile)
        if content_type in {DOCX_CONTENT_TYPE, "application/docx"}:
            return self._analyze_docx(source_bytes, profile)
        raise ValueError("Unsupported resume format for ATS analysis.")

    def analyze_text(self, text: str, *, profile: str = "generic", source_format: str = "text") -> dict[str, Any]:
        parsed = self._parse_text(text, source_format=source_format, metadata={})
        return self._build_result(parsed, profile)

    def run_test_lab(self, fixtures: list[dict[str, Any]]) -> dict[str, Any]:
        results = []
        for fixture in fixtures:
            analysis = self.analyze_bytes(
                fixture["source_bytes"],
                fixture["content_type"],
                profile=fixture.get("profile", "generic"),
            )
            expected = fixture.get("expected_text", "")
            extracted = analysis["parser_preview"]["raw_text"]
            expected_tokens = self._tokens(expected)
            extracted_tokens = self._tokens(extracted)
            matched = expected_tokens & extracted_tokens
            accuracy = round(len(matched) / max(len(expected_tokens), 1) * 100, 2)
            results.append({
                "name": fixture["name"],
                "extraction_accuracy": accuracy,
                "missing_expected_tokens": sorted(expected_tokens - extracted_tokens),
                "parsing_risks": analysis["compatibility"]["risks"],
                "parser_preview": analysis["parser_preview"],
            })
        return {"fixture_count": len(results), "results": results}

    def _analyze_docx(self, source_bytes: bytes, profile: str) -> dict[str, Any]:
        doc = Document(io.BytesIO(source_bytes))
        blocks = []
        images = len(doc.inline_shapes)
        tables = 0
        for child in doc.element.body.iterchildren():
            if child.tag == qn("w:p"):
                text = "".join(node.text or "" for node in child.iter() if node.tag == qn("w:t"))
                if text.strip():
                    blocks.append({"type": "paragraph", "text": text})
            elif child.tag == qn("w:tbl"):
                tables += 1
                rows = []
                for row in child.iterchildren(qn("w:tr")):
                    cells = []
                    for cell in row.iterchildren(qn("w:tc")):
                        cells.append(" ".join(node.text or "" for node in cell.iter() if node.tag == qn("w:t")).strip())
                    rows.append(" | ".join(item for item in cells if item))
                table_text = "\n".join(item for item in rows if item)
                if table_text:
                    blocks.append({"type": "table", "text": table_text})

        header_footer = []
        for section in doc.sections:
            for container in (section.header, section.footer):
                header_footer.extend(paragraph.text for paragraph in container.paragraphs if paragraph.text.strip())
        text_boxes = len(doc.element.xpath(".//w:txbxContent"))
        columns = 1
        for section in doc.sections:
            cols = section._sectPr.xpath("./w:cols")
            if cols:
                columns = max(columns, int(cols[0].get(qn("w:num"), "1")))
        text = "\n".join(block["text"] for block in blocks)
        metadata = {
            "blocks": blocks,
            "tables": tables,
            "columns": columns,
            "images": images,
            "headers_footers": header_footer,
            "text_boxes": text_boxes,
        }
        return self._build_result(self._parse_text(text, source_format="docx", metadata=metadata), profile)

    def _analyze_pdf(self, source_bytes: bytes, profile: str) -> dict[str, Any]:
        reader = PdfReader(io.BytesIO(source_bytes))
        pages = []
        images = 0
        for page in reader.pages:
            pages.append(page.extract_text() or "")
            resources = page.get("/Resources") or {}
            resources = resources.get_object() if hasattr(resources, "get_object") else resources
            xobjects = resources.get("/XObject") or {}
            images += sum(
                1 for reference in xobjects.values()
                if (reference.get_object() if hasattr(reference, "get_object") else reference).get("/Subtype") == "/Image"
            )
        text = "\n".join(pages)
        metadata = {"pages": len(reader.pages), "images": images, "columns": 1, "tables": 0, "headers_footers": [], "text_boxes": 0}
        return self._build_result(self._parse_text(text, source_format="pdf", metadata=metadata), profile)

    def _parse_text(self, text: str, *, source_format: str, metadata: dict[str, Any]) -> dict[str, Any]:
        raw_text = text or ""
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        sections: dict[str, list[str]] = {key: [] for key in SECTION_ALIASES}
        other: list[str] = []
        current = None
        detected_headings = []
        for line in lines:
            heading = self._section_key(line)
            if heading:
                current = heading
                detected_headings.append(heading)
                continue
            if current:
                sections[current].append(line)
            else:
                other.append(line)

        email = re.findall(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", raw_text)
        phone = re.findall(r"(?<!\w)(?:\+?\d[\d().\s-]{7,}\d)(?!\w)", raw_text)
        links = re.findall(r"\b(?:https?://|www\.)\S+", raw_text, flags=re.IGNORECASE)
        contact = {"emails": sorted(set(email)), "phones": sorted(set(" ".join(item.split()) for item in phone)), "links": sorted(set(links))}
        name = self._guess_name(lines, contact)
        skills = self._split_items(sections["skills"])
        summary = " ".join(sections["summary"])
        fields = {
            "name": name,
            "contact": contact,
            "professional_summary": summary,
            "skills": skills,
            "experience": sections["experience"],
            "projects": sections["projects"],
            "education": sections["education"],
            "certifications": sections["certifications"],
            "achievements": sections["achievements"],
            "other": other,
        }
        missing = [key for key in ("professional_summary", "skills", "experience", "projects", "education") if not fields[key]]
        return {
            "source_format": source_format,
            "raw_text": raw_text.strip(),
            "lines": lines,
            "fields": fields,
            "missing_fields": missing,
            "detected_headings": detected_headings,
            "metadata": metadata,
        }

    def _build_result(self, parsed: dict[str, Any], profile: str) -> dict[str, Any]:
        profile_key = re.sub(r"\s+", " ", (profile or "generic").strip().lower())
        profile_key = {
            "generic ats": "generic",
            "greenhouse-oriented": "greenhouse",
            "greenhouse oriented": "greenhouse",
            "workday-oriented": "workday",
            "workday oriented": "workday",
        }.get(profile_key, profile_key)
        if profile_key not in PROFILE_CONFIG:
            raise ValueError(f"Unknown ATS profile: {profile}")
        checks = self._checks(parsed)
        selected = [check for check in checks if check["id"] in PROFILE_CONFIG[profile_key]["checks"]]
        score = self._score_checks(selected)
        risks = [check["message"] for check in selected if check["status"] != "pass"]
        return {
            "profile": profile_key,
            "profile_description": PROFILE_CONFIG[profile_key]["description"],
            "parser_preview": {
                "source_format": parsed["source_format"],
                "raw_text": parsed["raw_text"],
                "fields": parsed["fields"],
                "missing_fields": parsed["missing_fields"],
                "detected_headings": parsed["detected_headings"],
                "metadata": parsed["metadata"],
            },
            "compatibility": {
                "ats_score": score,
                "checks": selected,
                "risks": risks,
                "limitations": ["This is deterministic compatibility analysis based on observable document characteristics, not a reproduction of proprietary ATS internals."],
            },
        }

    def _checks(self, parsed: dict[str, Any]) -> list[dict[str, Any]]:
        fields = parsed["fields"]
        metadata = parsed["metadata"]
        raw_text = parsed["raw_text"]
        headings = parsed["detected_headings"]
        text_ok = len(raw_text.strip()) >= 40
        checks = [
            self._check("text_extractability", "pass" if text_ok else "fail", "Text is extractable from the source." if text_ok else "Little or no text was extracted; this may be an image-only resume."),
            self._check("standard_section_headings", "pass" if len(set(headings)) >= 2 else "warning", "Standard section headings were detected." if len(set(headings)) >= 2 else "Few or no standard section headings were detected."),
            self._check("reading_order", "fail" if metadata.get("columns", 1) > 1 else "warning" if metadata.get("tables", 0) else "pass", "Reading order is likely linear." if metadata.get("columns", 1) == 1 and not metadata.get("tables", 0) else "Columns or tables require ATS reading-order review."),
            self._check("contact_information", "pass" if fields["contact"]["emails"] or fields["contact"]["phones"] else "warning", "Contact information was extracted." if fields["contact"]["emails"] or fields["contact"]["phones"] else "No email address or phone number was extracted."),
            self._check("tables", "warning" if metadata.get("tables", 0) else "pass", "Tables are present and may affect field ordering." if metadata.get("tables", 0) else "No tables detected."),
            self._check("multiple_columns", "warning" if metadata.get("columns", 1) > 1 else "pass", "Multiple columns may be read in an unexpected order." if metadata.get("columns", 1) > 1 else "No multiple-column layout detected."),
            self._check("graphics_images", "warning" if metadata.get("images", 0) else "pass", "Images or graphics may not provide extractable text." if metadata.get("images", 0) else "No embedded images detected."),
            self._check("image_only", "fail" if not text_ok and metadata.get("images", 0) else "pass", "The source appears image-only." if not text_ok and metadata.get("images", 0) else "Extractable text is present."),
            self._check("headers_footers", "warning" if metadata.get("headers_footers") else "pass", "Header or footer text may be detached or repeated by an ATS." if metadata.get("headers_footers") else "No header/footer text detected."),
            self._check("text_boxes", "warning" if metadata.get("text_boxes") else "pass", "Text boxes were detected and may be skipped by some extractors." if metadata.get("text_boxes") else "No detectable text boxes."),
            self._check("unusual_symbols", "warning" if self._unusual_symbol_count(raw_text) >= 3 else "pass", "Unusual symbols may reduce consistent token extraction." if self._unusual_symbol_count(raw_text) >= 3 else "No unusual symbol concentration detected."),
            self._date_check(raw_text),
            self._check("keyword_organization", "pass" if fields["skills"] else "warning", "Skills are grouped under a detected skills heading." if fields["skills"] else "Skills were not extracted under a standard skills heading."),
            self._section_order_check(headings),
        ]
        return checks

    @staticmethod
    def _check(identifier: str, status: str, message: str) -> dict[str, str]:
        return {"id": identifier, "status": status, "message": message}

    @staticmethod
    def _score_checks(checks: list[dict[str, Any]]) -> float:
        if not checks:
            return 0.0
        values = {"pass": 100.0, "warning": 50.0, "fail": 0.0}
        return round(sum(values[check["status"]] for check in checks) / len(checks), 2)

    @staticmethod
    def _section_key(line: str) -> str | None:
        normalized = re.sub(r"[^a-z ]", "", line.lower()).strip()
        for key, aliases in SECTION_ALIASES.items():
            if normalized in aliases:
                return key
        return None

    @staticmethod
    def _guess_name(lines: list[str], contact: dict[str, list[str]]) -> str | None:
        for line in lines[:5]:
            if ATSParserService._section_key(line) or line in contact["emails"]:
                continue
            if "@" not in line and not re.search(r"\d", line) and len(line.split()) <= 5:
                return line
        return None

    @staticmethod
    def _split_items(lines: list[str]) -> list[str]:
        items = []
        for line in lines:
            items.extend(part.strip(" •-\t") for part in re.split(r"[,;|]", line) if part.strip(" •-\t"))
        return items

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9+#.]+", text.lower()))

    @staticmethod
    def _unusual_symbol_count(text: str) -> int:
        return sum(1 for char in text if not (char.isalnum() or char.isspace() or char in ".,;:!?()[]{}@+#/&%'-"))

    @staticmethod
    def _date_check(text: str) -> dict[str, str]:
        years = [int(year) for year in re.findall(r"\b(19\d{2}|20\d{2})\b", text)]
        current_year = datetime.now().year
        invalid = [year for year in years if year > current_year + 1]
        return ATSParserService._check(
            "date_consistency",
            "warning" if invalid else "pass",
            "Dates contain future years that should be reviewed." if invalid else "No obvious date inconsistency detected.",
        )

    @staticmethod
    def _section_order_check(headings: list[str]) -> dict[str, str]:
        order = {key: index for index, key in enumerate(SECTION_ALIASES)}
        positions = [order[item] for item in headings if item in order]
        inverted = any(left > right for left, right in zip(positions, positions[1:]))
        return ATSParserService._check(
            "section_structure",
            "warning" if inverted else "pass",
            "Section headings appear in an unusual order." if inverted else "Section structure is in a conventional order.",
        )