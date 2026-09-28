from app.services.benchmark_service import BenchmarkService


def records(role, texts):
    return [{"role_name": role, "text": text} for text in texts]


def test_role_normalization_groups_equivalent_titles_but_not_unrelated_roles():
    service = BenchmarkService()

    assert service.normalize_role("Backend Developer") == "backend engineering"
    assert service.normalize_role("Backend Engineer") == "backend engineering"
    assert service.normalize_role("Frontend Developer") == "frontend engineering"
    assert service.normalize_role("Product Manager") == "product management"
    assert service.normalize_role("Backend Engineer") != service.normalize_role("Data Scientist")


def test_backend_role_benchmark_is_role_specific_and_compares_jd_and_resume():
    service = BenchmarkService()
    result = service.summarize(
        records("Backend Developer", [
            "Backend Engineer Python FastAPI Docker design services",
            "Backend Engineer Python FastAPI PostgreSQL build APIs",
        ]) + records("Frontend Developer", ["Frontend Developer React CSS JavaScript"]),
        role_name="Backend Engineer",
        current_jd_text="Backend Engineer Python FastAPI",
        resume_text="Backend Engineer Python Docker",
    )

    assert result["normalized_role_family"] == "backend engineering"
    assert result["sample_size"] == 2
    assert result["data_sufficiency"] == "LIMITED"
    assert {item["item"] for item in result["common_skills"]} >= {"python", "fastapi"}
    assert "fastapi" in result["current_jd_comparison"]["signals_in_current_jd"]
    assert "python" in result["resume_comparison"]["benchmark_common_and_present"]
    assert "fastapi" in result["resume_comparison"]["benchmark_common_but_not_evidenced"]


def test_frontend_and_software_engineering_benchmarks_remain_separate():
    service = BenchmarkService()
    result = service.summarize(
        records("Software Engineer", [
            "Software Engineer Python SQL APIs",
            "Software Engineer Python Docker services",
        ]) + records("Frontend Developer", [
            "Frontend Developer React TypeScript CSS",
            "Frontend Developer React JavaScript UI",
        ]),
        role_name="Frontend Engineer",
    )

    skills = {item["item"] for item in result["common_skills"]}
    assert result["normalized_role_family"] == "frontend engineering"
    assert skills == {"react"}
    assert "python" not in skills


def test_limited_and_insufficient_data_are_explicit_without_fake_statistics():
    service = BenchmarkService()
    insufficient = service.summarize(records("Backend Engineer", ["Python FastAPI"]), role_name="Backend Engineer")
    limited = service.summarize(records("Backend Engineer", ["Python FastAPI", "Python Docker"]), role_name="Backend Engineer")

    assert insufficient["data_sufficiency"] == "INSUFFICIENT"
    assert insufficient["common_skills"] == []
    assert limited["data_sufficiency"] == "LIMITED"
    assert limited["common_skills"]
    assert "market" not in limited["summary"].lower()


def test_benchmark_does_not_treat_common_skill_as_current_jd_requirement():
    result = BenchmarkService().summarize(
        records("Backend Engineer", ["Python FastAPI", "Python FastAPI"]),
        role_name="Backend Engineer",
        current_jd_text="Python",
        resume_text="Python developer",
    )

    assert "fastapi" in result["current_jd_comparison"]["common_but_absent_from_current_jd"]
    assert "fastapi" in result["resume_comparison"]["benchmark_common_but_not_evidenced"]
    assert result["data_sufficiency"] == "LIMITED"