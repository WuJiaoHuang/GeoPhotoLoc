"""Immutable offline snapshots, usable without SQLite, credentials or network."""
import base64
import json
from pathlib import Path
from geophotoloc.vision import prepare_image
from geophotoloc.models import VisionExtractionResult, MapMatchingResult, PoseLocalizationResult
from .pipeline import DemoResult

ROOT = Path(__file__).resolve().parents[3]
CASES = {'北京 CBD':'beijing_cbd','广州天际线':'guangzhou_skyline','上海东方明珠':'oriental_pearl'}


def load_camera_evaluations():
    path=ROOT/'docs/evaluation/stage5/camera_evaluation.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []


def load_case(case_id):
    if case_id not in CASES.values():
        raise ValueError('未知离线案例')
    root = ROOT/'docs/evaluation'
    vision = VisionExtractionResult.model_validate_json((root/f'stage2_1/results/{case_id}.json').read_text(encoding='utf-8'))
    matching = MapMatchingResult.model_validate_json((root/f'stage3/{case_id}_matches.json').read_text(encoding='utf-8'))
    localization = PoseLocalizationResult.model_validate_json((root/f'stage4/{case_id}.json').read_text(encoding='utf-8'))
    prepared = prepare_image(root/f'stage2_1/images/{case_id}.jpg')
    if prepared.metadata.processed_size != vision.image.processed_size:
        raise ValueError('历史图片尺寸与视觉结果不一致')
    return DemoResult(mode='offline',provenance='离线复现实验结果，非本次实时模型推理。',vision=vision,
                      matching=matching,localization=localization,
                      processed_jpeg=base64.b64decode(prepared.data_url.split(',',1)[1]))
