"""Deterministic proposal formatting; no clinical text generation."""
LABELS = {"complaints": "Со слов пациента", "anamnesis": "Анамнез заболевания",
          "dispensary_treatment": "Прежнее лечение", "dynamics": "Уточнение динамики",
          "sleep": "Сон (со слов пациента)", "sleep_hours": "Продолжительность сна, ч",
          "sleep_days": "Период этой продолжительности, дней"}


def section_text(proposals):
    lines = []
    for proposal in proposals:
        value = proposal.get("clinician_value", proposal["value"])
        if isinstance(value, list):
            value = "; ".join(value)
        lines.append(f"{LABELS[proposal['target']]}: {value}")
    return "\n".join(lines)
