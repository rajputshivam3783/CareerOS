"""Curated seed catalog for the canonical Skill Intelligence layer.

This is an editorial catalog, the same posture as
app.resume_ai.skill_gap._ADJACENT_SKILLS: a small, fixed, human-curated
set — not something an AI call generates or extends at request time.
Admins can add more skills/aliases/relationships via the admin API
(app.api.skill_intelligence); ``is_admin_added`` distinguishes those
rows from this seed set.

Deliberately overlaps with app.services.career.SKILLS (the V6/V8
matching vocabulary) rather than forking a parallel list — every name
in that vocabulary that has an obvious canonical form is included here
too, so app.skill_intelligence.gap can resolve resume/job skill
strings against one shared catalog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Skill, SkillAlias, SkillRelationship


@dataclass
class SkillSeed:
    canonical_name: str
    display_name: str
    category: str  # technical / soft
    subcategory: str
    difficulty: str = "beginner"
    description: str | None = None
    aliases: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Canonical skills
# ---------------------------------------------------------------------------

SKILLS_SEED: list[SkillSeed] = [
    # -- Programming languages -------------------------------------------------
    SkillSeed("python", "Python", "technical", "programming_language", "beginner",
              "General-purpose language widely used for scripting, data, ML, and backends.",
              aliases=["py"]),
    SkillSeed("java", "Java", "technical", "programming_language", "beginner",
              aliases=[]),
    SkillSeed("javascript", "JavaScript", "technical", "programming_language", "beginner",
              aliases=["js"]),
    SkillSeed("typescript", "TypeScript", "technical", "programming_language", "intermediate",
              aliases=["ts"]),
    SkillSeed("sql", "SQL", "technical", "programming_language", "beginner", aliases=[]),
    SkillSeed("c++", "C++", "technical", "programming_language", "intermediate", aliases=["cpp"]),
    SkillSeed("go", "Go", "technical", "programming_language", "intermediate", aliases=["golang"]),

    # -- Frameworks --------------------------------------------------------
    SkillSeed("react", "React", "technical", "framework", "intermediate", aliases=["reactjs"]),
    SkillSeed("next.js", "Next.js", "technical", "framework", "advanced", aliases=["nextjs"]),
    SkillSeed("spring boot", "Spring Boot", "technical", "framework", "intermediate", aliases=["springboot"]),
    SkillSeed("fastapi", "FastAPI", "technical", "framework", "intermediate", aliases=[]),
    SkillSeed("django", "Django", "technical", "framework", "intermediate", aliases=[]),
    SkillSeed("node.js", "Node.js", "technical", "framework", "intermediate", aliases=["nodejs", "node"]),

    # -- Databases -----------------------------------------------------------
    SkillSeed("postgresql", "PostgreSQL", "technical", "database", "intermediate", aliases=["postgres"]),
    SkillSeed("mysql", "MySQL", "technical", "database", "beginner", aliases=[]),
    SkillSeed("mongodb", "MongoDB", "technical", "database", "intermediate", aliases=["mongo"]),
    SkillSeed("redis", "Redis", "technical", "database", "intermediate", aliases=[]),

    # -- Cloud -----------------------------------------------------------
    SkillSeed("aws", "AWS", "technical", "cloud", "intermediate", aliases=["amazon web services"]),
    SkillSeed("azure", "Azure", "technical", "cloud", "intermediate", aliases=["microsoft azure"]),
    SkillSeed("gcp", "Google Cloud Platform", "technical", "cloud", "intermediate",
              aliases=["google cloud", "google cloud platform"]),

    # -- DevOps -----------------------------------------------------------
    SkillSeed("docker", "Docker", "technical", "devops", "intermediate", aliases=[]),
    SkillSeed("kubernetes", "Kubernetes", "technical", "devops", "advanced", aliases=["k8s"]),
    SkillSeed("ci/cd", "CI/CD", "technical", "devops", "intermediate", aliases=["cicd", "continuous integration"]),
    SkillSeed("terraform", "Terraform", "technical", "devops", "advanced", aliases=[]),

    # -- Data science -----------------------------------------------------
    SkillSeed("numpy", "NumPy", "technical", "data_science", "beginner", aliases=[]),
    SkillSeed("pandas", "Pandas", "technical", "data_science", "intermediate", aliases=[]),
    SkillSeed("data analysis", "Data Analysis", "technical", "data_science", "beginner", aliases=[]),
    SkillSeed("power bi", "Power BI", "technical", "data_science", "beginner", aliases=["powerbi"]),
    SkillSeed("excel", "Excel", "technical", "data_science", "beginner", aliases=["ms excel", "microsoft excel"]),

    # -- Machine learning / AI -----------------------------------------------
    SkillSeed("machine learning", "Machine Learning", "technical", "machine_learning", "advanced", aliases=["ml"]),
    SkillSeed("scikit-learn", "scikit-learn", "technical", "machine_learning", "intermediate",
              aliases=["sklearn"]),
    SkillSeed("deep learning", "Deep Learning", "technical", "ai", "expert", aliases=["dl"]),
    SkillSeed("nlp", "Natural Language Processing", "technical", "ai", "advanced",
              aliases=["natural language processing"]),
    SkillSeed("prompt engineering", "Prompt Engineering", "technical", "ai", "intermediate", aliases=[]),

    # -- Cybersecurity -----------------------------------------------------
    SkillSeed("network security", "Network Security", "technical", "cybersecurity", "advanced", aliases=[]),
    SkillSeed("penetration testing", "Penetration Testing", "technical", "cybersecurity", "advanced",
              aliases=["pentesting", "pen testing"]),
    SkillSeed("cryptography", "Cryptography", "technical", "cybersecurity", "advanced", aliases=[]),

    # -- Tools -----------------------------------------------------------
    SkillSeed("git", "Git", "technical", "tool", "beginner", aliases=[]),
    SkillSeed("linux", "Linux", "technical", "tool", "intermediate", aliases=[]),
    SkillSeed("data structures", "Data Structures", "technical", "tool", "intermediate", aliases=["dsa"]),

    # -- Soft skills -----------------------------------------------------
    SkillSeed("communication", "Communication", "soft", "communication", "beginner", aliases=[]),
    SkillSeed("public speaking", "Public Speaking", "soft", "communication", "intermediate", aliases=[]),
    SkillSeed("leadership", "Leadership", "soft", "leadership", "intermediate", aliases=[]),
    SkillSeed("team management", "Team Management", "soft", "leadership", "advanced", aliases=[]),
    SkillSeed("problem solving", "Problem Solving", "soft", "problem_solving", "beginner", aliases=[]),
    SkillSeed("critical thinking", "Critical Thinking", "soft", "problem_solving", "intermediate", aliases=[]),
]

# ---------------------------------------------------------------------------
# Skill graph — (from_canonical, relationship_type, to_canonical)
# relationship_type: prerequisite | related | advanced_version | alternative
#                     | complementary
# ---------------------------------------------------------------------------

RELATIONSHIPS_SEED: list[tuple[str, str, str]] = [
    # The exact worked example from the V20.5 spec:
    # Python -> NumPy -> Pandas -> Machine Learning -> Deep Learning
    ("python", "prerequisite", "numpy"),
    ("numpy", "prerequisite", "pandas"),
    ("pandas", "prerequisite", "machine learning"),
    ("machine learning", "prerequisite", "deep learning"),
    ("machine learning", "related", "scikit-learn"),
    ("deep learning", "related", "nlp"),
    ("python", "prerequisite", "data analysis"),
    ("sql", "related", "data analysis"),
    ("data analysis", "related", "power bi"),
    ("data analysis", "related", "excel"),
    # Web track
    ("javascript", "prerequisite", "typescript"),
    ("javascript", "prerequisite", "react"),
    ("typescript", "related", "react"),
    ("react", "advanced_version", "next.js"),
    ("node.js", "related", "javascript"),
    # Backend / JVM track
    ("java", "prerequisite", "spring boot"),
    ("python", "alternative", "java"),
    ("python", "prerequisite", "fastapi"),
    ("python", "prerequisite", "django"),
    # Cloud / DevOps
    ("docker", "prerequisite", "kubernetes"),
    ("docker", "related", "ci/cd"),
    ("kubernetes", "related", "terraform"),
    ("aws", "alternative", "azure"),
    ("aws", "alternative", "gcp"),
    ("azure", "alternative", "gcp"),
    ("docker", "complementary", "aws"),
    # Databases
    ("sql", "prerequisite", "postgresql"),
    ("sql", "prerequisite", "mysql"),
    ("postgresql", "alternative", "mysql"),
    ("postgresql", "alternative", "mongodb"),
    ("redis", "complementary", "postgresql"),
    # Security
    ("network security", "related", "penetration testing"),
    ("network security", "prerequisite", "cryptography"),
    # Tools
    ("git", "complementary", "docker"),
    ("data structures", "related", "machine learning"),
    # Soft skills
    ("communication", "related", "public speaking"),
    ("leadership", "related", "team management"),
    ("problem solving", "related", "critical thinking"),
    ("problem solving", "complementary", "communication"),
]


def seed_skills(db: Session) -> dict:
    """Idempotently insert the seed catalog. Safe to call on every
    startup — existing rows (matched by canonical_name / alias /
    relationship triple) are left untouched; only missing rows are
    added. Never overwrites an admin's edits to an existing row."""

    existing = {s.canonical_name: s for s in db.scalars(select(Skill))}
    created_skills = 0
    created_aliases = 0

    for seed in SKILLS_SEED:
        skill = existing.get(seed.canonical_name)
        if skill is None:
            skill = Skill(
                canonical_name=seed.canonical_name,
                display_name=seed.display_name,
                category=seed.category,
                subcategory=seed.subcategory,
                difficulty=seed.difficulty,
                description=seed.description,
                is_admin_added=False,
                created_at=datetime.utcnow(),
            )
            db.add(skill)
            db.flush()
            existing[seed.canonical_name] = skill
            created_skills += 1

        existing_aliases = {a.alias for a in db.scalars(select(SkillAlias).where(SkillAlias.skill_id == skill.id))}
        for alias in seed.aliases:
            if alias not in existing_aliases:
                db.add(SkillAlias(skill_id=skill.id, alias=alias))
                created_aliases += 1

    db.flush()
    name_to_id = {name: sk.id for name, sk in existing.items()}
    existing_rels = {
        (r.from_skill_id, r.to_skill_id, r.relationship_type) for r in db.scalars(select(SkillRelationship))
    }
    created_relationships = 0
    for from_name, rel_type, to_name in RELATIONSHIPS_SEED:
        from_id = name_to_id.get(from_name)
        to_id = name_to_id.get(to_name)
        if from_id is None or to_id is None:
            continue
        key = (from_id, to_id, rel_type)
        if key not in existing_rels:
            db.add(SkillRelationship(from_skill_id=from_id, to_skill_id=to_id, relationship_type=rel_type))
            existing_rels.add(key)
            created_relationships += 1

    db.commit()
    return {
        "skills_created": created_skills,
        "aliases_created": created_aliases,
        "relationships_created": created_relationships,
        "total_skills": len(existing),
    }
