"""절약 가이드 RAG — 질문과 분석 결과로 관련 가이드 문서를 고른다.

가이드 본문을 '줄(항목) 단위 조각'으로 나누고, 조각마다 topic(카테고리/이상결제)을 메타데이터로
붙여 TF-IDF 벡터 인덱스를 만든다. 과제1의 runbook 검색과 같은 방식이다.

질의 = 사용자 질문 + 분석에서 문제가 된 카테고리 이름(예산 초과·증가폭 1위) + 이상 결제 유형.
예) "9월 지출 줄이는 방법 알려줘" — 질문에는 카테고리가 없지만 예산 초과가 쇼핑·구독이면
    쇼핑·구독 가이드가 올라온다.

한국어는 띄어쓰기·조사 때문에 단어 단위가 약해서 문자 2~3-gram을 함께 쓴다(외부 모델 불필요).
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GUIDE_DIR = DATA_DIR / "guides"


def _tokens(text: str) -> list[str]:
    text = text.lower()
    words = re.findall(r"[a-z0-9.%/]+|[가-힣]+", text)
    grams = [w[i:i + n] for w in words if re.fullmatch(r"[가-힣]+", w)
             for n in (2, 3) for i in range(len(w) - n + 1)]
    return words + grams


class _TfidfIndex:
    def __init__(self, docs: list[str]):
        self.doc_tokens = [Counter(_tokens(d)) for d in docs]
        df = Counter(t for toks in self.doc_tokens for t in toks)
        n = len(docs)
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
        self.doc_vecs = [self._vec(toks) for toks in self.doc_tokens]

    def _vec(self, counts: Counter) -> dict[str, float]:
        vec = {t: (1 + math.log(c)) * self.idf.get(t, 0.0) for t, c in counts.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def search(self, query: str) -> list[float]:
        q = self._vec(Counter(_tokens(query)))
        return [sum(w * d.get(t, 0.0) for t, w in q.items()) for d in self.doc_vecs]


class GuideRetriever:
    """가이드 조각 인덱스. 프로세스당 1번 만든다."""

    def __init__(self):
        meta = {k: v for k, v in json.loads((DATA_DIR / "guides_meta.json").read_text(encoding="utf-8")).items()
                if not k.startswith("_")}
        self.chunks: list[dict] = []   # {"topic", "text", "is_meta"}
        for path in sorted(GUIDE_DIR.glob("*.md")):
            topic = path.stem
            for line in path.read_text(encoding="utf-8").splitlines():
                text = re.sub(r"^\s*(?:#+|\d+\.)\s*", "", line).strip()   # 제목 기호·번호만 뗀다
                if text:
                    # 제목 줄("# 절약 가이드: 구독")은 검색에는 쓰되 답변 근거(본문)로는 내보내지 않는다
                    self.chunks.append({"topic": topic, "text": text, "is_meta": line.lstrip().startswith("#")})
            for phrase in meta.get(topic, []) + [topic]:
                self.chunks.append({"topic": topic, "text": phrase, "is_meta": True})
        self.topics = sorted({c["topic"] for c in self.chunks})
        self.index = _TfidfIndex([c["text"] for c in self.chunks])

    def retrieve(self, query: str, hints: list[str] | None = None, top_topics: int = 2,
                 lines_per_topic: int = 3) -> list[dict]:
        """[{topic, score, lines}] — 점수 높은 주제 top_topics개와, 그 주제에서 질의와 가장 가까운 본문 줄."""
        text = " ".join([query] + list(hints or []))
        sims = self.index.search(text)
        per_topic: dict[str, list[tuple[float, dict]]] = {t: [] for t in self.topics}
        for chunk, s in zip(self.chunks, sims):
            per_topic[chunk["topic"]].append((s, chunk))
        scored = []
        for topic, items in per_topic.items():
            top3 = sorted((s for s, _ in items), reverse=True)[:3]
            score = sum(top3)
            if score <= 0:
                continue
            body = sorted(((s, c) for s, c in items if not c["is_meta"]), key=lambda x: -x[0])
            scored.append({"topic": topic, "score": round(score, 3),
                           "lines": [c["text"] for _, c in body[:lines_per_topic]]})
        scored.sort(key=lambda x: -x["score"])
        return scored[:top_topics]
