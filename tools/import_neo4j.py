#!/usr/bin/env python3
"""Import knowledge_graph.cypher into Neo4j database."""
import sys
from pathlib import Path

try:
    from neo4j import GraphDatabase
except ImportError:
    print("需要安装 neo4j driver: uv add neo4j")
    sys.exit(1)

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "tply7620"
CYPHER_FILE = Path(__file__).parent.parent / "output" / "knowledge_graph.cypher"


def main():
    if not CYPHER_FILE.exists():
        print(f"文件不存在: {CYPHER_FILE}")
        sys.exit(1)

    print(f"正在读取 {CYPHER_FILE}...")
    content = CYPHER_FILE.read_text(encoding="utf-8")

    # 按分号拆分语句，去掉空白和注释
    statements = []
    for stmt in content.split(";"):
        stmt = stmt.strip()
        if stmt and not stmt.startswith("//"):
            statements.append(stmt + ";")

    print(f"解析到 {len(statements)} 条 Cypher 语句")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    # 先清空数据库（忽略约束）
    with driver.session(database="neo4j") as session:
        print("\n=== 清空数据库 ===")
        session.run("MATCH (n) DETACH DELETE n")
        # 删除所有约束重新创建
        for record in session.run("SHOW CONSTRAINTS"):
            try:
                session.run(f"DROP CONSTRAINT {record['name']}")
            except Exception:
                pass
        print("已清空")

    # 分批执行: 先约束，再节点，再关系
    batch_names = [
        ("CREATE CONSTRAINT", lambda s: s.startswith("CREATE CONSTRAINT")),
        ("MERGE nodes", lambda s: s.startswith("MERGE") and "MERGE (a:" not in s),
        ("MERGE relationships", lambda s: s.startswith("MATCH")),
    ]

    total = 0
    for batch_name, predicate in batch_names:
        batch = [s for s in statements if predicate(s)]
        if not batch:
            continue
        print(f"\n=== 执行 {batch_name} ({len(batch)} 条) ===")
        with driver.session(database="neo4j") as session:
            for i, stmt in enumerate(batch, 1):
                try:
                    session.run(stmt)
                    if i % 500 == 0:
                        print(f"  进度: {i}/{len(batch)}")
                except Exception as e:
                    # 忽略约束已存在的警告
                    msg = str(e)
                    if "EquivalentSchemaRuleAlreadyExists" in msg:
                        continue
                    print(f"  [{i}/{len(batch)}] 错误: {e}")
                    print(f"  语句: {stmt[:120]}...")
        total += len(batch)
        print(f"  [完成] {len(batch)} 条")

    driver.close()
    print(f"\n全部导入完成! 共执行 {total} 条语句")

    # 统计验证
    print("\n=== 验证 ===")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session(database="neo4j") as session:
        result = session.run("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS cnt ORDER BY cnt DESC")
        print(f"{'节点类型':<25} {'数量':>6}")
        print("-" * 33)
        for record in result:
            print(f"{record['label']:<25} {record['cnt']:>6}")

        print()
        result = session.run("MATCH ()-[r]->() RETURN type(r) AS rel_type, count(*) AS cnt ORDER BY cnt DESC")
        print(f"{'关系类型':<30} {'数量':>6}")
        print("-" * 38)
        for record in result:
            print(f"{record['rel_type']:<30} {record['cnt']:>6}")
    driver.close()


if __name__ == "__main__":
    main()
