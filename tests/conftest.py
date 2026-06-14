"""pytest 公共 fixtures"""
import sys
import os

# 将 backend 目录加入路径，使单元测试可以直接 import
BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

import pytest
import httpx

BASE_URL = "http://127.0.0.1:9001"


@pytest.fixture(scope="session")
def api():
    """httpx 同步客户端，供集成测试使用"""
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as c:
        yield c


@pytest.fixture(scope="session")
def first_backtest_id(api):
    """返回第一个回测 ID，供多个集成测试复用"""
    r = api.get("/api/backtests")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) > 0
    return items[0]["backtestId"]
