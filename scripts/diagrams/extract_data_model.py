#!/usr/bin/env python3
"""Extract data model ERD from SQLModel classes in db_models.py."""

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_MODELS_PATH = PROJECT_ROOT / "teleclaude" / "core" / "db_models.py"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "diagrams" / "data-model.mmd"


@dataclass
class FieldInfo:
    name: str
    type: str
    pk: str = ""
    fk: str = ""


@dataclass
class ModelInfo:
    class_name: str
    table_name: str
    fields: list[FieldInfo] = field(default_factory=list)


def parse_sqlmodel_classes(tree: ast.Module) -> list[ModelInfo]:
    """Extract SQLModel table classes with their fields and metadata."""
    models: list[ModelInfo] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Check if class inherits from SQLModel with table=True
        is_table = False
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "SQLModel":
                is_table = True
        for kw in node.keywords:
            if kw.arg == "table" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                is_table = True

        if not is_table:
            continue

        # Extract table name from __tablename__
        table_name = node.name
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "__tablename__":
                        if isinstance(item.value, ast.Constant):
                            table_name = str(item.value.value)

        # Extract fields from annotated assignments
        fields: list[FieldInfo] = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                field_name = item.target.id
                if field_name.startswith("__"):
                    continue

                field_type = _resolve_type(item.annotation)
                is_pk = False
                is_fk = False
                fk_ref = ""

                # Check Field() call for metadata
                if item.value and isinstance(item.value, ast.Call):
                    for kw in item.value.keywords:
                        if kw.arg == "primary_key" and isinstance(kw.value, ast.Constant):
                            is_pk = bool(kw.value.value)
                        if kw.arg == "foreign_key" and isinstance(kw.value, ast.Constant):
                            is_fk = True
                            fk_ref = str(kw.value.value)

                fields.append(
                    FieldInfo(
                        name=field_name,
                        type=field_type,
                        pk="PK" if is_pk else "",
                        fk=f"FK ({fk_ref})" if is_fk else "",
                    )
                )

        models.append(
            ModelInfo(
                class_name=node.name,
                table_name=table_name,
                fields=fields,
            )
        )

    return models


def _resolve_type(node: ast.expr) -> str:
    """Resolve type annotation to a readable string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Subscript):
        base = _resolve_type(node.value)
        inner = _resolve_type(node.slice)
        return f"{base}[{inner}]"
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _resolve_type(node.left)
        right = _resolve_type(node.right)
        return f"{left} | {right}"
    return "Any"


def generate_mermaid(models: list[ModelInfo]) -> str:
    """Generate Mermaid ER diagram from parsed models."""
    lines: list[str] = [
        "---",
        "title: Data Model (SQLModel)",
        "---",
        "erDiagram",
    ]

    for model in models:
        lines.append(f"    {model.table_name} {{")
        for f in model.fields:
            type_str = f.type.replace("[", "_").replace("]", "").replace(" | ", "_or_")
            markers = []
            if f.pk:
                markers.append(f.pk)
            if f.fk:
                markers.append(f.fk)
            marker_str = f' "{" ".join(markers)}"' if markers else ""
            lines.append(f"        {type_str} {f.name}{marker_str}")
        lines.append("    }")
        lines.append("")

    # Add relationships based on FK references
    table_names = {m.table_name for m in models}
    for model in models:
        for f in model.fields:
            if f.fk and "(" in f.fk:
                ref_table = f.fk.split("(")[1].split(".")[0].strip()
                if ref_table in table_names:
                    lines.append(f"    {ref_table} ||--o{{ {model.table_name} : has")

    return "\n".join(lines) + "\n"


def main() -> None:
    if not DB_MODELS_PATH.exists():
        print(f"ERROR: {DB_MODELS_PATH} not found", file=sys.stderr)
        sys.exit(1)

    source = DB_MODELS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DB_MODELS_PATH))

    models = parse_sqlmodel_classes(tree)
    if not models:
        print("WARNING: No SQLModel table classes found", file=sys.stderr)

    mermaid = generate_mermaid(models)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(mermaid, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
