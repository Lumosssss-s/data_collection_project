"""A3 疾病档案入库：把 data/clean/disease_profiles/*.json 写入 medical_disease_profiles。

ingest.py 对该目录标注为「写入方法待建」，本脚本直接调用仓库层已有的
add_disease_profile（含 bge-m3 向量计算），不经过主索引。

用法（容器内）：
  python scripts/data_pipeline/load_disease_profiles.py
"""
import glob
import json
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from core.config import settings  # noqa: E402
from repositories.elasticsearch import ElasticsearchRepository  # noqa: E402

PROFILE_DIR = os.path.join(BASE_DIR, "data", "clean", "disease_profiles")


def main() -> None:
    files = sorted(glob.glob(os.path.join(PROFILE_DIR, "*.json")))
    if not files:
        raise SystemExit(f"未找到疾病档案：{PROFILE_DIR}")

    repo = ElasticsearchRepository()

    # 先把嵌入模型加载并预热一次：容器内存紧张时首次加载可能失败，
    # 成功后模型常驻，后续写入不再重复加载。
    for attempt in range(3):
        try:
            repo._embed_texts(["warmup"])
            print("  嵌入模型预热完成")
            break
        except Exception as e:
            print(f"  预热第 {attempt + 1} 次失败：{type(e).__name__}，2 秒后重试")
            repo._model = None
            time.sleep(2)

    ok = 0
    for path in files:
        profile = json.load(open(path, encoding="utf-8"))
        did = profile.get("disease_id")
        filled = sum(1 for v in (profile.get("sections") or {}).values() if v)
        written = False
        for attempt in range(3):
            if repo.add_disease_profile(profile):
                written = True
                break
            repo._model = None  # 加载失败后清缓存，允许下次重试
            time.sleep(1)
        if written:
            ok += 1
            print(f"  ✓ {did} {profile.get('name_canonical')} 已填 {filled}/20 节")
        else:
            print(f"  ✗ {did} 写入失败")

    count = repo.client.count(index=settings.es_disease_index_name)["count"]
    print(f"\n入库 {ok}/{len(files)} 条，索引现有 {count} 条")


if __name__ == "__main__":
    main()
