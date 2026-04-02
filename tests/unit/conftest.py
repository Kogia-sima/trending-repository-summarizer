"""共有フィクスチャの定義"""

import datetime

import pytest

from trending_repository_summarizer.main import (
    ReferenceSite,
    RepositoryInfo,
    RepositoryMetaData,
    RepositorySummary,
)


@pytest.fixture
def sample_metadata() -> RepositoryMetaData:
    """テスト用リポジトリメタデータ"""
    return RepositoryMetaData(
        repo_id="owner/sample-repo",
        repo_name="sample-repo",
        repo_url="https://github.com/owner/sample-repo",
        description="A sample repository for testing",
        default_branch="main",
        stars=1000,
        pushed_at=datetime.datetime(2024, 1, 15, 12, 0, 0),
        licenses=["MIT License"],
        thumbnail_url=None,
        reference_sites=[
            ReferenceSite(name="ホームページ", url="https://example.com"),
            ReferenceSite(name="GitHubリポジトリ", url="https://github.com/owner/sample-repo"),
        ],
        retrieval_time=datetime.datetime(2024, 1, 20, 9, 0, 0),
    )


@pytest.fixture
def sample_summary() -> RepositorySummary:
    """テスト用リポジトリサマリー"""
    return RepositorySummary(
        description="テスト用のリポジトリです。",
        short_description="テスト用リポジトリ",
        pros="- **利点1:** 高速な処理が可能です。\n- **利点2:** 使いやすいAPIを提供します。",
        cons="- **注意1:** 設定が複雑です。",
        usecases="- **ユースケース1:** 大規模データの処理に適しています。",
        anti_usecases="- **非推奨1:** 小規模プロジェクトには不向きです。",
        quickstart="1. インストール: `pip install sample-repo`\n2. 使用: `import sample_repo`",
        tags=["ツール", "生成AI"],
    )


@pytest.fixture
def sample_info(
    sample_metadata: RepositoryMetaData, sample_summary: RepositorySummary
) -> RepositoryInfo:
    """テスト用リポジトリ情報"""
    return RepositoryInfo(
        metadata=sample_metadata,
        summary=sample_summary,
        readme="# Sample Repo\n\nThis is a sample repository.\n",
    )


@pytest.fixture
def sample_readme_with_image() -> str:
    """画像URLを含むテスト用READMEテキスト"""
    return "# Sample Repo\n\n![screenshot](images/screenshot.png)\n\nSome description text here.\n"


@pytest.fixture
def sample_readme_no_image() -> str:
    """画像URLを含まないテスト用READMEテキスト"""
    return "# Sample Repo\n\nSome description text here. No images.\n"
