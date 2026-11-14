"""Idempotent bounded initialization; never overwrite a valid populated region."""
from pathlib import Path
from geophotoloc.maps import LandmarkStore, OverpassClient, import_region
from geophotoloc.maps.regions import REGIONS


def database_status(db_path):
    if not Path(db_path).is_file():
        return []
    try:
        with LandmarkStore(db_path) as store:
            return [region for region in store.coverage_regions() if store.connection.execute(
                'SELECT 1 FROM memberships WHERE region_id=? LIMIT 1',(region,)).fetchone()]
    except Exception:
        return []


def setup_demo(db_path='.cache/geophotoloc/maps.sqlite3', *, client=None, offline=False):
    results = []
    try:
        with LandmarkStore(db_path) as store:
            existing = set(database_status(db_path))
            for region in REGIONS:
                if region in existing:
                    results.append({'region':region,'status':'reused'})
                    continue
                try:
                    meta = import_region(store,region,client or OverpassClient(),offline=offline)
                    results.append({'region':region,'status':'imported','entities':meta['stored_entities']})
                except (RuntimeError,OSError,ValueError):
                    results.append({'region':region,'status':'failed','message':'地图服务或缓存不可用；可稍后重试，离线案例仍可展示。'})
    except Exception:
        return [{'region':'database','status':'failed','message':'数据库不可读；未覆盖已有文件，可使用 --db 指定新路径。'}]
    return results
