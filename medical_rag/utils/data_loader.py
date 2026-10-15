"""文件态数据加载器（C3 §5：8 个「不入 ES」目录的统一读取入口）。

背景：B 组功能数据（B1 红旗征 / B2 槽位表 / B3 分诊映射 / B4 随访模板 / B5 患者消息 /
B6 质控规则）与运营指标（B7）按 C3 §5 归为**文件态**——校验后仅登记目录、不入 ES，
由对应模块直接读 `data/clean/<目录>/*.json|*.jsonl`。

设计要点：
- **按目录整体加载 + mtime 缓存**：一次读入目录内全部 JSON，按「文件名 + mtime」签名
  缓存；目录内容变化（数据更新/新增文件）时下次调用自动重载。
- **缺失即降级**：目录或文件不存在时返回空列表，**不抛异常**——调用方据此置
  `degraded=True` 并给出「数据未就绪」提示，保证服务在数据到位前仍可启动与浏览。
- **只认 G2 格式**（`.json` 顶层数组 / `.jsonl` 每行一条），与 `ingest.py` 口径一致。
"""
import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

from core.config import settings

logger = logging.getLogger(__name__)

# dir_name -> (签名, 记录列表)；签名变化即重载
_CACHE: Dict[str, Tuple[Tuple, List[Dict]]] = {}
_LOCK = threading.RLock()


def _dir_path(dir_name: str) -> str:
    return os.path.join(settings.clean_data_dir, dir_name)


def _list_data_files(dir_name: str) -> List[str]:
    """列出目录下的 .json / .jsonl 文件（排序保证签名稳定）。"""
    d = _dir_path(dir_name)
    if not os.path.isdir(d):
        return []
    names = [
        n for n in os.listdir(d)
        if n.endswith(".json") or n.endswith(".jsonl")
    ]
    return sorted(names)


def _signature(dir_name: str, names: List[str]) -> Tuple:
    """目录内容签名：(文件名, mtime) 有序元组；文件被删/改/增都会变化。"""
    d = _dir_path(dir_name)
    sig = []
    for n in names:
        try:
            sig.append((n, os.path.getmtime(os.path.join(d, n))))
        except OSError:
            sig.append((n, -1.0))
    return tuple(sig)


def _read_file(path: str) -> List[Dict]:
    """读取单个 G2 文件（.json 顶层数组 / .jsonl 每行一条）。"""
    try:
        if path.endswith(".jsonl"):
            records: List[Dict] = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            records.append(obj)
            return records
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        logger.warning(f"[data_loader] {os.path.basename(path)} 顶层非数组（不符 G2），跳过")
        return []
    except Exception as e:
        logger.warning(f"[data_loader] 解析失败 {os.path.basename(path)}: {e}")
        return []


def dir_exists(dir_name: str) -> bool:
    """目录是否存在（供调用方区分「无数据目录」与「目录空」）。"""
    return os.path.isdir(_dir_path(dir_name))


def load_dir_records(dir_name: str, force_reload: bool = False) -> List[Dict]:
    """加载 `data/clean/<dir_name>/` 下全部记录（带 mtime 缓存）。

    目录缺失或文件为空时返回 ``[]``，不抛异常。
    """
    names = _list_data_files(dir_name)
    sig = _signature(dir_name, names)

    with _LOCK:
        cached = _CACHE.get(dir_name)
        if cached and not force_reload and cached[0] == sig:
            return cached[1]

    records: List[Dict] = []
    d = _dir_path(dir_name)
    for n in names:
        records.extend(_read_file(os.path.join(d, n)))

    with _LOCK:
        _CACHE[dir_name] = (sig, records)
    if records:
        logger.info(f"[data_loader] {dir_name}: 载入 {len(records)} 条记录（{len(names)} 文件）")
    return records


def load_records_by_type(dir_name: str, record_type: str,
                         type_field: str = "record_type") -> List[Dict]:
    """加载目录记录并按 `record_type` 过滤。

    用于 `triage_rules/` 这类同目录容纳多类记录的目录（C3 §5 注 2：B1 红旗征与
    B3 分诊映射共用 `triage_rules/`，靠 `record_type` 区分）。
    """
    return [r for r in load_dir_records(dir_name) if r.get(type_field) == record_type]


def data_status(dir_name: str) -> Dict[str, Any]:
    """目录就绪状态（供 API 组装 degraded 提示）。"""
    exists = dir_exists(dir_name)
    records = load_dir_records(dir_name) if exists else []
    return {
        "dir": dir_name,
        "exists": exists,
        "record_count": len(records),
        "ready": exists and len(records) > 0,
    }


def clear_cache(dir_name: Optional[str] = None) -> None:
    """清空加载缓存（测试或数据热更新后手动调用）。"""
    with _LOCK:
        if dir_name is None:
            _CACHE.clear()
        else:
            _CACHE.pop(dir_name, None)
