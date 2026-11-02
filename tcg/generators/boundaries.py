"""Domain-agnostic, template-driven Boundary Value Analysis (BVA) test generator.

Follows Hexagonal Architecture: Contains NO hardcoded domain strings,
specific signal names, or hardware assumptions. All phrasing, templates,
and fixture steps are injected by the caller or configuration.
"""
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class BoundaryTestConfig:
    """Configuration for generating a boundary value test case."""
    name: str
    min_val: Decimal | float | int
    max_val: Decimal | float | int
    nominal_val: Decimal | float | int | None = None
    unit: str = ''
    epsilon: Decimal | float | int | None = None
    set_template: str = "{name} = {val}{unit}"
    check_template: str = "{name} == {val}{unit}"
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    test_id: str | None = None
    include_out_of_bounds: bool = False


def calculate_boundary_points(
    min_val: Decimal,
    max_val: Decimal,
    nominal_val: Decimal | None = None,
    epsilon: Decimal | None = None,
    include_out_of_bounds: bool = False,
) -> list[Decimal]:
    """Calculates ordered test points according to Boundary Value Analysis principles."""
    if min_val > max_val:
        raise ValueError(f"min_val ({min_val}) cannot be greater than max_val ({max_val})")

    nominal = nominal_val if nominal_val is not None else (min_val + max_val) / Decimal('2')

    points = []
    if include_out_of_bounds and epsilon is not None:
        points.append(min_val - epsilon)

    points.append(min_val)
    if min_val < nominal < max_val:
        points.append(nominal)
    points.append(max_val)

    if include_out_of_bounds and epsilon is not None:
        points.append(max_val + epsilon)

    return points


def generate_boundary_spec(config: BoundaryTestConfig) -> str:
    """Generates a complete, deterministic test specification using configurable templates."""
    min_d = Decimal(str(config.min_val))
    max_d = Decimal(str(config.max_val))
    nom_d = Decimal(str(config.nominal_val)) if config.nominal_val is not None else None
    eps_d = Decimal(str(config.epsilon)) if config.epsilon is not None else None

    points = calculate_boundary_points(
        min_val=min_d,
        max_val=max_d,
        nominal_val=nom_d,
        epsilon=eps_d,
        include_out_of_bounds=config.include_out_of_bounds,
    )

    u_spaced = f" {config.unit}" if config.unit else ""
    step_num = 10

    lines = []
    # Precondition section
    lines.append("Precondition")
    for pre in config.preconditions:
        lines.append(f"{step_num}. {pre.strip()}")
        step_num += 10

    # Action & Expected Result
    action_lines = []
    expected_lines = []
    for pt in points:
        action_text = config.set_template.format(
            name=config.name,
            val=pt,
            unit=u_spaced,
        )
        expected_text = config.check_template.format(
            name=config.name,
            val=pt,
            unit=u_spaced,
        )
        action_lines.append(f"{step_num}. {action_text.strip()}")
        expected_lines.append(f"{step_num}. {expected_text.strip()}")
        step_num += 10

    lines.append("")
    lines.append("Action")
    lines.extend(action_lines)

    lines.append("")
    lines.append("Expected Result")
    lines.extend(expected_lines)

    # Postcondition section
    lines.append("")
    lines.append("Postcondition")
    for post in config.postconditions:
        lines.append(f"{step_num}. {post.strip()}")
        step_num += 10

    lines.append("")
    return "\n".join(lines)


def generate_boundary_suite(
    variable_definitions: dict[str, dict],
    target_variables: list[str],
    set_template: str,
    check_template: str,
    output_dir: Path | str,
    preconditions: list[str] | tuple[str, ...] = (),
    postconditions: list[str] | tuple[str, ...] = (),
    file_prefix: str = "tc_bva_",
) -> list[Path]:
    """Generates boundary value test specifications for multiple variables without hardcoding domain specifics."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_files = []

    for name in target_variables:
        if name not in variable_definitions:
            raise KeyError(f"Variable {name!r} not found in variable definitions")
        meta = variable_definitions[name]
        min_v = meta.get("min", meta.get("minimum", 0))
        max_v = meta.get("max", meta.get("maximum", 100))
        nom_v = meta.get("default", meta.get("nominal", None))
        unit = meta.get("unit", "")

        cfg = BoundaryTestConfig(
            name=name,
            min_val=min_v,
            max_val=max_v,
            nominal_val=nom_v,
            unit=unit,
            set_template=set_template,
            check_template=check_template,
            preconditions=tuple(preconditions),
            postconditions=tuple(postconditions),
        )
        spec_text = generate_boundary_spec(cfg)
        out_file = out_dir / f"{file_prefix}{name.lower()}.txt"
        out_file.write_text(spec_text, encoding="utf-8")
        generated_files.append(out_file)

    return generated_files
