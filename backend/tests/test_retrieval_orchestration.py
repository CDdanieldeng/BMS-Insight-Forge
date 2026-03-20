"""
Simple test for retriever orchestration.

Run from backend: python tests/test_retrieval_orchestration.py

Shows: the query and which chunks finally remained after recall + rerank.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retriever.orchestration import run_retrieval_pipeline

# ---------------------------------------------------------------------------
# Example HCP transcript (your sample file)
# ---------------------------------------------------------------------------

EXAMPLE_DOC = """
HCP 14
问题 Q1. 请您简单介绍一下您的执业背景
答案：我在天津三甲医院，主任医师，从业时间较长。

问题 Q3. 您如何理解中重度银屑病的严重性和长期影响
答案：银屑病重要，但我不会把它看得过于"需要激进管理"。

问题 Q4. 您在临床上如何区分轻/中/重度
答案：我主要还是凭经验和临床观察判断严重度。

问题 Q5. 您如何评估疾病对患者生活质量的影响
答案：患者如果不主动提，我一般不会特别多问生活层面的影响。

问题 Q6. 对中重度患者，您心中的理想治疗目标是什么
答案：目标是稳定控制，不给患者太多额外折腾。

问题 Q7. 请以一个典型中重度患者为例，您从初诊到随访通常如何选择治疗路径
答案：我的路径还是传统阶梯式，先熟悉药，再看需不需要升级。

问题 Q8. 中度与重度患者的治疗策略是否不同
答案：重度会升级更快，但不会一开始就全都往最强方案走。

问题 Q9. 在系统治疗中，您更倾向选择哪一类作为起始或核心方案
答案：传统 oral 是我最熟悉的起点，advanced 更多留到后面。

问题 Q13. 在治疗选择沟通中，您更倾向共同决策还是直接推荐
答案：我会讲方案，但不会特别去说服患者接受某个新东西。

问题 Q15. 如果有一款新的口服创新药进入市场，您的第一反应通常是什么
答案：新口服药我会先观察，不会立刻判断它应该放多靠前。

问题 Q16. 在什么情况下您会考虑使用这类新药
答案：更适合那些口服偏好强、又对现有传统 oral 不满意的人。

问题 Q17. 哪些因素会明显提升您尝试处方新药的意愿
答案：如果越来越多同道都用得顺，我会更容易接受。

问题 Q18. 哪些顾虑可能会阻碍您处方新药
答案：没有经验、长期定位不清楚，是主要顾虑。

问题 Q19. 哪类证据最能促使您尝试新药
答案：同道案例比宣传材料更能说服我。

问题 Q21. 当药物价格、报销或院内准入情况不同时，您通常如何权衡
答案：如果医院没进、患者还要自己承担很多，我通常不会优先考虑。

问题 Q23. 您主要通过哪些渠道获取银屑病领域的新进展
答案：我获取信息主要靠会议和同行交流，不会特意追最新概念。

问题 Q25. 从职业发展角度，您希望同行和患者如何评价您
答案：我希望同行觉得我是经验型、稳妥型医生。
"""



# RAW_QUERY="""
# Business Objective
# Support targeted commercial planning and resource allocation across different geographic markets

# Segmentation Lens
# 1. City tier

# Segmentation Guideline
# 1. Identify the city tier based on explicit mentions of the HCP's practice location in the uploaded research materials, such as "Tier 1 metropolitan area," "mid-sized city," or "smaller market."
# 2. Classify HCPs into tiers based on the specific geographic descriptors provided in the documents, such as "major urban center," "regional hub," or "rural area," without inferring or assuming additional criteria beyond what is stated.


# """

RAW_QUERY="""
Segments to populate (columns): "Tier 1 HCPs"
Row labels to fill (in order): ['Demographics  (i.e., age, gender, etc.)']
"""


def main():
    # Summary that drives the retrieval query (what you're looking for in the doc)


    print("=" * 60)
    print("  RETRIEVAL PIPELINE TEST")
    print("=" * 60)
    print("\nInput: 1 doc (HCP transcript), raw_query drives the query rewrite")
    print("Pipeline: query_rewrite → facet → chunk → embed → recall → rerank\n")

    # Run the full pipeline (uses real LLM/embed/rerank if API keys set)
    combined, metadata = run_retrieval_pipeline(
        raw_query=RAW_QUERY.strip(),
        file_ids=[],
        session_upload_docs=[
            {"filename": "hcp14_transcript.txt", "markdown_content": EXAMPLE_DOC},
        ],
        recall_top_k=5,
        rerank_top_k=2,
        correlation_key="test",
    )

    # Show query (from metadata)
    print("-" * 60)
    print("QUERY (rewritten for retrieval):")
    print(metadata.get("query_preview", "(see metadata)"))
    print()

    # Show facet results (per doc)
    print("-" * 60)
    print("FACET (per document):")
    print("-" * 60)
    for fr in metadata.get("facet_results", []):
        print(f"  {fr.get('filename', '?')}: file_type={fr.get('file_type', '?')}")
        if fr.get("summary"):
            print(f"    summary: {fr['summary'][:100]}{'…' if len(fr.get('summary', '')) > 100 else ''}")
    print()

    # Show metadata
    print("-" * 60)
    print("METADATA:")
    print(f"  recalled:  {metadata.get('recalled_count', 0)} chunks")
    print(f"  reranked: {metadata.get('reranked_count', 0)} chunks kept")
    print()

    # Show recalled chunks (before rerank)
    print("-" * 60)
    print("RECALLED CHUNKS (before rerank):")
    print("-" * 60)
    recalled = metadata.get("recalled_chunks", [])
    for i, ch in enumerate(recalled, 1):
        fn = ch.get("filename", ch.get("file_id", "?"))
        score = ch.get("score", 0)
        text = ch.get("text", "")
        preview = (text[:150] + "...") if len(text) > 150 else text
        print(f"\n[Recalled {i}] {fn} (score: {score:.4f})\n{preview}")
    if not recalled:
        print("(none)")
    print()

    # Show final chunks that remained
    print("-" * 60)
    print("FINAL CHUNKS (what remained):")
    print("-" * 60)
    if combined:
        blocks = combined.split("\n\n---\n\n")
        for i, block in enumerate(blocks, 1):
            lines = block.strip().split("\n", 1)
            header = lines[0] if lines else ""
            body = lines[1].strip() if len(lines) > 1 else ""
            print(f"\n[Chunk {i}] {header}\n")
            print(body)
            print()
    else:
        print("(empty)")

    print("=" * 60)
    print("Done.")


if __name__ == "__main__":
    main()
