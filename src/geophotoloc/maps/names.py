"""Generic lexical normalization, never a landmark-to-city lookup."""

import re
import unicodedata


def normalize_name(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKC", value).casefold() if char.isalnum())


GENERIC_WORDS = set("""a an the of with on in and or unknown unidentified generic ordinary
 tall very high rise highrise skyscraper tower towers building buildings structure structures
 glass steel concrete rectangular tapered flared top topped crowned dark grey gray blue
 red white black slab left right center central far foreground background pyramid roof
 river water bridge road island stadium loop cantilevered lattice modern cylindrical
 dome domed round sphere spherical large small long short signage logo like shaped
 city urban residential commercial office complex waterfront bank shore financial finance
 international centre headquarters
""".split())


def is_specific_name(value: str) -> bool:
    normalized = normalize_name(value)
    if len(normalized) < 2:
        return False
    if normalized in {"高楼", "高塔", "大桥", "未知建筑", "高层建筑", "普通高楼", "高楼建筑", "玻璃大楼", "未识别建筑", "建筑物", "桥梁", "河流", "道路", "摩天大楼"}:
        return False
    words = re.findall(r"[a-z]+", unicodedata.normalize("NFKC", value).casefold())
    if words and all(word in GENERIC_WORDS for word in words) and not any("\u3400" <= char <= "\u9fff" for char in value):
        return False
    return True


def distinctive_words(value: str) -> set[str]:
    return set(re.findall(r"[a-z]+", value.casefold())) - GENERIC_WORDS
