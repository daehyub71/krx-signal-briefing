# 다이어그램 원본

PNG는 Graphviz로 만든다. 고치면 다시 렌더링한다 (`brew install graphviz`).

```bash
cd docs/diagrams
dot -Tpng -Gdpi=160 arch.dot    -o ../arch-overview.png
dot -Tpng -Gdpi=160 graph.dot   -o ../graph.png
dot -Tpng -Gdpi=160 modules.dot -o ../modules.png
```

`graph.png`는 설계도다. 구현 후의 실제 그래프는 `scripts/export_graph.py`가 `docs/GRAPH.md`(mermaid)로 뽑는다 — 둘이 다르면 코드가 설계에서 벗어난 것이다.
