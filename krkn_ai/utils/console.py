from typing import List

from rich.console import Console
from rich.table import Table

from krkn_ai.models.app import CommandRunResult
from krkn_ai.utils.logger import get_logger
from krkn_ai.utils.output import format_duration

logger = get_logger(__name__)
_console = Console(highlight=False)


def _to_pct(score: float, num_components: int) -> str:
    if num_components == 0:
        return "0.0%"
    return f"{score / num_components * 100:.1f}%"


def print_generation_table(
    generation_id: int,
    results: List[CommandRunResult],
    num_components: int = 4,
) -> None:
    sorted_results = sorted(
        results,
        key=lambda r: r.fitness_result.fitness_score,
        reverse=True,
    )
    best = sorted_results[0] if sorted_results else None

    table = Table(
        title=f"Generation {generation_id + 1} Results",
        title_style="bold cyan",
        show_lines=False,
        pad_edge=True,
    )
    table.add_column("ID", style="dim", justify="right", width=4)
    table.add_column("Scenario", style="white", min_width=20, max_width=30)
    table.add_column("SLO", justify="right")
    table.add_column("HC Fail", justify="right")
    table.add_column("HC Resp", justify="right")
    table.add_column("Krkn", justify="right")
    table.add_column("Fitness", justify="right", style="bold")

    for r in sorted_results:
        fr = r.fitness_result
        slo_total = sum(s.weighted_score for s in fr.scores)
        is_best = r is best
        style = "bold green" if is_best else ""

        table.add_row(
            str(r.scenario_id),
            r.scenario.name,
            f"{slo_total:.3f}",
            f"{fr.health_check_failure_score:.3f}",
            f"{fr.health_check_response_time_score:.3f}",
            f"{fr.krkn_failure_score:.3f}",
            _to_pct(fr.fitness_score, num_components),
            style=style,
        )

    _console.print(table)

    if best:
        _console.print(
            f"  Best: [bold]{best.scenario.name}[/bold]"
            f" ({_to_pct(best.fitness_result.fitness_score, num_components)})\n"
        )
        logger.debug(
            "Generation %d best: %s (%.4f)",
            generation_id + 1,
            best.scenario.name,
            best.fitness_result.fitness_score,
        )


def print_run_summary(
    best_of_generation: List[CommandRunResult],
    completed_generations: int,
    elapsed_seconds: float,
    num_components: int = 4,
) -> None:
    if not best_of_generation:
        return

    table = Table(
        title="Run Summary",
        title_style="bold cyan",
        show_lines=False,
    )
    table.add_column("Generation", justify="right", style="dim")
    table.add_column("Best Scenario", min_width=20, max_width=30)
    table.add_column("Fitness", justify="right", style="bold")

    overall_best = max(
        best_of_generation,
        key=lambda r: r.fitness_result.fitness_score,
    )

    for i, r in enumerate(best_of_generation):
        is_best = r is overall_best
        table.add_row(
            str(i + 1),
            r.scenario.name,
            _to_pct(r.fitness_result.fitness_score, num_components),
            style="bold green" if is_best else "",
        )

    _console.print()
    _console.print(table)
    _console.print(
        f"  Completed [bold]{completed_generations}[/bold] generations "
        f"in [bold]{format_duration(elapsed_seconds)}[/bold]"
    )
    _console.print(
        f"  Overall best: [bold green]{overall_best.scenario.name}[/bold green] "
        f"({_to_pct(overall_best.fitness_result.fitness_score, num_components)})\n"
    )
