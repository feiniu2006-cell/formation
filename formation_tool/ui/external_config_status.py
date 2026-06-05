"""Status and warning helpers for external db_config.json loading."""


def find_missing_selected_databases(database_configs, selected_databases):
    """Return selected database aliases that are not present in current config."""
    configured = set((database_configs or {}).keys())
    missing = []
    seen = set()
    for label, db_name in selected_databases:
        db_name = (db_name or "").strip()
        if not db_name or db_name in configured or db_name in seen:
            continue
        seen.add(db_name)
        missing.append((label, db_name))
    return missing


def build_missing_database_warning(missing_databases, *, external_source=None, load_error=None):
    """Build a user-facing warning for missing selected database aliases."""
    lines = []
    if external_source:
        lines.append(f"已加载外部 db_config.json：{external_source}")
        lines.append("但当前界面选择的数据库别名在配置中不存在：")
    elif load_error:
        lines.append("外部 db_config.json 加载失败，当前使用内置配置。")
        lines.append("同时，当前界面选择的数据库别名在配置中不存在：")
    else:
        lines.append("当前数据库配置中缺少界面已选择的数据库别名：")

    lines.extend(f"- {label}: {db_name}" for label, db_name in missing_databases)
    lines.append("")
    lines.append("请检查 db_config.json 中是否包含这些顶层配置项，或在主界面下拉框重新选择可用数据库。")
    return "\n".join(lines)
