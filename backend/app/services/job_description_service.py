from __future__ import annotations

import html as html_lib
import json
import re
from urllib.parse import urljoin, urlparse

from lxml import html as lxml_html
from fastapi import HTTPException, UploadFile, status

from app.core.config import settings
from app.services.ai_service import AIService, AIServiceError
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.repositories.job_description_repository import JobDescriptionRepository
from app.models.document_chunk import DocumentChunk
from app.models.embedding import Embedding
from app.models.job_match_result import JobMatchResult
from app.models.resume_version import ResumeVersion
from app.services.chunking import chunk_text
from app.services.embedding_service import EmbeddingRepository, EmbeddingService, GeminiEmbeddingProvider
from app.services.document_processing import (
    MAX_FILE_SIZE_BYTES,
    detect_prompt_injection,
    extract_text_from_upload,
    fetch_public_url,
    normalize_jd_text,
    validate_document_signature,
    validate_image_upload,
    validate_public_url,
    validate_upload,
)
from app.services.storage_service import StorageService


class JobDescriptionService:
    def __init__(self, db, storage: StorageService | None = None):
        self.db = db
        self.repository = JobDescriptionRepository(db)
        self.storage = storage or StorageService()

    def create_from_text(self, user_id: int, text: str) -> dict:
        cleaned = text.strip()
        if not cleaned:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Job description text is required.",
            )

        injection_detected = detect_prompt_injection(cleaned)
        normalized = normalize_jd_text(cleaned)
        role_name, company_name = self._derive_job_metadata(cleaned)
        jd = self.repository.create(
            user_id=user_id,
            source_type="paste",
            role_name=role_name,
            company_name=company_name,
            text_content=cleaned,
            normalized_text=normalized,
            source_html=None,
            prompt_injection_detected=injection_detected,
        )
        self._process_chunks_and_embeddings(jd.id, user_id, normalized)
        return {
            "id": jd.id,
            "user_id": user_id,
            "filename": jd.filename,
            "role_name": jd.role_name,
            "company_name": jd.company_name,
            "source_type": jd.source_type,
            "content_type": jd.content_type,
            "text_content": jd.text_content,
            "normalized_text": jd.normalized_text,
            "url": jd.url,
            "source_html": jd.source_html,
            "prompt_injection_detected": jd.prompt_injection_detected,
            "status": jd.status,
            "processing_error": jd.processing_error,
        }

    def delete_job_description(self, job_description_id: int, user_id: int) -> None:
        jd = self.repository.get_for_user(job_description_id, user_id)
        if jd is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job description not found")

        storage = self.storage
        keys = [jd.storage_path]
        if jd.source_html:
            try:
                metadata = json.loads(jd.source_html)
                keys.extend(item.get("storage_path") for item in metadata.get("images", []) if item.get("storage_path"))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        versions = self.db.query(ResumeVersion).filter(ResumeVersion.job_description_id == jd.id, ResumeVersion.user_id == user_id).all()
        keys.extend(path for version in versions for path in (version.document_path, version.pdf_path) if path)
        chunk_ids = [row.id for row in self.db.query(DocumentChunk.id).filter(DocumentChunk.job_description_id == jd.id).all()]
        if chunk_ids:
            self.db.query(Embedding).filter(Embedding.chunk_id.in_(chunk_ids), Embedding.user_id == user_id).delete(synchronize_session=False)
        self.db.query(JobMatchResult).filter(JobMatchResult.job_description_id == jd.id, JobMatchResult.user_id == user_id).delete(synchronize_session=False)
        self.db.query(ResumeVersion).filter(ResumeVersion.job_description_id == jd.id, ResumeVersion.user_id == user_id).delete(synchronize_session=False)
        self.db.query(DocumentChunk).filter(DocumentChunk.job_description_id == jd.id).delete(synchronize_session=False)
        self.db.delete(jd)
        self.db.commit()
        for key in keys:
            try:
                storage.delete(key)
            except (FileNotFoundError, OSError, ValueError):
                pass

    def create_from_upload(self, user_id: int, file: UploadFile) -> dict:
        validate_upload(file)
        file_bytes = file.file.read()
        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File is too large. Maximum supported size is 10MB.",
            )

        content_type = file.content_type or "application/octet-stream"
        validate_document_signature(file_bytes, content_type)
        text_content = extract_text_from_upload(file_bytes, content_type)
        injection_detected = detect_prompt_injection(text_content)
        normalized = normalize_jd_text(text_content)
        role_name, company_name = self._derive_job_metadata(text_content)
        storage_path = self.storage.put_upload(
            user_id=user_id,
            kind="job-descriptions",
            filename=file.filename or "job-description",
            data=file_bytes,
            content_type=content_type,
        )

        try:
            jd = self.repository.create(
                user_id=user_id,
                filename=file.filename,
                role_name=role_name,
                company_name=company_name,
                source_type="upload",
                content_type=content_type,
                file_size=len(file_bytes),
                storage_path=storage_path,
                text_content=text_content,
                normalized_text=normalized,
                prompt_injection_detected=injection_detected,
                source_html=None,
            )
            self._process_chunks_and_embeddings(jd.id, user_id, normalized)
            return {
                "id": jd.id,
                "user_id": user_id,
                "filename": jd.filename,
                "role_name": jd.role_name,
                "company_name": jd.company_name,
                "source_type": jd.source_type,
                "content_type": jd.content_type,
                "file_size": jd.file_size,
                "storage_path": jd.storage_path,
                "text_content": jd.text_content,
                "normalized_text": jd.normalized_text,
                "url": jd.url,
                "prompt_injection_detected": jd.prompt_injection_detected,
                "status": jd.status,
                "processing_error": jd.processing_error,
            }
        except Exception:
            self.storage.delete(storage_path)
            raise

    def create_from_images(self, user_id: int, files: list[UploadFile]) -> dict:
        if not files:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one JD screenshot is required.")
        if not settings.GEMINI_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Image JD extraction requires a configured Gemini vision service.",
            )

        extracted = []
        stored_paths = []
        try:
            vision = AIService()
            for file in files:
                file_bytes = file.file.read()
                width, height = validate_image_upload(file, file_bytes)
                result = vision.extract_job_description_image(file_bytes, file.content_type or "")
                text = result.extracted_text.strip()
                if not text:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"No readable job-description text was extracted from '{file.filename}'.",
                    )
                extracted.append({
                    "filename": file.filename,
                    "content_type": file.content_type,
                    "width": width,
                    "height": height,
                    "text": text,
                    "bytes": file_bytes,
                    "size": len(file_bytes),
                    "structured": result.model_dump(exclude={"extracted_text"}),
                })

            combined_text = self._merge_image_text(extracted)
            injection_detected = detect_prompt_injection(combined_text)
            normalized = normalize_jd_text(combined_text)
            first_structured = next((item["structured"] for item in extracted if item["structured"].get("job_title")), extracted[0]["structured"])
            role_name = first_structured.get("job_title") or self._derive_job_metadata(combined_text)[0]
            company_name = self._derive_job_metadata(combined_text)[1]
            for item in extracted:
                path = self.storage.put_upload(
                    user_id=user_id,
                    kind="job-descriptions/images",
                    filename=item["filename"] or "job-description.png",
                    data=item["bytes"],
                    content_type=item["content_type"] or "application/octet-stream",
                )
                item["storage_path"] = path
                stored_paths.append(path)
        except AIServiceError as exc:
            raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        except Exception:
            for path in stored_paths:
                self.storage.delete(path)
            raise

        try:
            jd = self.repository.create(
                user_id=user_id,
                filename=files[0].filename or "job-description-screenshots",
                role_name=role_name,
                company_name=company_name,
                source_type="image",
                content_type=files[0].content_type,
                file_size=sum(item["size"] for item in extracted),
                storage_path=stored_paths[0] if stored_paths else None,
                text_content=combined_text,
                normalized_text=normalized,
                prompt_injection_detected=injection_detected,
                source_html=json.dumps({"images": [{key: item[key] for key in ("filename", "content_type", "width", "height", "storage_path")} for item in extracted]}),
            )
            self._process_chunks_and_embeddings(jd.id, user_id, normalized)
            return {
                "id": jd.id,
                "user_id": jd.user_id,
                "filename": jd.filename,
                "role_name": jd.role_name,
                "company_name": jd.company_name,
                "source_type": jd.source_type,
                "content_type": jd.content_type,
                "file_size": jd.file_size,
                "storage_path": jd.storage_path,
                "text_content": jd.text_content,
                "normalized_text": jd.normalized_text,
                "url": jd.url,
                "source_html": jd.source_html,
                "prompt_injection_detected": jd.prompt_injection_detected,
                "status": jd.status,
                "processing_error": jd.processing_error,
                "source_images": [
                    {key: item[key] for key in ("filename", "content_type", "width", "height", "storage_path")}
                    for item in extracted
                ],
                "structured_extraction": self._merge_structured_extraction(extracted),
            }
        except Exception:
            for path in stored_paths:
                self.storage.delete(path)
            raise

    @staticmethod
    def _merge_image_text(extracted: list[dict]) -> str:
        merged: list[str] = []
        for item in extracted:
            lines = [line.strip() for line in item["text"].splitlines() if line.strip()]
            normalized_lines = [re.sub(r"\s+", " ", line).lower() for line in lines]
            overlap = 0
            for size in range(min(10, len(merged), len(lines)), 0, -1):
                if [re.sub(r"\s+", " ", line).lower() for line in merged[-size:]] == normalized_lines[:size]:
                    overlap = size
                    break
            merged.extend(lines[overlap:])
        return "\n".join(merged).strip()

    @staticmethod
    def _merge_structured_extraction(extracted: list[dict]) -> dict:
        fields = ("required_skills", "preferred_skills", "responsibilities", "technical_tools", "soft_skills", "experience", "education", "certifications", "important_keywords", "other_requirements")
        merged = {field: [] for field in fields}
        merged["job_title"] = next((item["structured"].get("job_title") for item in extracted if item["structured"].get("job_title")), None)
        for item in extracted:
            for field in fields:
                for value in item["structured"].get(field, []):
                    if value not in merged[field]:
                        merged[field].append(value)
        return merged

    def create_from_url(self, user_id: int, url: str) -> dict:
        preview = self.preview_from_url(url)
        return self.confirm_url_import(user_id, url, preview["text_content"])

    def preview_from_url(self, url: str) -> dict:
        validate_public_url(url)
        try:
            final_url, raw_html = fetch_public_url(url)
            html = raw_html.decode("utf-8", errors="ignore")
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to retrieve URL content: {exc}",
            ) from exc

        text_content = self._extract_text_from_html(html)
        alnum_length = len(re.sub(r"[^A-Za-z0-9]", "", text_content or ""))
        words = re.findall(r"[A-Za-z0-9]+", text_content or "")
        job_like_markers = (
            "hiring",
            "role",
            "position",
            "experience",
            "engineer",
            "developer",
            "team",
            "job",
            "candidate",
            "requirements",
        )
        if alnum_length < 80 and (
            len(words) < 8 or not any(marker in (text_content or "").lower() for marker in job_like_markers)
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not extract enough job-description text from this URL. Paste or upload the job description instead.",
            )
        role_name, company_name = self._extract_job_metadata_from_html(html, text_content)
        if not company_name:
            host = urlparse(url).hostname or ""
            if host:
                company_name = host.split(".")[0].replace("-", " ").title()
        return {
            "source_url": url,
            "final_url": final_url,
            "role_name": role_name,
            "company_name": company_name,
            "text_content": text_content,
            "normalized_text": normalize_jd_text(text_content),
            "structured_extraction": self._build_url_structure(text_content, role_name),
        }

    def confirm_url_import(self, user_id: int, url: str, text_content: str) -> dict:
        cleaned = text_content.strip()
        if len(re.sub(r"[^A-Za-z0-9]", "", cleaned)) < 40:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Confirmed job-description content is too short.")
        injection_detected = detect_prompt_injection(cleaned)
        normalized = normalize_jd_text(cleaned)
        role_name, company_name = self._derive_job_metadata(cleaned)
        filename = role_name or "Imported job description"
        jd = self.repository.create(
            user_id=user_id,
            source_type="url",
            filename=filename[:255],
            role_name=role_name,
            company_name=company_name,
            text_content=cleaned,
            normalized_text=normalized,
            url=url,
            source_html=None,
            prompt_injection_detected=injection_detected,
        )
        self._process_chunks_and_embeddings(jd.id, user_id, normalized)
        return {
            "id": jd.id,
            "user_id": user_id,
            "filename": jd.filename,
            "role_name": jd.role_name,
            "company_name": jd.company_name,
            "source_type": jd.source_type,
            "content_type": jd.content_type,
            "text_content": jd.text_content,
            "normalized_text": jd.normalized_text,
            "url": jd.url,
            "source_html": jd.source_html,
            "prompt_injection_detected": jd.prompt_injection_detected,
            "status": jd.status,
            "processing_error": jd.processing_error,
        }

    @staticmethod
    def _build_url_structure(text: str, role_name: str | None) -> dict:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        fields = {key: [] for key in ("responsibilities", "required_skills", "preferred_skills", "experience", "education", "certifications", "other_requirements")}
        current = "other_requirements"
        aliases = {
            "responsibilities": "responsibilities", "what you ll do": "responsibilities", "requirements": "required_skills",
            "required qualifications": "required_skills", "preferred qualifications": "preferred_skills", "preferred skills": "preferred_skills",
            "experience": "experience", "education": "education", "certifications": "certifications",
        }
        for line in lines:
            key = re.sub(r"[^a-z ]", "", line.lower()).strip()
            if key in aliases:
                current = aliases[key]
                continue
            fields[current].append(line)
        fields["job_title"] = role_name
        return fields

    @staticmethod
    def _sanitize_source_html(html: str) -> str:
        # Preserve the fetched page's visual structure while removing executable content.
        cleaned = re.sub(
            r"<(script|iframe|object|embed|form|noscript|template)[^>]*>.*?</\1>",
            "",
            html or "",
            flags=re.DOTALL | re.IGNORECASE,
        )
        cleaned = re.sub(
            r'''\s+on[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)''',
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r'''(href|src)\s*=\s*(["'])\s*javascript:[^"']*\2''',
            r"\1=\2#\2",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.strip()

    @staticmethod
    def _add_source_base_url(html: str, page_url: str) -> str:
        if not page_url:
            return html
        base_tag = f'<base href="{html_lib.escape(urljoin(page_url, "/"))}">'
        if re.search(r"<head[^>]*>", html, flags=re.IGNORECASE):
            return re.sub(
                r"(<head[^>]*>)",
                r"\1" + base_tag,
                html,
                count=1,
                flags=re.IGNORECASE,
            )
        return "<head>" + base_tag + "</head>" + html

    @staticmethod
    def _derive_job_metadata(text: str) -> tuple[str | None, str | None]:
        clean = re.sub(r"\s+", " ", text or "").strip()
        role = None
        company = None

        patterns = [
            r"(?:job title|role|position|title)\s*[:\-]\s*([^|,.]+)",
            r"(?:hiring|looking for|seeking)\s+(?:an?\s+)?([A-Z][^.!|]{2,100})",
        ]
        for pattern in patterns:
            match = re.search(pattern, clean, flags=re.IGNORECASE)
            if match:
                role = match.group(1).strip()
                break

        company_patterns = [
            r"(?:company|employer|organization)\s*[:\-]\s*([^|,.]+)",
            r"\bat\s+([A-Z][A-Za-z0-9& ._-]{2,80})(?:\s+(?:is|are|we|for|as)\b|[.!|,]|$)",
        ]
        for pattern in company_patterns:
            match = re.search(pattern, clean, flags=re.IGNORECASE)
            if match:
                company = match.group(1).strip()
                break

        if not role:
            first_line = next((line.strip() for line in (text or "").splitlines() if line.strip()), "")
            if 2 <= len(first_line.split()) <= 10 and len(first_line) <= 100:
                role = first_line

        return role[:255] if role else None, company[:255] if company else None

    @staticmethod
    def _extract_job_metadata_from_html(html: str, text_content: str) -> tuple[str | None, str | None]:
        scripts = re.findall(
            r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        for raw in scripts:
            try:
                payload = json.loads(html_lib.unescape(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            candidates = payload if isinstance(payload, list) else [payload]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("@type")
                if item_type == "JobPosting" or "JobPosting" in (item_type or []):
                    role = str(item.get("title") or "").strip() or None
                    organization = item.get("hiringOrganization") or {}
                    company = organization.get("name") if isinstance(organization, dict) else None
                    if role or company:
                        return role[:255] if role else None, str(company)[:255] if company else None

        role = JobDescriptionService._extract_job_title_from_html(html) or None
        _, company = JobDescriptionService._derive_job_metadata(text_content)
        return role[:255] if role else None, company[:255] if company else None

    def _process_chunks_and_embeddings(
        self,
        job_description_id: int,
        user_id: int,
        text_content: str,
    ) -> None:
        chunks = chunk_text(text_content)
        stored_chunks = DocumentChunkRepository(self.db).upsert_chunks(
            job_description_id=job_description_id,
            chunks=chunks,
        )
        if not settings.GEMINI_API_KEY or not stored_chunks:
            return

        try:
            embedding_service = EmbeddingService(
                repository=EmbeddingRepository(self.db),
                provider=GeminiEmbeddingProvider(),
                user_id=user_id,
            )
            embedding_service.process_chunks(
                source_type="job_description_chunk",
                source_id=job_description_id,
                document_id=job_description_id,
                chunks=stored_chunks,
                user_id=user_id,
            )
        except Exception as exc:
            jd = self.repository.get_for_user(job_description_id, user_id)
            if jd is not None:
                jd.status = "failed"
                jd.processing_error = "Job description embedding generation failed."
                self.db.add(jd)
                self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Job description embedding generation failed.",
            ) from exc

    @staticmethod
    def _extract_job_title_from_html(html: str) -> str:
        scripts = re.findall(
            r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        for raw in scripts:
            try:
                payload = json.loads(html_lib.unescape(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            candidates = payload if isinstance(payload, list) else [payload]
            for item in candidates:
                if isinstance(item, dict):
                    item_type = item.get("@type")
                    if item_type == "JobPosting" or "JobPosting" in (item_type or []):
                        title = str(item.get("title") or "").strip()
                        if title:
                            return re.sub(r"\s+", " ", title)
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.DOTALL | re.IGNORECASE)
        if title_match:
            title = re.sub(r"<[^>]+>", " ", title_match.group(1))
            title = re.sub(r"\s+", " ", html_lib.unescape(title)).strip()
            title = re.split(r"\s*\|\s*|\s+[-â€“â€”]\s+Job ID\b", title, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            if title:
                return title

        match = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.DOTALL | re.IGNORECASE)
        if match:
            title = re.sub(r"<[^>]+>", " ", match.group(1))
            title = re.sub(r"\s+", " ", html_lib.unescape(title)).strip()
            return title[:255]
        return ""

    @staticmethod
    def _clean_html_fragment(value: str) -> str:
        value = html_lib.unescape(value or "")
        value = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
        value = re.sub(r"<[^>]+>", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _extract_structured_job_description(root) -> str:
        if root is None:
            return ""
        scripts = root.xpath('//script[@type="application/ld+json"]/text()')
        for raw in scripts:
            try:
                payload = json.loads(html_lib.unescape(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            candidates = payload if isinstance(payload, list) else [payload]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("@type")
                is_job_posting = item_type == "JobPosting" or "JobPosting" in (item_type or [])
                if not is_job_posting:
                    continue
                description = JobDescriptionService._clean_html_fragment(
                    str(item.get("description") or "")
                )
                if len(description) >= 80:
                    return description
        return ""

    @staticmethod
    def _extract_meta_job_description(root) -> str:
        if root is None:
            return ""
        candidates = (
            root.xpath('//meta[@property="og:description"]/@content')
            + root.xpath('//meta[@name="description"]/@content')
        )
        for candidate in candidates:
            description = JobDescriptionService._clean_html_fragment(candidate)
            if len(description) >= 80:
                return description
        return ""

    @staticmethod
    def _extract_text_from_html(html: str) -> str:
        try:
            root = lxml_html.fromstring(html or "")
        except (TypeError, ValueError):
            root = None

        # Many modern job sites render the visible posting client-side. Prefer
        # structured JobPosting data and OpenGraph/meta descriptions before
        # falling back to visible HTML parsing.
        structured = JobDescriptionService._extract_structured_job_description(root)
        if structured:
            return structured

        meta_description = JobDescriptionService._extract_meta_job_description(root)
        if meta_description:
            return meta_description

        if root is not None:
            job_roots = root.xpath('//*[@id="job-detail"] | //*[@id="job-description"] | //main | //article')
            container = max(job_roots, key=lambda node: len(node.text_content())) if job_roots else root

            for bad in container.xpath(
                './/script | .//style | .//noscript | .//svg | '
                './/nav | .//footer | .//header | .//aside | .//form | .//iframe | .//*[contains(@class,"cookie")] | .//*[contains(@class,"advert")] | .//*[contains(@class,"social")]'
            ):
                bad.drop_tree()

            lines: list[str] = []

            title_nodes = container.xpath('.//h1[contains(@class,"title")]')
            if title_nodes:
                title = re.sub(r"\s+", " ", title_nodes[0].text_content()).strip()
                if title:
                    lines.append(title)

            meta_nodes = container.xpath('.//*[contains(@class,"details-line")]')
            for node in meta_nodes:
                meta = re.sub(r"\s+", " ", node.text_content()).strip()
                if meta and meta.lower() not in {x.lower() for x in lines}:
                    lines.append(meta)

            content_nodes = container.xpath('.//div[contains(@class,"content")]')
            content_root = content_nodes[0] if content_nodes else container

            for node in content_root.xpath('.//h1 | .//h2 | .//p | .//li'):
                text = html_lib.unescape(node.text_content())
                text = re.sub(r"\s+", " ", text).strip(" \t?-")
                if text:
                    lines.append(text)

            detail_nodes = container.xpath('.//div[contains(@class,"sidebar")]//li')
            for node in detail_nodes:
                text = re.sub(r"\s+", " ", html_lib.unescape(node.text_content())).strip(" \t?-")
                if text and text.lower() not in {x.lower() for x in lines}:
                    lines.append(text)

            deduped: list[str] = []
            seen: set[str] = set()
            for line in lines:
                key = line.lower()
                if key not in seen:
                    seen.add(key)
                    deduped.append(line)

            if deduped:
                return "\n".join(deduped)

        fallback_lines: list[str] = []
        if root is not None:
            for node in root.xpath('.//body//*'):
                if node.tag.lower() not in {"h1", "h2", "h3", "p", "li"}:
                    continue
                text = html_lib.unescape(node.text_content())
                text = re.sub(r"\s+", " ", text).strip(" \t?-")
                if text and text.lower() not in {x.lower() for x in fallback_lines}:
                    fallback_lines.append(text)
            if fallback_lines:
                return "\n".join(fallback_lines)

        cleaned_html = re.sub(
            r"<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>",
            " ",
            html or "",
            flags=re.DOTALL | re.IGNORECASE,
        )
        cleaned_html = re.sub(
            r"</(p|li|h1|h2|h3|h4|h5|h6|div|section|article|br)[^>]*>",
            "\n",
            cleaned_html,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"<[^>]+>", " ", cleaned_html)
        lines = []
        for raw_line in html_lib.unescape(text).splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip(" \t?-")
            if line:
                lines.append(line)
        return "\n".join(lines).strip()

