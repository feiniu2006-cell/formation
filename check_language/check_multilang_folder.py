# -*- coding: utf-8 -*-
import re
import sys
import json
import time
import os
import queue
import threading
import traceback
import warnings
import importlib.util
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout
from contextlib import redirect_stdout, redirect_stderr

warnings.filterwarnings("ignore", category=UserWarning, module="translators")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ── 导入父目录的数据库配置 ──
_parent_dir = Path(__file__).resolve().parent.parent
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))
try:
    from db_config import DATABASE_CONFIGS
except ImportError:
    DATABASE_CONFIGS = {}

# 指定使用哪个数据库（对应 db_config.py 中的键）
DB_KEY = "MY"
_raw_cfg = DATABASE_CONFIGS.get(DB_KEY, {})
DB_CONFIG: dict = {**_raw_cfg, "charset": "utf8mb4"} if _raw_cfg else {}

BASE   = Path(r"C:\VegasGames")
MINIGAME = Path(r"C:\VegasGames\MiniGame")
COMMON   = Path(r"C:\VegasGames\策划\公用多语言")  # 公用文本路径
PATTERN  = re.compile(r"^\(\d+\)")

SCAN_ROOTS = [
    ("VegasGames", BASE),
    ("MiniGame",   MINIGAME),
    ("公用多语言", COMMON),  # 添加公用文本
]

# ── 需要检查的语言文件夹列表（按实际情况修改）──
REQUIRED_LANGS = [
    "eng",  # ── 英语（翻译基准语言）
    "ind",  # ── 印尼语
    "por",  # ── 葡萄牙语 (巴西)
    "spa",  # ── 西班牙语
    "tha",  # ── 泰语
    "vie",  # ── 越南语
    "sch",  # ── 简体中文
    "tch",  # ── 繁体中文
    "hin",  # ── 印地语 (印度)
    "ben",  # ── 孟加拉语
    "msa",  # ── 马来语
    "mya",  # ── 缅甸语
    "khm",  # ── 高棉语 (柬埔寨)
    "lao",  # ── 老挝语
    "tgl",  # ── 菲律宾语
    "jpn",  # ── 日语
    "kor",  # ── 韩语
]

# ── 内部语言代码 → translators 库语言代码 ──
LANG_CODE_MAP = {
    "eng": "en",  "ind": "id",  "por": "pt",  "spa": "es",
    "tha": "th",  "vie": "vi",  "sch": "zh-Hans", "tch": "zh-Hant",
    "hin": "hi",  "ben": "bn",  "msa": "ms",  "mya": "my",
    "khm": "km",  "lao": "lo",  "tgl": "tl",  "jpn": "ja",  "kor": "ko",
}

# 术语/特殊短语专用翻译配置。源文命中这些固定短语时，优先使用这里的译法。
# 如果所有语言译法都与英文相同，则表示该术语允许保留英文，不视为未翻译。
SPECIAL_PHRASE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "Wild": {
        "eng": "Wild",
        "ind": "Wild",
        "por": "Wild",
        "spa": "Wild",
        "tha": "Wild",
        "vie": "Wild",
        "sch": "Wild",
        "tch": "Wild",
        "hin": "Wild",
        "ben": "Wild",
        "msa": "Wild",
        "mya": "Wild",
        "khm": "Wild",
        "lao": "Wild",
        "tgl": "Wild",
        "jpn": "Wild",
        "kor": "Wild",
    },
    "Scatter": {
        "eng": "Scatter",
        "ind": "Scatter",
        "por": "Scatter",
        "spa": "Scatter",
        "tha": "Scatter",
        "vie": "Scatter",
        "sch": "Scatter",
        "tch": "Scatter",
        "hin": "Scatter",
        "ben": "Scatter",
        "msa": "Scatter",
        "mya": "Scatter",
        "khm": "Scatter",
        "lao": "Scatter",
        "tgl": "Scatter",
        "jpn": "Scatter",
        "kor": "Scatter",
    },
    "multiplier": {
        "eng": "multiplier",
        "ind": "multiplier",
        "por": "multiplier",
        "spa": "multiplier",
        "tha": "multiplier",
        "vie": "multiplier",
        "sch": "multiplier",
        "tch": "multiplier",
        "hin": "multiplier",
        "ben": "multiplier",
        "msa": "multiplier",
        "mya": "multiplier",
        "khm": "multiplier",
        "lao": "multiplier",
        "tgl": "multiplier",
        "jpn": "multiplier",
        "kor": "multiplier",
    },
    "Bonus": {
        "eng": "Bonus",
        "ind": "Bonus",
        "por": "Bonus",
        "spa": "Bonus",
        "tha": "Bonus",
        "vie": "Bonus",
        "sch": "Bonus",
        "tch": "Bonus",
        "hin": "Bonus",
        "ben": "Bonus",
        "msa": "Bonus",
        "mya": "Bonus",
        "khm": "Bonus",
        "lao": "Bonus",
        "tgl": "Bonus",
        "jpn": "Bonus",
        "kor": "Bonus",
    },
    "Wilds-on-the-Way": {
        "eng": "Wilds-on-the-Way",
        "ind": "Wild Beruntun Multi-Jalur",
        "por": "Wilds em Cascata Multivias",
        "spa": "Wilds en Cascada Multivía",
        "tha": "ไวลด์หลายทางแบบต่อเนื่อง",
        "vie": "Wild Nhiều Đường Liên Hoàn",
        "sch": "多路连消百搭",
        "tch": "多路連消百搭",
        "hin": "मल्टी-वे कैस्केडिंग वाइल्ड्स",
        "ben": "মাল্টি-ওয়ে ধারাবাহিক ওয়াইল্ডস",
        "msa": "Wild Berantai Berbilang Laluan",
        "mya": "လမ်းကြောင်းများစွာ ဆက်တိုက် Wilds",
        "khm": "Wilds ច្រើនផ្លូវបំបែកបន្ត",
        "lao": "Wilds ຫຼາຍເສັ້ນທາງແບບຕໍ່ເນື່ອງ",
        "tgl": "Multi-way Cascading Wilds",
        "jpn": "マルチウェイ連鎖ワイルド",
        "kor": "멀티웨이 연쇄 와일드",
    },
    "Ante Bet": {
        "eng": "Ante Bet",
        "ind": "Taruhan Ante",
        "por": "Aposta Ante",
        "spa": "Apuesta Ante",
        "tha": "เดิมพันแอนที",
        "vie": "Cược Ante",
        "sch": "前注",
        "tch": "前注",
        "hin": "एंटी बेट",
        "ben": "অ্যান্টে বাজি",
        "msa": "Pertaruhan Ante",
        "mya": "Ante လောင်းကြေး",
        "khm": "ការភ្នាល់ Ante",
        "lao": "ການເດີມພັນ Ante",
        "tgl": "Ante Bet",
        "jpn": "アンティベット",
        "kor": "앤티 베팅",
    },
}

NO_TRANSLATE_KEYS: set[str] = {        # 这些 key 的值保留英文原文，翻译和检测均跳过
    # "MultiplierTitle",
    # "WildSymbolTitle",
    # "ScatterSymbolTitle",
    # "FreeSpinFeatureTitle",
    # "GoldPlatedFeatureTitle",
    # "PayoutMainTitle",
}

# 所有语言均可保留英文的游戏专有名词（由特殊短语表派生，不视为"未翻译"）
UNIVERSAL_ENGLISH_TERMS: set[str] = {
    source
    for source, targets in SPECIAL_PHRASE_TRANSLATIONS.items()
    if all(targets.get(lang) == source for lang in REQUIRED_LANGS)
}

SOURCE_LANG        = "eng"
PLACEHOLDER_RE     = re.compile(r"%\{[^}]+\}")
GOOGLE_CLOUD_API_KEY = "AIzaSyBztVXdHU7NVx1hI4qunhk1vUdY1QIExE8"   # Google Cloud Translation API Key
TRANSLATOR_FALLBACK = ["google-cloud"]
# TRANSLATOR_FALLBACK = ["google-cloud", "google", "alibaba", "papago", "bing"]
TRANSLATE_MAX_RETRY = 3    # 翻译失败时最大重试次数
TRANSLATE_RETRY_DELAY = 5  # 每次重试前等待秒数
TRANSLATE_TIMEOUT   = 15   # 单次引擎调用超时秒数

# Google Cloud API 语言代码与内部代码的差异映射
_GCLOUD_LANG_MAP = {
    "zh-Hans": "zh-CN",
    "zh-Hant": "zh-TW",
}

# ── 检测模式 ──
MODE_FILES = "1"   # 只检查文件/文件夹是否存在
MODE_TRANS = "2"   # 只检查翻译内容是否正确
MODE_BOTH  = "3"   # 两项都检查

MODE_LABELS = {
    MODE_FILES: "文件缺失检测",
    MODE_TRANS: "翻译内容检测",
    MODE_BOTH:  "完整检测",
}


# ════════════════════════════════════════════════════════════════════════════════
# 翻译内容校验辅助
# ════════════════════════════════════════════════════════════════════════════════

def _collect_placeholders(node) -> set:
    if isinstance(node, dict):
        r = set()
        for v in node.values():
            r |= _collect_placeholders(v)
        return r
    if isinstance(node, list):
        r = set()
        for item in node:
            r |= _collect_placeholders(item)
        return r
    if isinstance(node, str):
        return set(PLACEHOLDER_RE.findall(node))
    return set()


def _collect_strings(node) -> list:
    if isinstance(node, dict):
        r = []
        for v in node.values():
            r.extend(_collect_strings(v))
        return r
    if isinstance(node, list):
        r = []
        for item in node:
            r.extend(_collect_strings(item))
        return r
    if isinstance(node, str):
        return [node]
    return []


def _is_translatable(text: str) -> bool:
    cleaned = PLACEHOLDER_RE.sub("", text).strip()
    if len(cleaned) < 4:
        return False
    if re.match(r'^[\d\s\W]+$', cleaned):
        return False
    # 纯数学公式（数字 + 运算符 + x/X 作为乘号），无需翻译
    if re.match(r'^[\d\s×xX+\-=*/%.,()]+$', cleaned):
        return False
    # 移除通用英文术语后若无实质内容，视为不需翻译
    stripped = cleaned
    for term in UNIVERSAL_ENGLISH_TERMS:
        stripped = re.sub(r'\b' + re.escape(term) + r'\b', '', stripped, flags=re.IGNORECASE)
    stripped = stripped.strip()
    if not stripped or len(stripped) < 4 or re.match(r'^[\d\s\W]+$', stripped):
        return False
    return True


def _find_untranslated_paths(src, tgt, path: str = "") -> list[str]:
    if isinstance(src, dict) and isinstance(tgt, dict):
        r = []
        for k in src:
            if k in NO_TRANSLATE_KEYS:
                continue
            if k in tgt:
                child = f"{path}.{k}" if path else k
                r.extend(_find_untranslated_paths(src[k], tgt[k], child))
        return r
    if isinstance(src, list) and isinstance(tgt, list):
        r = []
        for i, (s, t) in enumerate(zip(src, tgt)):
            r.extend(_find_untranslated_paths(s, t, f"{path}[{i}]"))
        return r
    if isinstance(src, str) and isinstance(tgt, str):
        if src == tgt and _is_translatable(src):
            preview = (src[:40] + "...") if len(src) > 40 else src
            return [f"{path}  (\"{preview}\")"]
    return []


def _has_english_intro_copula(text: str, source_name: str | None) -> bool:
    if not source_name:
        return False
    return bool(re.match(
        r'^\s*' + re.escape(source_name.strip()) + r'\s+is\s+an?\s+',
        text.strip(),
        flags=re.IGNORECASE,
    ))


def _zh_intro_missing_copula(src: str, tgt: str, source_name: str | None,
                             target_name: str | None, lang: str | None) -> bool:
    if lang not in {"sch", "tch"}:
        return False
    if not _has_english_intro_copula(src, source_name):
        return False
    if not target_name:
        return False
    text = tgt.strip()
    name = target_name.strip()
    if not text.startswith(name):
        return False
    rest = text[len(name):].lstrip(" \t，,、:：-—")
    if not rest:
        return False
    return not rest.startswith(("是", "为", "為", "系", "乃"))


def _find_zh_intro_copula_issues(src, tgt, source_name: str | None,
                                 target_name: str | None, lang: str | None,
                                 path: str = "") -> list[str]:
    if isinstance(src, dict) and isinstance(tgt, dict):
        r = []
        for k in src:
            if k in NO_TRANSLATE_KEYS:
                continue
            if k in tgt:
                child = f"{path}.{k}" if path else k
                r.extend(_find_zh_intro_copula_issues(
                    src[k], tgt[k], source_name, target_name, lang, child
                ))
        return r
    if isinstance(src, list) and isinstance(tgt, list):
        r = []
        for i, (s, t) in enumerate(zip(src, tgt)):
            r.extend(_find_zh_intro_copula_issues(
                s, t, source_name, target_name, lang, f"{path}[{i}]"
            ))
        return r
    if isinstance(src, str) and isinstance(tgt, str):
        if _zh_intro_missing_copula(src, tgt, source_name, target_name, lang):
            preview = (tgt[:40] + "...") if len(tgt) > 40 else tgt
            return [f"{path}  (疑似漏译 is a/an：\"{preview}\")"]
    return []


def _configured_special_terms(lang: str | None) -> list[tuple[str, str]]:
    if not lang:
        return []
    terms = [
        (source, targets[lang])
        for source, targets in SPECIAL_PHRASE_TRANSLATIONS.items()
        if targets.get(lang)
    ]
    return sorted(terms, key=lambda item: len(item[0]), reverse=True)


def _special_source_pattern(source: str):
    return re.compile(
        r'(?<![A-Za-z0-9])' + re.escape(source) + r'(?![A-Za-z0-9])',
        flags=re.IGNORECASE,
    )


def _contains_special_source(text: str, source: str) -> bool:
    return bool(_special_source_pattern(source).search(text))


def _replace_special_source(text: str, source: str, replacement: str) -> str:
    return _special_source_pattern(source).sub(replacement, text)


def _exact_special_translation(text: str, lang: str | None) -> str | None:
    stripped = text.strip()
    for source, target in _configured_special_terms(lang):
        if stripped.lower() == source.lower():
            prefix = text[:len(text) - len(text.lstrip())]
            suffix = text[len(text.rstrip()):]
            return f"{prefix}{target}{suffix}"
    return None


def _find_special_phrase_issues(src, tgt, lang: str | None,
                                path: str = "") -> list[str]:
    if isinstance(src, dict) and isinstance(tgt, dict):
        r = []
        for k in src:
            if k in NO_TRANSLATE_KEYS:
                continue
            if k in tgt:
                child = f"{path}.{k}" if path else k
                r.extend(_find_special_phrase_issues(src[k], tgt[k], lang, child))
        return r
    if isinstance(src, list) and isinstance(tgt, list):
        r = []
        for i, (s, t) in enumerate(zip(src, tgt)):
            r.extend(_find_special_phrase_issues(s, t, lang, f"{path}[{i}]"))
        return r
    if isinstance(src, str) and isinstance(tgt, str):
        issues = []
        for source, target in _configured_special_terms(lang):
            if source in UNIVERSAL_ENGLISH_TERMS:
                continue
            if _contains_special_source(src, source) and target not in tgt:
                issues.append(f"{path}  (特殊短语未使用配置翻译：\"{source}\" → \"{target}\")")
        return issues
    return []


def _json_type_name(node) -> str:
    if isinstance(node, dict):
        return "object"
    if isinstance(node, list):
        return "array"
    if isinstance(node, str):
        return "string"
    if isinstance(node, bool):
        return "boolean"
    if node is None:
        return "null"
    if isinstance(node, (int, float)):
        return "number"
    return type(node).__name__


def _join_json_path(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _display_json_path(path: str) -> str:
    return path or "<root>"


def _find_structure_issues(src, tgt, path: str = "") -> list[str]:
    issues: list[str] = []
    current = _display_json_path(path)

    if isinstance(src, dict):
        if not isinstance(tgt, dict):
            return [f"{current}  (类型不一致：eng=object, target={_json_type_name(tgt)})"]

        src_keys = set(src.keys())
        tgt_keys = set(tgt.keys())
        for key in src:
            if key not in tgt:
                issues.append(f"{current}  (缺少 key：{key})")
        for key in tgt:
            if key not in src_keys:
                issues.append(f"{current}  (多余 key：{key})")
        for key in src:
            if key in tgt:
                issues.extend(_find_structure_issues(src[key], tgt[key], _join_json_path(path, key)))
        return issues

    if isinstance(src, list):
        if not isinstance(tgt, list):
            return [f"{current}  (类型不一致：eng=array, target={_json_type_name(tgt)})"]
        if len(src) != len(tgt):
            issues.append(f"{current}  (列表长度不一致：eng={len(src)}, target={len(tgt)})")
        for i, (s, t) in enumerate(zip(src, tgt)):
            issues.extend(_find_structure_issues(s, t, f"{path}[{i}]"))
        return issues

    if _json_type_name(src) != _json_type_name(tgt):
        return [f"{current}  (类型不一致：eng={_json_type_name(src)}, target={_json_type_name(tgt)})"]
    return []


def check_translation_ok(json_path: Path, eng_data, lang: str | None = None) -> bool | list[str] | None:
    """True=完整, False=完全未翻译/占位符丢失, list=部分未翻译(含路径), None=无法判断"""
    if eng_data is None:
        return None
    try:
        tgt = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    issues = _find_structure_issues(eng_data, tgt)
    src_placeholders = _collect_placeholders(eng_data)
    tgt_placeholders = _collect_placeholders(tgt)
    if src_placeholders != tgt_placeholders:
        missing = sorted(src_placeholders - tgt_placeholders)
        extra = sorted(tgt_placeholders - src_placeholders)
        detail = []
        if missing:
            detail.append(f"缺少 {missing}")
        if extra:
            detail.append(f"多余 {extra}")
        issues.append(f"<root>  (占位符不一致：{'; '.join(detail)})")
    if _collect_strings(eng_data) == _collect_strings(tgt):
        if issues:
            issues.append("<root>  (内容完全未翻译)")
            return issues
        return False
    untranslated = _find_untranslated_paths(eng_data, tgt)
    source_name = _extract_name(eng_data)
    target_name = _extract_name(tgt)
    intro_issues = _find_zh_intro_copula_issues(
        eng_data, tgt, source_name, target_name, lang
    )
    special_issues = _find_special_phrase_issues(eng_data, tgt, lang)
    issues.extend(untranslated + intro_issues + special_issues)
    return issues if issues else True


def _add_trans_issue(trans_ok, issue: str):
    if isinstance(trans_ok, list):
        return [issue] + [item for item in trans_ok if item != issue]
    if trans_ok is False:
        return [issue, "内容未翻译或占位符丢失"]
    if trans_ok is None:
        return [issue, "无法验证翻译"]
    return [issue]


def _is_db_name_issue(issue: str) -> bool:
    return (
        issue.startswith("名称不匹配：")
        or issue.startswith("名称缺失：")
        or issue.startswith("DB名称缺失：")
        or issue.startswith("名称检查失败：")
    )


# ════════════════════════════════════════════════════════════════════════════════
# 功能一：检测
# lang 结果元组：(lang, folder_exists, json_exists, translation_ok)
# ════════════════════════════════════════════════════════════════════════════════

def check_multilang(game_dir: Path, check_trans: bool = True):
    """返回 None 表示「多语言」文件夹不存在，否则返回语言检测结果列表。"""
    multilang = game_dir / "资源制作" / "多语言"
    if not multilang.is_dir():
        return None

    eng_data = None
    if check_trans:
        eng_json = multilang / SOURCE_LANG / "GameRule.json"
        try:
            eng_data = json.loads(eng_json.read_text(encoding="utf-8")) if eng_json.is_file() else None
        except Exception:
            pass

    # 查询 DB 中该游戏各语言的名称，用于检测时比对
    db_names: dict = {}
    room_id = None
    require_db_names = False
    if check_trans:
        room_id = extract_room_id(game_dir.name)
        if room_id:
            db_names = query_room_names(room_id)
            require_db_names = bool(DB_CONFIG)

    results = []
    for lang in REQUIRED_LANGS:
        lang_dir = multilang / lang
        if not lang_dir.is_dir():
            results.append((lang, False, False, None))
            continue
        json_path = lang_dir / "GameRule.json"
        if not json_path.is_file():
            results.append((lang, True, False, None))
            continue
        if not check_trans or lang == SOURCE_LANG:
            trans_ok = True if lang == SOURCE_LANG else None
        else:
            trans_ok = check_translation_ok(json_path, eng_data, lang)

        # 与 DB 中的名称做比对（DB 有值时才检查）。eng 也是业务数据，必须与 DB 一致。
        if check_trans:
            db_name = db_names.get(lang)
            if require_db_names and not db_name:
                trans_ok = _add_trans_issue(
                    trans_ok,
                    f"DB名称缺失：room_id={room_id} lang={lang} 无名称，无法确认文件 Name 与 DB 一致",
                )
            elif db_name:
                try:
                    tgt_data  = json.loads(json_path.read_text(encoding="utf-8"))
                    file_name = _extract_name(tgt_data)
                    if file_name and file_name.strip() == db_name.strip():
                        # Name 与 DB 一致：DB 为权威，清除因 src==tgt 产生的 Name 误报
                        if isinstance(trans_ok, list):
                            trans_ok = [item for item in trans_ok
                                        if not re.search(r'\.Name\b', item)]
                            if not trans_ok:
                                trans_ok = True
                    else:
                        issue = (
                            f"名称不匹配：文件=\"{file_name}\"  DB=\"{db_name}\""
                            if file_name
                            else f"名称缺失：DB=\"{db_name}\""
                        )
                        trans_ok = _add_trans_issue(trans_ok, issue)
                except Exception as e:
                    trans_ok = _add_trans_issue(trans_ok, f"名称检查失败：{e}")
        results.append((lang, True, True, trans_ok))

    return results


def check_common_multilang(common_dir: Path, check_trans: bool = True):
    """检查公用多语言文件夹（直接包含语言子目录）"""
    if not common_dir.is_dir():
        return None

    eng_data = None
    eng_json = common_dir / SOURCE_LANG / "common.json"
    if check_trans:
        try:
            eng_data = json.loads(eng_json.read_text(encoding="utf-8")) if eng_json.is_file() else None
        except Exception:
            pass

    results = []
    for lang in REQUIRED_LANGS:
        lang_dir = common_dir / lang
        if not lang_dir.is_dir():
            results.append((lang, False, False, None))
            continue
        json_path = lang_dir / "common.json"
        if not json_path.is_file():
            results.append((lang, True, False, None))
            continue
        if not check_trans or lang == SOURCE_LANG:
          trans_ok = True if lang == SOURCE_LANG else None
        else:
            trans_ok = check_translation_ok(json_path, eng_data, lang)
        results.append((lang, True, True, trans_ok))

    return results


def _eng_missing(lang_results: list) -> bool:
    """eng 文件夹或 GameRule.json 不存在。"""
    for lang, folder_ok, json_ok, _ in lang_results:
        if lang == SOURCE_LANG:
            return not folder_ok or not json_ok
    return False


def _has_file_issues(lang_results: list) -> bool:
    return any(not folder_ok or not json_ok for _, folder_ok, json_ok, _ in lang_results)


def _has_trans_issues(lang_results: list) -> bool:
    return any(
        trans_ok is not True
        for lang, folder_ok, json_ok, trans_ok in lang_results
        if folder_ok and json_ok
    )


def is_all_ok(lang_results: list, mode: str) -> bool:
    if mode == MODE_FILES:
        return not _has_file_issues(lang_results)
    if mode == MODE_TRANS:
        return not _has_trans_issues(lang_results)
    return not _has_file_issues(lang_results) and not _has_trans_issues(lang_results)


def scan_root(label: str, root: Path, mode: str, skip_ids: set[int] | None = None):
    if not root.is_dir():
        print(f"[警告] 目录不存在，已跳过：{root}")
        return label, root, [], [], 0

    check_trans = mode in (MODE_TRANS, MODE_BOTH)
    game_dirs = sorted(
        d for d in root.iterdir()
        if d.is_dir() and PATTERN.match(d.name)
    )

    has_list, missing_list = [], []
    skipped_count = 0
    for game_dir in game_dirs:
        if skip_ids:
            room_id = extract_room_id(game_dir.name)
            if room_id and room_id in skip_ids:
                skipped_count += 1
                continue
        result = check_multilang(game_dir, check_trans)
        if result is None:
            missing_list.append(game_dir)
        else:
            has_list.append((game_dir, result))

    return label, root, has_list, missing_list, skipped_count


def _lang_status_lines(lang: str, folder_ok: bool, json_ok: bool, trans_ok, mode: str) -> list[str]:
    """返回该语言的状态行，按模式过滤不相关的问题。"""
    file_ok = folder_ok and json_ok

    if mode == MODE_FILES:
        if not folder_ok:
            return [f"         ❌ {lang:<10}  文件夹不存在"]
        if not json_ok:
            return [f"         ❌ {lang:<10}  GameRule.json 不存在"]
        return []

    if mode == MODE_TRANS:
        if not file_ok:
            return []   # 文件缺失是模式1的问题，此处不显示
        if trans_ok is False:
            return [f"         ⚠️  {lang:<10}  内容未翻译或占位符丢失"]
        if isinstance(trans_ok, list):
            lines = [f"         ⚠️  {lang:<10}  部分内容未翻译（{len(trans_ok)} 处）："]
            for p in trans_ok:
                lines.append(f"                  • {p}")
            return lines
        if trans_ok is None:
            return [f"         ❓ {lang:<10}  无法验证翻译（英文源缺失）"]
        return []

    # MODE_BOTH
    if not folder_ok:
        return [f"         ❌ {lang:<10}  文件夹不存在"]
    if not json_ok:
        return [f"         ❌ {lang:<10}  GameRule.json 不存在"]
    if trans_ok is False:
        return [f"         ⚠️  {lang:<10}  内容未翻译或占位符丢失"]
    if isinstance(trans_ok, list):
        lines = [f"         ⚠️  {lang:<10}  部分内容未翻译（{len(trans_ok)} 处）："]
        for p in trans_ok:
            lines.append(f"                  • {p}")
        return lines
    if trans_ok is None:
        return [f"         ❓ {lang:<10}  无法验证翻译（英文源缺失）"]
    return []


def section(lines: list, label: str, root: Path, has_list: list, missing_list: list, mode: str):
    total         = len(has_list) + len(missing_list)
    games_ok      = [(d, r) for d, r in has_list if is_all_ok(r, mode)]
    games_partial = [(d, r) for d, r in has_list if not is_all_ok(r, mode)]

    lines.append("")
    lines.append("█" * 80)
    lines.append(f"  {label}  ({root})")
    lines.append("█" * 80)
    lines.append(f"共检测 (数字) 游戏文件夹：{total} 个")

    if mode == MODE_FILES:
        lines.append(f"  ✅ 文件完整：{len(games_ok)} 个")
        lines.append(f"  ⚠️  文件缺失：{len(games_partial)} 个")
        lines.append(f"  ❌ 缺少「多语言」文件夹：{len(missing_list)} 个")
    elif mode == MODE_TRANS:
        lines.append(f"  ✅ 翻译完整：{len(games_ok)} 个")
        lines.append(f"  ⚠️  有翻译问题：{len(games_partial)} 个")
        lines.append(f"  （注：文件缺失问题请使用模式1，共 {len(missing_list)} 个游戏无「多语言」文件夹）")
    else:
        lines.append(f"  ✅ 完整（文件存在 + 翻译正确）：{len(games_ok)} 个")
        lines.append(f"  ⚠️  存在问题：{len(games_partial)} 个")
        lines.append(f"  ❌ 缺少「多语言」文件夹：{len(missing_list)} 个")

    # 缺少「多语言」文件夹（模式2不显示）
    if mode != MODE_TRANS and missing_list:
        lines.append("")
        lines.append("─" * 80)
        lines.append(f"❌ 缺少「多语言」文件夹 ({len(missing_list)} 个)：")
        lines.append("─" * 80)
        for i, d in enumerate(missing_list, 1):
            lines.append(f"  {i:>3}. {d.name}")

    # 有问题的游戏
    if games_partial:
        lines.append("")
        lines.append("─" * 80)
        label_str = "文件缺失" if mode == MODE_FILES else ("翻译问题" if mode == MODE_TRANS else "存在问题")
        lines.append(f"⚠️  {label_str} ({len(games_partial)} 个)：")
        lines.append("─" * 80)
        for i, (game_dir, lang_results) in enumerate(games_partial, 1):
            lines.append(f"  {i:>3}. {game_dir.name}")
            if mode in (MODE_FILES, MODE_BOTH) and _eng_missing(lang_results):
                lines.append(f"         ❌ 无英文（eng）文件，无法创建其它语言")
            else:
                for lang, folder_ok, json_ok, trans_ok in lang_results:
                    status = _lang_status_lines(lang, folder_ok, json_ok, trans_ok, mode)
                    lines.extend(status)

    # 完整的游戏
    if games_ok:
        lines.append("")
        lines.append("─" * 80)
        lines.append(f"✅ 无问题 ({len(games_ok)} 个)：")
        lines.append("─" * 80)
        for i, (game_dir, _) in enumerate(games_ok, 1):
            lines.append(f"  {i:>3}. {game_dir.name}")


def build_scan_report(results: list, mode: str, now: str | None = None) -> tuple[str, dict]:
    """根据扫描结果生成报告文本，并返回界面/命令行共用的统计信息。"""
    now = now or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    all_has_list   = [(d, r) for _, _, h, _, _ in results for d, r in h]
    all_missing    = [d for _, _, _, m, _ in results for d in m]
    total_skipped  = sum(s for _, _, _, _, s in results)

    total_all  = len(all_has_list) + len(all_missing)
    total_ok   = sum(1 for _, r in all_has_list if is_all_ok(r, mode))
    total_warn = sum(1 for _, r in all_has_list if not is_all_ok(r, mode))
    total_miss = len(all_missing)

    lines = []
    lines.append("=" * 80)
    lines.append(f"{MODE_LABELS.get(mode, '检测')}报告  ({now})")
    lines.append("=" * 80)
    lines.append(f"检查语言：{', '.join(REQUIRED_LANGS)}")
    lines.append(f"汇总：共 {total_all} 个游戏（已跳过 status=1 游戏 {total_skipped} 个）")
    lines.append(f"  ✅ 无问题：{total_ok} 个")
    lines.append(f"  ⚠️  有问题：{total_warn} 个")
    lines.append(f"  ❌ 缺少「多语言」文件夹：{total_miss} 个")

    for label, root, has_list, missing_list, _ in results:
        section(lines, label, root, has_list, missing_list, mode)

    lines.append("")
    lines.append("=" * 80)

    summary = {
        "all_has_list": all_has_list,
        "all_missing": all_missing,
        "total_skipped": total_skipped,
        "total_all": total_all,
        "total_ok": total_ok,
        "total_warn": total_warn,
        "total_miss": total_miss,
        "has_file_issues": bool(all_missing) or any(_has_file_issues(r) for _, r in all_has_list),
        "has_trans_issues": any(_has_trans_issues(r) for _, r in all_has_list),
    }
    return "\n".join(lines), summary


def save_report(report: str) -> Path:
    report_path = Path(__file__).parent / "检测报告.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    return report_path


# ════════════════════════════════════════════════════════════════════════════════
# 功能二：修复
# ════════════════════════════════════════════════════════════════════════════════

def _atomic_write_json(path: Path, data) -> None:
    """写入临时文件后重命名，保证目标文件要么完整要么不存在，防止中断产生损坏的 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    tmp.replace(path)   # os.replace 在同一文件系统上是原子操作


def _ph_token(i: int) -> str:
    return f"{_PH_KEY}{i}{_PH_KEY}"


def _protect(text: str) -> tuple[str, list[str]]:
    holders = PLACEHOLDER_RE.findall(text)
    for i, ph in enumerate(holders):
        text = text.replace(ph, _ph_token(i), 1)
    return text, holders


def _restore(text: str, holders: list[str]) -> str:
    for i, ph in enumerate(holders):
        # 用正则匹配，允许 API 在 token 内部插入空格或改变大小写
        pattern = re.escape(_PH_KEY) + r'\s*' + re.escape(str(i)) + r'\s*' + re.escape(_PH_KEY)
        text = re.sub(pattern, ph, text, flags=re.IGNORECASE)
    return text


def _special_term_token(i: int) -> str:
    return f"{_PH_KEY}TERM{i}{_PH_KEY}"


def _protect_special_phrases(text: str, lang: str | None) -> tuple[str, list[tuple[int, str]]]:
    holders: list[tuple[int, str]] = []
    for i, (source, target) in enumerate(_configured_special_terms(lang)):
        if _contains_special_source(text, source):
            text = _replace_special_source(text, source, _special_term_token(i))
            holders.append((i, target))
    return text, holders


def _restore_special_phrases(text: str, holders: list[tuple[int, str]]) -> str:
    for i, target in holders:
        pattern = re.escape(_PH_KEY) + r'\s*TERM\s*' + re.escape(str(i)) + r'\s*' + re.escape(_PH_KEY)
        text = re.sub(pattern, target, text, flags=re.IGNORECASE)
    return text


def _gcloud_translate_html(protected_text: str, to_lang: str) -> str:
    """
    使用 HTML 格式调用 Google Cloud Translation API。
    将所有 _PH_KEY token 包裹在 <span translate="no"> 中，
    阻止 API 修改占位符，解决 format=text 时 token 被改写的问题。
    """
    import requests
    import html as _html

    lang = _GCLOUD_LANG_MAP.get(to_lang, to_lang)

    # 匹配所有 _PH_KEY 包裹的 token（数字索引或 GAMENAME 等）
    ph_re = re.escape(_PH_KEY) + r'[A-Z0-9]*' + re.escape(_PH_KEY)

    # 将每个 token 用 <span translate="no"> 包裹，防止 API 修改
    html_text = re.sub(ph_re, lambda m: f'<span translate="no">{m.group()}</span>', protected_text)

    resp = requests.post(
        "https://translation.googleapis.com/language/translate/v2",
        params={"key": GOOGLE_CLOUD_API_KEY},
        json={"q": html_text, "source": "en", "target": lang, "format": "html"},
        timeout=TRANSLATE_TIMEOUT,
    )
    resp.raise_for_status()
    translated_html = resp.json()["data"]["translations"][0]["translatedText"]

    # HTML 实体反转义（API 会对 & < > 等字符转义）
    result = _html.unescape(translated_html)

    # 剥除 <span translate="no">TOKEN</span> 包裹，还原 token
    result = re.sub(r'<span\b[^>]*>\s*(' + ph_re + r')\s*</span>', r'\1', result)

    # 兜底：去掉任何残留的 HTML 标签
    result = re.sub(r'<[^>]+>', '', result)

    return result


def _translate_str(text: str, to_lang: str, lang: str | None = None) -> str:
    global _active_engine, _free_apis_decision
    import translators as ts
    exact = _exact_special_translation(text, lang)
    if exact is not None:
        return exact
    protected, holders = _protect(text)
    protected, special_holders = _protect_special_phrases(protected, lang)
    errors   = {}
    fallback = None   # 引擎成功但返回与原文相同时的候补结果
    for engine in TRANSLATOR_FALLBACK:
        # ── 引擎准入检查 ──
        if engine == "google-cloud":
            if not GOOGLE_CLOUD_API_KEY:
                continue
            # 用户已批准免费引擎时说明 google-cloud 本次会话失败，跳过避免重复等待
            if _free_apis_decision is True:
                continue
        else:
            # 非 google-cloud 引擎的准入检查
            if _free_apis_decision is False:
                break   # 用户已拒绝，不再尝试
            if _free_apis_decision is None and "google-cloud" in errors:
                # google-cloud 真正报错（不是"返回原文"），第一次遇到时询问用户
                free_list = ", ".join(e for e in TRANSLATOR_FALLBACK if e != "google-cloud")
                gcloud_err = errors["google-cloud"]
                if _free_apis_decision_callback is not None:
                    _free_apis_decision = bool(_free_apis_decision_callback(free_list, gcloud_err))
                else:
                    print(f"\n  [提示] Google Cloud 失败（{gcloud_err}）\n"
                          f"         是否启用免费引擎（{free_list}）？(y/n): ",
                          end="", flush=True)
                    ans = input().strip().lower()
                    _free_apis_decision = (ans == "y")
                if not _free_apis_decision:
                    break
            # _free_apis_decision is None 且 google-cloud 未报错（仅返回原文）
            # → 静默继续尝试免费引擎，无需询问
        # 切换到新引擎时打印一次
        if engine != _active_engine:
            print(f"[{engine}]", end=" ", flush=True)
            _active_engine = engine
        _ex = ThreadPoolExecutor(max_workers=1)
        try:
            if engine == "google-cloud":
                _future = _ex.submit(_gcloud_translate_html, protected, to_lang)
            else:
                _future = _ex.submit(
                    ts.translate_text, protected,
                    translator=engine, from_language="en", to_language=to_lang,
                )
            try:
                result = _future.result(timeout=TRANSLATE_TIMEOUT)
            except _FuturesTimeout:
                print(f"\n    [超时] {engine} 超过 {TRANSLATE_TIMEOUT}s 无响应，切换下一引擎...",
                      end=" ", flush=True)
                raise RuntimeError(f"超时（>{TRANSLATE_TIMEOUT}s）")
            restored = _restore(result, holders)
            restored = _restore_special_phrases(restored, special_holders)
            # 只检查 %{xxx} 对应的数字 token 是否还原
            # NAME_TOKEN（_PH_KEY+GAMENAME+_PH_KEY）由 _restore_name_token 单独处理，不在此检查
            _digit_tok_re = re.escape(_PH_KEY) + r'\d+' + re.escape(_PH_KEY)
            if holders and re.search(_digit_tok_re, restored, re.IGNORECASE):
                raise RuntimeError(f"占位符还原失败（token 残留）")
            if special_holders and re.search(re.escape(_PH_KEY) + r'\s*TERM', restored, re.IGNORECASE):
                raise RuntimeError("特殊短语还原失败（token 残留）")
            # 优先返回真正翻译了（与原文不同）的结果
            if result != protected:
                return restored
            # 原文相同：记为候补，继续尝试下一引擎
            if fallback is None:
                fallback = restored
        except Exception as e:
            errors[engine] = str(e)
        finally:
            _ex.shutdown(wait=False)  # 不等待可能已卡住的线程，立即放弃
    # 所有引擎都返回原文（词汇本身即英文借用词），接受之
    if fallback is not None:
        return fallback
    detail = "  |  ".join(f"{eng}: {msg}" for eng, msg in errors.items())
    raise RuntimeError(f"全部引擎失败 → {detail}")


def _translate_node(node, to_lang: str, lang: str | None = None):
    if isinstance(node, dict):
        return {k: (node[k] if k in NO_TRANSLATE_KEYS else _translate_node(v, to_lang, lang)) for k, v in node.items()}
    if isinstance(node, list):
        return [_translate_node(item, to_lang, lang) for item in node]
    if isinstance(node, str):
        return _translate_str(node, to_lang, lang)
    return node


def _fix_remaining_english(translated, eng_ref, to_lang: str, lang: str | None = None):
    """
    翻译完成后的修复通道：对值仍与英文相同的叶子字符串，
    改用句子包裹方式再次尝试翻译，帮助解决 API 拒绝翻译短词的问题。
    """
    if isinstance(eng_ref, dict) and isinstance(translated, dict):
        return {
            k: (_fix_remaining_english(translated[k], eng_ref.get(k), to_lang, lang)
                if k not in NO_TRANSLATE_KEYS and k in eng_ref
                else translated[k])
            for k in translated
        }
    if isinstance(eng_ref, list) and isinstance(translated, list):
        return [_fix_remaining_english(t, e, to_lang, lang)
                for t, e in zip(translated, eng_ref)]
    if isinstance(eng_ref, str) and isinstance(translated, str):
        if translated == eng_ref and _is_translatable(eng_ref):
            try:
                # 用句子包裹，迫使引擎真正翻译
                wrapped   = f"Game feature name: {eng_ref}."
                w_result  = _translate_str(wrapped, to_lang, lang)
                # 从翻译结果里提取术语部分（去掉可能保留的英文引导词）
                if w_result != wrapped:
                    # 简单策略：取冒号后面的部分（如果有），否则取整个结果
                    parts = re.split(r'[:：]', w_result, maxsplit=1)
                    candidate = parts[-1].strip().rstrip('.')
                    if candidate and candidate != eng_ref:
                        return candidate
            except Exception:
                pass
    return translated


def _fix_zh_intro_copula(translated, eng_ref, source_name: str | None,
                         target_name: str | None, lang: str | None):
    if isinstance(eng_ref, dict) and isinstance(translated, dict):
        return {
            k: (_fix_zh_intro_copula(translated[k], eng_ref.get(k), source_name, target_name, lang)
                if k not in NO_TRANSLATE_KEYS and k in eng_ref
                else translated[k])
            for k in translated
        }
    if isinstance(eng_ref, list) and isinstance(translated, list):
        return [_fix_zh_intro_copula(t, e, source_name, target_name, lang)
                for t, e in zip(translated, eng_ref)]
    if isinstance(eng_ref, str) and isinstance(translated, str):
        if _zh_intro_missing_copula(eng_ref, translated, source_name, target_name, lang):
            name = target_name.strip()
            m = re.match(r'^(\s*)(' + re.escape(name) + r')([\s，,、:：\-—]*)', translated)
            if m:
                rest = translated[m.end():].lstrip()
                link = "是" if rest.startswith(("一款", "一个", "一個", "一种", "一種")) else "是一款"
                return f"{m.group(1)}{m.group(2)}{link}{rest}"
    return translated


def _extract_name(node) -> str | None:
    if isinstance(node, dict):
        if "Name" in node and isinstance(node["Name"], str):
            return node["Name"]
        for v in node.values():
            r = _extract_name(v)
            if r:
                return r
    if isinstance(node, list):
        for item in node:
            r = _extract_name(item)
            if r:
                return r
    return None


def _replace_in_strings(node, old: str, new: str):
    if isinstance(node, dict):
        return {k: _replace_in_strings(v, old, new) for k, v in node.items()}
    if isinstance(node, list):
        return [_replace_in_strings(item, old, new) for item in node]
    if isinstance(node, str):
        return node.replace(old, new)
    return node


def _patch_name(node, new_name: str):
    """递归找到第一个 Name 字段并将其值替换为 new_name。"""
    if isinstance(node, dict):
        if "Name" in node and isinstance(node["Name"], str):
            return {**node, "Name": new_name}
        return {k: _patch_name(v, new_name) for k, v in node.items()}
    if isinstance(node, list):
        return [_patch_name(item, new_name) for item in node]
    return node


# ── 占位符保护用的随机 key（每次运行唯一，防止 API 改动）──
import random as _random
import string as _string
_PH_KEY = "".join(_random.choices(_string.ascii_uppercase, k=6))

# 当前正在使用的翻译引擎（用于进度显示，每种语言翻译前重置）
_active_engine: str | None = None

# 免费引擎使用策略（每次 run_fix 开始时重置）
# None=尚未询问  False=用户拒绝  True=用户允许
_free_apis_decision: bool | None = None
_free_apis_decision_callback = None


def _restore_name_token(node, final_name: str):
    """
    递归替换所有字符串中残留的 NAME_TOKEN。
    使用模糊正则（取 _PH_KEY 前 3 字符作锚点），
    允许 API 在 token 内部增删字符。
    """
    anchor  = re.escape(_PH_KEY[:3])
    pattern = anchor + r'\w*?GAMENAME\w*?' + anchor + r'\w*'
    if isinstance(node, dict):
        return {k: _restore_name_token(v, final_name) for k, v in node.items()}
    if isinstance(node, list):
        return [_restore_name_token(item, final_name) for item in node]
    if isinstance(node, str) and re.search(pattern, node, re.IGNORECASE):
        return re.sub(pattern, lambda _: final_name, node, flags=re.IGNORECASE)
    return node

# ── 数据库辅助 ──

def extract_room_id(folder_name: str) -> int | None:
    """从文件夹名 (3001)秘境传说 中提取 room_id。"""
    m = re.match(r'^\((\d+)\)', folder_name)
    return int(m.group(1)) if m else None


def query_skip_room_ids() -> set[int]:
    """查询 room_name 表中 status=1 的所有 room_id，这些游戏扫描时跳过。"""
    if not DB_CONFIG:
        return set()
    try:
        import pymysql
        conn = pymysql.connect(**DB_CONFIG)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT room_id FROM room_name WHERE status = 1")
                rows = cur.fetchall()
        finally:
            conn.close()
        return {row[0] for row in rows}
    except Exception as e:
        print(f"\n  [DB警告] 查询 status 失败：{e}")
        return set()


def query_room_names(room_id: int) -> dict[str, str | None]:
    """
    查询 room_name 表，返回 {lang: name_or_None}。
    DB 不可用或无对应行时返回空字典。
    """
    if not DB_CONFIG:
        return {}
    try:
        import pymysql
        cols = ", ".join(f"`{lang}`" for lang in REQUIRED_LANGS)
        conn = pymysql.connect(**DB_CONFIG)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {cols} FROM room_name WHERE room_id = %s LIMIT 1",
                    (room_id,)
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return {}
        return {lang: val for lang, val in zip(REQUIRED_LANGS, row)}
    except Exception as e:
        print(f"\n  [DB警告] 查询 room_name 失败：{e}")
        return {}


def update_rooms_status_ok(room_ids: set[int]):
    """将检测无问题的游戏 room_name.status 更新为 1。"""
    if not DB_CONFIG or not room_ids:
        return
    try:
        import pymysql
        placeholders = ", ".join(["%s"] * len(room_ids))
        conn = pymysql.connect(**DB_CONFIG)
        try:
            with conn.cursor() as cur:
                affected = cur.execute(
                    f"UPDATE room_name SET status = 1 WHERE room_id IN ({placeholders})",
                    tuple(room_ids),
                )
            conn.commit()
        finally:
            conn.close()
        print(f"  [DB] 已将 {affected} 个游戏 status 更新为 1")
    except Exception as e:
        print(f"\n  [DB警告] 更新 status 失败：{e}")


def update_room_names(room_id: int, updates: dict[str, str]):
    """将翻译好的游戏名写回 room_name 表中原本为 NULL 的语言列。"""
    if not DB_CONFIG or not updates:
        return
    try:
        import pymysql
        # 用 UPDATE ... WHERE room_id=? AND `lang` IS NULL 防止覆盖已有值
        conn = pymysql.connect(**DB_CONFIG)
        try:
            with conn.cursor() as cur:
                written = []
                for lang, name in updates.items():
                    rows = cur.execute(
                        f"UPDATE room_name SET `{lang}` = %s "
                        f"WHERE room_id = %s AND (`{lang}` IS NULL OR `{lang}` = '')",
                        (name, room_id),
                    )
                    if rows:
                        written.append(lang)
                    else:
                        print(f"  [DB] room_id={room_id} lang={lang}：UPDATE 影响 0 行"
                              f"（行不存在或该列已有值）")
            conn.commit()
        finally:
            conn.close()
        if written:
            print(f"  [DB] room_id={room_id} 已写回语言：{', '.join(written)}")
        else:
            print(f"  [DB] room_id={room_id}：没有任何列被更新，"
                  f"请确认 DB_KEY=\"{DB_KEY}\" 对应的数据库包含该 room_id 的行")
    except Exception as e:
        print(f"\n  [DB警告] 写入 room_name 失败：{e}")


def fix_game(game_dir: Path, lang_results: list, mode: str):
    multilang   = game_dir / "资源制作" / "多语言"
    source_json = multilang / SOURCE_LANG / "GameRule.json"

    if not source_json.is_file():
        print(f"  [跳过] {game_dir.name}：找不到英文源文件")
        return

    source_data = json.loads(source_json.read_text(encoding="utf-8"))
    eng_name    = _extract_name(source_data)

    # 查询 DB 中该游戏所有语言的名称
    room_id  = extract_room_id(game_dir.name)
    if room_id is None:
        print(f"  [DB] 无法从文件夹名提取 room_id：{game_dir.name}")
    db_names = query_room_names(room_id) if room_id else {}
    if room_id:
        null_langs = [lang for lang in REQUIRED_LANGS if not db_names.get(lang)]
        print(f"  [DB] room_id={room_id}，DB 中为 NULL/空白 的语言：{null_langs if null_langs else '无'}")
    to_write_db: dict[str, str] = {}   # 翻译后需回写 DB 的 {lang: name}

    for lang, folder_ok, json_ok, trans_ok in lang_results:
        if lang == SOURCE_LANG:
            if (mode != MODE_FILES
                    and isinstance(trans_ok, list) and trans_ok
                    and all(_is_db_name_issue(item) for item in trans_ok)):
                db_canonical = db_names.get(lang)
                if db_canonical:
                    try:
                        existing = json.loads(source_json.read_text(encoding="utf-8"))
                        old_name = _extract_name(existing)
                        if not old_name:
                            print(f"  {game_dir.name} → {lang}  [跳过] 文件中没有 Name 字段，无法自动修正")
                        else:
                            patched = _patch_name(existing, db_canonical)
                            if old_name != db_canonical:
                                patched = _replace_in_strings(patched, old_name, db_canonical)
                            _atomic_write_json(source_json, patched)
                            print(f"  {game_dir.name} → {lang}  名称已修正为 \"{db_canonical}\" ✅")
                    except Exception as e:
                        print(f"  {game_dir.name} → {lang}  名称修正失败：{e}")
                else:
                    print(f"  {game_dir.name} → {lang}  [跳过] DB 无名称可用")
            continue

        if mode == MODE_FILES:
            if folder_ok and json_ok:
                continue
        elif mode == MODE_TRANS:
            if not (folder_ok and json_ok):
                continue
            if trans_ok is True:
                continue
        else:
            if folder_ok and json_ok and trans_ok is True:
                continue

        lang_dir    = multilang / lang
        target_json = lang_dir / "GameRule.json"
        lang_dir.mkdir(parents=True, exist_ok=True)

        if mode == MODE_FILES:
            _atomic_write_json(target_json, source_data)
            print(f"  {game_dir.name} → {lang}  已复制英文原文 ✅")
            continue

        # 仅名称与 DB 不匹配（无其它翻译问题）：直接用 DB 值修正，不重新翻译
        if (isinstance(trans_ok, list) and trans_ok
                and all(_is_db_name_issue(item) for item in trans_ok)):
            db_canonical = db_names.get(lang)
            if db_canonical:
                try:
                    existing = json.loads(target_json.read_text(encoding="utf-8"))
                    old_name = _extract_name(existing)
                    if not old_name:
                        print(f"  {game_dir.name} → {lang}  [跳过] 文件中没有 Name 字段，无法自动修正")
                    else:
                        # 先修正 Name 字段
                        patched  = _patch_name(existing, db_canonical)
                        # 再把正文里所有出现的旧游戏名（如 Rule1 等）一并替换
                        if old_name != db_canonical:
                            patched = _replace_in_strings(patched, old_name, db_canonical)
                        _atomic_write_json(target_json, patched)
                        print(f"  {game_dir.name} → {lang}  名称已修正为 \"{db_canonical}\" ✅")
                except Exception as e:
                    print(f"  {game_dir.name} → {lang}  名称修正失败：{e}")
            else:
                print(f"  {game_dir.name} → {lang}  [跳过] DB 无名称可用")
            continue

        to_lang = LANG_CODE_MAP.get(lang)
        if not to_lang:
            print(f"  [跳过] {lang}：无对应翻译语言代码")
            continue

        global _active_engine
        _active_engine = None   # 每种语言重置，确保首个引擎名被打印
        print(f"  {game_dir.name} → {lang} ({to_lang}) ...", end=" ", flush=True)

        # ── 带重试的翻译流程 ──
        NAME_TOKEN = f"{_PH_KEY}GAMENAME{_PH_KEY}"
        db_name    = db_names.get(lang) if eng_name else None

        translated  = None
        name_for_db = None   # 仅在翻译成功后才写入 DB

        for attempt in range(1, TRANSLATE_MAX_RETRY + 1):
            try:
                # 确定游戏名（每次重试独立计算，不跨 attempt 复用）
                if eng_name and db_name:
                    final_name      = db_name
                    _name_candidate = None          # DB 已有，无需回写
                elif eng_name:
                    fn              = _translate_str(eng_name, to_lang, lang)
                    final_name      = fn if (fn and fn.strip()) else eng_name
                    _name_candidate = final_name    # DB 为 NULL 时始终回写，即使与英文相同
                else:
                    final_name      = None
                    _name_candidate = None

                # 翻译前保护游戏名
                protected_source = (
                    _replace_in_strings(source_data, eng_name, NAME_TOKEN)
                    if eng_name and final_name else source_data
                )

                translated = _translate_node(protected_source, to_lang, lang)

                # 还原游戏名（模糊匹配，允许 API 修改 token 内部字符）
                if eng_name and final_name:
                    translated = _restore_name_token(translated, final_name)
                    translated = _replace_in_strings(translated, eng_name, final_name)

                # 修复仍与英文相同的短字段（API 拒绝翻译的借用词除外）
                # 用原始英文 source_data 做对比基准：
                #   Name 字段已由 _restore_name_token 设为 final_name（目标语言），
                #   与英文 eng_name 不同 → 不会被误判为"未翻译"再次包裹重译
                translated = _fix_remaining_english(translated, source_data, to_lang, lang)
                translated = _fix_zh_intro_copula(translated, source_data, eng_name, final_name, lang)

                # 翻译成功：确认候选回写值
                name_for_db = _name_candidate
                break

            except Exception as e:
                translated  = None
                name_for_db = None
                if attempt < TRANSLATE_MAX_RETRY:
                    print(f"\n    [异常] {e}，{TRANSLATE_RETRY_DELAY}s 后重新翻译"
                          f"（第 {attempt}/{TRANSLATE_MAX_RETRY} 次）...",
                          end=" ", flush=True)
                    time.sleep(TRANSLATE_RETRY_DELAY)
                else:
                    print(f"\n    [失败] 已重试 {TRANSLATE_MAX_RETRY} 次，跳过 {lang}")

        if translated is None:
            continue  # 重试全部失败，跳过该语言，不写文件也不写 DB

        # 文件写入成功后才登记 DB 回写
        _atomic_write_json(target_json, translated)

        # ── 写入后立即核对 Name 与 DB 是否一致 ──
        db_canonical = db_names.get(lang)
        if db_canonical:
            written_name = _extract_name(translated)
            if written_name and written_name.strip() != db_canonical.strip():
                # Name 被翻译流程改错，用 DB 权威值修正
                patched = _patch_name(translated, db_canonical)
                patched = _replace_in_strings(patched, written_name, db_canonical)
                _atomic_write_json(target_json, patched)
                translated = patched
                print(f"\n    [Name修正] \"{written_name}\" → \"{db_canonical}\"",
                      end=" ", flush=True)
                name_for_db = None   # DB 已有值，无需回写

        if name_for_db:
            to_write_db[lang] = name_for_db
            print(f"✅  [DB待写] {lang} → \"{name_for_db}\"")
        else:
            print("✅")
        time.sleep(0.5)

    # 对已有翻译文件但 DB 仍为 NULL 的语言，从文件中读取 Name 补录回 DB
    if room_id:
        for lang, folder_ok, json_ok, _ in lang_results:
            if lang == SOURCE_LANG:
                continue
            if not (folder_ok and json_ok):
                continue
            if db_names.get(lang):   # 非空则 DB 已有值，无需补录
                continue
            if lang in to_write_db:
                continue  # 本次刚翻译，已有候选值
            existing_path = multilang / lang / "GameRule.json"
            try:
                existing_data = json.loads(existing_path.read_text(encoding="utf-8"))
                existing_name = _extract_name(existing_data)
                if existing_name:
                    to_write_db[lang] = existing_name
                    print(f"  [DB补录] {lang} 文件已存在，读取名称：\"{existing_name}\"")
            except Exception as e:
                print(f"  [DB补录] 读取 {lang} 文件失败：{e}")

    # 将本次翻译产生的新名称回写 DB
    if to_write_db and room_id:
        print(f"  [DB] 准备回写 {len(to_write_db)} 条记录：{to_write_db}")
        update_room_names(room_id, to_write_db)
    elif room_id:
        print(f"  [DB] 无需回写（所有语言 DB 已有名称）")


def run_fix_targets(targets: list[tuple[Path, list]], mode: str) -> None:
    global _free_apis_decision
    _free_apis_decision = None   # 每次修复会话重置，让用户重新决策

    if mode != MODE_FILES and importlib.util.find_spec("translators") is None:
        print("\n[错误] 未安装 translators 库，请先运行：pip install translators")
        return

    if not targets:
        print("\n无需修复的项目。")
        return

    print(f"\n共 {len(targets)} 个游戏需要处理：")
    for i, (game_dir, _) in enumerate(targets, 1):
        print(f"  {i:>3}. {game_dir.name}")

    print()
    for game_dir, lang_results in targets:
        fix_game(game_dir, lang_results, mode)
    print("\n处理完成。")


def run_fix(results: list, mode: str):
    remaining = [
        (game_dir, lang_results)
        for _, _, has_list, _, _ in results
        for game_dir, lang_results in has_list
        if not is_all_ok(lang_results, mode)
    ]

    if not remaining:
        print("\n无需修复的项目。")
        return

    while remaining:
        print(f"\n共 {len(remaining)} 个游戏需要处理：")
        for i, (game_dir, _) in enumerate(remaining, 1):
            print(f"  {i:>3}. {game_dir.name}")

        print("\n输入序号处理单个游戏（如 1），输入 all 处理全部，输入其他取消：")
        answer = input("> ").strip().lower()

        if answer == "all":
            targets   = remaining[:]
            remaining = []
        elif answer.isdigit() and 1 <= int(answer) <= len(remaining):
            idx       = int(answer) - 1
            targets   = [remaining.pop(idx)]
        else:
            print("已取消。")
            break

        run_fix_targets(targets, mode)

        if not remaining:
            print("所有游戏已处理完毕。")
            break

        cont = input("是否继续处理其它游戏？(y/n): ").strip().lower()
        if cont != "y":
            break


class _QueueWriter:
    """把 print 输出转发到界面的日志队列。"""

    def __init__(self, event_queue: queue.Queue):
        self.event_queue = event_queue

    def write(self, text: str) -> None:
        if text:
            self.event_queue.put(("log", text))

    def flush(self) -> None:
        pass


class MultilangCheckerApp:
    FIX_MODES = {
        "全部问题": MODE_BOTH,
        "缺失文件": MODE_FILES,
        "翻译内容": MODE_TRANS,
    }

    def __init__(self, root):
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.scan_results: list | None = None
        self.summary: dict = {}
        self.report_path: Path | None = None
        self.game_rows: dict[str, tuple[Path, list]] = {}
        self.busy = False

        self.scope_var = tk.StringVar(value="all")
        self.vegas_path_var = tk.StringVar(value=str(BASE))
        self.mini_path_var = tk.StringVar(value=str(MINIGAME))
        self.common_path_var = tk.StringVar(value=str(COMMON))  # 公用文本路径
        self.auto_status_var = tk.BooleanVar(value=True)
        self.fix_mode_var = tk.StringVar(value="全部问题")
        self.summary_var = tk.StringVar(value="尚未检测")
        self.status_var = tk.StringVar(value="就绪")

        self._build_ui()
        self._poll_events()

    def _build_ui(self) -> None:
        self.root.title("多语言检测与修复工具")
        self.root.geometry("1180x760")
        self.root.minsize(980, 620)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=26)

        main = ttk.Frame(self.root, padding=10)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        config = ttk.Frame(main)
        config.grid(row=0, column=0, sticky="ew")
        config.columnconfigure(1, weight=1)

        scope_frame = ttk.LabelFrame(config, text="扫描范围", padding=8)
        scope_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        ttk.Radiobutton(scope_frame, text="VegasGames", variable=self.scope_var,
                        value="vegas").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(scope_frame, text="MiniGame", variable=self.scope_var,
                        value="mini").grid(row=1, column=0, sticky="w")
        ttk.Radiobutton(scope_frame, text="全部", variable=self.scope_var,
                        value="all").grid(row=3, column=0, sticky="w")
        ttk.Radiobutton(scope_frame, text="公用多语言", variable=self.scope_var,
                      value="common").grid(row=2, column=0, sticky="w")

        path_frame = ttk.LabelFrame(config, text="目录", padding=8)
        path_frame.grid(row=0, column=1, sticky="ew")
        path_frame.columnconfigure(1, weight=1)
        ttk.Label(path_frame, text="VegasGames").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(path_frame, textvariable=self.vegas_path_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(path_frame, text="选择", width=8,
                   command=lambda: self._browse_path(self.vegas_path_var)).grid(row=0, column=2, padx=(8, 0))
        ttk.Label(path_frame, text="MiniGame").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        ttk.Entry(path_frame, textvariable=self.mini_path_var).grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(path_frame, text="选择", width=8,
                   command=lambda: self._browse_path(self.mini_path_var)).grid(row=1, column=2, padx=(8, 0), pady=(6, 0))
        ttk.Label(path_frame, text="公用多语言").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        ttk.Entry(path_frame, textvariable=self.common_path_var).grid(row=2, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(path_frame, text="选择", width=8,
             command=lambda: self._browse_path(self.common_path_var)).grid(row=2, column=2, padx=(8, 0), pady=(6, 0))

        option_frame = ttk.LabelFrame(config, text="操作", padding=8)
        option_frame.grid(row=0, column=2, sticky="nse", padx=(8, 0))
        ttk.Checkbutton(option_frame, text="无问题时更新 status=1",
                        variable=self.auto_status_var).grid(row=0, column=0, sticky="w")
        ttk.Label(option_frame, text="修复类型").grid(row=1, column=0, sticky="w", pady=(8, 2))
        ttk.Combobox(option_frame, textvariable=self.fix_mode_var,
                     values=list(self.FIX_MODES.keys()), width=12,
                     state="readonly").grid(row=2, column=0, sticky="ew")

        button_bar = ttk.Frame(main)
        button_bar.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        button_bar.columnconfigure(7, weight=1)

        self.scan_button = ttk.Button(button_bar, text="开始检测", command=self.start_scan)
        self.scan_button.grid(row=0, column=0, padx=(0, 6))
        self.fix_selected_button = ttk.Button(button_bar, text="修复选中", command=self.start_fix_selected)
        self.fix_selected_button.grid(row=0, column=1, padx=(0, 6))
        self.fix_all_button = ttk.Button(button_bar, text="修复当前全部问题", command=self.start_fix_all)
        self.fix_all_button.grid(row=0, column=2, padx=(0, 6))
        self.open_report_button = ttk.Button(button_bar, text="打开报告", command=self.open_report)
        self.open_report_button.grid(row=0, column=3, padx=(0, 14))

        self.progress = ttk.Progressbar(button_bar, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=4, padx=(0, 12))
        ttk.Label(button_bar, textvariable=self.summary_var).grid(row=0, column=5, sticky="w")
        ttk.Label(button_bar, textvariable=self.status_var).grid(row=0, column=7, sticky="e")

        body = ttk.PanedWindow(main, orient=tk.VERTICAL)
        body.grid(row=2, column=0, sticky="nsew")

        tree_frame = ttk.Frame(body)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        columns = ("game", "scope", "status", "files", "trans", "path")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings",
                                 selectmode="extended")
        headings = {
            "game": "游戏",
            "scope": "范围",
            "status": "状态",
            "files": "文件问题",
            "trans": "翻译问题",
            "path": "路径",
        }
        widths = {
            "game": 260,
            "scope": 95,
            "status": 110,
            "files": 90,
            "trans": 90,
            "path": 480,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.tag_configure("ok", foreground="#0a6f45")
        self.tree.tag_configure("warn", foreground="#9a5b00")
        self.tree.tag_configure("missing", foreground="#b42318")
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tree_scroll.set)
        body.add(tree_frame, weight=3)

        notebook = ttk.Notebook(body)
        self.report_text = self._make_text_page(notebook, "报告", wrap="none")
        self.log_text = self._make_text_page(notebook, "日志", wrap="word")
        body.add(notebook, weight=2)

    def _make_text_page(self, notebook, title: str, wrap: str):
        frame = ttk.Frame(notebook)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text = tk.Text(frame, wrap=wrap, font=("Consolas", 10), undo=False)
        text.grid(row=0, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        notebook.add(frame, text=title)
        return text

    def _browse_path(self, var) -> None:
        current = Path(var.get()).expanduser()
        initial = str(current if current.exists() else Path.cwd())
        selected = filedialog.askdirectory(initialdir=initial)
        if selected:
            var.set(selected)

    def _selected_roots(self) -> list[tuple[str, Path]] | None:
        vegas_raw = self.vegas_path_var.get().strip()
        mini_raw = self.mini_path_var.get().strip()
        common_raw = self.common_path_var.get().strip()
        roots = {
            "vegas": ("VegasGames", vegas_raw, Path(vegas_raw)),
            "mini": ("MiniGame", mini_raw, Path(mini_raw)),
            "common": ("公用多语言", common_raw, Path(common_raw)),
        }
        scope = self.scope_var.get()
        keys = ["vegas", "mini", "common"] if scope == "all" else [scope]
        selected = []
        for key in keys:
            label, raw_path, path = roots[key]
            if not raw_path:
                messagebox.showwarning("目录为空", f"请先设置 {label} 的目录。")
                return None
            selected.append((label, path))
        return selected

    def _append_text(self, widget, text: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.insert(tk.END, text)
        widget.see(tk.END)
        widget.configure(state=tk.DISABLED)

    def _set_text(self, widget, text: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state=tk.DISABLED)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.scan_button.configure(state=state)
        self.fix_selected_button.configure(state=state)
        self.fix_all_button.configure(state=state)
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _start_worker(self, title: str, job) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.status_var.set(f"{title}中...")
        thread = threading.Thread(target=self._worker_wrapper, args=(title, job), daemon=True)
        thread.start()

    def _worker_wrapper(self, title: str, job) -> None:
        writer = _QueueWriter(self.events)
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                job()
        except Exception:
            self.events.put(("error", title, traceback.format_exc()))
        finally:
            self.events.put(("worker_done", title))

    def _poll_events(self) -> None:
        while True:
            try:
                kind, *payload = self.events.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                self._append_text(self.log_text, payload[0])
            elif kind == "scan_done":
                results, report, summary, report_path = payload
                self.scan_results = results
                self.summary = summary
                self.report_path = report_path
                self._set_text(self.report_text, report)
                self._populate_tree(results)
                self.summary_var.set(
                    f"共 {summary['total_all']} 个，"
                    f"无问题 {summary['total_ok']} 个，"
                    f"有问题 {summary['total_warn']} 个，"
                    f"缺多语言 {summary['total_miss']} 个"
                )
                self.status_var.set(f"检测完成：{report_path}")
            elif kind == "fix_done":
                count = payload[0]
                self.status_var.set(f"修复完成，已处理 {count} 个游戏")
            elif kind == "error":
                title, detail = payload
                self._append_text(self.log_text, "\n" + detail + "\n")
                self.status_var.set(f"{title}失败")
                messagebox.showerror(f"{title}失败", detail)
            elif kind == "ask_free_apis":
                free_list, error_text, done, result = payload
                try:
                    result["value"] = messagebox.askyesno(
                        "Google Cloud 翻译失败",
                        f"Google Cloud 失败：{error_text}\n\n"
                        f"是否启用免费引擎（{free_list}）继续尝试？",
                    )
                finally:
                    done.set()
            elif kind == "worker_done":
                self._set_busy(False)

        self.root.after(100, self._poll_events)

    def _populate_tree(self, results: list) -> None:
        self.tree.delete(*self.tree.get_children())
        self.game_rows.clear()
        row_no = 0
        for label, _, has_list, missing_list, _ in results:
            for game_dir, lang_results in has_list:
                row_no += 1
                file_count = self._file_issue_count(lang_results)
                trans_count = self._trans_issue_count(lang_results)
                ok = is_all_ok(lang_results, MODE_BOTH)
                iid = f"game-{row_no}"
                self.game_rows[iid] = (game_dir, lang_results)
                self.tree.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        game_dir.name,
                        label,
                        "无问题" if ok else "有问题",
                        "0" if file_count == 0 else f"{file_count} 项",
                        "0" if trans_count == 0 else f"{trans_count} 项",
                        str(game_dir),
                    ),
                    tags=("ok" if ok else "warn",),
                )
            for game_dir in missing_list:
                row_no += 1
                self.tree.insert(
                    "",
                    "end",
                    iid=f"missing-{row_no}",
                    values=(game_dir.name, label, "缺少多语言", "-", "-", str(game_dir)),
                    tags=("missing",),
                )

    @staticmethod
    def _file_issue_count(lang_results: list) -> int:
        return sum(1 for _, folder_ok, json_ok, _ in lang_results
                   if not folder_ok or not json_ok)

    @staticmethod
    def _trans_issue_count(lang_results: list) -> int:
        return sum(
            1
            for lang, folder_ok, json_ok, trans_ok in lang_results
            if folder_ok and json_ok and trans_ok is not True
        )

    def _scan_job(self, roots: list[tuple[str, Path]], auto_update: bool) -> None:
        results, report, summary, report_path = self._run_scan(roots, auto_update)
        self.events.put(("scan_done", results, report, summary, report_path))

    def _run_scan(self, roots: list[tuple[str, Path]], auto_update: bool):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] 开始完整检测...")
        skip_ids = query_skip_room_ids()
        results = [scan_root(label, root, MODE_BOTH, skip_ids) for label, root in roots]
        report, summary = build_scan_report(results, MODE_BOTH, now)
        report_path = save_report(report)
        print(f"\n报告已保存到: {report_path}")

        if auto_update:
            ok_room_ids = set()
            for game_dir, lang_results in summary["all_has_list"]:
                if is_all_ok(lang_results, MODE_BOTH):
                    room_id = extract_room_id(game_dir.name)
                    if room_id:
                        ok_room_ids.add(room_id)
            if ok_room_ids:
                update_rooms_status_ok(ok_room_ids)

        return results, report, summary, report_path

    def start_scan(self) -> None:
        roots = self._selected_roots()
        if not roots:
            return
        auto_update = self.auto_status_var.get()
        self._set_text(self.log_text, "")
        self._start_worker(
            "检测",
            lambda: self._scan_job(roots, auto_update),
        )

    def _current_fix_mode(self) -> str:
        return self.FIX_MODES.get(self.fix_mode_var.get(), MODE_BOTH)

    def _all_fix_targets(self, mode: str) -> list[tuple[Path, list]]:
        if not self.scan_results:
            return []
        return [
            (game_dir, lang_results)
            for _, _, has_list, _, _ in self.scan_results
            for game_dir, lang_results in has_list
            if not is_all_ok(lang_results, mode)
        ]

    def _selected_fix_targets(self, mode: str) -> list[tuple[Path, list]]:
        selected = []
        seen: set[Path] = set()
        for iid in self.tree.selection():
            item = self.game_rows.get(iid)
            if not item:
                continue
            game_dir, lang_results = item
            if game_dir in seen or is_all_ok(lang_results, mode):
                continue
            seen.add(game_dir)
            selected.append(item)
        return selected

    def _confirm_fix(self, targets: list, mode: str) -> bool:
        if not self.scan_results:
            messagebox.showinfo("请先检测", "请先点击“开始检测”，再执行修复。")
            return False
        if not targets:
            messagebox.showinfo("无需修复", "当前选择没有可修复的问题。")
            return False
        mode_label = next((label for label, value in self.FIX_MODES.items() if value == mode), "问题")
        return messagebox.askyesno(
            "确认修复",
            f"将按“{mode_label}”处理 {len(targets)} 个游戏。\n"
            "修复会写入 GameRule.json，翻译修复还可能访问翻译 API 和数据库。是否继续？",
        )

    def _start_fix(self, targets: list[tuple[Path, list]], mode: str) -> None:
        roots = self._selected_roots()
        if not roots or not self._confirm_fix(targets, mode):
            return
        auto_update = self.auto_status_var.get()
        self._start_worker(
            "修复",
            lambda: self._fix_job(targets, mode, roots, auto_update),
        )

    def start_fix_selected(self) -> None:
        mode = self._current_fix_mode()
        self._start_fix(self._selected_fix_targets(mode), mode)

    def start_fix_all(self) -> None:
        mode = self._current_fix_mode()
        self._start_fix(self._all_fix_targets(mode), mode)

    def _fix_job(self, targets: list[tuple[Path, list]], mode: str,
                 roots: list[tuple[str, Path]], auto_update: bool) -> None:
        global _free_apis_decision_callback
        old_callback = _free_apis_decision_callback
        _free_apis_decision_callback = self._ask_free_apis_in_gui
        try:
            run_fix_targets(targets, mode)
        finally:
            _free_apis_decision_callback = old_callback
        print("\n修复流程结束，正在重新检测...")
        results, report, summary, report_path = self._run_scan(roots, auto_update)
        self.events.put(("scan_done", results, report, summary, report_path))
        self.events.put(("fix_done", len(targets)))

    def _ask_free_apis_in_gui(self, free_list: str, error_text: str) -> bool:
        done = threading.Event()
        result = {"value": False}
        self.events.put(("ask_free_apis", free_list, error_text, done, result))
        done.wait()
        return result["value"]

    def open_report(self) -> None:
        if not self.report_path:
            default_path = Path(__file__).parent / "检测报告.txt"
            self.report_path = default_path if default_path.is_file() else None
        if not self.report_path or not self.report_path.is_file():
            messagebox.showinfo("没有报告", "还没有生成检测报告。")
            return
        os.startfile(self.report_path)


# ════════════════════════════════════════════════════════════════════════════════
# 命令行主流程
# ════════════════════════════════════════════════════════════════════════════════

def select_scope() -> list:
    """返回本次要扫描的 [(label, root), ...] 列表。"""
    print("请选择扫描范围：")
    print("  1. VegasGames")
    print("  2. MiniGame")
    print("  3. 全部")
    while True:
        answer = input("> ").strip()
        if answer == "1":
            return [SCAN_ROOTS[0]]
        if answer == "2":
            return [SCAN_ROOTS[1]]
        if answer == "3":
            return list(SCAN_ROOTS)
        print("请输入 1、2 或 3。")


def select_action(has_file_issues: bool, has_trans_issues: bool) -> str | None:
    """扫描完成后让用户选择修复操作，返回对应模式常量，None 表示跳过。"""
    if not has_file_issues and not has_trans_issues:
        print("\n✅ 未发现任何问题，无需修复。")
        return None

    options: list[tuple[str | None, str]] = []
    if has_file_issues:
        options.append((MODE_FILES, "修复缺失文件（复制英文原文）"))
    if has_trans_issues:
        options.append((MODE_TRANS, "重新翻译有问题的内容"))
    if has_file_issues and has_trans_issues:
        options.append((MODE_BOTH, "两项都修复"))
    options.append((None, "跳过，不修复"))

    print("\n请选择要执行的操作：")
    for i, (_, label) in enumerate(options, 1):
        print(f"  {i}. {label}")
    while True:
        answer = input("> ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][0]
        print(f"请输入 1 到 {len(options)} 之间的数字。")


def main():
    scope    = select_scope()
    now      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    skip_ids = query_skip_room_ids()

    # 始终做完整扫描（文件 + 翻译）
    results = [scan_root(label, root, MODE_BOTH, skip_ids) for label, root in scope]

    report, summary = build_scan_report(results, MODE_BOTH, now)
    print(report)

    report_path = save_report(report)
    print(f"\n报告已保存到: {report_path}")

    all_has_list = summary["all_has_list"]
    all_missing = summary["all_missing"]

    # 检测无问题的游戏，自动将 status 更新为 1
    ok_room_ids = set()
    for game_dir, r in all_has_list:
        if is_all_ok(r, MODE_BOTH):
            rid = extract_room_id(game_dir.name)
            if rid:
                ok_room_ids.add(rid)
    if ok_room_ids:
        update_rooms_status_ok(ok_room_ids)

    has_file_issues  = summary["has_file_issues"]
    has_trans_issues = summary["has_trans_issues"]

    action = select_action(has_file_issues, has_trans_issues)
    if action:
        run_fix(results, action)


def run_cli_loop() -> None:
    while True:
        main()
        cont = input("\n是否重新检测？(y/n): ").strip().lower()
        if cont != "y":
            break


def launch_gui() -> None:
    global tk, ttk, filedialog, messagebox
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk()
    MultilangCheckerApp(root)
    root.mainloop()


if __name__ == "__main__":
    if "--cli" in sys.argv:
        run_cli_loop()
    else:
        launch_gui()
