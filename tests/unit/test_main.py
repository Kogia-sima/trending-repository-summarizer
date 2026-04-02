"""main.py のユニットテスト"""

import base64
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from trending_repository_summarizer.main import (
    RepositoryInfo,
    RepositoryMetaData,
    RepositorySummary,
    RepositoryTags,
    _invoke_llm,
    create_notion_page_from_md,
    extract_thumbnail_url,
    format_repository_info,
    get_repository_metadata,
    get_repository_readme,
    get_trending_repositories,
    lambda_handler,
    main,
    save_repository_info,
    summarize_repository,
)

# ─────────────────────────────────────────────
# テスト用ヘルパー
# ─────────────────────────────────────────────


def _make_summarize_side_effect(tag_responses: list[RepositoryTags]) -> Any:
    """summarize_repository テスト用の _invoke_llm サイドエフェクトを生成する"""
    str_results = iter(
        [
            "description text",
            "short description",
            "pros text",
            "cons text",
            "usecases text",
            "anti_usecases text",
            "quickstart text",
        ]
    )
    tag_iter = iter(tag_responses)

    def side_effect(*args: Any, **kwargs: Any) -> Any:
        # format キーワード引数がある場合はタグレスポンスを返す
        if kwargs.get("format") is not None:
            return next(tag_iter)
        return next(str_results)

    return side_effect


# ─────────────────────────────────────────────
# get_trending_repositories
# ─────────────────────────────────────────────


class TestGetTrendingRepositories:
    """get_trending_repositories のテスト"""

    def test_returns_repo_names(self) -> None:
        """正常系: HTML からリポジトリ名を抽出して返す"""
        html_content = (
            "<html><body>"
            '<h2 class="h3 lh-condensed"><a href="/owner1/repo1">repo1</a></h2>'
            '<h2 class="h3 lh-condensed"><a href="/owner2/repo2">repo2</a></h2>'
            "</body></html>"
        )
        mock_response = MagicMock()
        mock_response.text = html_content

        with patch("trending_repository_summarizer.main.requests.get") as mock_get:
            mock_get.return_value = mock_response
            result = get_trending_repositories("python", "monthly")

        assert result == ["owner1/repo1", "owner2/repo2"]
        mock_get.assert_called_once_with(
            "https://github.com/trending/python?since=monthly", timeout=30
        )

    def test_raises_on_http_error(self) -> None:
        """異常系: HTTP エラー時に例外を送出する"""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404")

        with patch("trending_repository_summarizer.main.requests.get") as mock_get:
            mock_get.return_value = mock_response
            with pytest.raises(requests.HTTPError):
                get_trending_repositories("python", "monthly")

    def test_custom_selector(self) -> None:
        """カスタムセレクタを使用してリポジトリ名を取得できる"""
        html_content = (
            '<html><body><div class="custom"><a href="/owner/repo">link</a></div></body></html>'
        )
        mock_response = MagicMock()
        mock_response.text = html_content

        with patch("trending_repository_summarizer.main.requests.get") as mock_get:
            mock_get.return_value = mock_response
            result = get_trending_repositories("python", "daily", selector="div.custom > a")

        assert result == ["owner/repo"]


# ─────────────────────────────────────────────
# get_repository_metadata
# ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "homepage, license_data, expected_reference_count, expected_license",
    [
        # homepage あり、license あり
        (
            "https://example.com",
            {"name": "MIT License"},
            2,
            ["MIT License"],
        ),
        # homepage なし、license あり
        (
            None,
            {"name": "Apache License 2.0"},
            1,
            ["Apache License 2.0"],
        ),
        # homepage あり、license なし
        (
            "https://example.com",
            None,
            2,
            [],
        ),
        # homepage なし、license なし
        (
            None,
            None,
            1,
            [],
        ),
    ],
)
class TestGetRepositoryMetadata:
    """get_repository_metadata のテスト"""

    def test_returns_metadata(
        self,
        homepage: str | None,
        license_data: dict | None,
        expected_reference_count: int,
        expected_license: list[str],
    ) -> None:
        """Homepage と license の有無に応じてメタデータを正しく構築する"""
        api_response = {
            "name": "sample-repo",
            "html_url": "https://github.com/owner/sample-repo",
            "description": "A test repo",
            "default_branch": "main",
            "stargazers_count": 500,
            "pushed_at": "2024-01-15T12:00:00Z",
            "homepage": homepage,
            "license": license_data,
        }
        mock_response = MagicMock()
        mock_response.json.return_value = api_response

        with patch("trending_repository_summarizer.main.requests.get") as mock_get:
            mock_get.return_value = mock_response
            result = get_repository_metadata("owner/sample-repo")

        assert result.repo_id == "owner/sample-repo"
        assert result.repo_name == "sample-repo"
        assert result.stars == 500
        assert result.licenses == expected_license
        assert len(result.reference_sites) == expected_reference_count
        # GitHubリポジトリリンクは常に含まれる
        assert any(s.name == "GitHubリポジトリ" for s in result.reference_sites)
        # homepage がある場合は先頭に挿入される
        if homepage:
            assert result.reference_sites[0].name == "ホームページ"


# ─────────────────────────────────────────────
# get_repository_readme
# ─────────────────────────────────────────────


class TestGetRepositoryReadme:
    """get_repository_readme のテスト"""

    def test_decodes_base64_content(self) -> None:
        """base64 エンコードされた README コンテンツをデコードして返す"""
        original_text = "# My README\n\nHello world!\n"
        encoded = base64.b64encode(original_text.encode("utf-8")).decode("utf-8")

        api_response = {"content": encoded}
        mock_response = MagicMock()
        mock_response.json.return_value = api_response

        with patch("trending_repository_summarizer.main.requests.get") as mock_get:
            mock_get.return_value = mock_response
            result = get_repository_readme("owner/sample-repo")

        assert result == original_text

    def test_raises_on_http_error(self) -> None:
        """HTTP エラー時に例外を送出する"""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404")

        with patch("trending_repository_summarizer.main.requests.get") as mock_get:
            mock_get.return_value = mock_response
            with pytest.raises(requests.HTTPError):
                get_repository_readme("owner/sample-repo")


# ─────────────────────────────────────────────
# extract_thumbnail_url
# ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "readme, expected_suffix",
    [
        # 有効拡張子 .png の相対 URL → 絶対 URL に変換される
        (
            "![img](images/screenshot.png)",
            "/raw/main/images/screenshot.png",
        ),
        # 有効拡張子 .jpg
        (
            "![img](photo.jpg)",
            "/raw/main/photo.jpg",
        ),
        # 有効拡張子 .jpeg
        (
            "![img](photo.jpeg)",
            "/raw/main/photo.jpeg",
        ),
        # 有効拡張子 .webp
        (
            "![img](banner.webp)",
            "/raw/main/banner.webp",
        ),
        # 絶対 URL はそのまま保持される
        (
            "![img](https://example.com/image.png)",
            None,  # 別途チェック
        ),
    ],
)
class TestExtractThumbnailUrlWithImage:
    """有効な画像 URL を含む README のテスト"""

    def test_returns_url(
        self,
        sample_metadata: RepositoryMetaData,
        readme: str,
        expected_suffix: str | None,
    ) -> None:
        """有効な画像 URL を返す"""
        result = extract_thumbnail_url(sample_metadata, readme)

        assert result is not None
        if expected_suffix is not None:
            assert result.endswith(expected_suffix)
        else:
            # 絶対 URL の場合
            assert result == "https://example.com/image.png"


class TestExtractThumbnailUrlNoImage:
    """画像なし README のテスト"""

    def test_returns_none_when_no_image(
        self,
        sample_metadata: RepositoryMetaData,
        sample_readme_no_image: str,
    ) -> None:
        """画像がない場合は None を返す"""
        result = extract_thumbnail_url(sample_metadata, sample_readme_no_image)
        assert result is None

    def test_returns_none_for_invalid_extension(self, sample_metadata: RepositoryMetaData) -> None:
        """無効な拡張子 (.svg) の場合は None を返す"""
        readme = "![img](logo.svg)\n"
        result = extract_thumbnail_url(sample_metadata, readme)
        assert result is None

    def test_returns_none_for_gif(self, sample_metadata: RepositoryMetaData) -> None:
        """.gif 拡張子の場合も None を返す"""
        readme = "![img](animation.gif)\n"
        result = extract_thumbnail_url(sample_metadata, readme)
        assert result is None


# ─────────────────────────────────────────────
# summarize_repository
# ─────────────────────────────────────────────


class TestSummarizeRepository:
    """summarize_repository のテスト"""

    def test_valid_tags_on_first_try(self, sample_metadata: RepositoryMetaData) -> None:
        """初回で有効なタグが返された場合、即座に完了する"""
        valid_tags = RepositoryTags(tags=["ツール", "生成AI"])
        side_effect = _make_summarize_side_effect([valid_tags])

        with patch("trending_repository_summarizer.main._invoke_llm") as mock_llm:
            mock_llm.side_effect = side_effect
            result = summarize_repository(sample_metadata, "# README")

        assert result.tags == ["ツール", "生成AI"]
        # 7回（テキスト生成）+ 1回（タグ）= 8回呼ばれる
        assert mock_llm.call_count == 8

    def test_invalid_tags_then_valid_on_retry(self, sample_metadata: RepositoryMetaData) -> None:
        """無効なタグが返された場合、リトライして有効なタグを取得する"""
        invalid_tags = RepositoryTags(tags=["無効なタグ"])
        valid_tags = RepositoryTags(tags=["フレームワーク"])
        side_effect = _make_summarize_side_effect([invalid_tags, valid_tags])

        with patch("trending_repository_summarizer.main._invoke_llm") as mock_llm:
            mock_llm.side_effect = side_effect
            result = summarize_repository(sample_metadata, "# README")

        assert result.tags == ["フレームワーク"]
        # 7回（テキスト）+ 2回（タグ：1回失敗 + 1回成功）= 9回
        assert mock_llm.call_count == 9

    def test_always_invalid_tags_returns_empty(
        self, sample_metadata: RepositoryMetaData, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Temperature が 2.0 に達しても無効なタグの場合、空リストを返す"""
        # floating point の累積誤差でループ回数が変わるため、無制限に無効タグを返す
        str_results = iter(
            [
                "description text",
                "short description",
                "pros text",
                "cons text",
                "usecases text",
                "anti_usecases text",
                "quickstart text",
            ]
        )

        def always_invalid(*args: Any, **kwargs: Any) -> Any:
            # format が指定されたタグ呼び出しでは常に無効なタグを返す
            if kwargs.get("format") is not None:
                return RepositoryTags(tags=["無効なタグ"])
            return next(str_results)

        with patch("trending_repository_summarizer.main._invoke_llm") as mock_llm:
            mock_llm.side_effect = always_invalid
            with caplog.at_level(logging.WARNING):
                result = summarize_repository(sample_metadata, "# README")

        assert result.tags == []
        assert "Failed to generate tags" in caplog.text

    def test_returns_full_summary(self, sample_metadata: RepositoryMetaData) -> None:
        """戻り値が RepositorySummary の全フィールドを含む"""
        valid_tags = RepositoryTags(tags=["ツール"])
        side_effect = _make_summarize_side_effect([valid_tags])

        with patch("trending_repository_summarizer.main._invoke_llm") as mock_llm:
            mock_llm.side_effect = side_effect
            result = summarize_repository(sample_metadata, "# README")

        assert isinstance(result, RepositorySummary)
        assert result.description == "description text"
        assert result.short_description == "short description"
        assert result.pros == "pros text"
        assert result.cons == "cons text"
        assert result.usecases == "usecases text"
        assert result.anti_usecases == "anti_usecases text"
        assert result.quickstart == "quickstart text"


# ─────────────────────────────────────────────
# format_repository_info
# ─────────────────────────────────────────────


class TestFormatRepositoryInfo:
    """format_repository_info のテスト"""

    def test_contains_required_sections(self, sample_info: RepositoryInfo) -> None:
        """出力に必須のセクションが含まれている"""
        result = format_repository_info(sample_info)

        assert "# 1. 概要" in result
        assert "# 2. ユースケース" in result
        assert sample_info.metadata.repo_name in result

    def test_contains_description(self, sample_info: RepositoryInfo) -> None:
        """リポジトリの説明が含まれている"""
        result = format_repository_info(sample_info)
        assert sample_info.summary.description in result

    def test_contains_reference_sites(self, sample_info: RepositoryInfo) -> None:
        """参照サイトのリンクが含まれている"""
        result = format_repository_info(sample_info)
        for site in sample_info.metadata.reference_sites:
            assert site.url in result
            assert site.name in result

    def test_multiple_reference_sites(self, sample_info: RepositoryInfo) -> None:
        """複数の参照サイトがすべて出力に含まれている"""
        result = format_repository_info(sample_info)
        # フィクスチャには 2 つのサイトがある
        assert result.count("- [") >= 2

    def test_contains_pros_cons(self, sample_info: RepositoryInfo) -> None:
        """pros/cons が出力に含まれている"""
        result = format_repository_info(sample_info)
        assert sample_info.summary.pros in result
        assert sample_info.summary.cons in result


# ─────────────────────────────────────────────
# save_repository_info
# ─────────────────────────────────────────────


class TestSaveRepositoryInfo:
    """save_repository_info のテスト"""

    def test_creates_parent_and_writes_json(self, sample_info: RepositoryInfo) -> None:
        """親ディレクトリを作成し、JSON テキストを書き込む"""
        mock_path = MagicMock()

        save_repository_info(mock_path, sample_info)

        mock_path.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_path.write_text.assert_called_once()
        # JSON として書き込まれていることを確認
        written_text = mock_path.write_text.call_args[0][0]
        assert '"version"' in written_text
        assert '"metadata"' in written_text

    def test_writes_with_utf8_encoding(self, sample_info: RepositoryInfo) -> None:
        """UTF-8 エンコーディングで書き込まれる"""
        mock_path = MagicMock()

        save_repository_info(mock_path, sample_info)

        _, kwargs = mock_path.write_text.call_args
        assert kwargs.get("encoding") == "utf-8"


# ─────────────────────────────────────────────
# create_notion_page_from_md
# ─────────────────────────────────────────────


class TestCreateNotionPageFromMd:
    """create_notion_page_from_md のテスト"""

    def _make_notion_client(self) -> MagicMock:
        """Notion クライアントのモックを生成する"""
        mock_client = MagicMock()
        mock_client.pages.create.return_value = {"id": "test-page-id"}
        return mock_client

    def test_creates_page_with_title_only(self) -> None:
        """最低限のパラメータでページを作成できる"""
        mock_client = self._make_notion_client()

        with (
            patch("trending_repository_summarizer.main.Client", return_value=mock_client),
            patch(
                "trending_repository_summarizer.main.parse_markdown_to_notion_blocks",
                return_value=[],
            ),
            patch(
                "trending_repository_summarizer.main.process_inline_formatting",
                return_value=[],
            ),
        ):
            create_notion_page_from_md(title="Test Page", markdown_text="# Hello")

        mock_client.pages.create.assert_called_once()
        mock_client.pages.update.assert_called_once()

    def test_sets_short_description_when_provided(self) -> None:
        """short_description が指定された場合、properties に追加する"""
        mock_client = self._make_notion_client()

        with (
            patch("trending_repository_summarizer.main.Client", return_value=mock_client),
            patch(
                "trending_repository_summarizer.main.parse_markdown_to_notion_blocks",
                return_value=[],
            ),
            patch(
                "trending_repository_summarizer.main.process_inline_formatting",
                return_value=[{"type": "text"}],
            ),
        ):
            create_notion_page_from_md(
                title="Test Page",
                markdown_text="# Hello",
                short_description="Short desc",
            )

        _, kwargs = mock_client.pages.update.call_args
        properties = kwargs["properties"]
        assert "Description" in properties

    def test_short_description_not_set_when_none(self) -> None:
        """short_description が None の場合、properties に含まれない"""
        mock_client = self._make_notion_client()

        with (
            patch("trending_repository_summarizer.main.Client", return_value=mock_client),
            patch(
                "trending_repository_summarizer.main.parse_markdown_to_notion_blocks",
                return_value=[],
            ),
            patch("trending_repository_summarizer.main.process_inline_formatting"),
        ):
            create_notion_page_from_md(
                title="Test Page",
                markdown_text="# Hello",
                short_description=None,
            )

        _, kwargs = mock_client.pages.update.call_args
        properties = kwargs["properties"]
        assert "Description" not in properties

    def test_sets_tags_when_provided(self) -> None:
        """Tags が指定された場合、multi_select として properties に追加する"""
        mock_client = self._make_notion_client()

        with (
            patch("trending_repository_summarizer.main.Client", return_value=mock_client),
            patch(
                "trending_repository_summarizer.main.parse_markdown_to_notion_blocks",
                return_value=[],
            ),
            patch("trending_repository_summarizer.main.process_inline_formatting"),
        ):
            create_notion_page_from_md(
                title="Test Page",
                markdown_text="# Hello",
                tags=["ツール", "生成AI"],
            )

        _, kwargs = mock_client.pages.update.call_args
        properties = kwargs["properties"]
        assert "Tags" in properties
        assert properties["Tags"]["multi_select"] == [
            {"name": "ツール"},
            {"name": "生成AI"},
        ]

    def test_tags_not_set_when_none(self) -> None:
        """Tags が None の場合、properties に含まれない"""
        mock_client = self._make_notion_client()

        with (
            patch("trending_repository_summarizer.main.Client", return_value=mock_client),
            patch(
                "trending_repository_summarizer.main.parse_markdown_to_notion_blocks",
                return_value=[],
            ),
            patch("trending_repository_summarizer.main.process_inline_formatting"),
        ):
            create_notion_page_from_md(
                title="Test Page",
                markdown_text="# Hello",
                tags=None,
            )

        _, kwargs = mock_client.pages.update.call_args
        properties = kwargs["properties"]
        assert "Tags" not in properties

    @pytest.mark.parametrize(
        "error_code",
        [
            pytest.param("invalid_json", id="InvalidJSON"),
            pytest.param("invalid_request", id="InvalidRequest"),
            pytest.param("invalid_request_url", id="InvalidRequestURL"),
            pytest.param("object_not_found", id="ObjectNotFound"),
            pytest.param("validation_error", id="ValidationError"),
        ],
    )
    def test_catches_specific_api_errors(self, error_code: str) -> None:
        """特定の APIResponseError は捕捉してログ出力するだけでスキップする"""
        from notion_client.errors import APIErrorCode, APIResponseError

        mock_client = self._make_notion_client()
        mock_response = MagicMock()
        mock_response.status_code = 400
        api_error = APIResponseError(mock_response, "error", APIErrorCode(error_code))
        mock_client.blocks.children.append.side_effect = api_error

        with (
            patch("trending_repository_summarizer.main.Client", return_value=mock_client),
            patch(
                "trending_repository_summarizer.main.parse_markdown_to_notion_blocks",
                return_value=[{"type": "paragraph"}],
            ),
            patch("trending_repository_summarizer.main.process_inline_formatting"),
        ):
            # 例外が送出されないことを確認
            create_notion_page_from_md(title="Test", markdown_text="# Hello")

    def test_reraises_unhandled_api_errors(self) -> None:
        """捕捉対象外の APIResponseError は再 raise される"""
        from notion_client.errors import APIErrorCode, APIResponseError

        mock_client = self._make_notion_client()
        mock_response = MagicMock()
        mock_response.status_code = 500
        api_error = APIResponseError(
            mock_response, "server error", APIErrorCode.InternalServerError
        )
        mock_client.blocks.children.append.side_effect = api_error

        with (
            patch("trending_repository_summarizer.main.Client", return_value=mock_client),
            patch(
                "trending_repository_summarizer.main.parse_markdown_to_notion_blocks",
                return_value=[{"type": "paragraph"}],
            ),
            patch("trending_repository_summarizer.main.process_inline_formatting"),
        ):
            with pytest.raises(APIResponseError):
                create_notion_page_from_md(title="Test", markdown_text="# Hello")


# ─────────────────────────────────────────────
# _invoke_llm
# ─────────────────────────────────────────────


class TestInvokeLlm:
    """_invoke_llm のテスト"""

    def test_returns_content_without_format(self) -> None:
        """Format なしの場合、response.content を返す"""
        mock_response = MagicMock()
        mock_response.content = "LLM の回答テキスト"
        mock_chat = MagicMock()
        mock_chat.invoke.return_value = mock_response

        with patch("trending_repository_summarizer.main.ChatOpenAI", return_value=mock_chat):
            result = _invoke_llm(
                system_prompt="システムプロンプト", user_prompt="ユーザープロンプト"
            )

        assert result == "LLM の回答テキスト"
        mock_chat.with_structured_output.assert_not_called()

    def test_returns_structured_output_with_format(self) -> None:
        """Format が指定された場合、with_structured_output を使用して構造体を返す"""
        expected_output = RepositoryTags(tags=["ツール"])
        mock_structured_chain = MagicMock()
        mock_structured_chain.invoke.return_value = expected_output
        mock_chat = MagicMock()
        mock_chat.with_structured_output.return_value = mock_structured_chain

        with patch("trending_repository_summarizer.main.ChatOpenAI", return_value=mock_chat):
            result = _invoke_llm(
                system_prompt="システムプロンプト",
                user_prompt="ユーザープロンプト",
                format=RepositoryTags,
                temperature=0.5,
            )

        assert result == expected_output
        mock_chat.with_structured_output.assert_called_once_with(RepositoryTags)

    def test_temperature_passed_to_chat_openai(self) -> None:
        """Temperature パラメータが ChatOpenAI に渡される"""
        mock_response = MagicMock()
        mock_response.content = "response"
        mock_chat = MagicMock()
        mock_chat.invoke.return_value = mock_response

        with patch(
            "trending_repository_summarizer.main.ChatOpenAI", return_value=mock_chat
        ) as mock_cls:
            _invoke_llm(system_prompt="sys", user_prompt="usr", temperature=1.0)

        _, kwargs = mock_cls.call_args
        assert kwargs["temperature"] == 1.0


# ─────────────────────────────────────────────
# main
# ─────────────────────────────────────────────


class TestMain:
    """main のテスト"""

    def _make_mock_upath(self, repo_exists: bool = False) -> MagicMock:
        """UPath モックを生成する（repos ディレクトリ・ファイルの存在チェック含む）"""
        mock_upath_instance = MagicMock()
        # / 演算子でリポジトリのファイルパスを返す
        mock_file = MagicMock()
        mock_file.exists.return_value = repo_exists
        mock_upath_instance.__truediv__ = MagicMock(return_value=mock_file)
        return mock_upath_instance

    def test_skips_existing_repository(
        self,
        sample_metadata: RepositoryMetaData,
        sample_summary: RepositorySummary,
    ) -> None:
        """既に存在するリポジトリはスキップされる"""
        mock_upath_cls = MagicMock(return_value=self._make_mock_upath(repo_exists=True))

        with (
            patch("trending_repository_summarizer.main.UPath", mock_upath_cls),
            patch(
                "trending_repository_summarizer.main.get_trending_repositories",
                return_value=["owner/repo"],
            ),
            patch("trending_repository_summarizer.main.get_repository_metadata") as mock_get_meta,
        ):
            main()

        # 既存リポジトリなので metadata 取得が呼ばれない
        mock_get_meta.assert_not_called()

    def test_processes_new_repository(
        self,
        sample_metadata: RepositoryMetaData,
        sample_summary: RepositorySummary,
        sample_info: RepositoryInfo,
    ) -> None:
        """新規リポジトリは全処理が実行される"""
        mock_upath_cls = MagicMock(return_value=self._make_mock_upath(repo_exists=False))

        with (
            patch("trending_repository_summarizer.main.UPath", mock_upath_cls),
            patch(
                "trending_repository_summarizer.main.get_trending_repositories",
                return_value=["owner/repo"],
            ),
            patch(
                "trending_repository_summarizer.main.get_repository_metadata",
                return_value=sample_metadata,
            ),
            patch(
                "trending_repository_summarizer.main.get_repository_readme",
                return_value="# README",
            ),
            patch(
                "trending_repository_summarizer.main.extract_thumbnail_url",
                return_value="https://example.com/image.png",
            ),
            patch(
                "trending_repository_summarizer.main.summarize_repository",
                return_value=sample_summary,
            ),
            patch(
                "trending_repository_summarizer.main.format_repository_info",
                return_value="markdown text",
            ),
            patch("trending_repository_summarizer.main.create_notion_page_from_md"),
            patch("trending_repository_summarizer.main.save_repository_info") as mock_save,
            patch("trending_repository_summarizer.main.time.sleep"),
        ):
            main()

        # save_repository_info が呼ばれたことを確認
        mock_save.assert_called_once()

    def test_logging_with_existing_handlers(self) -> None:
        """既にハンドラが設定されている場合、setLevel が呼ばれる"""
        mock_upath_cls = MagicMock(return_value=self._make_mock_upath(repo_exists=True))
        mock_handler = MagicMock()

        with (
            patch("trending_repository_summarizer.main.UPath", mock_upath_cls),
            patch(
                "trending_repository_summarizer.main.get_trending_repositories",
                return_value=[],
            ),
            patch.object(logging.getLogger(), "handlers", [mock_handler]),
        ):
            main()

        # ハンドラが存在する場合、setLevel が呼ばれる（例外が発生しない）

    def test_logging_without_handlers(self) -> None:
        """ハンドラが未設定の場合、basicConfig が呼ばれる"""
        mock_upath_cls = MagicMock(return_value=self._make_mock_upath(repo_exists=True))

        with (
            patch("trending_repository_summarizer.main.UPath", mock_upath_cls),
            patch(
                "trending_repository_summarizer.main.get_trending_repositories",
                return_value=[],
            ),
            patch("logging.basicConfig") as mock_basic_config,
            patch.object(logging.getLogger(), "handlers", []),
        ):
            main()

        mock_basic_config.assert_called_once_with(level=logging.INFO)


# ─────────────────────────────────────────────
# lambda_handler
# ─────────────────────────────────────────────


class TestLambdaHandler:
    """lambda_handler のテスト"""

    def test_calls_main_and_returns_success(self) -> None:
        """Main を呼び出して 'Success' を返す"""
        with patch("trending_repository_summarizer.main.main") as mock_main:
            result = lambda_handler({}, {})

        mock_main.assert_called_once()
        assert result == "Success"
