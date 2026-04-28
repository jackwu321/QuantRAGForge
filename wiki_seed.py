from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from wiki_schemas import ConceptArticle, serialize_concept


@dataclass(frozen=True)
class SeedConcept:
    slug: str
    title: str
    aliases: tuple[str, ...]
    content_types: tuple[str, ...]
    definition: str


SEED_CONCEPTS: tuple[SeedConcept, ...] = (
    SeedConcept(
        slug="factor-models",
        title="Factor Models",
        aliases=("因子模型", "多因子"),
        content_types=("methodology",),
        definition="Multi-factor frameworks describing cross-sectional return drivers.",
    ),
    SeedConcept(
        slug="factor-timing",
        title="Factor Timing",
        aliases=("因子择时",),
        content_types=("methodology",),
        definition="Methods that vary factor exposure over time based on signals or regime.",
    ),
    SeedConcept(
        slug="regime-detection",
        title="Regime Detection",
        aliases=("风格切换", "状态识别"),
        content_types=("methodology",),
        definition="Identification of market states that change which strategies work.",
    ),
    SeedConcept(
        slug="momentum-strategies",
        title="Momentum Strategies",
        aliases=("动量策略", "momentum"),
        content_types=("strategy",),
        definition="Trading rules that buy past winners or trend assets.",
    ),
    SeedConcept(
        slug="etf-rotation",
        title="ETF Rotation",
        aliases=("etf轮动", "行业轮动"),
        content_types=("strategy", "allocation"),
        definition="Periodic rebalancing across ETFs/sectors based on a ranking signal.",
    ),
    SeedConcept(
        slug="risk-parity",
        title="Risk Parity",
        aliases=("风险平价",),
        content_types=("allocation", "risk_control"),
        definition="Portfolio construction that allocates by risk contribution rather than capital weight.",
    ),
    SeedConcept(
        slug="volatility-targeting",
        title="Volatility Targeting",
        aliases=("波动率择时", "风险预算"),
        content_types=("risk_control",),
        definition="Position sizing based on rolling realized or implied volatility.",
    ),
)


def _seed_to_concept(seed: SeedConcept, today: str) -> ConceptArticle:
    return ConceptArticle(
        title=seed.title,
        slug=seed.slug,
        aliases=list(seed.aliases),
        status="stable",
        related_concepts=[],
        sources=[],
        content_types=list(seed.content_types),
        last_compiled=today,
        compile_version=0,
        synthesis="_pending: no sources yet_",
        definition=seed.definition,
        key_idea_blocks=[],
        variants=[],
        common_combinations=[],
        transfer_targets=[],
        failure_modes=[],
        open_questions=[],
        source_basenames=[],
    )


def bootstrap_wiki(wiki_dir: Path) -> list[Path]:
    """Create wiki/{concepts,sources}/ and write stubs for each seed concept.

    Idempotent: existing concept stubs are NOT overwritten.
    Returns the list of files actually created.
    """
    concepts_dir = wiki_dir / "concepts"
    sources_dir = wiki_dir / "sources"
    concepts_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    created: list[Path] = []
    for seed in SEED_CONCEPTS:
        path = concepts_dir / f"{seed.slug}.md"
        if path.exists():
            continue
        concept = _seed_to_concept(seed, today)
        path.write_text(serialize_concept(concept), encoding="utf-8")
        created.append(path)
    return created
