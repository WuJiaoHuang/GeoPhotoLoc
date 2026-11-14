"""Online orchestration. No truth data, historical answers or UI state enter run()."""
import base64
import hashlib
from pathlib import Path
import tempfile
from pydantic import BaseModel, Field

from geophotoloc.config import VisionConfig, ConfigurationError
from geophotoloc.vision import VisionAnalyzer, VisionAPIError, VisionResponseError, ImageInputError, prepare_image
from geophotoloc.maps import LandmarkStore, MapMatcher
from geophotoloc.localization import PoseSolver, PoseSearchConfig
from geophotoloc.models import VisionExtractionResult, MapMatchingResult, PoseLocalizationResult


class PipelineFailure(RuntimeError):
    def __init__(self, stage, code, message):
        super().__init__(message)
        self.stage, self.code = stage, code


class DemoResult(BaseModel):
    mode: str
    provenance: str
    vision: VisionExtractionResult
    matching: MapMatchingResult
    localization: PoseLocalizationResult
    processed_jpeg: bytes = Field(exclude=True, repr=False)
    cache_hit: bool = False
    vision_cache_hit: bool = False


def api_error_message(error):
    # The vision adapter already strips remote bodies; never display raw SDK errors.
    text = str(error).lower()
    if 'timed out' in text:
        return 'API_TIMEOUT', '视觉请求超时；请稍后重试。'
    if 'rate limit' in text:
        return 'API_LIMIT', '视觉服务限流或配额受限；请稍后重试并检查账户配额。'
    if 'authentication' in text:
        return 'API_AUTH', '视觉服务认证失败；请检查本地 API Key。'
    if any(code in text for code in ('402','403')):
        return 'API_ACCOUNT', '视觉账户权限、余额或配额可能受限；请在百炼控制台核实。'
    if '400' in text:
        return 'API_REJECTED','视觉请求被拒绝；请核实模型可用性、图片及账户余额/配额，未确认具体原因。'
    return 'API_NETWORK', '视觉请求失败；请检查网络、账户状态和服务可用性。'


def validate_upload(data, filename):
    """Safe preview gate, reusing Stage 2 rather than duplicating image rules."""
    if len(data)>20*1024*1024:
        raise PipelineFailure('image','IMAGE_TOO_LARGE','图片文件超过 20 MiB 限制。')
    try:
        with tempfile.TemporaryDirectory(prefix='geophotoloc-preview-') as folder:
            path=Path(folder)/('upload'+Path(filename).suffix.lower())
            path.write_bytes(data)
            return prepare_image(path)
    except (ImageInputError,OSError):
        raise PipelineFailure('image','INVALID_IMAGE','图片损坏、格式不支持或尺寸超限，无法预览。') from None


class LocalizationPipeline:
    def __init__(self, db_path='.cache/geophotoloc/maps.sqlite3', *, vision_config=None,
                 search_config=None, analyzer=None, store_factory=LandmarkStore,
                 matcher_factory=MapMatcher, solver_factory=PoseSolver):
        self.db_path = Path(db_path)
        self.vision_config = vision_config
        self.search_config = search_config or PoseSearchConfig()
        self.analyzer = analyzer
        self.store_factory, self.matcher_factory, self.solver_factory = store_factory, matcher_factory, solver_factory
        self._vision_cache = {}
        self._result_cache = {}

    def run(self, image_path):
        try:
            prepared = prepare_image(image_path)
        except ImageInputError:
            raise PipelineFailure('image','INVALID_IMAGE','图片不支持、已损坏或超出大小/尺寸限制，请选择 JPEG、PNG 或 WebP。') from None
        if not self.db_path.is_file():
            raise PipelineFailure('maps','DB_MISSING','本地地图数据库缺失，请点击初始化地图或运行 demo-setup。')
        try:
            store = self.store_factory(self.db_path)
            coverage = store.coverage_regions()
            if not coverage:
                store.close()
                raise PipelineFailure('maps','DB_EMPTY','地图覆盖为空，请运行 demo-setup 初始化三个演示区域。')
        except PipelineFailure:
            raise
        except Exception:
            raise PipelineFailure('maps','DB_INVALID','地图数据库无法读取，请选择有效数据库或重新初始化到新路径。') from None
        try:
            config = self.vision_config
            if self.analyzer is None and config is None:
                try:
                    config = VisionConfig.from_env()
                except ConfigurationError:
                    raise PipelineFailure('vision','KEY_MISSING','尚未配置有效视觉参数，请检查 .env 的 API Key、模型、地址及超时。') from None
            credential = hashlib.sha256(config.api_key.get_secret_value().encode()).hexdigest() if config else 'injected-client'
            model_key = (config.model,config.base_url,credential) if config else ('injected',)
            vision_key = (hashlib.sha256(prepared.data_url.encode()).hexdigest(),model_key)
            db_stat = self.db_path.stat()
            result_key = (vision_key,self.search_config.model_dump_json(),str(self.db_path.resolve()),db_stat.st_mtime_ns,db_stat.st_size)
            if result_key in self._result_cache:
                return self._result_cache[result_key].model_copy(update={
                    'cache_hit':True,'vision_cache_hit':True,'provenance':'本次全部复用本会话缓存：未调用模型，未重新求解。'},deep=True)
            vision_cached = vision_key in self._vision_cache
            if vision_key not in self._vision_cache:
                try:
                    analyzer = self.analyzer or VisionAnalyzer(config)
                    self._vision_cache[vision_key] = analyzer.analyze_prepared(prepared)
                except VisionAPIError as error:
                    code,message = api_error_message(error)
                    raise PipelineFailure('vision',code,message) from None
                except VisionResponseError:
                    raise PipelineFailure('vision','INVALID_MODEL_OUTPUT','模型未返回可校验的识别结果；没有将失败伪装成定位成功。') from None
            vision = self._vision_cache[vision_key].model_copy(deep=True)
            try:
                matching = self.matcher_factory(store).match(vision)
                localization = self.solver_factory(store,self.search_config).solve(vision,matching)
            except (ValueError,RuntimeError):
                raise PipelineFailure('geometry','SOLVE_FAILED','地图匹配或几何求解失败，请检查本地覆盖数据和搜索参数。') from None
            result = DemoResult(mode='online',provenance=('复用本会话识别，本次重新执行地图匹配和几何求解。' if vision_cached
                                                        else '本次真实调用视觉模型，并执行地图匹配和几何求解。'),
                                vision=vision,matching=matching,localization=localization,
                                vision_cache_hit=vision_cached,
                                processed_jpeg=base64.b64decode(prepared.data_url.split(',',1)[1]))
            self._result_cache[result_key] = result.model_copy(deep=True)
            for cache in (self._vision_cache,self._result_cache):
                while len(cache)>6:
                    cache.pop(next(iter(cache)))
            return result
        finally:
            store.close()
