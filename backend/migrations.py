"""
轻量级 schema 自愈（SQLite / Postgres 通用）。
create_all 只建新表，不会给已存在的表加列；本模块扫描元数据与库内实际列差异，
自动 ALTER TABLE ADD COLUMN，避免"模型改了、演示库还是旧结构"导致的运行时错误。
"""
from sqlalchemy import inspect, text
from database import engine, Base


def ensure_schema() -> list[str]:
    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    applied = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl_type = col.type.compile(engine.dialect)
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl_type}"))
                applied.append(f"{table.name}.{col.name}")
    if applied:
        print("[migrate] added columns:", ", ".join(applied))
    return applied


def normalize_data() -> None:
    """新列回填：新增布尔/标签列后，历史行需要给出确定的默认值，否则响应校验会失败。"""
    statements = [
        "UPDATE materials SET selected = 0 WHERE selected IS NULL",
        "UPDATE materials SET variant = 'A' WHERE variant IS NULL AND version = 1",
    ]
    with engine.begin() as conn:
        for sql in statements:
            try:
                conn.execute(text(sql))
            except Exception as e:   # 列可能尚不存在（非 SQLite）
                print("[migrate] skip:", sql, "->", str(e)[:80])
